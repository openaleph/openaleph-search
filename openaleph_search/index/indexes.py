import logging
from copy import deepcopy
from functools import cache
from typing import Any, Literal, TypeAlias

from banal import ensure_list
from followthemoney import model
from followthemoney.exc import InvalidData
from followthemoney.schema import Schema
from followthemoney.types import registry

from openaleph_search.index.util import (
    GEOPOINT,
    KEYWORD,
    KEYWORD_COPY,
    NUMERIC,
    NUMERIC_TYPES,
    PARTIAL_DATE,
    configure_index,
    index_name,
    index_settings,
)
from openaleph_search.settings import Settings

log = logging.getLogger(__name__)
settings = Settings()

TYPE_MAPPINGS = {
    registry.text: {"type": "text", "index": False},
    registry.html: {"type": "text", "index": False},
    registry.json: {"type": "text", "index": False},
    registry.date: PARTIAL_DATE,
}

BUCKETS = ("things", "intervals", "documents", "pages")
INDEX_BUCKET = Literal["things", "intervals", "documents", "pages"]
PAGES = ("Page", "Pages")

SchemaType: TypeAlias = Schema | str


@cache
def ensure_schema(schema: SchemaType) -> Schema:
    schema_ = model.get(schema)
    if schema_ is not None:
        return schema_
    raise ValueError(f"Invalid schema: `{schema}`")


@cache
def schema_bucket(schema: SchemaType) -> INDEX_BUCKET:
    """Convert a schema to its index bucket"""
    schema = ensure_schema(schema)
    if schema.name in PAGES:
        return "pages"
    if schema.is_a("Document"):
        return "documents"
    if schema.is_a("Thing"):  # catch "Event"
        return "things"
    if schema.is_a("Interval"):
        return "intervals"
    return "things"  # FIXME e.g. Mentions


@cache
def bucket_index(bucket: INDEX_BUCKET, version: str):
    """Convert a bucket str to an index name."""
    name = "entity-%s" % bucket
    return index_name(name, version=version)


@cache
def schema_index(schema: SchemaType, version: str):
    """Convert a schema object to an index name."""
    schema = ensure_schema(schema)
    if schema.abstract:
        raise InvalidData("Cannot index abstract schema: %s" % schema)
    return bucket_index(schema_bucket(schema), version)


def schema_scope(
    schema: SchemaType | list[SchemaType] | None = None, expand: bool | None = True
):
    schemata: set[Schema] = set()
    names = ensure_list(schema) or model.schemata.values()
    for schema_ in names:
        if schema_:
            schema_ = ensure_schema(schema_)
            schemata.add(schema_)
            if expand:
                schemata.update(schema_.descendants)
    for schema in schemata:
        if not schema.abstract:
            yield schema


def entities_index_list(
    schema: SchemaType | list[SchemaType] | None = None, expand: bool | None = True
) -> set[str]:
    """Combined index to run all queries against."""
    indexes: set[str] = set()
    for schema_ in schema_scope(schema, expand=expand):
        for version in settings.index_read:
            indexes.add(schema_index(schema_, version))
    return indexes


def entities_read_index(
    schema: SchemaType | list[SchemaType] | None = None, expand: bool | None = True
) -> str:
    """Current configured read indexes"""
    indexes = entities_index_list(schema=schema, expand=expand)
    return ",".join(indexes)


def entities_write_index(schema):
    """Index that is currently written by new queries."""
    return schema_index(schema, settings.index_write)


@cache
def get_schema_bucket_mapping(bucket: INDEX_BUCKET) -> dict[str, Any]:
    """Configure the property mapping for the given schema bucket"""
    mapping = {}
    for schema in model.schemata.values():
        if schema_bucket(schema) == bucket:
            for prop in schema.properties.values():
                config = deepcopy(TYPE_MAPPINGS.get(prop.type, KEYWORD))
                config["copy_to"] = ["text"]
                mapping[prop.name] = config
    return mapping


@cache
def get_numeric_mapping() -> dict[str, Any]:
    mapping = {}
    for prop in model.properties:
        if prop.type in NUMERIC_TYPES:
            mapping[prop.name] = NUMERIC
    return mapping


def configure_entities():
    """Configure all the entity indexes"""
    for bucket in BUCKETS:
        for version in settings.index_read:
            configure_schema_bucket(bucket, version)


def configure_schema_bucket(bucket: INDEX_BUCKET, version: str):
    """
    Generate relevant type mappings for entity properties so that
    we can do correct searches on each.
    """
    schema_mapping = get_schema_bucket_mapping(bucket)
    numeric_mapping = get_numeric_mapping()

    mapping = {
        "date_detection": False,
        "dynamic": False,
        "_source": {"excludes": ["text", "fingerprints"]},
        "properties": {
            "caption": KEYWORD,
            "schema": KEYWORD,
            "schemata": KEYWORD,
            registry.entity.group: KEYWORD,
            registry.language.group: KEYWORD,
            registry.country.group: KEYWORD,
            registry.checksum.group: KEYWORD,
            registry.ip.group: KEYWORD,
            registry.url.group: KEYWORD,
            registry.email.group: KEYWORD,
            registry.phone.group: KEYWORD,
            registry.mimetype.group: KEYWORD,
            registry.identifier.group: KEYWORD,
            registry.date.group: PARTIAL_DATE,
            registry.address.group: KEYWORD,
            registry.name.group: KEYWORD,
            "symbols": KEYWORD_COPY,
            "fingerprints": KEYWORD_COPY,
            "text": {
                "type": "text",
                "term_vector": "with_positions_offsets",
            },
            "properties": {"type": "object", "properties": schema_mapping},
            "numeric": {"type": "object", "properties": numeric_mapping},
            "geo_point": GEOPOINT,
            "role_id": KEYWORD,
            "profile_id": KEYWORD,
            "dataset": KEYWORD,
            "collection_id": KEYWORD,  # FIXME
            "origin": KEYWORD,
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
        },
    }

    index = bucket_index(bucket, version)
    settings = index_settings()
    return configure_index(index, mapping, settings)
