from typing import TypeAlias

from anystore.functools import weakref_cache
from followthemoney import Schema, model
from followthemoney.dataset.util import dataset_name_check

SchemaType: TypeAlias = Schema | str


@weakref_cache
def valid_dataset(dataset: str) -> str:
    return dataset_name_check(dataset)


@weakref_cache
def ensure_schema(schema: SchemaType) -> Schema:
    schema_ = model.get(schema)
    if schema_ is not None:
        return schema_
    raise ValueError(f"Invalid schema: `{schema}`")
