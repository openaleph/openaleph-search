from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.queries import EntitiesQuery


def _search_highlight(q: str) -> str | None:
    args = [("q", q), ("highlight", "true")]
    query = EntitiesQuery(SearchQueryParser(args, None))
    res = query.search()
    for hit in res["hits"]["hits"]:
        for values in hit["highlight"].values():
            return " ".join(values)


def test_highlighting(index_entities):
    highlight = _search_highlight("search wikipedia")
    assert highlight is not None
    assert "<em>Search</em> <em>Wikipedia</em>" in highlight

    highlight = _search_highlight('"search wikipedia"')
    assert highlight is not None
    assert "<em>Search</em> <em>Wikipedia</em>" in highlight

    highlight = _search_highlight("Українська")
    assert highlight is not None
    assert "<em>Українська</em>" in highlight
