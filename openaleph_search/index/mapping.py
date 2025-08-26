"""
Index mappings
"""

from collections import defaultdict as ddict
from typing import Any, Iterable, TypeAlias

from followthemoney import model
from followthemoney.types import registry

from openaleph_search.util import SchemaType

MappingProperty: TypeAlias = dict[str, list[str] | str]
Mapping: TypeAlias = dict[str, MappingProperty]

# MAPPING SHORTCUTS #
DEFAULT_ANALYZER = "default"
DEFAULT_NORMALIZER = "default"
ICU_ANALYZER = "icu-default"
ICU_NORMALIZER = "icu-default"
HTML_ANALYZER = "strip-html"
KW_NORMALIZER = "kw-normalizer"
NAME_KW_NORMALIZER = "name-kw-normalizer"
DATE_FORMAT = "yyyy-MM-dd'T'HH||yyyy-MM-dd'T'HH:mm||yyyy-MM-dd'T'HH:mm:ss||yyyy-MM-dd||yyyy-MM||yyyy||strict_date_optional_time"  # noqa: B950
NUMERIC_TYPES = (registry.number, registry.date)

# INDEX SETTINGS #
ANALYZE_SETTINGS = {
    "analysis": {
        "char_filter": {
            "remove_special_chars": {
                "type": "pattern_replace",
                "pattern": "[^\\p{L}\\p{N}\\s]",
                "replacement": "",
            },
            "squash_spaces": {
                "type": "pattern_replace",
                "pattern": "[\\r\\n\\s]+",
                "replacement": " ",
            },
            "remove_html_tags": {
                "type": "pattern_replace",
                "pattern": "<[^>]*>",
                "replacement": " ",
            },
        },
        "normalizer": {
            ICU_NORMALIZER: {
                "type": "custom",
                "filter": ["icu_folding"],
            },
            NAME_KW_NORMALIZER: {
                "type": "custom",
                "char_filter": [
                    "remove_special_chars",
                    "squash_spaces",
                    "remove_html_tags",
                ],
                "filter": ["lowercase", "asciifolding", "trim"],
            },
            KW_NORMALIZER: {
                "type": "custom",
                "char_filter": [
                    "remove_html_tags",
                    "squash_spaces",
                ],
                "filter": ["trim"],
            },
        },
        "analyzer": {
            ICU_ANALYZER: {
                "char_filter": ["html_strip"],
                "tokenizer": "icu_tokenizer",
                "filter": [
                    "icu_folding",
                    "icu_normalizer",
                ],
            },
            HTML_ANALYZER: {
                "tokenizer": "standard",
                "char_filter": ["html_strip", "squash_spaces"],
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

    NUMERIC = "numeric"
    PROPERTIES = "properties"

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

    # length norm
    NUM_VALUES = "num_values"

    # index metadata
    INDEX_BUCKET = "index_bucket"
    INDEX_VERSION = "index_version"
    INDEX_TS = "indexed_at"


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
        "term_vector": "with_positions_offsets",
    }
    # additional text copied over from other properties for arbitrary lookups,
    # default analyzer
    TEXT = {"type": "text", "analyzer": HTML_ANALYZER, "search_analyzer": HTML_ANALYZER}

    KEYWORD = {"type": "keyword", "normalizer": KW_NORMALIZER}
    KEYWORD_COPY = {"type": "keyword", "copy_to": Field.TEXT}
    NUMERIC = {"type": "double"}
    INTEGER = {"type": "integer"}
    GEOPOINT = {"type": "geo_point"}

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
            Field.NAME,
            Field.NAME_KEYS,
            Field.NAME_PARTS,
            Field.NAME_SYMBOLS,
            Field.NAME_PHONETIC,
        ]
    )
)


