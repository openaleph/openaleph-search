import asyncio
import itertools
import os
import threading
from datetime import datetime, timedelta
from typing import Any, Iterable, NamedTuple

from anystore.decorators import error_handler
from anystore.io import logged_items
from anystore.logging import get_logger
from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk
from followthemoney import EntityProxy

from openaleph_search.core import get_async_ingest_es, get_es, get_ingest_es
from openaleph_search.index.util import MAX_REQUEST_TIMEOUT, refresh_sync
from openaleph_search.settings import Settings
from openaleph_search.transform.entity import format_batch, iter_batches
from openaleph_search.util import Action, Actions

log = get_logger(__name__)
settings = Settings()


_local = threading.local()


def _get_loop() -> asyncio.AbstractEventLoop:
    """Persistent per-thread event loop for the indexer.

    Reusing one loop across calls keeps the per-loop cached async ES client
    (see `core.get_async_ingest_es`) alive, instead of paying a fresh client
    plus `es.info()` handshake per call as `asyncio.run` would. Pid-guarded so
    processes forked after creation don't reuse the parent's loop.
    """
    if getattr(_local, "pid", None) != os.getpid() or _local.loop.is_closed():
        _local.loop = asyncio.new_event_loop()
        _local.pid = os.getpid()
    return _local.loop


@error_handler(logger=log, max_retries=settings.max_retries)
def query_delete(index, query, sync=False, **kwargs):
    "Delete all documents matching the given query inside the index."
    es = get_es()
    return es.delete_by_query(
        index=index,
        body={"query": query},
        # _source=False,
        # slices="auto",
        conflicts="proceed",
        wait_for_completion=sync,
        refresh=refresh_sync(sync),
        timeout=f"{MAX_REQUEST_TIMEOUT}s",
        scroll_size=settings.index_delete_by_query_batchsize,
        **kwargs,
    )


class IndexStats(NamedTuple):
    """Outcome of an indexing run."""

    indexed: int = 0
    failed: int = 0
    took: timedelta = timedelta(0)


async def _bulk(
    es: AsyncElasticsearch, actions: list[Action], sync: bool | None
) -> tuple[int, int]:
    """Issue one bulk request for an already-bounded list of actions.

    Returns `(indexed, failed)`. Per-document failures are logged and counted
    rather than aborting the run (`raise_on_error=False`) -- one bad document
    should not discard the rest of a large ingest; the count surfaces via
    `IndexStats.failed`. Transport-level errors still propagate.

    `chunk_size=len(actions)` stops the helper re-chunking behind our back:
    batching is the caller's job, and concurrency comes from several of these
    running at once. `max_chunk_bytes` remains as a safety net for the
    formatted-actions path, which cannot cheaply measure its own size.

    Deliberately undecorated: `anystore.decorators.error_handler` installs a
    *sync* wrapper, so on a coroutine function it returns the coroutine before
    anything can raise and its retry/backoff never runs. Retries come from
    `async_bulk(max_retries=...)` and the transport's own `max_retries` /
    `retry_on_status`, which do apply.
    """
    indexed, failures = await async_bulk(
        es,
        actions,
        max_retries=settings.max_retries,
        refresh=refresh_sync(sync),
        timeout=f"{MAX_REQUEST_TIMEOUT}s",
        request_timeout=MAX_REQUEST_TIMEOUT,  # Client-side timeout
        chunk_size=max(1, len(actions)),
        max_chunk_bytes=settings.indexer_max_chunk_bytes,
        raise_on_error=False,
    )
    failed = 0
    for failure in failures:
        # deleting something that is already gone is not a failure
        if failure.get("delete", {}).get("status") == 404:
            continue
        failed += 1
        if failed <= 10:  # log the first few only, avoid spam
            log.error("Bulk index error: %r" % failure)
    if failed > 10:
        log.error("... and %d more bulk errors (truncated)" % (failed - 10))
    return indexed, failed


