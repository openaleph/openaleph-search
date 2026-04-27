"""
Index mappings
"""

from collections import defaultdict as ddict
from typing import Any, Iterable, TypeAlias

from followthemoney import model
from followthemoney.types import registry

from openaleph_search.settings import Settings
from openaleph_search.util import SchemaType

settings = Settings()

MappingProperty: TypeAlias = dict[str, Any]
Mapping: TypeAlias = dict[str, MappingProperty]

PROP_TRANSLATED = "translatedText"

# MAPPING SHORTCUTS #
DEFAULT_ANALYZER = "default"
DEFAULT_NORMALIZER = "default"
ICU_ANALYZER = "icu-default"
ICU_SEARCH_ANALYZER = "icu-search-synonyms"
ICU_NORMALIZER = "icu-default"
HTML_ANALYZER = "strip-html"
KW_NORMALIZER = "kw-normalizer"
NAME_KW_NORMALIZER = "name-kw-normalizer"
# Field-level `format` for date properties. The hour-only-after-T variant
# (`yyyy-MM-dd'T'HH`) is **load-bearing** — FtM's `prefixdate.parse(...).text`
# canonically emits that shape, and ES `strict_date_optional_time` does
# *not* parse it (it requires `HH:mm` minimum after the `T`). Order is
# the historical one so existing indexes don't see a `format` change at
# upgrade time (ES blocks mutating the `format` parameter on a live
# date field).
DATE_FORMAT = "yyyy-MM-dd'T'HH||yyyy-MM-dd'T'HH:mm||yyyy-MM-dd'T'HH:mm:ss||yyyy-MM-dd||yyyy-MM||yyyy||strict_date_optional_time"  # noqa: B950
# Format used by date aggregations (`date_histogram`, etc.) for two
# things:
#   1. Output serialization of bucket `key_as_string` — ES uses the first
#      entry in a `||` list, so leading with `strict_date_optional_time`
#      gives canonical ISO 8601 (e.g. `1970-08-21T00:00:00.000Z`).
#   2. Input parsing of `extended_bounds.min` / `max` — ES falls through
#      the `||` list until one entry parses the bound value. The trailing
#      partial-date entries cover FtM-emitted shapes (`2021`, `2021-02`,
#      `2021-02-16T21`, …) that a caller might pass as a filter bound;
#      `strict_date_optional_time` alone would reject the hour-only form.
# Decoupled from `DATE_FORMAT` so the field-level format can keep its
# original order (upgrade-stable on existing indexes) while aggregation
# output stays canonical for downstream consumers.
DATE_AGG_FORMAT = "strict_date_optional_time||yyyy-MM-dd'T'HH||yyyy-MM-dd'T'HH:mm||yyyy-MM-dd'T'HH:mm:ss||yyyy-MM-dd||yyyy-MM||yyyy"  # noqa: B950
NUMERIC_TYPES = (registry.number, registry.date)

# INDEX SETTINGS #
ANALYZE_SETTINGS = {
    "analysis": {
        "char_filter": {
            "remove_punctuation": {
                "type": "pattern_replace",
                "pattern": "[^\\p{L}\\p{N}]",
                "replacement": " ",
            },
            "squash_spaces": {
                "type": "pattern_replace",
                "pattern": "\\s+",
                "replacement": " ",
            },
        },
        "filter": {
            "ann_capture": {
                "type": "pattern_capture",
                "preserve_original": False,
                "patterns": ["([^\u200d]+)"],
            },
            "person_name_synonyms": {
                "type": "synonym_graph",
                "synonyms_path": "person_name_synonyms.txt",
                "updateable": True,
            },
        },
        "normalizer": {
            ICU_NORMALIZER: {
                "type": "custom",
                "filter": ["icu_folding"],
            },
            NAME_KW_NORMALIZER: {
                "type": "custom",
                "char_filter": ["remove_punctuation", "squash_spaces"],
                "filter": ["lowercase", "asciifolding", "trim"],
            },
            KW_NORMALIZER: {
                "type": "custom",
                "filter": ["trim"],
            },
        },
        "analyzer": {
            ICU_ANALYZER: {
                "char_filter": ["html_strip"],
                "tokenizer": "standard",
                "filter": [
                    "ann_capture",
                    "lowercase",
                    "icu_folding",
                ],
            },
            ICU_SEARCH_ANALYZER: {
                "char_filter": ["html_strip"],
                "tokenizer": "standard",
                "filter": [
                    "lowercase",
                    "person_name_synonyms",
                    "icu_folding",
                ],
            },
            HTML_ANALYZER: {
                "tokenizer": "standard",
                "char_filter": ["html_strip"],
                "filter": ["lowercase", "asciifolding", "trim"],
            },
        },
    },
}


