from ftmq.util import make_entity

from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.queries import EntitiesQuery
from openaleph_search.transform.entity import format_entity


def test_routing():
    ent = make_entity({"id": "1", "schema": "Person"})
    doc = format_entity("routing_dataset", ent)
    assert doc
    assert doc["_routing"] == "routing_dataset"

    parser = SearchQueryParser([("q", "banana")])
    assert parser.routing_key is None
    parser = SearchQueryParser([("q", "banana"), ("filter:dataset", "routing_dataset")])
    assert parser.routing_key == "routing_dataset"
    parser = SearchQueryParser(
        [
            ("q", "banana"),
            ("filter:dataset", "routing_dataset"),
            ("filter:dataset", "another"),
        ]
    )
    assert parser.routing_key is None

    # just see if nothing breaks
    query = EntitiesQuery(parser)
    res = query.search()
    assert res["hits"]["hits"] == []
