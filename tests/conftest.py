from pathlib import Path

import pytest
from ftmq.io import smart_read_proxies

from openaleph_search.core import get_es
from openaleph_search.index.admin import delete_index, upgrade_search
from openaleph_search.index.entities import index_bulk

FIXTURES_PATH = (Path(__file__).parent / "fixtures").absolute()
ENTITIES = "samples.ijson"


@pytest.fixture(scope="module")
def fixtures_path():
    return FIXTURES_PATH


@pytest.fixture(scope="module")
def entities():
    return list(smart_read_proxies(FIXTURES_PATH / ENTITIES))


@pytest.fixture(scope="module")
def index_entities(entities):
    index_bulk("test_dataset", entities)


@pytest.fixture(scope="module", autouse=True)
def clear_es():
    get_es.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def setup_es():
    delete_index()
    upgrade_search()
