import itertools
import logging
from typing import Iterable

import fingerprints
from banal import ensure_list, first
from elasticsearch.helpers import scan
from followthemoney import model
from followthemoney.proxy import EntityProxy
from followthemoney.types import registry

from openaleph_search import __version__
from openaleph_search.core import get_es
from openaleph_search.index.indexes import (
    entities_read_index,
    entities_write_index,
)
from openaleph_search.index.util import (
    MAX_PAGE,
    MAX_REQUEST_TIMEOUT,
    MAX_TIMEOUT,
    NUMERIC_TYPES,
    authz_query,
    bulk_actions,
    delete_safe,
    unpack_result,
)

log = logging.getLogger(__name__)
PROXY_INCLUDES = [
    "schema",
    "properties",
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


def _entities_query(filters, authz, collection_id, schemata):
    filters = filters or []
    if authz is not None:
        filters.append(authz_query(authz))
    if collection_id is not None:
        filters.append({"term": {"collection_id": collection_id}})
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
    authz=None,
    collection_id=None,
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
        "query": _entities_query(filters, authz, collection_id, schemata),
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


def iter_adjacent(collection_id, entity_id):
    """Used for recursively deleting entities and their linked associations."""
    yield from iter_entities(
        includes=["collection_id"],
        collection_id=collection_id,
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
        raise RuntimeError("Caching not implemented")

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


def index_entity(entity, sync=False):
    """Index an entity."""
    return index_proxy(entity.collection, entity.to_proxy(), sync=sync)


def index_proxy(dataset: str, proxy: EntityProxy, sync=False):
    delete_entity(proxy.id, exclude=proxy.schema, sync=False)
    return index_bulk(dataset, [proxy], sync=sync)


def index_bulk(dataset: str, entities: Iterable[EntityProxy], sync=False):
    """Index a set of entities."""
    _entities = (format_proxy(p, dataset) for p in entities)
    _entities = (e for e in _entities if e is not None)
    bulk_actions(_entities, sync=sync)


def _numeric_values(type_, values):
    values = [type_.to_number(v) for v in ensure_list(values)]
    return [v for v in values if v is not None]


def get_geopoints(proxy: EntityProxy) -> list[dict[str, str]]:
    points = []
    if proxy.schema.is_a("Address"):
        lons = proxy.get("longitude")
        lats = proxy.get("latitude")
        for lon, lat in itertools.product(lons, lats):
            points.append({"lon": lon, "lat": lat})
    return points


def format_proxy(proxy: EntityProxy, dataset: str):
    """Apply final denormalisations to the index."""
    # Abstract entities can appear when profile fragments for a missing entity
    # are present.
    if proxy.schema.abstract:
        log.warning("Tried to index an abstract-typed entity: %r", proxy)
        return None

    # FIXME
    # a hack to display text previews in search for `Pages` `bodyText` property
    # will be removed again in `views.serializers.EntitySerializer` to reduce
    # api response size
    if proxy.schema.name == "Pages":
        proxy.add("bodyText", " ".join(proxy.get("indexText")))
    data = proxy.to_full_dict(matchable=True)
    data["schemata"] = list(proxy.schema.names)
    data["caption"] = proxy.caption

    names = data.get("names", [])
    fps = set([fingerprints.generate(name) for name in names])
    fps.update(names)
    data["fingerprints"] = [fp for fp in fps if fp is not None]

    # Slight hack: a magic property in followthemoney that gets taken out
    # of the properties and added straight to the index text.
    properties = data.get("properties")
    data["text"] = properties.pop("indexText", [])

    # integer casting
    numeric = {}
    for prop in proxy.iterprops():
        if prop.type in NUMERIC_TYPES:
            values = proxy.get(prop)
            numeric[prop.name] = _numeric_values(prop.type, values)
    # also cast group field for dates
    numeric["dates"] = _numeric_values(registry.date, data.get("dates"))
    data["numeric"] = numeric

    # geo data if entity is an Address
    if proxy.schema.is_a("Address"):
        data["geo_point"] = get_geopoints(proxy)

    data["dataset"] = dataset

    # Context data - from aleph system, not followthemoney.
    data["collection_id"] = first(data.get("collection_id")) or dataset  # FIXME
    data["role_id"] = first(data.get("role_id"))
    data["profile_id"] = first(data.get("profile_id"))
    data["mutable"] = False  # deprecated
    data["origin"] = ensure_list(data.get("origin"))
    # Logical simplifications of dates:
    created_at = ensure_list(data.get("created_at"))
    if len(created_at) > 0:
        data["created_at"] = min(created_at)
    updated_at = ensure_list(data.get("updated_at")) or created_at
    if len(updated_at) > 0:
        data["updated_at"] = max(updated_at)

    data["index_version"] = __version__

    # log.info("%s", pformat(data))
    entity_id = data.pop("id")
    return {
        "_id": entity_id,
        "_index": entities_write_index(proxy.schema),
        "_source": data,
    }


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
