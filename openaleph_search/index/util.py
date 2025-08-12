import asyncio
import itertools
from typing import Generator, Iterable, TypeAlias

from anystore.decorators import error_handler
from anystore.logging import get_logger
from anystore.types import SDict
from banal import ensure_list, is_mapping
from elasticsearch.helpers import async_bulk
from followthemoney.types import registry

from openaleph_search.core import get_async_es, get_es
from openaleph_search.settings import Settings

log = get_logger(__name__)
settings = Settings()

BULK_PAGE = 500
# cf. https://www.elastic.co/guide/en/elasticsearch/reference/current/search-request-from-size.html  # noqa: B950
MAX_PAGE = 9999
NUMERIC_TYPES = (
    registry.number,
    registry.date,
)
MAX_TIMEOUT = "700m"
MAX_REQUEST_TIMEOUT = 84600

# Mapping shortcuts
DATE_FORMAT = "yyyy-MM-dd'T'HH:mm:ss||yyyy-MM-dd||yyyy-MM||yyyy"
PARTIAL_DATE = {"type": "date", "format": DATE_FORMAT}
TEXT = {
    "type": "text",
    "analyzer": "default",
    "search_analyzer": "default",
}
ANNOTATED_TEXT = {
    "type": "annotated_text",
    "analyzer": "default",
    "search_analyzer": "default",
}
KEYWORD = {"type": "keyword"}
KEYWORD_COPY = {"type": "keyword", "copy_to": "text"}
NUMERIC = {"type": "double"}
GEOPOINT = {"type": "geo_point"}

Actions: TypeAlias = Generator[SDict, None, None] | Iterable[SDict]


def refresh_sync(sync: bool | None = False) -> bool:
    if settings.testing:
        return True
    return True if sync else False


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


def authz_query(authz, field="collection_id"):
    """Generate a search query filter from an authz object."""
    # Hot-wire authorization entirely for admins.
    if authz.is_admin:
        return {"match_all": {}}
    collections = authz.collections(authz.READ)
    if not len(collections):
        return {"match_none": {}}
    return {"terms": {field: collections}}


def bool_query() -> SDict:
    return {"bool": {"should": [], "filter": [], "must": [], "must_not": []}}


def none_query(query: SDict | None = None) -> SDict:
    if query is None:
        query = bool_query()
    query["bool"]["must"].append({"match_none": {}})
    return query


def field_filter_query(field: str, values: str | Iterable[str]) -> SDict:
    """Need to define work-around for full-text fields."""
    values = ensure_list(values)
    if not len(values):
        return {"match_all": {}}
    if field in ["_id", "id"]:
        return {"ids": {"values": values}}
    if field in ["names"]:
        field = "fingerprints"
    if len(values) == 1:
        # if field in ['addresses']:
        #     field = '%s.text' % field
        #     return {'match_phrase': {field: values[0]}}
        return {"term": {field: values[0]}}
    return {"terms": {field: values}}


def range_filter_query(field: str, ops) -> SDict:
    return {"range": {field: ops}}


def filter_text(spec, invert=False):
    """Try to convert a given filter to a lucene query string."""
    # CAVEAT: This doesn't cover all filters used by aleph.
    if isinstance(spec, (list, tuple, set)):
        parts = [filter_text(s, invert=invert) for s in spec]
        return " ".join(parts)
    if not is_mapping(spec):
        return spec
    for op, props in spec.items():
        if op == "term":
            field, value = next(iter(props.items()))
            field = "-%s" % field if invert else field
            return '%s:"%s"' % (field, value)
        if op == "terms":
            field, values = next(iter(props.items()))
            parts = [{"term": {field: v}} for v in values]
            parts = [filter_text(p, invert=invert) for p in parts]
            predicate = " AND " if invert else " OR "
            text = predicate.join(parts)
            if len(parts) > 1:
                text = "(%s)" % text
            return text
        if op == "exists":
            field = props.get("field")
            field = "-%s" % field if invert else field
            return "%s:*" % field


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
async def bulk_actions_async(
    actions: Actions,
    chunk_size: int | None = BULK_PAGE,
    sync: bool | None = False,
    max_concurrency: int | None = settings.indexer_concurrency,
):
    """Async parallel bulk indexing with concurrency control."""
    es = await get_async_es()

    async def process_chunk(chunk_actions):
        try:
            result = await async_bulk(
                es,
                chunk_actions,
                chunk_size=chunk_size,
                max_retries=10,
                refresh=refresh_sync(sync),
                request_timeout=MAX_REQUEST_TIMEOUT,
            )
            success, failed = result
            failed_list = ensure_list(failed) if failed else []
            for failure in failed_list:
                if failure.get("delete", {}).get("status") == 404:
                    continue
                log.warning("Bulk index error: %r", failure)
            return success, failed_list
        except Exception as e:
            log.error("Bulk indexing chunk failed: %r", e)
            return 0, []

    chunks = itertools.batched(actions, n=BULK_PAGE)
    max_concurrency = max_concurrency or settings.indexer_concurrency
    semaphore = asyncio.Semaphore(max_concurrency)

    async def process_with_semaphore(chunk):
        async with semaphore:
            return await process_chunk(chunk)

    tasks = [process_with_semaphore(chunk) for chunk in chunks]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    total_success = 0
    total_failed = 0
    for result in results:
        if isinstance(result, Exception):
            log.error("Task failed with exception: %r", result)
            continue
        success, failed = result
        total_success += success
        total_failed += len(failed)

    log.info(
        "Bulk indexing completed: %d successful, %d failed", total_success, total_failed
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
        log.error("Index [%s] error: %s", index, error)
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
        log.info("Configuring index: %s...", index)
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
        log.info("Creating index: %s...", index)
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
