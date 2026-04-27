"""Tests for PercolatorQuery against the things bucket.

Each entity in the things bucket carries a stored percolator query built
from its cleaned name variants at index time (see
`openaleph_search.transform.entity.format_entity`). These tests exercise
the end-to-end pipeline by indexing real entities via the `index_entities`
fixture and percolating documents that mention them.

Available test entities (from `tests/conftest.py`):

- `Vladimir L.` (Person, `test_samples` dataset, multi-token, kept)
- `Banana ba Nana` (Person id `banana3`, `test_private`, multi-token, kept)
- `KwaZulu` (Company id `id-company`, `test_public`, single token, 7 chars,
  exactly at the cleaner threshold — kept)
- `Banana` (Person ids `banana1`, `banana2`, `test_private`, single token,
  6 chars — DROPPED by `clean_matching_names`, so they should NOT be
  matched even if a doc says "Banana")
"""

from unittest import mock

import pytest
from ftmq.util import make_entity

from openaleph_search.index.entities import index_bulk
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.queries import PercolatorQuery


def _percolate(text: str, args: list[tuple[str, str]] | None = None):
    parser = SearchQueryParser(args or [])
    return PercolatorQuery(parser, text=text).search()


def test_percolator_query_finds_entity(index_entities):
    """Percolating a doc that mentions two indexed entities returns both."""
    text = (
        "An investigation into KwaZulu revealed that "
        "Banana ba Nana was involved in the affair."
    )
    # Highlights are opt-in, same as every other Query subclass.
    result = _percolate(text, args=[("highlight", "true")])

    hits = result["hits"]["hits"]
    by_id = {h["_id"]: h for h in hits}

    assert "id-company" in by_id, f"id-company missing from {list(by_id)}"
    assert "banana3" in by_id, f"banana3 missing from {list(by_id)}"

    company_hit = by_id["id-company"]
    assert company_hit["_source"]["surface_forms"] == ["KwaZulu"]

    banana_hit = by_id["banana3"]
    assert banana_hit["_source"]["surface_forms"] == ["Banana ba Nana"]


def test_percolator_query_no_match(index_entities):
    """A document with no recognizable entity names returns nothing."""
    result = _percolate("The weather forecast predicts rain for the entire week.")
    assert result["hits"]["total"]["value"] == 0
    assert result["hits"]["hits"] == []


def test_percolator_query_dataset_filter(index_entities):
    """Standard filter:dataset narrows the percolator candidate set."""
    text = (
        "An investigation into KwaZulu revealed that "
        "Banana ba Nana was involved in the affair."
    )
    result = _percolate(text, args=[("filter:dataset", "test_public")])

    hits = result["hits"]["hits"]
    ids = {h["_id"] for h in hits}

    # KwaZulu Company is in test_public — it should match
    assert "id-company" in ids
    # banana3 Person is in test_private — it should be filtered out
    assert "banana3" not in ids


def test_percolator_query_dehydrate(index_entities):
    """parser.dehydrate strips properties but keeps surface_forms."""
    text = "An investigation into KwaZulu was launched."
    result = _percolate(text, args=[("dehydrate", "true"), ("highlight", "true")])

    hits = result["hits"]["hits"]
    assert len(hits) >= 1
    company_hit = next(h for h in hits if h["_id"] == "id-company")

    # Properties stripped
    assert "properties" not in company_hit["_source"]
    # surface_forms still present
    assert company_hit["_source"]["surface_forms"] == ["KwaZulu"]


def test_percolator_query_short_single_token_dropped(index_entities, cleanup_after):
    """clean_matching_names drops single-token names < 7 chars.

    The fixture has Person `banana1`/`banana2` with name "Banana" (6 chars,
    single token). They should NOT have a stored percolator query, so a
    document mentioning "Banana" should not return them.

    We also index a custom Person whose name is "Doe" (3 chars) to be
    extra explicit about the threshold.
    """
    short_name_entity = make_entity(
        {
            "id": "doe-person",
            "schema": "Person",
            "properties": {"name": ["Doe"]},
        }
    )
    index_bulk("test_short_names", [short_name_entity], sync=True)

    result = _percolate("John Doe walked away from the meeting at noon.")
    ids = {h["_id"] for h in result["hits"]["hits"]}

    # Neither the "Doe" entity nor the "Banana" entities should match —
    # their cleaned name lists are empty so they have no `query` field.
    assert "doe-person" not in ids
    assert "banana1" not in ids
    assert "banana2" not in ids


