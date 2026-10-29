from openaleph_search.index import entities


def test_delete_entity_passes_sync(monkeypatch):
    # the test settings refresh on every write, so check the call instead
    deleted = []
    monkeypatch.setattr(
        entities, "entities_by_ids", lambda *args, **kwargs: iter([{"_index": "a"}])
    )
    monkeypatch.setattr(
        entities,
        "delete_safe",
        lambda index, id, sync=False: deleted.append((index, id, sync)),
    )
    entities.delete_entity("e1", sync=True)
    entities.delete_entity("e1")
    assert deleted == [("a", "e1", True), ("a", "e1", False)]