# FIELD NAMES #
class Field:
    DATASET = "dataset"
    DATASETS = "datasets"
    SCHEMA = "schema"
    SCHEMATA = "schemata"
    CAPTION = "caption"
    NAME = "name"
    NAMES = "names"
    NAME_KEYS = "name_keys"
    NAME_PARTS = "name_parts"
    NAME_SYMBOLS = "name_symbols"
    NAME_PHONETIC = "name_phonetic"
    PROPERTIES = "properties"
    NUMERIC = "numeric"
    GEO_POINT = "geo_point"
    CONTENT = "content"
    TEXT = "text"
    TAGS = "tags"
    TRANSLATION = "translation"

    # entities group convenience
    ENTITIES = "entities"

    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"

    # align with nomenklatura
    FIRST_SEEN = "first_seen"
    LAST_SEEN = "last_seen"
    LAST_CHANGE = "last_change"
    REFERENTS = "referents"

    # leaked from OpenAleph app, probably deprecated in v6
    ROLE = "role_id"
    PROFILE = "profile_id"
    ORIGIN = "origin"
    COLLECTION_ID = "collection_id"
    MUTABLE = "mutable"

    # length norm
    NUM_VALUES = "num_values"

    # stored percolator query (things bucket only); built from the entity's
    # cleaned name variants at index time. See PercolatorQuery.
    QUERY = "query"

    # index metadata
    INDEX_BUCKET = "index_bucket"
    INDEX_VERSION = "index_version"
    INDEX_TS = "indexed_at"


FULLTEXTS = [Field.CONTENT, Field.TEXT]


# FIELD TYPES #
class FieldType:
    DATE = {"type": "date"}
    PARTIAL_DATE = {"type": "date", "format": DATE_FORMAT}
    # actual text content (bodyText et. al), optimized for highlighting and
    # termvectors
    CONTENT = {
        "type": "text",
        "analyzer": ICU_ANALYZER,
        "search_analyzer": ICU_ANALYZER,
        "index_phrases": True,  # shingles
        "term_vector": (
            "with_positions_offsets" if settings.content_term_vectors else False
        ),
    }
    # additional text copied over from other properties for arbitrary lookups
    TEXT = {"type": "text", "analyzer": HTML_ANALYZER, "search_analyzer": HTML_ANALYZER}

    KEYWORD = {"type": "keyword", "normalizer": KW_NORMALIZER}
    KEYWORD_COPY = {"type": "keyword", "copy_to": Field.TEXT}
    NUMERIC = {"type": "double"}
    INTEGER = {"type": "integer"}
    GEOPOINT = {"type": "geo_point"}
    BOOL = {"type": "boolean"}
    # stored percolator query field (see Field.QUERY)
    PERCOLATOR = {"type": "percolator"}

    # No length normalization for names. Merged entities have a lot of names,
    # and we don't want to penalize them for that.
    NAME = {"type": "text", "similarity": "weak_length_norm", "store": True}

    # custom normalized name keywords (used for term aggregations et. al)
    # this is used for registry.name.group. store for nicer highlighting
    NAME_KEYWORD = {
        "type": "keyword",
        "normalizer": NAME_KW_NORMALIZER,
        "store": True,
    }


TYPE_MAPPINGS = {
    registry.text: {"type": "text", "index": False},
    registry.html: {"type": "text", "index": False},
    registry.json: {"type": "text", "index": False},
    registry.date: FieldType.PARTIAL_DATE,
}

GROUPS = {t.group for t in registry.groups.values() if t.group}


