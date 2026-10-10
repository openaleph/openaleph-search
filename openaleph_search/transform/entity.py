"""Transform followthemoney entities into index actions"""

import functools
import itertools
from datetime import datetime
from typing import Any, Iterable, Iterator

from anystore.logging import get_logger
from banal import ensure_list
from followthemoney import EntityProxy, model, registry
from followthemoney.namespace import Namespace
from followthemoney.schema import Schema
from followthemoney.types.common import PropertyType
from ftmq.aggregate import EntityPayload
from ftmq.util import SELECT_SYMBOLS, get_name_symbols
from rigour.names import NameTypeTag, analyze_names, pick_name

from openaleph_search.index.indexes import entities_write_index, schema_bucket
from openaleph_search.index.mapping import NUMERIC_TYPES, Field
from openaleph_search.settings import Settings, __version__
from openaleph_search.transform.util import (
    get_geopoints,
    index_name_keys,
    index_name_parts,
    make_percolator_query,
    phonetic_names,
)
from openaleph_search.util import (
    Action,
    Actions,
    EntityLike,
    ensure_schema,
    valid_dataset,
)

log = get_logger(__name__)
settings = Settings()


def _numeric_values(type_, values) -> list[float]:
    values = [type_.to_number(v) for v in ensure_list(values)]
    return [v for v in values if v is not None]


def _first(value):
    """First non-None item of a possibly merged (list-shaped) context value."""
    for item in ensure_list(value):
        if item is not None:
            return item
    return None


def _type_values(
    schema: Schema,
    properties: dict[str, list[str]],
    type_: PropertyType,
    matchable: bool = False,
) -> set[str]:
    """`EntityProxy.get_type_values` over a properties dict."""
    values: set[str] = set()
    for name, prop_values in properties.items():
        prop = schema.properties[name]
        if prop.type is type_ and (prop.matchable or not matchable):
            values.update(prop_values)
    return values


def _caption(schema: Schema, properties: dict[str, list[str]]) -> str:
    """`EntityProxy.caption` over a properties dict."""
    for name in schema.caption:
        values = properties.get(name)
        if not values:
            continue
        if schema.properties[name].type == registry.name and len(values) > 1:
            caption = pick_name(sorted(values))
            if caption is not None:
                return caption
        else:
            return values[0]
    return schema.label


def _get_symbols(
    schema: Schema, properties: dict[str, list[str]], names: set[str], texts: list[str]
) -> set[str]:
    # pre-computed in earlier stage, as `ftmq.util.select_symbols`
    symbols: set[str] = set()
    for text in texts:
        if text.startswith(SELECT_SYMBOLS):
            symbols.update(text.replace(SELECT_SYMBOLS, "").strip().split(","))
    if symbols:
        return symbols
    # sorted: the symbols `analyze_names` finds depend on the order of the names
    if schema.is_a("LegalEntity"):
        matchable = _type_values(schema, properties, registry.name, matchable=True)
        return {str(s) for s in get_name_symbols(schema, *sorted(matchable))}
    ordered = sorted(names)
    symbols.update(map(str, get_name_symbols(model["Person"], *ordered)))
    symbols.update(map(str, get_name_symbols(model["Organization"], *ordered)))
    return symbols


def _get_translations(texts: list[str]) -> set[str]:
    prefix = "__translation__"
    return {t.replace(prefix, "").strip() for t in texts if t.startswith(prefix)}


def _cap_text(texts: list[str], limit: int) -> list[str]:
    """Truncate `texts` to `limit` UTF-8 bytes in total, keeping order."""
    # 4 bytes is the widest UTF-8 character: skips encoding for all but huge text
    if sum(len(t) for t in texts) * 4 <= limit:
        return texts
    capped: list[str] = []
    for text in texts:
        data = text.encode()
        if len(data) > limit:
            tail = data[:limit].decode(errors="ignore")
            if tail:
                capped.append(tail)
            return capped
        capped.append(text)
        limit -= len(data)
    return texts


@functools.cache
def _get_namespace(value: str) -> Namespace:
    return Namespace(value)


def _sign_ids(
    ns: Namespace,
    schema: Schema,
    data: dict[str, Any],
    properties: dict[str, list[str]],
) -> None:
    """`Namespace.apply` on entity data, in place and without its clone."""
    data["id"] = ns.sign(data["id"])
    for name, values in properties.items():
        if schema.properties[name].type is registry.entity:
            properties[name] = [signed for signed in map(ns.sign, values) if signed]


