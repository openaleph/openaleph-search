from anystore.functools import weakref_cache
from followthemoney.dataset.util import dataset_name_check


@weakref_cache
def valid_dataset(dataset: str) -> str:
    return dataset_name_check(dataset)
