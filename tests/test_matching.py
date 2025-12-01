from ftmq.util import EntityProxy, make_entity

from openaleph_search.core import get_es
from openaleph_search.index.entities import index_bulk
from openaleph_search.index.indexes import entities_read_index
from openaleph_search.model import SearchAuth
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.matching import blocking_query
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


def _count(result) -> int:
    return result["hits"]["total"]["value"]


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
    assert _get_ids(result) == ["m2", "m5", "m6"]

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


def test_matchhing_auth(
    monkeypatch, cleanup_after, auth_admin, auth_private, auth_public
):
    """Test that MatchQuery respects authentication filters"""
    monkeypatch.setenv("OPENALEPH_SEARCH_AUTH", "true")

    # Create matching entities across datasets using same pattern as other tests
    # Jane Doe entities that should match
    public_entities = [
        _make_entity("pub1", "Person", "Jane Doe", nationality="us"),
        _make_entity("pub2", "Person", "Jane Doe", nationality="uk"),
        _make_entity("pub3", "Person", "Jane Dö", email="jane@example.com"),
    ]

    private_entities = [
        _make_entity("priv1", "Person", "Jane Doe", nationality="ca"),
        _make_entity("priv2", "Person", "Jane Doe", email="jane@private.com"),
        _make_entity(
            "priv3", "Person", "John Doe", country="us"
        ),  # Different first name, lower match
    ]

    # Index entities in different datasets
    index_bulk("test_public", public_entities, sync=True)
    index_bulk("test_private", private_entities, sync=True)

    # Use Jane Doe entity as source for matching
    source_entity = public_entities[0]  # Jane Doe with nationality=us

    unauthenticated = SearchAuth()

    # Test that unauthenticated users get no results
    parser = SearchQueryParser([], unauthenticated)
    match_query = MatchQuery(parser, source_entity)
    result = match_query.search()
    assert _count(result) == 0

    # Test that public auth only sees public results
    parser = SearchQueryParser([], auth_public)
    match_query = MatchQuery(parser, source_entity)
    result = match_query.search()
    public_hits = _count(result)

    # Should find Jane Doe matches in public dataset
    assert public_hits >= 2  # pub2 and pub3 should match
    hit_ids = _get_ids(result)
    # Should not include source entity
    assert "pub1" not in hit_ids
    # Should include other Jane Doe variants from public dataset
    assert "pub2" in hit_ids  # Jane Doe with different nationality
    assert "pub3" in hit_ids  # Jane Dö with email
    # Should only include public entities
    for hit_id in hit_ids:
        assert hit_id.startswith("pub")

    # Test that private auth sees both public and private results
    parser = SearchQueryParser([], auth_private)
    match_query = MatchQuery(parser, source_entity)
    result = match_query.search()
    private_hits = _count(result)
    hit_ids = _get_ids(result)

    # Private auth should see same or more results than public auth
    assert private_hits >= public_hits
    # Should include Jane Doe matches from both datasets
    assert "pub2" in hit_ids or "pub3" in hit_ids  # Public matches
    assert "priv1" in hit_ids or "priv2" in hit_ids  # Private matches
    # Source entity still excluded
    assert "pub1" not in hit_ids

    # Test that admin sees all results
    parser = SearchQueryParser([], auth_admin)
    match_query = MatchQuery(parser, source_entity)
    result = match_query.search()
    admin_hits = _count(result)

    # Admin should see same or more results than private auth
    assert admin_hits >= private_hits


def test_blocking_query(cleanup_after):
    """Test that blocking_query efficiently retrieves candidates without scoring."""
    # Create entities with various name variations
    # Use longer names to ensure phonetics are generated (short tokens are filtered)
    ent1 = _make_entity("b1", "Person", "Vladimir Putin", nationality="ru")
    ent2 = _make_entity(
        "b2", "Person", "Vladimir Putin", nationality="us"
    )  # exact match
    ent3 = _make_entity(
        "b3", "Person", "Wladimir Putin"
    )  # phonetic match (PTN overlap)
    ent4 = _make_entity("b4", "Page", "Vladimir Putin")  # non-matchable schema
    ent5 = _make_entity("b5", "Person", "Владимир Путин")  # cyrillic -> same name_key
    ent6 = _make_entity("b6", "Person", "Angela Merkel")  # no overlap
    ent7 = _make_entity("b7", "Company", "Acme Corp", registrationNumber="REG123")
    ent8 = _make_entity(
        "b8", "Company", "Acme Corporation", registrationNumber="REG123"
    )
    # Name symbol matches: John/Jack share [NICK:JACK] symbol
    ent9 = _make_entity("b9", "Person", "John Smith")
    ent10 = _make_entity("b10", "Person", "Jack Smith")  # symbol match via [NICK:JACK]
    index_bulk(
        "test_blocking", [ent1, ent2, ent3, ent4, ent5, ent6, ent7, ent8, ent9, ent10]
    )

    es = get_es()
    index = entities_read_index()

    # Test blocking query for Vladimir Putin - should find candidates via name_keys/phonetics
    query = blocking_query(ent1)
    result = es.search(index=index, query=query)
    hit_ids = _get_ids(result)

    # Should find exact name_key matches
    assert "b2" in hit_ids  # exact name_key match
    assert "b5" in hit_ids  # cyrillic has same name_key (putinvladimir)
    # Should find phonetic match (shares 'PTN' phoneme)
    assert "b3" in hit_ids  # Wladimir Putin - phonetic overlap
    # Should exclude self
    assert "b1" not in hit_ids
    # Should exclude non-matchable schema (Page)
    assert "b4" not in hit_ids
    # Should not match unrelated names
    assert "b6" not in hit_ids

    # Test name symbol matching (John/Jack share [NICK:JACK] symbol)
    query = blocking_query(ent9)
    result = es.search(index=index, query=query)
    hit_ids = _get_ids(result)

    # Should find Jack Smith via shared name symbol [NICK:JACK]
    assert "b10" in hit_ids  # symbol match
    assert "b9" not in hit_ids  # exclude self
    # Should not match unrelated persons
    assert "b1" not in hit_ids
    assert "b6" not in hit_ids

    # Test blocking query for Company with identifier
    query = blocking_query(ent7)
    result = es.search(index=index, query=query)
    hit_ids = _get_ids(result)

    # Should find match via shared identifier
    assert "b8" in hit_ids  # same registrationNumber
    assert "b7" not in hit_ids  # exclude self

    # Test that blocking query uses filter context (no scoring)
    # All results should have score of 0 or 1 (constant score in filter context)
    query = blocking_query(ent1)
    result = es.search(index=index, query=query)
    scores = [h["_score"] for h in result["hits"]["hits"]]
    # In filter context, scores are typically 0 or constant
    assert all(
        s == scores[0] for s in scores
    ), "All scores should be equal in filter context"

    # Test dataset filtering
    index_bulk(
        "test_blocking_other",
        [
            _make_entity("o1", "Person", "Vladimir Putin", nationality="ca"),
        ],
    )

    query = blocking_query(ent1, datasets=["test_blocking"])
    result = es.search(index=index, query=query)
    hit_ids = _get_ids(result)
    # Should only include entities from test_blocking dataset
    assert "o1" not in hit_ids

    # Test that non-matchable entities return match_none
    query = blocking_query(ent4)  # Page schema
    assert query == {"match_none": {}}
