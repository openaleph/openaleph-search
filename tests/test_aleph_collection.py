from openaleph_search.index.entities import index_bulk
from openaleph_search.search.logic import search_query_string


def test_aleph_collection(entities, cleanup_after):
    entities = [e for e in entities if e.schema.name != "Page"]
    entities1 = entities[:5]
    entities2 = entities[5:]
    index_bulk("collection1", entities1, collection_id=1)
    index_bulk("collection2", entities2, collection_id=2)
    res = search_query_string("", "filter:collection_id=1")
    assert len(res["hits"]["hits"]) == len(entities1)
    res = search_query_string("", "filter:collection_id=2")
    assert len(res["hits"]["hits"]) == len(entities2)
    ent = res["hits"]["hits"][0]
    assert ent["_source"]["collection_id"] == 2
