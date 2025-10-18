import asyncio
import itertools
from datetime import datetime
from typing import Any, Generator, Iterable, TypeAlias, TypedDict

from anystore.decorators import error_handler
from anystore.io import logged_items
from anystore.logging import get_logger
from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import BulkIndexError, async_bulk, bulk

from openaleph_search.core import (
    get_async_ingest_es,
    get_es,
    get_ingest_es,
)
from openaleph_search.index.util import (
    check_response,
    check_settings_changed,
    refresh_sync,
)
from openaleph_search.settings import Settings

log = get_logger(__name__)
settings = Settings()

MAX_TIMEOUT = "700m"
MAX_REQUEST_TIMEOUT = 84600


class Action(TypedDict):
    _id: str
    _index: str
    _source: dict[str, Any]


Actions: TypeAlias = Generator[Action, None, None] | Iterable[Action]


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


def bulk_actions(
    actions: Actions,
    chunk_size: int | None = settings.indexer_chunk_size,
    max_concurrency: int | None = settings.indexer_concurrency,
    sync: bool | None = False,
    debug: bool | None = None,
):
    """Bulk indexing with parallel async processing - entry point for sync
    applications

    Args:
        actions: Iterator/iterable of actions to index
        chunk_size: Number of actions per chunk
        max_concurrency: Maximum number of concurrent chunks
        sync: Whether to refresh index after operations
        debug: Enable instrumented debug version with extensive logging.
               If None (default), uses settings.indexer_debug
    """
    # Use setting default if not explicitly specified
    if debug is None:
        debug = settings.indexer_debug

    # shortcut for 1 worker
    if max_concurrency == 1:
        es = get_ingest_es()
        return bulk(
            es,
            actions,
            max_retries=settings.max_retries,
            chunk_size=settings.indexer_chunk_size,
            max_chunk_bytes=settings.indexer_max_chunk_bytes,
        )

    # Use debug version if requested
    if debug:
        from openaleph_search.index.debug import bulk_actions_async_debug

        return asyncio.run(
            bulk_actions_async_debug(actions, chunk_size, max_concurrency, sync)
        )

    return asyncio.run(bulk_actions_async(actions, chunk_size, max_concurrency, sync))


@error_handler(logger=log, max_retries=settings.max_retries)
async def process_chunk(es: AsyncElasticsearch, chunk_actions, sync: bool):
    try:
        result = await async_bulk(
            es,
            chunk_actions,
            max_retries=settings.max_retries,
            refresh=refresh_sync(sync),
            timeout=f"{MAX_REQUEST_TIMEOUT}s",
            request_timeout=MAX_REQUEST_TIMEOUT,  # Client-side timeout
            chunk_size=settings.indexer_chunk_size,
            max_chunk_bytes=settings.indexer_max_chunk_bytes,
        )
        success, failed = result
        for failure in failed:
            if failure.get("delete", {}).get("status") == 404:
                continue
            log.warning("Bulk index error: %r" % failure)
        return success, failed
    except BulkIndexError as e:
        log.error(f"BulkIndexError: {len(e.errors)} document(s) failed to index")
        log.error(f"Error details: {e}")

        # Log detailed information about each failed document
        for i, error in enumerate(e.errors[:10]):  # Log first 10 errors to avoid spam
            log.error(f"Document {i + 1} error: {error}")

        if len(e.errors) > 10:
            log.error(f"... and {len(e.errors) - 10} more errors (truncated)")

        # Re-raise the exception to maintain existing error handling
        raise


async def bulk_actions_async(
    actions: Actions,
    chunk_size: int | None = settings.indexer_chunk_size,
    max_concurrency: int | None = settings.indexer_concurrency,
    sync: bool | None = False,
):
    """Process chunks as they complete to limit memory usage."""
    start = datetime.now()
    es = await get_async_ingest_es()
    actions = logged_items(actions, "Loading", 10_000, item_name="doc", logger=log)
    chunks = itertools.batched(actions, n=chunk_size or settings.indexer_chunk_size)
    max_concurrency = max_concurrency or settings.indexer_concurrency
    semaphore = asyncio.Semaphore(max_concurrency)

    async def process_chunk_with_semaphore(chunk):
        async with semaphore:
            return await process_chunk(es, chunk, sync)

    success = 0
    errors = 0
    pending_tasks = set()

    try:
        for chunk in chunks:
            # Create task
            task = asyncio.create_task(process_chunk_with_semaphore(list(chunk)))
            pending_tasks.add(task)

            # Process completed tasks when we hit concurrency limit
            if len(pending_tasks) >= max_concurrency:
                done, pending_tasks = await asyncio.wait(
                    pending_tasks, return_when=asyncio.FIRST_COMPLETED
                )

                for task in done:
                    try:
                        result = await task
                        success += result[0]
                        errors += len(result[1])
                    except Exception as e:
                        log.error(f"Chunk processing failed: {e}")
                        errors += 1

        # Process remaining tasks
        if pending_tasks:
            results = await asyncio.gather(*pending_tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    log.error(f"Chunk processing failed: {result}")
                    errors += 1
                else:
                    success += result[0]
                    errors += len(result[1])

    finally:
        await es.close()

    end = datetime.now()
    log.info(
        "Bulk indexing completed: %d successful, %d failed" % (success, errors),
        took=end - start,
    )


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


@error_handler(logger=log, max_retries=settings.max_retries)
def rewrite_mapping_safe(pending, existing):
    """This re-writes mappings for ElasticSearch in such a way that
    immutable values are kept to their existing setting, while other
    fields are updated."""
    IMMUTABLE = ("type", "analyzer", "normalizer", "index", "store")
    # This is a pretty bad idea long-term. We need to make it easier
    # to use multiple index generations instead.
    if not isinstance(pending, dict) or not isinstance(existing, dict):
        return pending
    for key, value in list(pending.items()):
        old_value = existing.get(key)
        value = rewrite_mapping_safe(value, old_value)
        if key in IMMUTABLE and old_value is not None:
            value = old_value
        pending[key] = value
    for key, value in existing.items():
        if key not in pending:
            pending[key] = value
    return pending


@error_handler(logger=log, max_retries=settings.max_retries)
def configure_index(index, mapping, settings_):
    """Create or update a search index with the given mapping and
    SETTINGS. This will try to make a new index, or update an
    existing mapping with new properties.
    """
    es = get_es()
    if es.indices.exists(index=index):
        log.info("Configuring index: %s..." % index)
        options = {
            "index": index,
            "timeout": MAX_TIMEOUT,
            "master_timeout": MAX_TIMEOUT,
        }
        config = es.indices.get(index=index).get(index, {})
        settings_.get("index").pop("number_of_shards", settings.index_shards)
        if check_settings_changed(settings_, config.get("settings")):
            res = es.indices.close(ignore_unavailable=True, **options)
            res = es.indices.put_settings(body=settings_, **options)
            if not check_response(index, res):
                return False
        mapping = rewrite_mapping_safe(mapping, config.get("mappings"))
        res = es.indices.put_mapping(body=mapping, **options)
        if not check_response(index, res):
            return False
        res = es.indices.open(**options)
        return True
    else:
        log.info("Creating index: %s..." % index)
        body = {"settings": settings_, "mappings": mapping}
        res = es.indices.create(index=index, body=body)
        if not check_response(index, res):
            return False
        return True