class Indexer:
    """Transform entities and bulk-index them from a single process.

    The transform runs inline and each finished batch is handed to the event
    loop as an outstanding bulk request, so CPU and network overlap without
    any multiprocessing.
    """

    def __init__(
        self,
        dataset: str | None = None,
        chunk_size: int | None = None,
        batch_bytes: int | None = None,
        concurrency: int | None = None,
        sync: bool | None = False,
        **context: Any,
    ) -> None:
        self.dataset = dataset
        self.chunk_size = chunk_size or settings.indexer_chunk_size
        self.batch_bytes = batch_bytes or settings.indexer_batch_bytes
        self.concurrency = concurrency or settings.indexer_concurrency
        self.sync = sync
        self.context = context

    def index(self, entities: Iterable[EntityProxy]) -> IndexStats:
        """Transform and index a stream of entities."""
        if self.dataset is None:
            raise ValueError("Indexer needs a `dataset` to transform entities")
        entities = logged_items(
            entities, "Indexing", 10_000, item_name="entity", logger=log
        )
        batches = (
            format_batch(self.dataset, batch, **self.context)
            for batch in iter_batches(entities, self.chunk_size, self.batch_bytes)
        )
        return self._run(batches)

    def index_actions(self, actions: Actions) -> IndexStats:
        """Index a stream of already formatted actions."""
        actions = logged_items(actions, "Loading", 10_000, item_name="doc", logger=log)
        batches = iter_action_batches(actions, self.chunk_size)
        return self._run(batches)

    def _run(self, batches: Iterable[list[Action]]) -> IndexStats:
        return _get_loop().run_until_complete(self._run_async(batches))

    async def _run_async(self, batches: Iterable[list[Action]]) -> IndexStats:
        start = datetime.now()
        es = await get_async_ingest_es()
        indexed = 0
        failed = 0
        pending: set[asyncio.Task] = set()

        async def drain(done: set[asyncio.Task]) -> None:
            nonlocal indexed, failed
            for task in done:
                ok, errors = await task
                indexed += ok
                failed += errors

        try:
            for actions in batches:
                if not actions:
                    continue
                # Backpressure: never hold more than `concurrency` requests
                # open, which also bounds resident memory to
                # concurrency * batch_bytes.
                while len(pending) >= self.concurrency:
                    done, pending = await asyncio.wait(
                        pending, return_when=asyncio.FIRST_COMPLETED
                    )
                    await drain(done)
                pending.add(asyncio.create_task(_bulk(es, actions, self.sync)))
                # Yield to the loop so the requests we just queued actually get
                # written to their sockets before we block the loop on the next
                # transform. Without this the loop only runs when `pending` is
                # full, and the process idles through every round trip, which is
                # slower.
                await asyncio.sleep(0)

            while pending:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                await drain(done)
        except BaseException:
            # Fail loud, but do not abandon in-flight requests on a loop that
            # is reused across calls: cancel them and collect their results so
            # nothing surfaces later as "Task exception was never retrieved".
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            log.error(
                "Bulk indexing failed after %d indexed, %d failed" % (indexed, failed)
            )
            raise

        took = datetime.now() - start
        log.info(
            "Bulk indexing completed: %d successful, %d failed" % (indexed, failed),
            took=took,
        )
        return IndexStats(indexed, failed, took)


def iter_action_batches(
    actions: Actions, chunk_size: int | None = None
) -> Iterable[list[Action]]:
    """Batch already formatted actions by count.

    Unlike the entity path there is no free size proxy here (an `Action` would
    have to be serialized to measure it), so the byte bound is left to
    `async_bulk`'s `max_chunk_bytes`, which splits an oversized batch into
    several requests.
    """
    for batch in itertools.batched(
        actions, n=chunk_size or settings.indexer_chunk_size
    ):
        yield list(batch)


def bulk_actions(
    actions: Actions,
    chunk_size: int | None = None,
    max_concurrency: int | None = None,
    sync: bool | None = False,
) -> IndexStats:
    """Bulk index a stream of already formatted actions."""
    return Indexer(
        chunk_size=chunk_size,
        concurrency=max_concurrency,
        sync=sync,
    ).index_actions(actions)


@error_handler(logger=log, max_retries=settings.max_retries)
def index_safe(index, id, body, sync=False, **kwargs):
    """Index a single document and retry until it has been stored."""
    es = get_ingest_es()
    refresh = refresh_sync(sync)
    es.index(index=index, id=id, body=body, refresh=refresh, **kwargs)
    body["id"] = str(id)
    body.pop("text", None)
    return body


@error_handler(logger=log, max_retries=settings.max_retries)
def delete_safe(index: str, id: str, sync: bool | None = False):
    es = get_es()
    es.delete(index=index, id=id, ignore=[404], refresh=refresh_sync(sync))
