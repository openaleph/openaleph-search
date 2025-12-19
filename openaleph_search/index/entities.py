import logging
from typing import Any, Iterable

from banal import ensure_list
from elasticsearch.helpers import scan
from followthemoney import model
from followthemoney.proxy import EntityProxy
from followthemoney.types import registry

from openaleph_search.core import get_es
from openaleph_search.index.indexer import (
    MAX_REQUEST_TIMEOUT,
    MAX_TIMEOUT,
    bulk_actions,
    delete_safe,
)
from openaleph_search.index.indexes import (
    entities_read_index,
    entities_write_index,
)
from openaleph_search.index.util import unpack_result
from openaleph_search.model import SearchAuth
from openaleph_search.settings import MAX_PAGE
from openaleph_search.transform.entity import format_parallel

log = logging.getLogger(__name__)
PROXY_INCLUDES = [
    "caption",
    "schema",
    "properties",
    "tags",
    "dataset",
    "collection_id",
    "profile_id",
    "role_id",
    "mutable",
    "created_at",
    "updated_at",
]
ENTITY_SOURCE = {"includes": PROXY_INCLUDES}


def _source_spec(includes, excludes):
    includes = ensure_list(includes)
    excludes = ensure_list(excludes)
    return {"includes": includes, "excludes": excludes}


def _entities_query(
    filters: list[Any],
    auth: SearchAuth | None = None,
    dataset: str | None = None,
    collection_id: str | None = None,
    schemata: set[str] | None = None,
):
    filters = filters or []
    if auth is not None:
        filters.append(auth.datasets_query())
    if collection_id is not None:
        filters.append({"term": {"collection_id": collection_id}})
    elif dataset is not None:
        filters.append({"term": {"dataset": dataset}})
    if ensure_list(schemata):
        filters.append({"terms": {"schemata": ensure_list(schemata)}})
    return {"bool": {"filter": filters}}


def iter_entities(
    auth: SearchAuth | None = None,
    dataset: str | None = None,
    collection_id: str | None = None,
    schemata=None,
    includes=PROXY_INCLUDES,
    excludes=None,
    filters=None,
    sort=None,
    es_scroll="5m",
    es_scroll_size=1000,
):
    """Scan all entities matching the given criteria."""
    query = {
        "query": _entities_query(filters, auth, dataset, collection_id, schemata),
        "_source": _source_spec(includes, excludes),
    }
    preserve_order = False
    if sort is not None:
        query["sort"] = ensure_list(sort)
        preserve_order = True
    index = entities_read_index(schema=schemata)
    es = get_es()
    for res in scan(
        es,
        index=index,
        query=query,
        timeout=MAX_TIMEOUT,
        request_timeout=MAX_REQUEST_TIMEOUT,
        preserve_order=preserve_order,
        scroll=es_scroll,
        size=es_scroll_size,
    ):
        entity = unpack_result(res)
        if entity is not None:
            yield entity


