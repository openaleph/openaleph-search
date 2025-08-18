import asyncio
import itertools
from datetime import datetime
from typing import Generator, Iterable, TypeAlias

from anystore.decorators import error_handler
from anystore.io import logged_items
from anystore.logging import get_logger
from anystore.types import SDict
from banal import ensure_list
from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk
from followthemoney import EntityProxy

from openaleph_search.core import get_async_es, get_es
from openaleph_search.settings import Settings

log = get_logger(__name__)
settings = Settings()

BULK_PAGE = 1000
# cf. https://www.elastic.co/guide/en/elasticsearch/reference/current/search-request-from-size.html  # noqa: B950
MAX_PAGE = 9999
MAX_TIMEOUT = "700m"
MAX_REQUEST_TIMEOUT = 84600

Actions: TypeAlias = Generator[SDict, None, None] | Iterable[SDict]


def refresh_sync(sync: bool | None = False) -> bool:
    return settings.testing or bool(sync)


def index_name(name: str, version: str) -> str:
    return "-".join((settings.index_prefix, name, version))


def unpack_result(res: SDict) -> SDict | None:
    """Turn a document hit from ES into a more traditional JSON object."""
    error = res.get("error")
    if error is not None:
        raise RuntimeError("Query error: %r" % error)
    if res.get("found") is False:
        return
    data = res.get("_source", {})
    data["id"] = res.get("_id")
    data["_index"] = res.get("_index")

    _score = res.get("_score")
    if _score is not None and _score != 0.0 and "score" not in data:
        data["score"] = _score

    if "highlight" in res:
        data["highlight"] = []
        for value in res.get("highlight", {}).values():
            data["highlight"].extend(value)

    data["_sort"] = ensure_list(res.get("sort"))
    return data


@error_handler(logger=log, max_retries=settings.elasticsearch_max_retries)
def query_delete(index, query, sync=False, **kwargs):
    "Delete all documents matching the given query inside the index."
    es = get_es()
    return es.delete_by_query(
        index=index,
        body={"query": query},
        # _source=False,
        slices="auto",
        conflicts="proceed",
        wait_for_completion=sync,
        refresh=refresh_sync(sync),
        request_timeout=MAX_REQUEST_TIMEOUT,
        timeout=MAX_TIMEOUT,
        scroll_size=settings.index_delete_by_query_batchsize,
        **kwargs,
    )


def bulk_actions(
    actions: Actions,
    chunk_size: int | None = BULK_PAGE,
    sync: bool | None = False,
    max_concurrency: int | None = settings.indexer_concurrency,
):
    """Bulk indexing with parallel async processing - entry point for sync
    applications"""
    return asyncio.run(bulk_actions_async(actions, chunk_size, sync, max_concurrency))


@error_handler(logger=log, max_retries=settings.elasticsearch_max_retries)
async def process_chunk(es: AsyncElasticsearch, chunk_actions, sync: bool):
    result = await async_bulk(
        es,
        chunk_actions,
        max_retries=settings.elasticsearch_max_retries,
        refresh=refresh_sync(sync),
        request_timeout=MAX_REQUEST_TIMEOUT,
    )
    success, failed = result
    for failure in failed:
        if failure.get("delete", {}).get("status") == 404:
            continue
        log.warning("Bulk index error: %r" % failure)
    return success, failed


async def bulk_actions_async(
    actions: Actions,
    chunk_size: int | None = BULK_PAGE,
    sync: bool | None = False,
    max_concurrency: int | None = settings.indexer_concurrency,
):
    """Async parallel bulk indexing with concurrency control."""
    start = datetime.now()

    es = await get_async_es()

    actions = logged_items(actions, "Index", 1_000, item_name="action", logger=log)
    chunks = itertools.batched(actions, n=chunk_size or BULK_PAGE)
    max_concurrency = max_concurrency or settings.indexer_concurrency
    semaphore = asyncio.Semaphore(max_concurrency)

    success = 0
    errors = 0

    for chunk in chunks:
        async with semaphore:
            res = await process_chunk(es, chunk, sync)
            success += res[0]
            errors += len(res[1])

    end = datetime.now()
    log.info(
        "Bulk indexing completed: %d successful, %d failed" % (success, errors),
        took=end - start,
    )
    await es.close()


@error_handler(logger=log, max_retries=settings.elasticsearch_max_retries)
def index_safe(index, id, body, sync=False, **kwargs):
    """Index a single document and retry until it has been stored."""
    es = get_es()
    refresh = refresh_sync(sync)
    es.index(index=index, id=id, body=body, refresh=refresh, **kwargs)
    body["id"] = str(id)
    body.pop("text", None)
    return body


@error_handler(logger=log, max_retries=settings.elasticsearch_max_retries)
def delete_safe(index, id, sync=False):
    es = get_es()
    es.delete(index=index, id=str(id), ignore=[404], refresh=refresh_sync(sync))


def _check_response(index, res):
    """Check if a request succeeded."""
    if res.get("status", 0) > 399 and not res.get("acknowledged"):
        error = res.get("error", {}).get("reason")
        log.error("Index [%s] error: %s" % (index, error))
        return False
    return True


@error_handler(logger=log, max_retries=settings.elasticsearch_max_retries)
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


def check_settings_changed(updated, existing):
    """Since updating the settings requires closing the index, we don't
    want to do it unless it's really needed. This will check if all the
    updated settings are already in effect."""
    if not isinstance(updated, dict) or not isinstance(existing, dict):
        return updated != existing
    for key, value in list(updated.items()):
        if check_settings_changed(value, existing.get(key)):
            return True
    return False


@error_handler(logger=log, max_retries=settings.elasticsearch_max_retries)
def configure_index(index, mapping, settings):
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
        settings.get("index").pop("number_of_shards")
        if check_settings_changed(settings, config.get("settings")):
            res = es.indices.close(ignore_unavailable=True, **options)
            res = es.indices.put_settings(body=settings, **options)
            if not _check_response(index, res):
                return False
        mapping = rewrite_mapping_safe(mapping, config.get("mappings"))
        res = es.indices.put_mapping(body=mapping, **options)
        if not _check_response(index, res):
            return False
        res = es.indices.open(**options)
        return True
    else:
        log.info("Creating index: %s..." % index)
        body = {"settings": settings, "mappings": mapping}
        res = es.indices.create(index=index, body=body)
        if not _check_response(index, res):
            return False
        return True


def index_settings(
    shards: int | None = settings.index_shards,
    replicas: int | None = settings.index_replicas,
):
    """Configure an index in ES with support for text transliteration."""
    if settings.testing:
        shards = 1
        replicas = 0
    return {
        "index": {
            "number_of_shards": str(shards),
            "number_of_replicas": str(replicas),
            # "refresh_interval": refresh,
        }
    }


def routing_key(dataset: str) -> str:
    if not dataset:
        raise RuntimeError("Invalid routing key")
    return dataset


def entity_routing_key(e: EntityProxy) -> str:
    """Use the dataset as a shard routing key"""
    dataset = getattr(e, "dataset", None)
    if dataset in (None, "default"):
        raise RuntimeError(f"Invalid dataset: `{dataset}`")
    return routing_key(dataset)
