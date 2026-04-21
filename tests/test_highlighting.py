from ftmq.util import make_entity

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
    # Unified highlighter highlights individual terms rather than full phrase spans
    assert "<em>Mr</em>" in highlight
    assert "<em>Trump</em>" in highlight
    assert "<em>proclaimed</em>" in highlight

    highlight = _search_highlight('"former chairman"~2')
    assert "<em>former</em>" in highlight
    assert "<em>chairman</em>" in highlight

    highlight = _search_highlight('"paul manafort"')
    assert highlight is not None
    assert "<em>Paul</em>" in highlight
    assert "<em>Manafort</em>" in highlight

    highlight = _search_highlight("Українська")
    assert highlight is not None
    assert "<em>Українська" in highlight
    highlight = _search_highlight('"日本語"')
    assert highlight is not None
    assert "<em>日" in highlight


def test_highlighting_pages(fixture_pages, cleanup_after):
    """Test highlighting on Pages entities with parent-child relationships"""
    # Index the pages fixture data
    index_bulk("test_pages_highlight", fixture_pages, sync=True)

    # Search in the indexText (-> content) of a Pages (aka Document) entity
    # Unified highlighter highlights individual terms rather than full phrase spans
    highlight = _search_highlight(
        '"MIT license" "useful information" documentation', schema="Pages"
    )
    assert "<em>MIT</em>" in highlight
    assert "<em>license</em>" in highlight
    assert "<em>useful</em>" in highlight
    assert "<em>information</em>" in highlight
    assert "<em>documentation</em>" in highlight

    # Search within its child page entities (used in OpenAleph ui)
    highlight = _search_highlight(
        '"MIT license" "useful information" documentation',
        schema="Page",
        parent_id="f61295777cf69f423855655f1614794ce22086d8.b154e50f50c8c8133168767d78bbd1dff067f308",
    )
    assert "<em>MIT</em>" in highlight
    assert "<em>license</em>" in highlight
    assert "<em>useful</em>" in highlight
    assert "<em>information</em>" in highlight
    assert "<em>documentation</em>" in highlight

    # Include mentioned names
    highlight = _search_highlight(
        'names:"massachusetts institute of technology" "MIT license"', schema="Pages"
    )
    assert "massachusetts institute of technology" in highlight
    assert "<em>MIT</em>" in highlight
    assert "<em>license</em>" in highlight

    # Page doesn't contain "names" but still the highlight works for the text phrase
    highlight = _search_highlight(
        'names:"massachusetts institute of technology" "MIT license"',
        schema="Page",
        parent_id="f61295777cf69f423855655f1614794ce22086d8.b154e50f50c8c8133168767d78bbd1dff067f308",
    )
    assert "<em>MIT</em>" in highlight
    assert "<em>license</em>" in highlight


def test_highlighting_translation_plaintext(cleanup_after):
    """Test that translation highlights are returned under the 'translation' key,
    separate from 'content' highlights."""
    entity = make_entity(
        {
            "id": "plaintext-highlight-translation",
            "schema": "PlainText",
            "properties": {
                "fileName": ["report.txt"],
                "bodyText": ["Original text about financial regulations"],
                "translatedText": ["Übersetzter Text über Finanzvorschriften"],
            },
        }
    )

    index_bulk("test_highlight_translation", [entity], sync=True)

    args = [
        ("q", "Finanzvorschriften"),
        ("highlight", "true"),
        ("filter:dataset", "test_highlight_translation"),
    ]
    query = EntitiesQuery(SearchQueryParser(args, None))
    result = query.search()

    assert result["hits"]["total"]["value"] == 1
    hit = result["hits"]["hits"][0]
    assert "highlight" in hit
    # Translation highlights should be under the 'translation' key
    assert "translation" in hit["highlight"]
    assert any(
        "<em>Finanzvorschriften</em>" in fragment
        for fragment in hit["highlight"]["translation"]
    )


def test_highlighting_translation_pages(cleanup_after):
    """Test that Pages translation highlights are returned under 'translation' key,
    while original content highlights come under 'content'."""
    entity = make_entity(
        {
            "id": "pages-highlight-translation",
            "schema": "Pages",
            "properties": {
                "fileName": ["bericht.pdf"],
                "indexText": [
                    "Original German text about environmental policies",
                    "__translation__ Translated text about Umweltpolitik",
                ],
            },
        }
    )

    index_bulk("test_highlight_pages_translation", [entity], sync=True)

    # Search for a term in the translation
    args = [
        ("q", "Umweltpolitik"),
        ("highlight", "true"),
        ("filter:dataset", "test_highlight_pages_translation"),
    ]
    query = EntitiesQuery(SearchQueryParser(args, None))
    result = query.search()

    assert result["hits"]["total"]["value"] == 1
    hit = result["hits"]["hits"][0]
    assert "highlight" in hit
    assert "translation" in hit["highlight"]
    assert any(
        "<em>Umweltpolitik</em>" in fragment
        for fragment in hit["highlight"]["translation"]
    )

    # Search for a term in the original content — should highlight under 'content'
    args = [
        ("q", "environmental policies"),
        ("highlight", "true"),
        ("filter:dataset", "test_highlight_pages_translation"),
    ]
    query = EntitiesQuery(SearchQueryParser(args, None))
    result = query.search()

    assert result["hits"]["total"]["value"] == 1
    hit = result["hits"]["hits"][0]
    assert "highlight" in hit
    assert "content" in hit["highlight"]
    assert "translation" not in hit["highlight"]


