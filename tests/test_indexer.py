from ftmq.util import make_entity

from openaleph_search.index.admin import clear_index
from openaleph_search.index.entities import (
    EntityVersion,
    get_entity_version,
    index_bulk,
    iter_entities,
    iter_entity_ids,
)
from openaleph_search.index.indexer import rewrite_mapping_safe
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


def test_get_entity_version(cleanup_after):
    """get_entity_version returns (seq_no, primary_term) and bumps on rewrites."""
    clear_index()

    entity = make_entity(
        {
            "id": "version-test-person",
            "schema": "Person",
            "properties": {"name": ["Jane Versioned"]},
        }
    )
    index_bulk("test_versions", [entity], sync=True)

    v1 = get_entity_version("version-test-person")
    assert isinstance(v1, EntityVersion)
    assert isinstance(v1.seq_no, int)
    assert isinstance(v1.primary_term, int)

    # Re-indexing the same id bumps the seq_no.
    entity2 = make_entity(
        {
            "id": "version-test-person",
            "schema": "Person",
            "properties": {"name": ["Jane Versioned"], "nationality": ["DE"]},
        }
    )
    index_bulk("test_versions", [entity2], sync=True)

    v2 = get_entity_version("version-test-person")
    assert v2 is not None
    assert v2.seq_no > v1.seq_no

    # Unknown id returns None.
    assert get_entity_version("does-not-exist") is None


def test_iter_entity_ids(entities, cleanup_after):
    # clear
    clear_index()

    # Index entities from fixture
    index_bulk("test_dataset", entities)

    # Get all entity IDs
    entity_ids = list(iter_entity_ids())
    assert len(entity_ids) == 21

    # Verify IDs match the indexed entities
    expected_ids = {e.id for e in entities}
    actual_ids = set(entity_ids)
    assert actual_ids == expected_ids

    # Test filtering by dataset
    # Create separate entities for other dataset to avoid overwriting
    other_entities = [
        make_entity(
            {
                "id": f"other-{i}",
                "schema": "Person",
                "properties": {"name": [f"Person {i}"]},
            }
        )
        for i in range(5)
    ]
    index_bulk("other_dataset", other_entities)

    test_dataset_ids = list(iter_entity_ids(dataset="test_dataset"))
    assert len(test_dataset_ids) == 21

    other_dataset_ids = list(iter_entity_ids(dataset="other_dataset"))
    assert len(other_dataset_ids) == 5

    # Verify total count includes both datasets
    all_ids = list(iter_entity_ids())
    assert len(all_ids) == 26

    # Test sorting by _id (ascending)
    sorted_ids = list(iter_entity_ids(dataset="test_dataset", sort="_id"))
    assert len(sorted_ids) == 21
    assert sorted_ids == sorted(sorted_ids), "IDs should be sorted ascending"

    # Test sorting by _id (descending)
    desc_sorted_ids = list(
        iter_entity_ids(dataset="test_dataset", sort={"_id": "desc"})
    )
    assert len(desc_sorted_ids) == 21
    assert desc_sorted_ids == sorted(
        desc_sorted_ids, reverse=True
    ), "IDs should be sorted descending"


def test_translation_plaintext():
    """PlainText: translatedText property is kept in properties; the ES mapping
    copy_to directive copies it into the `translation` field at index time, so
    the transform payload should NOT contain a top-level `translation` key."""
    entity = make_entity(
        {
            "id": "plain-text-translated",
            "schema": "PlainText",
            "properties": {
                "fileName": ["document.txt"],
                "translatedText": ["This is the translated text"],
            },
        }
    )
    action = format_entity("test_dataset", entity)
    assert action is not None
    source = action["_source"]
    # translatedText stays in properties for ES copy_to to handle
    assert "translatedText" in source["properties"]
    assert source["properties"]["translatedText"] == ["This is the translated text"]
    # No explicit translation field — ES copy_to handles it
    assert "translation" not in source