# base property mapping without specific schema fields
BASE_MAPPING = {
    Field.DATASET: FieldType.KEYWORD,
    Field.SCHEMA: FieldType.KEYWORD,
    Field.SCHEMATA: FieldType.KEYWORD,
    # for fast label display
    Field.CAPTION: FieldType.KEYWORD,
    # original names as matching (text) field
    Field.NAME: FieldType.NAME,
    # names keywords, a bit normalized
    Field.NAMES: FieldType.NAME_KEYWORD,
    # name normalizations for filters and matching
    Field.NAME_KEYS: FieldType.KEYWORD,
    Field.NAME_PARTS: FieldType.KEYWORD_COPY,
    Field.NAME_SYMBOLS: FieldType.KEYWORD,
    Field.NAME_PHONETIC: FieldType.KEYWORD,
    # all entities can reference geo points
    Field.GEO_POINT: FieldType.GEOPOINT,
    # references to other entities (after merging)
    Field.REFERENTS: FieldType.KEYWORD,
    # full text
    Field.CONTENT: FieldType.CONTENT,
    Field.TEXT: FieldType.TEXT,
    # processing metadata
    Field.UPDATED_AT: FieldType.DATE,
    Field.CREATED_AT: FieldType.DATE,
    # data metadata, provenance
    Field.LAST_CHANGE: FieldType.DATE,
    Field.LAST_SEEN: FieldType.DATE,
    Field.FIRST_SEEN: FieldType.DATE,
    Field.ORIGIN: FieldType.KEYWORD,
    # probably deprecated soon
    Field.ROLE: FieldType.KEYWORD,
    Field.PROFILE: FieldType.KEYWORD,
    Field.COLLECTION_ID: FieldType.KEYWORD,
    # length normalization
    Field.NUM_VALUES: FieldType.INTEGER,
    # index metadata
    Field.INDEX_BUCKET: {**FieldType.KEYWORD, "index": False},
    Field.INDEX_VERSION: {**FieldType.KEYWORD, "index": False},
    Field.INDEX_TS: {**FieldType.DATE, "index": False},
}

# combined fields for emails, countries, ...
GROUP_MAPPING = {
    group: TYPE_MAPPINGS.get(type_, FieldType.KEYWORD)
    for group, type_ in registry.groups.items()
    if group not in BASE_MAPPING
}

# used for efficient sorting
NUMERIC_MAPPING = {
    **{
        prop.name: FieldType.NUMERIC
        for prop in model.properties
        if prop.type in NUMERIC_TYPES
    },
    **{
        group: FieldType.NUMERIC
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
        "_source": {"excludes": SOURCE_EXCLUDES},
        "properties": {
            **BASE_MAPPING,
            **GROUP_MAPPING,
            Field.NUMERIC: make_object_type(NUMERIC_MAPPING),
            Field.PROPERTIES: make_object_type(properties),
        },
    }


def make_schema_mapping(schemata: Iterable[SchemaType]) -> Mapping:
    """Create an entity mapping for given schemata with dynamic property resolution."""
    # Multiple schemata can have the same property name, but we flatten them
    # into a single field in the search index with probably multiple copy_to
    # targets. keyword type always has precedence over text.  All fields within
    # a group (text/keyword) are usually the same.  Currently, only "authority"
    # causes a collision (some are string, some are entity)
    merged_props: dict[str, dict[str, set[str]]] = ddict(lambda: ddict(set[str]))

    for schema_name in schemata:
        schema = model.get(schema_name)
        assert schema is not None, schema_name
        for name, prop in schema.properties.items():
            if prop.stub:
                continue
            merged_props[name]["type"].add(get_index_field_type(prop.type))
            if prop.type == registry.text:
                merged_props[name]["copy_to"].add(Field.CONTENT)
            else:
                merged_props[name]["copy_to"].add(Field.TEXT)
            if prop.type.group:
                merged_props[name]["copy_to"].add(prop.type.group)

    # clean up properties type
    properties: dict[str, MappingProperty] = {}
    for prop, config in merged_props.items():
        spec: MappingProperty = {"copy_to": list(config.pop("copy_to"))}
        type_ = config.pop("type")
        if "keyword" in type_:
            type_.discard("text")
        type_ = list(type_)
        assert len(type_) == 1, type_
        properties[prop] = {**spec, "type": type_[0]}

    return properties


def get_index_field_type(type_, to_numeric: bool | None = False) -> str:
    """Given a FtM property type, return the corresponding ElasticSearch field
    type (used for determining the sorting field)"""
    es_type = TYPE_MAPPINGS.get(type_, FieldType.KEYWORD)
    if to_numeric and type_ in NUMERIC_TYPES:
        es_type = FieldType.NUMERIC
    if es_type:
        return es_type.get("type") or FieldType.KEYWORD["type"]
    return FieldType.KEYWORD["type"]


def get_field_type(field) -> str:
    field = field.split(".")[-1]
    if field in registry.groups:
        return str(registry.groups[field])
    for prop in model.properties:
        if prop.name == field:
            return str(prop.type)
    return str(registry.string)