def _entity_data(entity: EntityLike) -> tuple[Schema, dict[str, Any], str | None]:
    """The schema, a copy of the data to modify, and the caption if known.
    Data that is not a proxy is trusted: only its properties are limited to the
    schema, as the `EntityProxy` constructor does."""
    if isinstance(entity, EntityProxy):
        # `StatementEntity.caption` prefers the system language
        return entity.schema, entity.to_dict(), entity.caption
    if isinstance(entity, EntityPayload):
        entity = entity.to_dict()
    if not entity.get("id"):
        raise ValueError("Entity has no ID.")
    data = dict(entity)
    schema = ensure_schema(data["schema"])
    data["properties"] = {
        name: values
        for name, values in (data.get("properties") or {}).items()
        if name in schema.properties
    }
    return schema, data, data.get(Field.CAPTION)


def entity_size(entity: EntityLike) -> int:
    """Summed length of all property values, as `EntityProxy._size`."""
    if isinstance(entity, EntityProxy):
        return entity._size
    if isinstance(entity, EntityPayload):
        entity = entity.to_dict()
    values = (entity.get("properties") or {}).values()
    return sum(map(len, itertools.chain.from_iterable(values)))


@functools.cache
def _warm_rigour_taggers() -> None:
    # Force rigour's Rust-backed AC name taggers to load in this process, so
    # the ~3.5s cold-load is paid once per process instead of on the first
    # `analyze_names` call in the middle of a batch.
    analyze_names(NameTypeTag.PER, ["x"])
    analyze_names(NameTypeTag.ORG, ["x"])


def format_entity(dataset: str, entity: EntityLike, **kwargs) -> Action | None:
    """Apply final denormalisations to the index. Trusted entity data (an
    `EntityPayload` or a dict) is transformed without building a proxy; the
    input is not modified."""
    schema, data, caption = _entity_data(entity)
    properties: dict[str, list[str]] = data["properties"]

    # Abstract entities can appear when profile fragments for a missing entity
    # are present.
    if schema.abstract:
        log.warning(
            "Tried to index an abstract-typed entity!",
            schema=schema.name,
            entity_id=data["id"],
        )
        return None

    if settings.index_namespace_ids:
        # Enforce namespaced IDs
        _sign_ids(_get_namespace(dataset), schema, data, properties)

    dataset = valid_dataset(dataset)

    # deprecated
    collection_id = kwargs.get("collection_id")
    if collection_id is None:
        # merged context is list-shaped, see CONTEXT DATA below
        collection_id = _first(data.pop(Field.COLLECTION_ID, None))
    if collection_id is not None:
        data[Field.COLLECTION_ID] = collection_id

    data[Field.DATASET] = dataset
    data[Field.SCHEMATA] = list(schema.names)
    data[Field.CAPTION] = caption or _caption(schema, properties)

    # Slight hack: a magic property in followthemoney that gets taken out
    # of the properties and added straight to the index text.
    text = properties.pop("indexText", [])

    # all names, including mentioned ones, for lookups
    names = _type_values(schema, properties, registry.name)
    symbols = list(_get_symbols(schema, properties, names, text))
    if symbols:
        data[Field.NAME_SYMBOLS] = symbols
    name_keys = list(index_name_keys(schema, names))
    if name_keys:
        data[Field.NAME_KEYS] = name_keys
    name_parts = list(index_name_parts(schema, names))
    if name_parts:
        data[Field.NAME_PARTS] = name_parts
    name_phonetics = list(phonetic_names(schema, names))
    if name_phonetics:
        data[Field.NAME_PHONETIC] = name_phonetics

    # Add tags from the entity context (they are added from aleph db before
    # indexing)
    tags = ensure_list(data.get("tags"))
    if tags:
        data[Field.TAGS] = tags

    capped = _cap_text(text, settings.indexer_max_text_bytes)
    if capped is not text:
        log.warning(
            "Truncated `indexText` to %d bytes" % settings.indexer_max_text_bytes,
            entity_id=data["id"],
        )
        text = capped

    # Another hack: Translations are prefixed with "__translation__" in
    # `Pages.indexText`
    if schema.name == "Pages":
        translations = _get_translations(text)
        if translations:
            data[Field.TRANSLATION] = list(translations)
            text = [t for t in text if not t.startswith("__translation__")]

    if text:
        data[Field.CONTENT] = text

    # length normalization
    data[Field.NUM_VALUES] = sum([len(v) for v in properties.values()])

    # Stored percolator query — only for entities in the things bucket
    # (Person, Company, Organization, …). Documents/Pages/Intervals never
    # get one. Entities whose name list is empty after cleaning get no
    # `query` field at all so they stay out of the percolator candidate
    # set. Globally gated by the `percolation` setting.
    #
    # Source the percolator names from `name` + `previousName` + `alias` only —
    # NOT `weakAlias`, which is too loose and causes significant false
    # positives.
    #
    # Main `name`s are passed separately so `make_percolator_query` can boost it
    # above `previousName`/`alias` (which go into one `other_name` group,
    # demoted in ranking)
    if settings.percolation and schema.is_a("Thing"):
        other_names = list(properties.get("previousName", []))
        other_names.extend(properties.get("alias", []))
        percolator_query = make_percolator_query(
            list(properties.get("name", [])),
            other_names=other_names,
        )
        if percolator_query is not None:
            data[Field.QUERY] = percolator_query

    # integer casting
    numeric = {}
    # parse each date once, for its property and for the `dates` group
    dates: dict[str, float | None] = {}
    for name, values in properties.items():
        type_ = schema.properties[name].type
        if type_ is registry.date:
            for value in values:
                if value not in dates:
                    dates[value] = type_.to_number(value)
            numeric[name] = [n for n in map(dates.get, values) if n is not None]
        elif type_ in NUMERIC_TYPES:
            numeric[name] = _numeric_values(type_, values)
    # also cast group field for dates
    date_values = [n for n in dates.values() if n is not None]
    if date_values:
        numeric["dates"] = date_values
    if numeric:
        data[Field.NUMERIC] = numeric

    # geo data if entity is an Address
    if "latitude" in schema.properties:
        data[Field.GEO_POINT] = get_geopoints(properties)

    # CONTEXT DATA
    # from aleph system, not followthemoney. Probably deprecated soon
    # Entities aggregated from multiple fragments carry *merged*
    # context: followthemoney's ``merge_context`` turns every scalar
    # context value into a deduped list (e.g. origins ingest +
    # analyze → ``role_id: [36]``, ``mutable: [False]``), as does
    # ``ftmq.aggregate.aggregate_fragments_unsafe`` even for a single
    # fragment. The
    # ``_entity_data`` above spread that raw shape into ``data``,
    # so fold every context key back to the scalar shape the index
    # contract expects. Only ``origin`` is legitimately multi-valued.
    role_id = _first(data.pop(Field.ROLE, None))
    if role_id is not None:
        data[Field.ROLE] = role_id
    profile_id = _first(data.pop(Field.PROFILE, None))
    if profile_id is not None:
        data[Field.PROFILE] = profile_id
    origin = ensure_list(data.pop(Field.ORIGIN, None))
    if origin:
        data[Field.ORIGIN] = origin
    # Fold merged booleans conservatively: if any fragment marked the
    # entity immutable, it stays immutable.
    mutable = [bool(v) for v in ensure_list(data.pop(Field.MUTABLE, None))]
    data[Field.MUTABLE] = all(mutable) if mutable else False
    # Logical simplifications of dates:
    created_at = ensure_list(data.pop(Field.CREATED_AT, None))
    if len(created_at) > 0:
        data[Field.CREATED_AT] = min(created_at)
    updated_at = ensure_list(data.pop(Field.UPDATED_AT, None)) or created_at
    if len(updated_at) > 0:
        data[Field.UPDATED_AT] = max(updated_at)

    data[Field.INDEX_BUCKET] = schema_bucket(data["schema"])
    data[Field.INDEX_VERSION] = __version__
    data[Field.INDEX_TS] = datetime.now().isoformat()

    if settings.auth_field not in data:
        raise RuntimeError(
            f"Auth field missing in entity data: `{settings.auth_field}`"
        )

    # log.info("%s", pformat(data))
    entity_id = data.pop("id")
    return {
        "_id": entity_id,
        "_index": entities_write_index(schema),
        "_source": data,
    }