# ── Annotated fulltext highlighting tests ─────────────────────────────

ZWJ = "\u200d"


def test_highlighting_annotated_crime_and_person(cleanup_after):
    """Searching for 'crime AND __PER__' highlights both the surface entity
    name and the context word 'crime'.

    Uses bodyText (which stays in _source via properties and copies to
    content) rather than indexText (which gets excluded from _source).
    """
    entity = make_entity(
        {
            "id": "ann-hl-1",
            "schema": "PlainText",
            "properties": {
                "bodyText": [
                    f"Serious crime involving "
                    f"Jane{ZWJ}__PER__{ZWJ}__doejane__ "
                    f"Doe{ZWJ}__PER__{ZWJ}__doejane__ "
                    f"at "
                    f"Acme{ZWJ}__LTD__{ZWJ}__acmecorp__ "
                    f"Corp{ZWJ}__LTD__{ZWJ}__acmecorp__"
                ],
            },
        }
    )
    index_bulk("test_ann_highlight", [entity], sync=True)

    args = [
        ("q", "crime AND __PER__"),
        ("highlight", "true"),
        ("filter:dataset", "test_ann_highlight"),
    ]
    query = EntitiesQuery(SearchQueryParser(args, None))
    result = query.search()

    assert result["hits"]["total"]["value"] == 1
    hit = result["hits"]["hits"][0]
    assert "highlight" in hit
    highlight_text = " ".join(v for values in hit["highlight"].values() for v in values)
    # "crime" should be highlighted
    assert "<em>crime</em>" in highlight_text
    # The unified highlighter wraps the entire ZWJ-joined annotation atom
    # in <em> tags, e.g. <em>Jane‍__PER__‍__doejane__</em>
    assert "<em>Jane" in highlight_text
    assert "<em>Doe" in highlight_text


def test_highlighting_annotated_proximity(cleanup_after):
    """Proximity query highlighting: '"crime __PER__"~5' highlights the
    matching span."""
    entity = make_entity(
        {
            "id": "ann-hl-2",
            "schema": "PlainText",
            "properties": {
                "bodyText": [
                    f"The investigation revealed crime by "
                    f"Vladimir{ZWJ}__PER__{ZWJ}__putin__ "
                    f"Putin{ZWJ}__PER__{ZWJ}__putin__ "
                    f"involving offshore accounts"
                ],
            },
        }
    )
    index_bulk("test_ann_hl_prox", [entity], sync=True)

    args = [
        ("q", '"crime __PER__"~5'),
        ("highlight", "true"),
        ("filter:dataset", "test_ann_hl_prox"),
    ]
    query = EntitiesQuery(SearchQueryParser(args, None))
    result = query.search()

    assert result["hits"]["total"]["value"] == 1
    hit = result["hits"]["hits"][0]
    assert "highlight" in hit
    highlight_text = " ".join(v for values in hit["highlight"].values() for v in values)
    assert "<em>crime</em>" in highlight_text.lower()


def test_highlighting_synonym_match(cleanup_after):
    """When synonyms expand 'Vladimir' to match 'Wladimir' in document text,
    the highlight shows the actual indexed text ('Wladimir')."""
    entity = make_entity(
        {
            "id": "syn-hl-1",
            "schema": "PlainText",
            "properties": {
                "bodyText": ["Report on Wladimir Igumnow and associates"],
            },
        }
    )
    index_bulk("test_syn_highlight", [entity], sync=True)

    args = [
        ("q", "Vladimir Igumnov"),
        ("synonyms", "true"),
        ("highlight", "true"),
        ("filter:dataset", "test_syn_highlight"),
    ]
    query = EntitiesQuery(SearchQueryParser(args, None))
    result = query.search()

    assert result["hits"]["total"]["value"] == 1
    hit = result["hits"]["hits"][0]
    assert "highlight" in hit
    highlight_text = " ".join(v for values in hit["highlight"].values() for v in values)
    # The actual indexed text "Wladimir" should be highlighted,
    # not the query term "Vladimir"
    assert "<em>Wladimir</em>" in highlight_text
