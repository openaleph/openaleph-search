import time

from followthemoney import EntityProxy, model

from openaleph_search.index.entities import index_proxy
from openaleph_search.index.indexes import entities_read_index
from openaleph_search.index.mapping import (
    BASE_MAPPING,
    GROUP_MAPPING,
    make_schema_mapping,
)


def test_mappings_copy_to(es, cleanup_after):
    """Test that all the mapping and indexing magic works.

    We test that by executing queries on specific fields of the indexed documents."""

    # Create a test entity with Vladimir Putin data
    entity = EntityProxy.from_dict(
        {
            "id": "Q7747",
            "schema": "Person",
            "properties": {
                "name": ["Vladimir Putin"],
                "citizenship": ["ru"],
                "topics": ["sanction"],
            },
            "datasets": ["test"],
            "referents": [],
            "first_seen": "2023-01-01T00:00:00",
            "last_seen": "2023-01-01T00:00:00",
            "last_change": "2023-01-01T00:00:00",
        }
    )

    index = entities_read_index()
    index_proxy("test_mapping", entity, sync=True)
    time.sleep(1)  # FIXME async es

    # all name fields are keyword
    search_result = es.search(
        index=index, query={"bool": {"must": [{"term": {"names": "Vladimir Putin"}}]}}
    )
    assert len(search_result["hits"]["hits"]) == 1, "Failed to match on names"

    # name_parts and name_phonetic are a bit of a special case, we syntesize them in the index=indexer
    search_result = es.search(
        index=index, query={"bool": {"must": [{"term": {"name_parts": "vladimir"}}]}}
    )
    assert len(search_result["hits"]["hits"]) == 1, "Failed to match on name_parts"
    search_result = es.search(
        index=index, query={"bool": {"must": [{"term": {"name_phonetic": "FLTMR"}}]}}
    )
    assert len(search_result["hits"]["hits"]) == 1, "Failed to match on name_phonetic"

    # Try to match on the countries field, which is a type field that is populated by copy_to from citizenship
    search_result = es.search(
        index=index, query={"bool": {"must": [{"term": {"countries": "ru"}}]}}
    )
    assert len(search_result["hits"]["hits"]) == 1, "Failed to match on countries"

    # Try to match on the text field, which is a copy_to field that is populated by just about everything
    search_result = es.search(
        index=index, query={"bool": {"must": [{"term": {"text": "ru"}}]}}
    )
    assert len(search_result["hits"]["hits"]) == 1, "Failed to match country on text"
    search_result = es.search(
        index=index, query={"bool": {"must": [{"term": {"text": "sanction"}}]}}
    )
    assert len(search_result["hits"]["hits"]) == 1, "Failed to match topics on text"
    search_result = es.search(
        index=index, query={"bool": {"must": [{"match": {"text": "vladimir"}}]}}
    )
    assert len(search_result["hits"]["hits"]) == 1, "Failed to match name on text"


def test_mapping_colliding_prop_names():
    """Test that we can handle multiple properties with the same property name."""
    mapping = make_schema_mapping(["CallForTenders", "Identification"])
    # CallForTenders:authority is an entity, Identification:authority is a string
    assert set(mapping["authority"]["copy_to"]) == set(["text", "entities"])
    assert mapping["authority"]["type"] == "keyword"


def test_mapping_spec():
    assert BASE_MAPPING["names"]["type"] == "keyword"
    assert "copy_to" not in BASE_MAPPING["names"]
    assert BASE_MAPPING["name_keys"]["type"] == "keyword"
    assert GROUP_MAPPING["dates"]["type"] == "date"
    assert GROUP_MAPPING["emails"]["type"] == "keyword"
    mapping = make_schema_mapping(model.schemata.values())
    assert all("text" in f["copy_to"] for f in mapping.values())
    assert "names" in mapping["name"]["copy_to"]
    assert "dates" in mapping["birthDate"]["copy_to"]
