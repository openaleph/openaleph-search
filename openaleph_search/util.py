from typing import TypeAlias

from anystore.functools import weakref_cache
from followthemoney import Schema
from followthemoney.dataset.util import dataset_name_check

SchemaType: TypeAlias = Schema | str


@weakref_cache
def valid_dataset(dataset: str) -> str:
    return dataset_name_check(dataset)
