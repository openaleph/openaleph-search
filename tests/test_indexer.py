from ftmq.util import make_entity

from openaleph_search.core import get_es
from openaleph_search.index.admin import clear_index
from openaleph_search.index.entities import index_bulk, iter_entities
from openaleph_search.index.util import bulk_indexing_mode
from openaleph_search.settings import Settings
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


def test_indexer_with_context(cleanup_after):
    # clear
    clear_index()

    # Create entity with OpenAleph metadata in context
    entity_data = {
        "id": "test-person-with-tags",
        "schema": "Person",
        "properties": {"name": ["Jane Doe"], "birthDate": ["1980-01-01"]},
    }
    entity = make_entity(entity_data)
    entity.context = {"role_id": 3, "mutable": True, "created_at": "2023-04-26"}

    # Verify format_entity includes the context
    formatted = format_entity("test_dataset", entity)
    assert formatted is not None
    assert formatted["_source"]["role_id"] == 3
    assert formatted["_source"]["mutable"] is True
    assert formatted["_source"]["created_at"] == "2023-04-26"

    index_bulk("test_dataset", [entity])

    # Verify entity was indexed
    indexed_entities = list(iter_entities())
    assert len(indexed_entities) == 1

    # Verify context is in the indexed document
    indexed_entity = indexed_entities[0]
    assert indexed_entity["role_id"] == 3
    assert indexed_entity["mutable"] is True
    assert indexed_entity["created_at"] == "2023-04-26"


def test_temporary_refresh_interval(cleanup_after):
    """Test temporarily setting refresh interval using bulk_indexing_mode."""
    es = get_es()
    settings = Settings()
    index_pattern = f"{settings.index_prefix}-entity-*"

    # Use bulk_indexing_mode to temporarily change interval
    with bulk_indexing_mode(refresh_interval="15m"):
        # Check that settings were changed inside the context
        temp_settings = es.indices.get_settings(index=index_pattern)
        for index_name, index_settings in temp_settings.items():
            refresh_interval = index_settings["settings"]["index"]["refresh_interval"]
            assert refresh_interval == "15m"

    # Check that settings were restored to configured default (not the previous "2s")
    restored_settings = es.indices.get_settings(index=index_pattern)
    for index_name, index_settings in restored_settings.items():
        refresh_interval = index_settings["settings"]["index"]["refresh_interval"]
        assert refresh_interval == settings.index_refresh_interval


def test_bulk_indexing_mode(cleanup_after):
    """Test the bulk indexing mode context manager."""
    es = get_es()
    settings = Settings()
    index_pattern = f"{settings.index_prefix}-entity-*"

    # Use bulk indexing mode context manager
    with bulk_indexing_mode("300s"):
        # Check that bulk settings were applied inside the context
        bulk_settings = es.indices.get_settings(index=index_pattern)
        for index_name, index_settings in bulk_settings.items():
            idx_settings = index_settings["settings"]["index"]
            assert idx_settings["refresh_interval"] == "300s"
            assert idx_settings["translog"]["durability"] == "async"
            assert idx_settings["translog"]["sync_interval"] == "60s"
            assert idx_settings["number_of_replicas"] == "0"

    # Check that settings were restored to configured defaults
    restored_settings = es.indices.get_settings(index=index_pattern)
    for index_name, index_settings in restored_settings.items():
        idx_settings = index_settings["settings"]["index"]
        assert idx_settings["refresh_interval"] == settings.index_refresh_interval
        assert idx_settings["translog"]["durability"] == "request"
        assert idx_settings["number_of_replicas"] == str(settings.index_replicas)
