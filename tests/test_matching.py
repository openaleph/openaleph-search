from ftmq.util import EntityProxy, make_entity

from openaleph_search.index.entities import index_bulk
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.queries import MatchQuery


def _make_entity(id: str, schema: str, name: str, **data) -> EntityProxy:
    return make_entity(
        {
            "id": id,
            "schema": schema,
            "properties": {"name": [name], **{k: [v] for k, v in data.items()}},
        }
    )


def _get_ids(result) -> list[str]:
    return [h["_id"] for h in result["hits"]["hits"]]


def test_matching(cleanup_after):
    ent1 = _make_entity("m1", "Person", "Jane Doe", nationality="us")
    ent2 = _make_entity("m2", "Person", "Jane Doe", nationality="mt")
    ent3 = _make_entity("m3", "Person", "John Doe", country="mt")
    ent4 = _make_entity("m4", "Pages", "John Doe", country="mt")
    ent5 = _make_entity("m5", "Person", "Jane Doe", email="jane@foo.local")
    ent6 = _make_entity("m6", "Person", "Jane Dö", email="jane@foo.local")
    index_bulk("test_matching1", [ent1, ent2, ent3, ent4, ent5, ent6])

    parser = SearchQueryParser([])
    query = MatchQuery(parser, ent1)
    result = query.search()
    assert _get_ids(result) == ["m2", "m5", "m6", "m3"]

    query = MatchQuery(parser, ent6)
    result = query.search()
    assert _get_ids(result)[0] == "m5"

    # documents can't match
    query = MatchQuery(parser, ent4)
    result = query.search()
    assert _get_ids(result) == []

    parser = SearchQueryParser([("filter:properties.nationality", "mt")])
    query = MatchQuery(parser, ent1)
    result = query.search()
    assert _get_ids(result) == ["m2"]