def iter_entity_ids(
    auth: SearchAuth | None = None,
    dataset: str | None = None,
    collection_id: str | None = None,
    schemata=None,
    filters=None,
    sort=None,
    index: str | None = None,
    es_scroll="5m",
    es_scroll_size=10000,
):
    """Scan entity IDs matching the given criteria (no source fields fetched).

    When sorting by _id, uses search_after with PIT (Point in Time) API instead of
    scroll, as _id sorting requires special handling in Elasticsearch.

    Args:
        auth: Optional auth filter
        dataset: Optional dataset filter
        collection_id: Optional collection ID filter
        schemata: Optional schema filter (used to determine index if index not provided)
        filters: Optional additional ES filters
        sort: Optional sort specification
        index: Optional explicit index name (overrides schemata-based index resolution)
        es_scroll: Scroll timeout
        es_scroll_size: Number of documents per scroll batch

    Yields:
        Entity IDs matching the criteria
    """
    if index is None:
        index = entities_read_index(schema=schemata)
    es = get_es()

    # Check if we're sorting by _id - this requires special handling
    sort_list = ensure_list(sort) if sort is not None else None
    uses_id_sort = sort_list and any(
        "_id" in s if isinstance(s, dict) else s == "_id" for s in sort_list
    )

    if uses_id_sort:
        # Use search_after with PIT for _id sorting
        # _id sorting requires fetching docs and sorting in memory, as ES doesn't allow
        # fielddata on _id. We do this in batches with search_after.

        # Translate _id sort to use search_after without requiring fielddata
        # We'll use _shard_doc for pagination and sort the results in memory
        pit = es.open_point_in_time(index=index, keep_alive=es_scroll)
        pit_id = pit["id"]

        try:
            # First, collect all IDs using _shard_doc for efficient pagination
            all_ids = []
            query_body = {
                "query": _entities_query(
                    filters, auth, dataset, collection_id, schemata
                ),
                "_source": False,
                "size": es_scroll_size,
                "sort": ["_shard_doc"],  # Use _shard_doc for efficient pagination
                "pit": {"id": pit_id, "keep_alive": es_scroll},
            }

            while True:
                response = es.search(
                    **query_body,
                    timeout=MAX_TIMEOUT,
                    request_timeout=MAX_REQUEST_TIMEOUT,
                )
                hits = response["hits"]["hits"]

                if not hits:
                    break

                for hit in hits:
                    all_ids.append(hit["_id"])

                # Update search_after for next page
                query_body["search_after"] = hits[-1]["sort"]
                # Update PIT ID (it may change between requests)
                query_body["pit"]["id"] = response["pit_id"]

            # Now sort the IDs based on the requested sort order
            reverse = False
            if isinstance(sort_list[0], dict):
                # Handle {"_id": "desc"} format
                reverse = list(sort_list[0].values())[0] == "desc"

            all_ids.sort(reverse=reverse)

            # Yield sorted IDs
            for id in all_ids:
                yield id
        finally:
            # Close the point in time
            try:
                es.close_point_in_time(id=pit_id)
            except Exception as e:
                log.warning(f"Failed to close point in time: {e}")
    else:
        # Use standard scroll API for other cases
        query = {
            "query": _entities_query(filters, auth, dataset, collection_id, schemata),
            "_source": False,  # Don't fetch any source fields - much faster
        }
        preserve_order = False
        if sort is not None:
            query["sort"] = sort_list
            preserve_order = True

        for res in scan(
            es,
            index=index,
            query=query,
            timeout=MAX_TIMEOUT,
            request_timeout=MAX_REQUEST_TIMEOUT,
            preserve_order=preserve_order,
            scroll=es_scroll,
            size=es_scroll_size,
        ):
            yield res["_id"]


def iter_proxies(**kw):
    for data in iter_entities(**kw):
        schema = model.get(data.get("schema"))
        if schema is None:
            continue
        yield model.get_proxy(data)


def iter_adjacent(dataset, entity_id):
    """Used for recursively deleting entities and their linked associations."""
    yield from iter_entities(
        includes=["dataset"],
        dataset=dataset,
        filters=[{"term": {"entities": entity_id}}],
    )


def entities_by_ids(
    ids, schemata=None, cached=False, includes=PROXY_INCLUDES, excludes=None
):
    """Iterate over unpacked entities based on a search for the given
    entity IDs."""
    ids = ensure_list(ids)
    if not len(ids):
        return
    if cached:
        # raise RuntimeError("Caching not implemented")
        log.warning("Caching not implemented")

    index = entities_read_index(schema=schemata)

    query = {
        "query": {"ids": {"values": ids}},
        "_source": _source_spec(includes, excludes),
        "size": MAX_PAGE,
    }
    es = get_es()
    result = es.search(index=index, body=query)
    for doc in result.get("hits", {}).get("hits", []):
        entity = unpack_result(doc)
        if entity is not None:
            yield entity


def get_entity(entity_id, **kwargs):
    """Fetch an entity from the index."""
    for entity in entities_by_ids(entity_id, cached=False, **kwargs):
        return entity


def index_proxy(dataset: str, proxy: EntityProxy, sync=False, **kwargs):
    delete_entity(proxy.id, exclude=proxy.schema, sync=False)
    return index_bulk(dataset, [proxy], sync=sync, **kwargs)


def index_bulk(dataset: str, entities: Iterable[EntityProxy], sync=False, **kwargs):
    """Index a set of entities."""
    actions = format_parallel(dataset, entities, **kwargs)
    bulk_actions(actions, sync=sync)


def delete_entity(entity_id, exclude=None, sync=False):
    """Delete an entity from the index."""
    if exclude is not None:
        exclude = entities_write_index(exclude)
    for entity in entities_by_ids(entity_id, excludes="*"):
        index = entity.get("_index")
        if index == exclude:
            continue
        delete_safe(index, entity_id)


def checksums_count(checksums):
    """Query how many documents mention a checksum."""
    schemata = model.get_type_schemata(registry.checksum)
    index = entities_read_index(schemata)
    body = []
    for checksum in checksums:
        body.append({"index": index})
        query = {"term": {registry.checksum.group: checksum}}
        body.append({"size": 0, "query": query})
    es = get_es()
    results = es.msearch(body=body)
    for checksum, result in zip(checksums, results.get("responses", [])):
        total = result.get("hits", {}).get("total", {}).get("value", 0)
        yield checksum, total
