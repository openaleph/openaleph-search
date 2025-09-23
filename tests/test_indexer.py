from ftmq.util import make_entity

from openaleph_search.index.admin import clear_index
from openaleph_search.index.entities import index_bulk, iter_entities
from openaleph_search.transform.entity import format_entity


def test_indexer(entities, cleanup_after):
    # clear
    clear_index()

    index_bulk("test_dataset", entities)
    assert len(list(iter_entities())) == 21

    # overwrite
    index_bulk("test_dataset", entities)
    assert len(list(iter_entities())) == 21


def test_indexer_with_tags(cleanup_after):
    # clear
    clear_index()

    # Create entity with tags in context
    entity_data = {
        "id": "test-person-with-tags",
        "schema": "Person",
        "properties": {"name": ["Jane Doe"], "birthDate": ["1980-01-01"]},
    }
    entity = make_entity(entity_data)
    entity.context["tags"] = ["politician", "businessman", "controversial"]

    # Verify format_entity includes the tags
    formatted = format_entity("test_dataset", entity)
    assert formatted is not None
    assert "tags" in formatted["_source"]
    assert formatted["_source"]["tags"] == [
        "politician",
        "businessman",
        "controversial",
    ]

    index_bulk("test_dataset", [entity])

    # Verify entity was indexed
    indexed_entities = list(iter_entities())
    assert len(indexed_entities) == 1

    # Verify tags are in the indexed document
    indexed_entity = indexed_entities[0]
    assert "tags" in indexed_entity
    assert indexed_entity["tags"] == ["politician", "businessman", "controversial"]
