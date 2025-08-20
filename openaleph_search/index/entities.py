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
from openaleph_search.transform.entity import format_entities

log = logging.getLogger(__name__)
PROXY_INCLUDES = [
    "schema",
    "properties",
    "dataset",
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
    schemata: set[str] | None = None,
):
    filters = filters or []
    if auth is not None:
        filters.append(auth.datasets_query())
    if dataset is not None:
        filters.append({"term": {"dataset": dataset}})
    # if ensure_list(schemata):
    #     filters.append({"terms": {"schemata": ensure_list(schemata)}})
    return {"bool": {"filter": filters}}


def get_field_type(field):
    field = field.split(".")[-1]
    if field in registry.groups:
        return registry.groups[field]
    for prop in model.properties:
        if prop.name == field:
            return prop.type
    return registry.string


def iter_entities(
    auth: SearchAuth | None = None,
    dataset: str | None = None,
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
        "query": _entities_query(filters, auth, dataset, schemata),
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
    entities = {}
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
            entity_id = entity.get("id")
            entities[entity_id] = entity

    for i in ids:
        entity = entities.get(i)
        if entity is not None:
            yield entity


def get_entity(entity_id, **kwargs):
    """Fetch an entity from the index."""
    for entity in entities_by_ids(entity_id, cached=True, **kwargs):
        return entity


def index_proxy(dataset: str, proxy: EntityProxy, sync=False):
    delete_entity(proxy.id, exclude=proxy.schema, sync=False)
    return index_bulk(dataset, [proxy], sync=sync)


def index_bulk(dataset: str, entities: Iterable[EntityProxy], sync=False):
    """Index a set of entities."""
    actions = format_entities(dataset, entities)
    # actions = format_parallel(dataset, entities)
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
