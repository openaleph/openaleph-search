from ftmq.util import make_entity

from openaleph_search.index.admin import clear_index
from openaleph_search.index.entities import index_bulk
from openaleph_search.index.export import export_index_actions
from openaleph_search.search.logic import make_parser
from openaleph_search.settings import Settings
from openaleph_search.transform.entity import format_entity


def test_export_index_actions(entities, cleanup_after):
    """Test that export_index_actions returns the same data as was indexed."""
    # Clear and index test data
    clear_index()
    dataset = "test_export"
    index_bulk(dataset, entities)

    settings = Settings()
    index_pattern = f"{settings.index_prefix}-entity-*"

    # Export all entities
    exported_actions = list(export_index_actions(index_pattern))

    # Should have exported all entities
    assert len(exported_actions) == len(entities)

    # Create a mapping of entity_id -> formatted action for comparison
    expected_actions = {}
    for entity in entities:
        formatted = format_entity(dataset, entity)
        if formatted:
            expected_actions[formatted["_id"]] = formatted

    # Compare exported actions with expected formatted actions
    for exported in exported_actions:
        entity_id = exported["_id"]
        assert entity_id in expected_actions

        expected = expected_actions[entity_id]

        # Check structure
        assert exported["_index"] == expected["_index"]
        assert exported["_id"] == expected["_id"]

        # Check key fields in _source
        exported_source = exported["_source"]
        expected_source = expected["_source"]

        assert exported_source["schema"] == expected_source["schema"]
        assert exported_source["dataset"] == expected_source["dataset"]
        assert exported_source["caption"] == expected_source["caption"]
        assert exported_source["properties"] == expected_source["properties"]


def test_export_with_context_data(cleanup_after):
    """Test that export preserves context data like tags and metadata."""
    clear_index()

    # Create entity with tags and context
    entity_data = {
        "id": "test-person-export",
        "schema": "Person",
        "properties": {"name": ["Jane Doe"], "birthDate": ["1985-05-15"]},
    }
    entity = make_entity(entity_data)
    entity.context = {
        "tags": ["politician", "activist"],
        "role_id": 5,
        "mutable": True,
        "created_at": "2023-01-15",
    }

    dataset = "test_export_context"
    index_bulk(dataset, [entity])

    settings = Settings()
    index_pattern = f"{settings.index_prefix}-entity-*"

    # Export the entity
    exported_actions = list(export_index_actions(index_pattern))
    assert len(exported_actions) == 1

    exported = exported_actions[0]
    exported_source = exported["_source"]

    # Verify context data was preserved
    assert exported_source["tags"] == ["politician", "activist"]
    assert exported_source["role_id"] == 5
    assert exported_source["mutable"] is True
    assert exported_source["created_at"] == "2023-01-15"


def test_export_specific_query(entities, cleanup_after):
    """Test export from a specific index pattern."""
    clear_index()

    # Index entities into two different datasets
    index_bulk("dataset_one", entities[:10])
    index_bulk("dataset_two", entities[10:])

    settings = Settings()

    parser = make_parser(args="filter:dataset=dataset_one")
    exported = list(export_index_actions(f"{settings.index_prefix}-entity-*", parser))
    assert len(exported) == 10

    parser = make_parser(args="filter:dataset=dataset_two")
    exported = list(export_index_actions(f"{settings.index_prefix}-entity-*", parser))
    assert len(exported) == 11


def test_export_with_excluded_fields(cleanup_after):
    """Test that include_excluded_fields retrieves fields excluded from _source."""
    from conftest import TEST_PRIVATE

    clear_index()
    dataset = "test_excluded"

    # Use TEST_PRIVATE which contains Person entities with names
    test_entities = [make_entity(e) for e in TEST_PRIVATE]
    index_bulk(dataset, test_entities)

    settings = Settings()
    index_pattern = f"{settings.index_prefix}-entity-*"

    # Export without excluded fields
    exported_without = list(export_index_actions(index_pattern))

    # Export with excluded fields
    exported_with = list(
        export_index_actions(index_pattern, include_excluded_fields=True)
    )

    assert len(exported_without) == len(exported_with) == len(TEST_PRIVATE)

    # Check that excluded fields are missing in default export
    for action in exported_without:
        source = action["_source"]
        # These fields should not be in _source by default
        assert "name_keys" not in source
        assert "name_parts" not in source
        assert "name_symbols" not in source

    # Check that excluded fields are present when requested
    has_name_keys = False
    for action in exported_with:
        source = action["_source"]
        # At least some entities should have these fields if they have names
        if "name_keys" in source and source["name_keys"]:
            has_name_keys = True
            # Verify it's an array (from docvalues)
            assert isinstance(source["name_keys"], list)

    # At least one entity should have had name_keys
    assert has_name_keys, "Expected at least one entity to have name_keys"


def test_export_with_stored_content(cleanup_after):
    """Test that include_excluded_fields retrieves stored content field."""
    clear_index()

    # Create entity with indexText (maps to content field)
    entity_data = {
        "id": "test-with-content",
        "schema": "PlainText",
        "properties": {
            "fileName": ["document.txt"],
            "indexText": ["This is the full text content that should be stored."],
        },
    }
    entity = make_entity(entity_data)

    dataset = "test_content"
    index_bulk(dataset, [entity])

    settings = Settings()
    index_pattern = f"{settings.index_prefix}-entity-*"

    # Export without excluded fields
    exported_without = list(export_index_actions(index_pattern))
    assert len(exported_without) == 1
    # Content should NOT be in _source by default
    assert "content" not in exported_without[0]["_source"]

    # Export with excluded fields
    exported_with = list(
        export_index_actions(index_pattern, include_excluded_fields=True)
    )
    assert len(exported_with) == 1

    # Content should be present when requested (from stored_fields)
    source = exported_with[0]["_source"]
    assert "content" in source
    assert isinstance(source["content"], list)
    assert "This is the full text content that should be stored." in source["content"]