# These fields will be pruned from the _source field after the document has been
# indexed, but before the _source field is stored. We can still search on these
# fields, even though they are not in the stored and returned _source.
SOURCE_EXCLUDES = list(
    sorted(
        [
            *GROUPS,
            Field.TEXT,
            Field.CONTENT,
            Field.TRANSLATION,
            Field.NAME,
            Field.NAME_KEYS,
            Field.NAME_PARTS,
            Field.NAME_SYMBOLS,
            Field.NAME_PHONETIC,
        ]
    )
)


def base_mapping() -> dict[str, MappingProperty]:
    """Base property mapping without specific schema fields.

    Returns fresh dicts on each call so callers can safely mutate the result.
    """
    ego = {"eager_global_ordinals": True} if settings.eager_global_ordinals else {}
    return {
        Field.DATASET: {**FieldType.KEYWORD, **ego},
        Field.SCHEMA: {**FieldType.KEYWORD, **ego},
        Field.SCHEMATA: {**FieldType.KEYWORD, **ego},
        # for fast label display
        Field.CAPTION: {**FieldType.KEYWORD},
        # original names as matching (text) field
        Field.NAME: {**FieldType.NAME},
        # names keywords, a bit normalized
        Field.NAMES: {**FieldType.NAME_KEYWORD, **ego},
        # name normalizations for filters and matching
        Field.NAME_KEYS: {**FieldType.KEYWORD},
        Field.NAME_PARTS: {**FieldType.KEYWORD_COPY},
        Field.NAME_SYMBOLS: {**FieldType.KEYWORD},
        Field.NAME_PHONETIC: {**FieldType.KEYWORD},
        # all entities can reference geo points
        Field.GEO_POINT: {**FieldType.GEOPOINT},
        # references to other entities (after merging)
        Field.REFERENTS: {**FieldType.KEYWORD},
        # full text
        Field.CONTENT: {**FieldType.CONTENT},
        Field.TEXT: {**FieldType.TEXT},
        Field.TRANSLATION: {**FieldType.TEXT},
        # tagging
        Field.TAGS: {**FieldType.KEYWORD, **ego},
        # processing metadata
        Field.UPDATED_AT: {**FieldType.DATE},
        Field.CREATED_AT: {**FieldType.DATE},
        # data metadata, provenance
        Field.LAST_CHANGE: {**FieldType.DATE},
        Field.LAST_SEEN: {**FieldType.DATE},
        Field.FIRST_SEEN: {**FieldType.DATE},
        Field.ORIGIN: {**FieldType.KEYWORD},
        # OpenAleph leaked context data probably deprecated soon
        Field.ROLE: {**FieldType.KEYWORD},
        Field.PROFILE: {**FieldType.KEYWORD},
        Field.COLLECTION_ID: {**FieldType.KEYWORD, **ego},
        Field.MUTABLE: {**FieldType.BOOL},
        # length normalization
        Field.NUM_VALUES: {**FieldType.INTEGER},
        # index metadata
        Field.INDEX_BUCKET: {**FieldType.KEYWORD, "index": False},
        Field.INDEX_VERSION: {**FieldType.KEYWORD, "index": False},
        Field.INDEX_TS: {**FieldType.DATE, "index": True},
    }


# keep module-level references for read-only access in tests etc.
BASE_MAPPING = base_mapping()


def group_mapping() -> dict[str, MappingProperty]:
    """Combined fields for emails, countries, etc.

    Returns fresh dicts on each call.
    """
    _base = base_mapping()
    return {
        group: {**TYPE_MAPPINGS.get(type_, FieldType.KEYWORD)}
        for group, type_ in registry.groups.items()
        if group not in _base
    }


GROUP_MAPPING = group_mapping()


def numeric_mapping() -> dict[str, MappingProperty]:
    """Numeric field mapping used for efficient sorting.

    Returns fresh dicts on each call.
    """
    return {
        **{
            prop.name: {**FieldType.NUMERIC}
            for prop in model.properties
            if prop.type in NUMERIC_TYPES
        },
        **{
            group: {**FieldType.NUMERIC}
            for group, type_ in registry.groups.items()
            if type_ in NUMERIC_TYPES
        },
    }


def property_field_name(prop: str) -> str:
    return f"{Field.PROPERTIES}.{prop}"