def format_entities(dataset: str, entities: Iterable[EntityLike], **kwargs) -> Actions:
    """Lazily transform a stream of entities into index actions."""
    _warm_rigour_taggers()
    for entity in entities:
        formatted = format_entity(dataset, entity, **kwargs)
        if formatted is not None:
            yield formatted


def format_batch(
    dataset: str, entities: Iterable[EntityLike], **kwargs
) -> list[Action]:
    _warm_rigour_taggers()
    actions = []
    for entity in entities:
        formatted = format_entity(dataset, entity, **kwargs)
        if formatted is not None:
            actions.append(formatted)
    return actions


def iter_batches(
    entities: Iterable[EntityLike],
    chunk_size: int | None = None,
    batch_bytes: int | None = None,
) -> Iterator[list[EntityLike]]:
    """Batch a stream of entities by entity count and payload bytes, cutting on
    whichever limit is reached first.

    A count-only bound is wrong in both directions: 1000 document entities can
    be 100MB (far past a sensible bulk request), while 1000 `Person`s can only
    be ~100KB (far below one). `entity_size` measures roughly the entity's JSON
    size
    """
    chunk_size = chunk_size or settings.indexer_chunk_size
    batch_bytes = batch_bytes or settings.indexer_batch_bytes
    batch: list[EntityLike] = []
    nbytes = 0
    for entity in entities:
        batch.append(entity)
        nbytes += entity_size(entity)
        if len(batch) >= chunk_size or nbytes >= batch_bytes:
            yield batch
            batch, nbytes = [], 0
    if batch:
        yield batch
