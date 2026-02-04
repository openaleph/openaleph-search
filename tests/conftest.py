from pathlib import Path

import pytest
from ftmq.io import smart_read_proxies
from ftmq.util import make_entity

from openaleph_search.core import get_es
from openaleph_search.index.admin import clear_index, delete_index, upgrade_search
from openaleph_search.index.entities import index_bulk
from openaleph_search.model import SearchAuth

FIXTURES_PATH = (Path(__file__).parent / "fixtures").absolute()
ENTITIES = "samples.ijson"

# from aleph tests
TEST_PRIVATE = [
    {
        "id": "banana1",
        "schema": "Person",
        "properties": {"name": ["Banana"], "birthDate": ["1970-08-21"]},
    },
    {
        "id": "banana2",
        "schema": "Person",
        "properties": {"name": ["Banana"], "birthDate": ["1970-03-21"]},
    },
    {
        "id": "banana3",
        "schema": "Person",
        "properties": {
            "name": ["Banana ba Nana"],
            "birthDate": ["1969-05-21"],
            "deathDate": ["1972-04-23"],
            "email": ["banana@example.com"],
            "phone": ["+1234567890"],
        },
    },
]
TEST_PUBLIC = [
    {
        "id": "id-company",
        "schema": "Company",
        "properties": {"name": ["KwaZulu"], "alias": ["kwazulu"]},
    },
    {
        "id": "id-note",
        "schema": "Note",
        "properties": {"description": ["note"], "entity": ["id-company"]},
    },
]


@pytest.fixture(scope="module")
def fixtures_path():
    return FIXTURES_PATH


@pytest.fixture(scope="module")
def entities():
    return list(smart_read_proxies(FIXTURES_PATH / ENTITIES))


@pytest.fixture(scope="module")
def fixture_pages():
    return list(smart_read_proxies(FIXTURES_PATH / "pages.jsonl"))


@pytest.fixture(scope="module")
def index_entities(entities):
    """Index some entities and delete them after test run"""
    index_bulk("test_samples", entities)
    index_bulk("test_private", map(make_entity, TEST_PRIVATE))
    index_bulk("test_public", map(make_entity, TEST_PUBLIC))
    yield
    clear_index()


@pytest.fixture(scope="function")
def cleanup_after():
    yield
    clear_index()


@pytest.fixture(scope="session")
def auth_public():
    return SearchAuth(datasets={"test_samples", "test_public"})


@pytest.fixture(scope="session")
def auth_private():
    return SearchAuth(
        logged_in=True, datasets={"test_samples", "test_public", "test_private"}
    )


@pytest.fixture(scope="session")
def auth_admin():
    return SearchAuth(logged_in=True, is_admin=True)


@pytest.fixture(scope="module", autouse=True)
def clear_es():
    get_es.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def setup_es():
    delete_index()
    upgrade_search()


@pytest.fixture(scope="session")
def es():
    yield get_es()