def test_percolator_query_globally_disabled(index_entities):
    """When OPENALEPH_SEARCH_PERCOLATION=0, PercolatorQuery short-circuits.

    The transform also skips writing the `query` field, but for this test
    we only need to verify the query side returns an empty result fast.
    """
    with mock.patch("openaleph_search.query.queries.settings.percolation", False):
        result = _percolate(
            "An investigation into KwaZulu and Banana ba Nana was launched."
        )
    assert result["hits"]["total"]["value"] == 0
    assert result["hits"]["hits"] == []


def test_percolator_query_highlight_snippets(cleanup_after):
    """Each hit carries an EntitiesQuery-format highlight block.

    The percolator highlight uses the same shape as `EntitiesQuery`
    highlights — a `highlight.content` list of fragment snippets with
    `<em>…</em>` markup, driven by `get_highlighter(Field.CONTENT)`.
    The marked spans inside the snippets agree with `_source.surface_forms`.
    """
    vessel = make_entity(
        {
            "id": "vessel-snippets",
            "schema": "Vessel",
            "properties": {
                "name": ["MV Snippet Tester"],
                "imoNumber": ["7654321"],
            },
        }
    )
    index_bulk("test_snippets", [vessel], sync=True)

    result = _percolate(
        "Inspectors confirmed that the MV Snippet Tester (IMO 7654321) "
        "had cleared customs without incident.",
        args=[("highlight", "true")],
    )

    hits = result["hits"]["hits"]
    by_id = {h["_id"]: h for h in hits}
    assert "vessel-snippets" in by_id
    hit = by_id["vessel-snippets"]

    # Highlight stays on the hit (not popped)
    assert "highlight" in hit
    snippets = hit["highlight"].get("content")
    assert snippets, f"expected highlight.content list, got {hit['highlight']!r}"
    assert isinstance(snippets, list)
    # At least one snippet contains <em>…</em> markup
    assert any("<em>" in s and "</em>" in s for s in snippets)

    # Every span surfaced under surface_forms is a phrase that appears
    # in at least one snippet (with markup stripped, the span text
    # should be present somewhere in the snippet text).
    surface_forms = hit["_source"]["surface_forms"]
    assert surface_forms  # non-empty
    flat_text = " ".join(snippets)
    flat_text = flat_text.replace("<em>", "").replace("</em>", "")
    for span in surface_forms:
        assert span in flat_text, f"surface form {span!r} not in {flat_text!r}"


def test_percolator_query_highlight_off_by_default(cleanup_after):
    """Highlights are opt-in. Without `highlight=true`, the highlight
    block is not present on hits and `_source.surface_forms` is empty,
    but `_source.percolator_match` still populates correctly.
    """
    vessel = make_entity(
        {
            "id": "vessel-no-hl",
            "schema": "Vessel",
            "properties": {
                "name": ["MV Quiet Tester"],
                "imoNumber": ["1112223"],
            },
        }
    )
    index_bulk("test_no_highlight", [vessel], sync=True)

    # Default args — no highlight=true
    result = _percolate("The vessel MV Quiet Tester was sighted near the canal.")

    hits = result["hits"]["hits"]
    by_id = {h["_id"]: h for h in hits}
    assert "vessel-no-hl" in by_id

    hit = by_id["vessel-no-hl"]
    # The highlight block is absent (ES skipped the highlighter entirely)
    assert "highlight" not in hit
    # surface_forms is empty without highlights
    assert hit["_source"]["surface_forms"] == []
    # percolator_match is independent of highlights and still works
    assert hit["_source"]["percolator_match"] == ["name"]


