import time

from followthemoney import EntityProxy, model

from openaleph_search.core import get_es
from openaleph_search.index.entities import index_proxy
from openaleph_search.index.indexes import (
    entities_read_index,
    make_schema_bucket_mapping,
)
from openaleph_search.index.mapping import (
    BASE_MAPPING,
    GROUP_MAPPING,
    make_mapping,
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

    # name is a text field, so need to use match
    search_result = es.search(
        index=index, query={"bool": {"must": [{"match": {"name": "Vladimir"}}]}}
    )
    assert len(search_result["hits"]["hits"]) == 1, "Failed to match on names"

    # all other name fields are keyword
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

    # add an analyzable document that mentiones putin
    entity = EntityProxy.from_dict(
        {
            "id": "doc123",
            "schema": "Document",
            "properties": {
                "fileName": ["a_document.pdf"],
                "title": ["My document"],
                "peopleMentioned": ["Vladimir Putin"],
            },
            "datasets": ["test"],
        }
    )
    index = entities_read_index()
    index_proxy("test_mapping", entity, sync=True)
    time.sleep(1)  # FIXME async es

    # name is a text field, so need to use match
    search_result = es.search(
        index=index, query={"bool": {"must": [{"match": {"name": "a_document.pdf"}}]}}
    )
    assert len(search_result["hits"]["hits"]) == 1, "Failed to match on names"
    search_result = es.search(
        index=index, query={"bool": {"must": [{"match": {"name": "My document"}}]}}
    )
    assert len(search_result["hits"]["hits"]) == 1, "Failed to match on names"

    # now we have 2 results for putin name keywords
    search_result = es.search(
        index=index, query={"bool": {"must": [{"term": {"names": "Vladimir Putin"}}]}}
    )
    assert len(search_result["hits"]["hits"]) == 2, "Failed to match on names"

    # Try to match on the text field, which is a copy_to field that is populated by just about everything
    search_result = es.search(
        index=index, query={"bool": {"must": [{"term": {"text": "vladimir"}}]}}
    )
    assert len(search_result["hits"]["hits"]) == 2, "Failed to match name parts on text"
    search_result = es.search(
        index=index, query={"bool": {"must": [{"match": {"text": "my document"}}]}}
    )
    assert (
        len(search_result["hits"]["hits"]) == 1
    ), "Failed to match document name on text"
    search_result = es.search(
        index=index, query={"bool": {"must": [{"match": {"text": "a_document.pdf"}}]}}
    )
    assert (
        len(search_result["hits"]["hits"]) == 1
    ), "Failed to match document name on text"
    search_result = es.search(
        index=index, query={"bool": {"must": [{"match": {"text": "vladimir putin"}}]}}
    )
    assert len(search_result["hits"]["hits"]) == 2, "Failed to match names on text"


def test_mapping_colliding_prop_names():
    """Test that we can handle multiple properties with the same property name."""
    mapping = make_schema_mapping(["CallForTenders", "Identification"])
    # CallForTenders:authority is an entity, Identification:authority is a string
    assert set(mapping["authority"]["copy_to"]) == set(["text", "entities"])
    assert mapping["authority"]["type"] == "keyword"


def test_mapping_spec():
    # name field is text match field, no copy_to as its properties will be
    # copied to text anyways
    assert BASE_MAPPING["name"]["type"] == "text"
    assert "copy_to" not in BASE_MAPPING["name"]

    # normalized names keywords
    assert BASE_MAPPING["names"]["type"] == "keyword"

    # other normalized name things not
    for f in ("name_keys", "name_parts", "name_phonetic"):
        assert BASE_MAPPING[f]["type"] == "keyword"
        assert "copy_to" not in f

    # all properties should be copied to their groups and to full text
    assert GROUP_MAPPING["dates"]["type"] == "date"
    assert GROUP_MAPPING["emails"]["type"] == "keyword"
    mapping = make_schema_mapping(model.schemata.values())
    assert all(
        ("text" in f["copy_to"] or "content" in f["copy_to"]) for f in mapping.values()
    )
    assert "names" in mapping["name"]["copy_to"]
    assert "dates" in mapping["birthDate"]["copy_to"]

    # Caption properties should copy to the name field
    assert (
        "name" in mapping["name"]["copy_to"]
    ), "name property should copy to name field"
    # Check Document schema caption properties (fileName and title)
    doc_mapping = make_schema_mapping(["Document"])
    assert (
        "name" in doc_mapping["fileName"]["copy_to"]
    ), "fileName should copy to name field"
    assert "name" in doc_mapping["title"]["copy_to"], "title should copy to name field"
    # Check Person schema caption property (name)
    person_mapping = make_schema_mapping(["Person"])
    assert (
        "name" in person_mapping["name"]["copy_to"]
    ), "Person name should copy to name field"

    full_mapping = make_mapping(mapping)
    assert "date" in full_mapping["properties"]["numeric"]["properties"]
    assert "dates" in full_mapping["properties"]["numeric"]["properties"]
    assert full_mapping["properties"]["numeric"]["properties"]["dates"] == {
        "type": "double"
    }


def test_mapping_schema_bucket():
    # full text is stored only for Pages entities
    mapping = make_schema_bucket_mapping("pages")
    assert mapping["properties"]["content"]["store"] is True
    mapping = make_schema_bucket_mapping("page")
    assert mapping["properties"]["content"]["store"] is False
    mapping = make_schema_bucket_mapping("documents")
    assert mapping["properties"]["content"]["store"] is False
    mapping = make_schema_bucket_mapping("intervals")
    assert mapping["properties"]["content"]["store"] is False
    mapping = make_schema_bucket_mapping("things")
    assert mapping["properties"]["content"]["store"] is False
