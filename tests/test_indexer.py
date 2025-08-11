from openaleph_search.index.entities import index_bulk, iter_entities


def test_indexer(entities):
    index_bulk("test_dataset", entities)
    assert len(list(iter_entities())) == 21

    # overwrite
    index_bulk("test_dataset", entities)
    assert len(list(iter_entities())) == 21