def test_percolator_scoring_tier_ordering(cleanup_after):
    """BM25 scoring honours the per-clause boost tiers.

    Three entities are indexed so each matches the percolation text via a
    different combination of clause kinds — their summed `_score`s
    reflect the boost tier:

    - `scoring-both`: primary name (boost 2.0) + alias (in the
      `other_name` group, boost 0.8) both fire → two clauses contribute
      → highest score.
    - `scoring-person`: primary name only (boost 2.0) → single clause.
    - `scoring-alias`: only `previousName` (in the `other_name` group,
      boost 0.8) fires → single clause, demoted below name.

    Expected `_score` ordering: both > person > alias.
    Default sort is `_score` desc, so the hits list is already ordered.
    """
    person = make_entity(
        {
            "id": "scoring-person",
            "schema": "Person",
            "properties": {"name": ["Alexandra Bouchard"]},
        }
    )
    both = make_entity(
        {
            "id": "scoring-both",
            "schema": "Company",
            "properties": {
                "name": ["Quantum Industries Limited"],
                "alias": ["Quantum Holdings International"],
            },
        }
    )
    alias_person = make_entity(
        {
            "id": "scoring-alias",
            "schema": "Person",
            "properties": {
                "name": ["Unrelated Primary Name"],
                "previousName": ["Jonas Oberlehrer"],
            },
        }
    )
    index_bulk("test_scoring", [person, both, alias_person], sync=True)

    result = _percolate(
        "Alexandra Bouchard met Jonas Oberlehrer at Quantum Industries "
        "Limited, also known as Quantum Holdings International."
    )
    hits = result["hits"]["hits"]
    scores = {h["_id"]: h["_score"] for h in hits}

    # All three fixture entities are found.
    assert {"scoring-both", "scoring-person", "scoring-alias"} <= set(scores)

    # Tier ordering: name+other_name (2.0+0.8) > name (2.0) > other_name (0.8).
    assert scores["scoring-both"] > scores["scoring-person"]
    assert scores["scoring-person"] > scores["scoring-alias"]

    # Default sort is _score desc — filtering to our three fixture entities
    # they should appear in that order within the hits list.
    relevant = ["scoring-both", "scoring-person", "scoring-alias"]
    ordered = [h["_id"] for h in hits if h["_id"] in relevant]
    assert ordered == relevant

    # Each hit surfaces the clause kinds it matched via `_name` tags.
    matched = {
        h["_id"]: set(h["_source"]["percolator_match"])
        for h in hits
        if h["_id"] in relevant
    }
    assert matched["scoring-both"] == {"name", "other_name"}
    assert matched["scoring-person"] == {"name"}
    assert matched["scoring-alias"] == {"other_name"}


# ---------------------------------------------------------------------------
# entity_id input mode — percolate against fulltext that is already indexed.
#
# Document descendants carry their text in `properties.bodyText` (in `_source`),
# while `Pages` entities have an empty `bodyText` and the aggregated text in
# `Field.CONTENT` (stored via `store: true` in the pages bucket only). The
# helper resolves both transparently. `Page` entities (which do NOT inherit
# from `Document` in FtM) and any non-document entities are rejected.
# ---------------------------------------------------------------------------


def test_percolator_query_by_document_entity_id(cleanup_after):
    """Percolating by id resolves bodyText from _source for Document entities."""
    target = make_entity(
        {
            "id": "doc-target-vessel",
            "schema": "Vessel",
            "properties": {
                "name": ["MV Indexed Document"],
                "imoNumber": ["1230098"],
            },
        }
    )
    document = make_entity(
        {
            "id": "doc-source-1",
            "schema": "PlainText",
            "properties": {
                "bodyText": [
                    "Inspectors confirmed that the MV Indexed Document "
                    "(IMO 1230098) had cleared customs without incident."
                ],
                "fileName": ["report.txt"],
            },
        }
    )
    index_bulk("test_doc_entity_id", [target, document], sync=True)

    parser = SearchQueryParser([("highlight", "true")])
    result = PercolatorQuery(parser, entity_id="doc-source-1").search()

    hits = result["hits"]["hits"]
    by_id = {h["_id"]: h for h in hits}
    assert "doc-target-vessel" in by_id, f"target missing from {list(by_id)}"

    hit = by_id["doc-target-vessel"]
    surface_forms = set(hit["_source"]["surface_forms"])
    assert "MV Indexed Document" in surface_forms
    assert hit["_source"]["percolator_match"] == ["name"]


