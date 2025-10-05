from openaleph_search.index.entities import index_bulk
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.queries import EntitiesQuery


def _search_highlight(
    q: str, schema: str | None = None, parent_id: str | None = None
) -> str | None:
    """Helper to search with highlighting and return first highlight"""
    args = [("q", q), ("highlight", "true")]
    if schema:
        args.append(("filter:schema", schema))
    if parent_id:
        args.append(("filter:properties.document", parent_id))
    query = EntitiesQuery(SearchQueryParser(args, None))
    res = query.search()
    for hit in res["hits"]["hits"]:
        return " ".join(
            v for values in hit.get("highlight", {}).values() for v in values
        )


def test_highlighting_phrases(index_entities):
    # this is using the sample entity 242d6724b38425f11df37437c38125b71fb13300
    highlight = _search_highlight('"Mr. Trump proclaimed"')
    assert "<em>Mr. Trump proclaimed</em>" in highlight

    highlight = _search_highlight('"former chairman"~2')
    assert "<em>former</em>" in highlight
    assert "<em>chairman</em>" in highlight

    highlight = _search_highlight('"paul manafort"')
    assert highlight is not None
    assert "<em>Paul Manafort</em>" in highlight

    highlight = _search_highlight("Українська")
    assert highlight is not None
    assert "<em>Українська" in highlight
    highlight = _search_highlight('"日本語"')
    assert highlight is not None
    assert "<em>本</em><em>語" in highlight


def test_highlighting_pages(fixture_pages, cleanup_after):
    """Test highlighting on Pages entities with parent-child relationships"""
    # Index the pages fixture data
    index_bulk("test_pages_highlight", fixture_pages, sync=True)

    # Search in the indexText (-> content) of a Pages (aka Document) entity
    highlight = _search_highlight(
        '"MIT license" "useful information" documentation', schema="Pages"
    )
    assert "<em>MIT license</em>" in highlight
    assert "<em>useful information</em>" in highlight
    assert "<em>documentation</em>" in highlight

    # Search within its child page entities (used in OpenAleph ui)
    highlight = _search_highlight(
        '"MIT license" "useful information" documentation',
        schema="Page",
        parent_id="f61295777cf69f423855655f1614794ce22086d8.b154e50f50c8c8133168767d78bbd1dff067f308",
    )
    assert "<em>MIT license</em>" in highlight
    assert "<em>useful information</em>" in highlight
    assert "<em>documentation</em>" in highlight

    # Include mentioned names
    highlight = _search_highlight(
        'names:"massachusetts institute of technology" "MIT license"', schema="Pages"
    )
    assert "massachusetts institute of technology" in highlight
    assert "<em>MIT license</em>" in highlight

    # Page doesn't contain "names" but still the highlight works for the text phrase
    highlight = _search_highlight(
        'names:"massachusetts institute of technology" "MIT license"',
        schema="Page",
        parent_id="f61295777cf69f423855655f1614794ce22086d8.b154e50f50c8c8133168767d78bbd1dff067f308",
    )
    assert "<em>MIT license</em>" in highlight