def make_object_type(properties: dict[str, MappingProperty]) -> dict[str, Any]:
    return {"type": "object", "properties": properties}


def make_mapping(properties: Mapping) -> dict[str, Any]:
    return {
        "date_detection": False,
        "dynamic": False,
        "_source": {"excludes": list(SOURCE_EXCLUDES)},
        "properties": {
            **base_mapping(),
            **group_mapping(),
            Field.NUMERIC: make_object_type(numeric_mapping()),
            Field.PROPERTIES: make_object_type(properties),
        },
    }


def make_schema_mapping(schemata: Iterable[SchemaType]) -> Mapping:
    """ES property mapping for the given schemata, merged across collisions.

    Multiple schemata can share a property name; we flatten them into one
    field with the union of their copy_to targets. When contributing FtM
    types disagree (currently only ``authority`` — entity vs string),
    keyword wins over text and TYPE_MAPPINGS extras (``index``,
    ``format``, …) are dropped — same conservative posture v4 took.
    """
    contrib_types: dict[str, list[Any]] = ddict(list)
    copy_to: dict[str, set[str]] = ddict(set)

    for schema_name in schemata:
        schema = model.get(schema_name)
        assert schema is not None, schema_name
        for name, prop in schema.properties.items():
            if prop.stub:
                continue
            contrib_types[name].append(prop.type)
            copy_to[name].update(_copy_to_targets(name, prop, schema))

    return {
        name: _build_property_spec(types, copy_to[name])
        for name, types in contrib_types.items()
    }


def _copy_to_targets(name: str, prop: Any, schema: Any) -> Iterable[str]:
    """Top-level fields a property's value should be copied into."""
    if name == PROP_TRANSLATED:
        yield Field.TRANSLATION
    elif prop.type in (registry.text, registry.html, registry.json):
        yield Field.CONTENT
    else:
        yield Field.TEXT
    if prop.type.group:
        yield prop.type.group
    if name in schema.caption:
        yield Field.NAME


def _build_property_spec(
    contrib_types: list[Any], copy_to_fields: set[str]
) -> MappingProperty:
    """Mapping spec for one property name, merged across contributing FtM types.

    Mirrors the v4 ``deepcopy(TYPE_MAPPINGS.get(prop.type, KEYWORD))``
    pattern: extras (``index``, ``format``, …) flow through whenever every
    contributor agrees; on disagreement we keep only the resolved
    ``type``.
    """
    es_types = {get_index_field_type(rt) for rt in contrib_types}
    if "keyword" in es_types and "text" in es_types:
        es_types.discard("text")
    assert len(es_types) == 1, es_types
    spec: MappingProperty = {
        "type": next(iter(es_types)),
        "copy_to": list(copy_to_fields),
    }
    spec.update(_consensus_extras(contrib_types))
    return spec


def _consensus_extras(contrib_types: list[Any]) -> dict[str, Any]:
    """Non-``type`` TYPE_MAPPINGS keys shared by every contributing FtM type."""
    extras = [
        {k: v for k, v in TYPE_MAPPINGS.get(rt, {}).items() if k != "type"}
        for rt in contrib_types
    ]
    consensus: dict[str, Any] = {}
    for key in set().union(*(s.keys() for s in extras)):
        values = {s.get(key) for s in extras}
        if len(values) == 1 and None not in values:
            consensus[key] = values.pop()
    return consensus


def get_index_field_type(type_, to_numeric: bool | None = False) -> str:
    """Given a FtM property type, return the corresponding ElasticSearch field
    type (used for determining the sorting field)"""
    es_type = TYPE_MAPPINGS.get(type_, FieldType.KEYWORD)
    if to_numeric and type_ in NUMERIC_TYPES:
        es_type = FieldType.NUMERIC
    if es_type:
        return es_type.get("type") or FieldType.KEYWORD["type"]
    return FieldType.KEYWORD["type"]


def get_field_type(field):
    """Return the FtM registry type object for a given field path."""
    field = field.split(".")[-1]
    if field in registry.groups:
        return registry.groups[field]
    for prop in model.properties:
        if prop.name == field:
            return prop.type
    return registry.string
