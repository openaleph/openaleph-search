import logging
from copy import deepcopy
from typing import Any, Literal, TypeAlias

from anystore.functools import weakref_cache as cache
from banal import ensure_list
from followthemoney import model
from followthemoney.exc import InvalidData
from followthemoney.schema import Schema

from openaleph_search.index.indexer import configure_index
from openaleph_search.index.mapping import TYPE_MAPPINGS, FieldType, make_mapping
from openaleph_search.index.util import index_name, index_settings
from openaleph_search.settings import Settings

log = logging.getLogger(__name__)
settings = Settings()

SchemaType: TypeAlias = Schema | str
Bucket: TypeAlias = Literal["pages", "documents", "intervals", "things"]
BUCKETS = ("pages", "documents", "intervals", "things")


@cache
def ensure_schema(schema: SchemaType) -> Schema:
    schema_ = model.get(schema)
    if schema_ is not None:
        return schema_
    raise ValueError(f"Invalid schema: `{schema}`")


@cache
def schema_bucket(schema: SchemaType) -> Bucket:
    """Convert a schema to its index bucket"""
    schema = ensure_schema(schema)
    if schema.name in ("Page", "Pages"):
        return "pages"
    if schema.is_a("Document"):
        return "documents"
    if schema.is_a("Thing"):  # catch "Event"
        return "things"
    if schema.is_a("Interval"):
        return "intervals"
    return "things"  # FIXME e.g. Mentions


@cache
def bucket_index(bucket: Bucket, version: str):
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
    for schema_ in ensure_list(schema) or model.schemata.values():
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
def get_schema_bucket_mapping(bucket: Bucket) -> dict[str, Any]:
    """Configure the property mapping for the given schema bucket"""
    mapping = {}
    for schema in model.schemata.values():
        if schema_bucket(schema) == bucket:
            for prop in schema.properties.values():
                config = deepcopy(TYPE_MAPPINGS.get(prop.type, FieldType.KEYWORD))
                config["copy_to"] = ["text"]
                mapping[prop.name] = config
    return mapping


def configure_entities():
    """Configure all the entity indexes"""
    for bucket in BUCKETS:
        for version in settings.index_read:
            configure_schema_bucket(bucket, version)


def make_schema_bucket_mapping(bucket: Bucket) -> dict[str, Any]:
    properties = get_schema_bucket_mapping(bucket)
    mapping = make_mapping(properties)
    if bucket == "pages":
        # store full text for highlighting
        mapping["properties"]["text"]["store"] = True
    return mapping


def configure_schema_bucket(bucket: Bucket, version: str):
    """
    Generate relevant type mappings for entity properties so that
    we can do correct searches on each.
    """
    mapping = make_schema_bucket_mapping(bucket)
    index = bucket_index(bucket, version)
    settings = index_settings()
    return configure_index(index, mapping, settings)
