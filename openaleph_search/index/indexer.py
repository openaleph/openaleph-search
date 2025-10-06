from datetime import datetime
from typing import Any, Generator, Iterable, TypeAlias, TypedDict

from anystore.decorators import error_handler
from anystore.io import logged_items
from anystore.logging import get_logger
from elasticsearch.helpers import BulkIndexError, parallel_bulk

from openaleph_search.core import get_es, get_ingest_es
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
):
    """Bulk indexing with parallel processing using thread pool.

    Uses elasticsearch.helpers.parallel_bulk for efficient parallel indexing
    with controlled concurrency via thread pool.
    """
    start = datetime.now()
    es = get_ingest_es()
    chunk_size = chunk_size or settings.indexer_chunk_size
    max_concurrency = max_concurrency or settings.indexer_concurrency

    # Add logging wrapper
    actions = logged_items(actions, "Loading", 10_000, item_name="doc", logger=log)

    success = 0
    errors = 0

    try:
        # parallel_bulk yields (success, info) tuples for each action
        for ok, info in parallel_bulk(
            es,
            actions,
            thread_count=max_concurrency,
            chunk_size=chunk_size,
            max_chunk_bytes=settings.indexer_max_chunk_bytes,
            raise_on_error=False,
            refresh=refresh_sync(sync),
            request_timeout=MAX_REQUEST_TIMEOUT,
        ):
            if ok:
                success += 1
            else:
                errors += 1
                # info contains error details for failed operations
                action, error_info = info.popitem()
                # Skip 404 errors for delete operations
                if action == "delete" and error_info.get("status") == 404:
                    continue
                log.warning("Bulk index error: %s - %r" % (action, error_info))
    except BulkIndexError as e:
        log.error(f"BulkIndexError: {len(e.errors)} document(s) failed to index")
        log.error(f"Error details: {e}")

        # Log detailed information about each failed document
        for i, error in enumerate(e.errors[:10]):  # Log first 10 errors to avoid spam
            log.error(f"Document {i + 1} error: {error}")

        if len(e.errors) > 10:
            log.error(f"... and {len(e.errors) - 10} more errors (truncated)")

        raise

    end = datetime.now()
    log.info(
        "Bulk indexing completed: %d successful, %d failed" % (success, errors),
        took=end - start,
    )

    return success, errors


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