def test_translation_pages():
    """Pages: translations are extracted from indexText values prefixed with
    `__translation__` and placed into the `translation` field explicitly."""
    entity = make_entity(
        {
            "id": "pages-translated",
            "schema": "Pages",
            "properties": {
                "fileName": ["document.pdf"],
                "indexText": [
                    "regular text content",
                    "__translation__ Dies ist der übersetzte Text",
                    "__translation__ Ceci est le texte traduit",
                ],
            },
        }
    )
    action = format_entity("test_dataset", entity)
    assert action is not None
    source = action["_source"]
    assert "translation" in source
    assert set(source["translation"]) == {
        "Dies ist der übersetzte Text",
        "Ceci est le texte traduit",
    }
    # indexText is moved to `content`, and translations are stripped out
    assert "content" in source


def test_rewrite_mapping_safe_preserves_default_immutables():
    """Regression for the e864564 ``index: false`` bugfix.

    Older indexes were created when ``make_schema_mapping`` dropped the
    ``index: false`` extra from ``TYPE_MAPPINGS``, so ES applied its
    default ``index: true`` to text/html/json properties. ES then froze
    that default — pushing ``index: false`` later raises
    ``illegal_argument_exception``. ``rewrite_mapping_safe`` must
    therefore drop the pending override when the field exists in the
    live mapping but the immutable key is absent (= ES default in
    effect).
    """
    # Field exists; the live mapping omits `index` (ES default `true`
    # was applied at creation). The pending update wants `index: false`
    # — that must be stripped, not pushed.
    pending = {
        "properties": {
            "properties": {
                "type": "object",
                "properties": {
                    "indexText": {
                        "type": "text",
                        "index": False,
                        "copy_to": ["content"],
                    },
                },
            },
        },
    }
    existing = {
        "properties": {
            "properties": {
                "type": "object",
                "properties": {
                    "indexText": {
                        "type": "text",
                        "copy_to": ["content"],
                    },
                },
            },
        },
    }
    result = rewrite_mapping_safe(pending, existing)
    field = result["properties"]["properties"]["properties"]["indexText"]
    assert "index" not in field, field
    assert field["type"] == "text"


def test_rewrite_mapping_safe_preserves_explicit_immutables():
    """Explicit immutable values on the live mapping always win."""
    pending = {
        "properties": {
            "name": {
                "type": "keyword",
                "normalizer": "name-kw-normalizer",
            },
        },
    }
    existing = {
        "properties": {
            "name": {
                "type": "keyword",
                "normalizer": "kw-normalizer",
            },
        },
    }
    result = rewrite_mapping_safe(pending, existing)
    assert result["properties"]["name"]["normalizer"] == "kw-normalizer"


def test_rewrite_mapping_safe_passes_through_new_fields():
    """Fields absent from the live mapping keep all their immutables."""
    pending = {
        "properties": {
            "newProp": {
                "type": "text",
                "index": False,
                "copy_to": ["content"],
            },
        },
    }
    existing = {"properties": {}}
    result = rewrite_mapping_safe(pending, existing)
    new = result["properties"]["newProp"]
    assert new["index"] is False
    assert new["type"] == "text"


def test_indexer_namespace(monkeypatch):
    import importlib

    from openaleph_search.transform import entity as entity_module

    data = {
        "id": "jane",
        "schema": "Person",
        "properties": {"name": ["Jane Doe"], "birthDate": ["1980-01-01"]},
    }
    entity = make_entity(data)
    action = entity_module.format_entity("test", entity)
    assert action is not None
    assert action["_id"] == "jane"

    # Test with namespace enforcement enabled
    monkeypatch.setenv("OPENALEPH_SEARCH_INDEX_NAMESPACE_IDS", "true")
    # Reload the settings module first, then the entity module
    from openaleph_search import settings as settings_module

    importlib.reload(settings_module)
    importlib.reload(entity_module)

    action = entity_module.format_entity("test", entity)
    assert action is not None
    assert action["_id"] == "jane.0ab35dc935d0e27f7bafd9a98610fb635d730ef7"

    # Clean up
    monkeypatch.setenv("OPENALEPH_SEARCH_INDEX_NAMESPACE_IDS", "false")
    importlib.reload(settings_module)
    importlib.reload(entity_module)
