from anystore.logging import get_logger
from banal import ensure_list, first
from followthemoney import EntityProxy, registry
from ftmq.util import get_symbols

from openaleph_search import __version__
from openaleph_search.index.indexes import entities_write_index
from openaleph_search.mapping import NUMERIC_TYPES, Field
from openaleph_search.transform.util import (
    get_geopoints,
    index_name_keys,
    index_name_parts,
    phonetic_names,
)

log = get_logger(__name__)


def _numeric_values(type_, values) -> list[float]:
    values = [type_.to_number(v) for v in ensure_list(values)]
    return [v for v in values if v is not None]


def format_entity(entity: EntityProxy, dataset: str):
    """Apply final denormalisations to the index."""
    # Abstract entities can appear when profile fragments for a missing entity
    # are present.
    if entity.schema.abstract:
        log.warning("Tried to index an abstract-typed entity: %r", entity)
        return None

    # FIXME
    # a hack to display text previews in search for `Pages` `bodyText` property
    # will be removed again in `views.serializers.EntitySerializer` to reduce
    # api response size
    if entity.schema.name == "Pages":
        entity.add("bodyText", " ".join(entity.get("indexText")))

    data = entity.to_full_dict(matchable=True)

    data[Field.DATASET] = dataset
    data[Field.SCHEMATA] = list(entity.schema.names)
    data[Field.CAPTION] = entity.caption

    names = list(entity.names)
    data[Field.NAME_SYMBOLS] = list(get_symbols(entity))
    data[Field.NAME_KEYS] = list(index_name_keys(entity.schema, names))
    data[Field.NAME_PARTS] = list(index_name_parts(entity.schema, names))
    data[Field.NAME_PHONETIC] = list(phonetic_names(entity.schema, names))

    # Slight hack: a magic property in followthemoney that gets taken out
    # of the properties and added straight to the index text.
    properties = data.get("properties", {})
    data["text"] = properties.pop("indexText", [])

    # integer casting
    numeric = {}
    for prop in entity.iterprops():
        if prop.type in NUMERIC_TYPES:
            values = entity.get(prop)
            numeric[prop.name] = _numeric_values(prop.type, values)
    # also cast group field for dates
    numeric["dates"] = _numeric_values(registry.date, data.get("dates"))
    data["numeric"] = numeric

    # geo data if entity is an Address
    if "latitude" in entity.schema.properties:
        data["geo_point"] = get_geopoints(entity)

    # Context data - from aleph system, not followthemoney.
    data["role_id"] = first(data.get("role_id", []))
    data["profile_id"] = first(data.get("profile_id", []))
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
        "_index": entities_write_index(entity.schema),
        "_source": data,
    }
