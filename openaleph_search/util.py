from functools import cache
from typing import Any, Generator, Iterable, Mapping, TypeAlias, TypedDict

from followthemoney import EntityProxy, Schema, model
from followthemoney.dataset.util import dataset_name_check
from ftmq.aggregate import EntityPayload

SchemaType: TypeAlias = Schema | str


class Action(TypedDict):
    """A single Elasticsearch bulk action, as produced by
    `transform.entity.format_entity`."""

    _id: str
    _index: str
    _source: dict[str, Any]


Actions: TypeAlias = Generator[Action, None, None] | Iterable[Action]

EntityLike: TypeAlias = EntityProxy | EntityPayload | Mapping[str, Any]
"""What the indexer takes: a proxy, or trusted entity data that is indexed
without building one (`ftmq.aggregate.*_unsafe`, a line of an
`entities.ftm.json`)."""


@cache
def valid_dataset(dataset: str) -> str:
    return dataset_name_check(dataset)


@cache
def ensure_schema(schema: SchemaType) -> Schema:
    schema_ = model.get(schema)
    if schema_ is not None:
        return schema_
    raise ValueError(f"Invalid schema: `{schema}`")
