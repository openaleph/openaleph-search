from datetime import datetime

from anystore.logging import get_logger
from anystore.types import SDict
from banal import ensure_list, first
from followthemoney import EntityProxy, model, registry
from ftmq.util import get_name_symbols, get_symbols

from openaleph_search.index.indexes import entities_write_index
from openaleph_search.mapping import NUMERIC_TYPES, Field
from openaleph_search.settings import __version__
from openaleph_search.transform.util import (
    get_geopoints,
    index_name_keys,
    index_name_parts,
    phonetic_names,
)
from openaleph_search.util import valid_dataset

log = get_logger(__name__)


def _numeric_values(type_, values) -> list[float]:
    values = [type_.to_number(v) for v in ensure_list(values)]
    return [v for v in values if v is not None]


def _get_symbols(entity: EntityProxy) -> set[str]:
    if entity.schema.is_a("LegalEntity"):
        return get_symbols(entity)
    symbols: set[str] = set()
    symbols.update(get_name_symbols(model["Person"], entity.names))
    symbols.update(get_name_symbols(model["Organization"], entity.names))
    return symbols


def format_entity(dataset: str, entity: EntityProxy) -> SDict | None:
    """Apply final denormalisations to the index."""
    # Abstract entities can appear when profile fragments for a missing entity
    # are present.
    if entity.schema.abstract:
        log.warning("Tried to index an abstract-typed entity: %r", entity)
        return None

    dataset = valid_dataset(dataset)

    data = entity.to_full_dict(matchable=True)

    data[Field.DATASET] = dataset
    data[Field.SCHEMATA] = list(entity.schema.names)
    data[Field.CAPTION] = entity.caption

    names = list(entity.names)
    data[Field.NAME_SYMBOLS] = list(_get_symbols(entity))
    data[Field.NAME_KEYS] = list(index_name_keys(entity.schema, names))
    data[Field.NAME_PARTS] = list(index_name_parts(entity.schema, names))
    data[Field.NAME_PHONETIC] = list(phonetic_names(entity.schema, names))

    # Slight hack: a magic property in followthemoney that gets taken out
    # of the properties and added straight to the index text.
    properties = data.get("properties", {})
    data["text"] = properties.pop("indexText", [])

    # length normalization
    data[Field.NUM_VALUES] = sum([len(v) for v in properties.values()])

    # integer casting
    numeric = {}
    for prop in entity.iterprops():
        if prop.type in NUMERIC_TYPES:
            values = entity.get(prop)
            numeric[prop.name] = _numeric_values(prop.type, values)
    # also cast group field for dates
    numeric["dates"] = _numeric_values(registry.date, data.get("dates"))
    data[Field.NUMERIC] = numeric

    # geo data if entity is an Address
    if "latitude" in entity.schema.properties:
        data[Field.GEO_POINT] = get_geopoints(entity)

    # Context data - from aleph system, not followthemoney. Probably deprecated soon
    data[Field.ROLE] = first(data.get("role_id", []))
    data[Field.PROFILE] = first(data.get("profile_id", []))
    data["mutable"] = False  # deprecated
    data[Field.ORIGIN] = ensure_list(data.get("origin"))
    # Logical simplifications of dates:
    created_at = ensure_list(data.get("created_at"))
    if len(created_at) > 0:
        data[Field.CREATED_AT] = min(created_at)
    updated_at = ensure_list(data.get("updated_at")) or created_at
    if len(updated_at) > 0:
        data[Field.UPDATED_AT] = max(updated_at)

    data[Field.INDEX_VERSION] = __version__
    data[Field.INDEX_TS] = datetime.now().isoformat()

    # log.info("%s", pformat(data))
    entity_id = data.pop("id")
    return {
        "_id": entity_id,
        "_index": entities_write_index(entity.schema),
        "_source": data,
        "_routing": dataset,
    }
