import logging
from typing import Any, Literal, TypeAlias

from anystore.functools import weakref_cache as cache
from banal import ensure_list
from followthemoney import model
from followthemoney.exc import InvalidData
from followthemoney.schema import Schema

from openaleph_search.index.indexer import configure_index
from openaleph_search.index.mapping import Field, make_mapping, make_schema_mapping
from openaleph_search.index.util import index_name, index_settings
from openaleph_search.settings import Settings
from openaleph_search.util import SchemaType, ensure_schema

log = logging.getLogger(__name__)
settings = Settings()

Bucket: TypeAlias = Literal["page", "pages", "documents", "intervals", "things"]
BUCKETS = ("page", "pages", "documents", "intervals", "things")


@cache
def schema_bucket(schema: SchemaType) -> Bucket:
    """Convert a schema to its index bucket"""
    schema = ensure_schema(schema)
    if schema.name == "Page":
        return "page"
    if schema.name == "Pages":
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


def make_schema_bucket_properties(bucket: Bucket) -> dict[str, Any]:
    """Configure the property mapping for the given schema bucket"""
    schemata: set[Schema] = set()
    for schema in model.schemata.values():
        if schema_bucket(schema) == bucket:
            schemata.add(schema)
    return make_schema_mapping(schemata)


def configure_entities():
    """Configure all the entity indexes"""
    for bucket in BUCKETS:
        for version in settings.index_read:
            configure_schema_bucket(bucket, version)


def make_schema_bucket_mapping(bucket: Bucket) -> dict[str, Any]:
    properties = make_schema_bucket_properties(bucket)
    mapping = make_mapping(properties)
    if bucket == "pages":
        # store full text for highlighting
        mapping["properties"][Field.CONTENT]["store"] = True
    else:
        mapping["properties"][Field.CONTENT]["store"] = False
    return mapping


def get_bucket_shard_num(
    bucket: Bucket, default_shards: int | None = settings.index_shards
) -> int:
    if settings.testing:
        return 1
    shards = default_shards or settings.index_shards
    if bucket == "things":
        return shards // 2
    if bucket == "intervals":
        return shards // 3
    return shards  # documents, pages


def configure_schema_bucket(bucket: Bucket, version: str):
    """
    Generate relevant type mappings for entity properties so that
    we can do correct searches on each.
    """
    mapping = make_schema_bucket_mapping(bucket)
    index = bucket_index(bucket, version)
    settings = index_settings(shards=get_bucket_shard_num(bucket))
    return configure_index(index, mapping, settings)