def test_percolator_query_by_pages_entity_id(cleanup_after):
    """Percolating by id resolves stored Field.CONTENT for Pages entities.

    `Pages.indexText` is the magic property the transform pops and routes
    into `Field.CONTENT`, which the pages bucket persists with
    `store: true`. The helper retrieves it via `stored_fields`.
    """
    target = make_entity(
        {
            "id": "pages-target-vessel",
            "schema": "Vessel",
            "properties": {
                "name": ["MV Pages Aggregator"],
                "imoNumber": ["7779991"],
            },
        }
    )
    pages = make_entity(
        {
            "id": "pages-source-1",
            "schema": "Pages",
            "properties": {
                "indexText": [
                    "The MV Pages Aggregator (IMO 7779991) was sighted "
                    "at the harbor on the morning of the inspection."
                ],
                "fileName": ["report.pdf"],
                "mimeType": ["application/pdf"],
            },
        }
    )
    index_bulk("test_pages_entity_id", [target, pages], sync=True)

    parser = SearchQueryParser([("highlight", "true")])
    result = PercolatorQuery(parser, entity_id="pages-source-1").search()

    hits = result["hits"]["hits"]
    by_id = {h["_id"]: h for h in hits}
    assert "pages-target-vessel" in by_id, f"target missing from {list(by_id)}"

    hit = by_id["pages-target-vessel"]
    surface_forms = set(hit["_source"]["surface_forms"])
    assert "MV Pages Aggregator" in surface_forms


def test_percolator_query_entity_id_rejects_page(cleanup_after):
    """Page entities are not Document descendants and are rejected.

    Page lives in its own bucket and is not part of `entities_read_index(
    schema="Document")`, so the helper returns `None` and the constructor
    raises `ValueError`.
    """
    page = make_entity(
        {
            "id": "page-source-1",
            "schema": "Page",
            "properties": {
                "index": ["1"],
                "bodyText": [
                    "Some page-level body text that should never be percolated."
                ],
            },
        }
    )
    index_bulk("test_page_reject", [page], sync=True)

    parser = SearchQueryParser([])
    with pytest.raises(ValueError, match="No percolatable fulltext"):
        PercolatorQuery(parser, entity_id="page-source-1")


def test_percolator_query_entity_id_rejects_thing(cleanup_after):
    """Person/Company/Vessel etc. live in things bucket — no fulltext."""
    person = make_entity(
        {
            "id": "thing-reject",
            "schema": "Person",
            "properties": {"name": ["John Doe Rejecter"]},
        }
    )
    index_bulk("test_thing_reject", [person], sync=True)

    parser = SearchQueryParser([])
    with pytest.raises(ValueError, match="No percolatable fulltext"):
        PercolatorQuery(parser, entity_id="thing-reject")


def test_percolator_query_entity_id_not_found():
    """Unknown entity id raises ValueError."""
    parser = SearchQueryParser([])
    with pytest.raises(ValueError, match="No percolatable fulltext"):
        PercolatorQuery(parser, entity_id="this-id-does-not-exist")


def test_percolator_query_text_and_entity_id_mutually_exclusive():
    """Exactly one of text/entity_id must be provided."""
    parser = SearchQueryParser([])
    with pytest.raises(ValueError, match="exactly one"):
        PercolatorQuery(parser, text="hello", entity_id="some-id")
    with pytest.raises(ValueError, match="exactly one"):
        PercolatorQuery(parser)
