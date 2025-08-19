"""
Index mappings
"""

from typing import Any

from followthemoney import model
from followthemoney.types import registry

# MAPPING SHORTCUTS #
TEXT = "text"
DEFAULT_ANALYZER = "default"
DATE_FORMAT = (
    "yyyy-MM-dd'T'HH:mm:ss||yyyy-MM-dd'T'HH:mm||yyyy-MM-dd||yyyy-MM||yyyy"  # noqa: E501
)
NUMERIC_TYPES = (
    registry.number,
    registry.date,
)


# FIELD TYPES #
class FieldType:
    DATE = {"type": "date"}
    PARTIAL_DATE = {"type": "date", "format": DATE_FORMAT}
    TEXT = {
        "type": TEXT,
        "analyzer": DEFAULT_ANALYZER,
        "search_analyzer": DEFAULT_ANALYZER,
        "index_phrases": True,  # shingles
    }
    TEXT_ANNOTATED = {
        "type": "annotated_text",
        "analyzer": DEFAULT_ANALYZER,
        "search_analyzer": DEFAULT_ANALYZER,
        "store": True,
    }
    KEYWORD = {"type": "keyword"}
    KEYWORD_COPY = {"type": "keyword", "copy_to": TEXT}
    NUMERIC = {"type": "double"}
    INTEGER = {"type": "integer"}
    GEOPOINT = {"type": "geo_point"}
    # No length normalization for names. Merged entities have a lot of names,
    # and we don't want to penalize them for that.
    NAMES_WEAK_NORM = {
        "type": "keyword",
        "copy_to": TEXT,
        "similarity": "weak_length_norm",
    }


TYPE_MAPPINGS = {
    registry.text: {"type": TEXT, "index": False},
    registry.html: {"type": TEXT, "index": False},
    registry.json: {"type": TEXT, "index": False},
    registry.date: FieldType.PARTIAL_DATE,
}


# FIELDS #
class Field:
    DATASET = "dataset"
    CAPTION = "caption"
    SCHEMA = "schema"
    SCHEMATA = "schemata"
    NAMES = "names"
    NAME_KEYS = "name_keys"
    NAME_PARTS = "name_parts"
    NAME_SYMBOLS = "name_symbols"
    NAME_PHONETIC = "name_phonetic"
    PROPERTIES = "properties"
    NUMERIC = "numeric"
    GEO_POINT = "geo_point"
    TEXT = "text"
    TEXT_ANNOTATED = "text_annotasted"

    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"

    # probably deprecated in v6
    ROLE = "role_id"
    PROFILE = "profile_id"
    ORIGIN = "origin"

    # length norm
    NUM_VALUES = "num_values"

    # index metadata
    INDEX_VERSION = "index_version"
    INDEX_TS = "indexed_at"


SOURCE_EXCLUDES = [
    *[t.group for t in registry.groups.values()],
    Field.TEXT,
    Field.NAMES,
    Field.NAME_KEYS,
    Field.NAME_PARTS,
    Field.NAME_SYMBOLS,
    Field.NAME_PHONETIC,
]

# base property mapping without specific schema fields
PROPERTIES = {
    Field.DATASET: FieldType.KEYWORD,
    Field.SCHEMA: FieldType.KEYWORD,
    Field.SCHEMATA: FieldType.KEYWORD,
    Field.CAPTION: FieldType.KEYWORD,
    Field.NAMES: FieldType.NAMES_WEAK_NORM,
    Field.NAME_KEYS: FieldType.KEYWORD,
    Field.NAME_PARTS: FieldType.KEYWORD_COPY,
    Field.NAME_SYMBOLS: FieldType.KEYWORD,
    Field.NAME_PHONETIC: FieldType.KEYWORD,
    Field.GEO_POINT: FieldType.GEOPOINT,
    # full text
    Field.TEXT: FieldType.TEXT,
    Field.TEXT_ANNOTATED: FieldType.TEXT_ANNOTATED,
    # metadata
    Field.UPDATED_AT: FieldType.DATE,
    Field.CREATED_AT: FieldType.DATE,
    Field.ROLE: FieldType.KEYWORD,
    Field.PROFILE: FieldType.KEYWORD,
    Field.ORIGIN: FieldType.KEYWORD,
    # prop type groups
    registry.entity.group: FieldType.KEYWORD,
    registry.language.group: FieldType.KEYWORD,
    registry.country.group: FieldType.KEYWORD,
    registry.checksum.group: FieldType.KEYWORD,
    registry.ip.group: FieldType.KEYWORD,
    registry.url.group: FieldType.KEYWORD,
    registry.email.group: FieldType.KEYWORD,
    registry.phone.group: FieldType.KEYWORD,
    registry.mimetype.group: FieldType.KEYWORD,
    registry.identifier.group: FieldType.KEYWORD,
    registry.date.group: FieldType.PARTIAL_DATE,
    registry.address.group: FieldType.KEYWORD,
    registry.name.group: FieldType.KEYWORD,
    # length normalization
    Field.NUM_VALUES: FieldType.INTEGER,
    # index metadata
    Field.INDEX_VERSION: {**FieldType.KEYWORD, "index": False},
    Field.INDEX_TS: {**FieldType.DATE, "index": False},
}


NUMERIC_MAPPING = {
    prop.name: FieldType.NUMERIC
    for prop in model.properties
    if prop.type in NUMERIC_TYPES
}


def property_field(prop: str) -> str:
    return f"properties.{prop}"


def make_object_type(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties}


def make_mapping(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "date_detection": False,
        "dynamic": False,
        "_source": {"excludes": SOURCE_EXCLUDES},
        "properties": {
            **PROPERTIES,
            "numeric": make_object_type(NUMERIC_MAPPING),
            "properties": make_object_type(properties),
        },
    }


def get_index_field_type(type_):
    """Given a FtM property type, return the corresponding ElasticSearch field type"""
    es_type = TYPE_MAPPINGS.get(type_, FieldType.KEYWORD)
    if type_ in NUMERIC_TYPES:
        es_type = FieldType.NUMERIC
    if es_type:
        return es_type.get("type")
