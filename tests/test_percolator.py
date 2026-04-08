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
  6 chars — DROPPED by `clean_percolator_names`, so they should NOT be
  matched even if a doc says "Banana")
"""

from unittest import mock

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
    """clean_percolator_names drops single-token names < 7 chars.

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


# ---------------------------------------------------------------------------
# Identifier tests (self-contained — each indexes its own entities into a
# dedicated dataset and uses `cleanup_after` to wipe between tests).
# ---------------------------------------------------------------------------


def test_percolator_query_matches_identifier(cleanup_after):
    """A document mentioning an identifier matches the entity by id alone."""
    vessel = make_entity(
        {
            "id": "vessel-1",
            "schema": "Vessel",
            "properties": {
                "name": ["MV Example"],
                "imoNumber": ["9123456"],
            },
        }
    )
    index_bulk("test_vessels", [vessel], sync=True)

    result = _percolate(
        "The vessel 9123456 was sighted near the canal.",
        args=[("highlight", "true")],
    )

    hits = result["hits"]["hits"]
    by_id = {h["_id"]: h for h in hits}
    assert "vessel-1" in by_id, f"vessel-1 missing from {list(by_id)}"

    hit = by_id["vessel-1"]
    assert hit["_source"]["surface_forms"] == ["9123456"]
    assert hit["_source"]["percolator_match"] == ["identifier"]


def test_percolator_query_short_identifier_dropped(cleanup_after):
    """An entity whose only identifier is < 5 chars gets no `query` field."""
    company = make_entity(
        {
            "id": "tiny-id-co",
            "schema": "Company",
            # 3-char identifier — dropped by clean_percolator_identifiers.
            # No name either, so the entity ends up with no usable signals.
            "properties": {"registrationNumber": ["GB1"]},
        }
    )
    index_bulk("test_short_ids", [company], sync=True)

    result = _percolate("The reference GB1 was noted in the filings.")
    ids = {h["_id"] for h in result["hits"]["hits"]}

    assert "tiny-id-co" not in ids


def test_percolator_query_match_signals_combined(cleanup_after):
    """Both name and identifier matching → percolator_match has both tags."""
    vessel = make_entity(
        {
            "id": "vessel-2",
            "schema": "Vessel",
            "properties": {
                "name": ["MV Example Two"],
                "imoNumber": ["9876543"],
            },
        }
    )
    index_bulk("test_vessels_combined", [vessel], sync=True)

    result = _percolate(
        "The vessel MV Example Two (IMO 9876543) cleared customs.",
        args=[("highlight", "true")],
    )

    hits = result["hits"]["hits"]
    by_id = {h["_id"]: h for h in hits}
    assert "vessel-2" in by_id

    hit = by_id["vessel-2"]
    # Both signals fired → deduped + sorted alphabetically: identifier, name
    assert hit["_source"]["percolator_match"] == ["identifier", "name"]
    # Surface forms include both the name and the identifier spans
    surface_forms = set(hit["_source"]["surface_forms"])
    assert "MV Example Two" in surface_forms
    assert "9876543" in surface_forms


def test_percolator_query_identifier_no_slop(cleanup_after):
    """Multi-token identifiers must match exactly — slop=0.

    A multi-token identifier like "DE HRB 12345" should NOT match a
    document where its tokens are split across other words. Names with
    slop=2 would match a similar split; identifiers must not.
    """
    company = make_entity(
        {
            "id": "de-company",
            "schema": "Company",
            "properties": {
                # No `name` so the only signal is the multi-token identifier.
                "registrationNumber": ["DE HRB 12345"],
            },
        }
    )
    index_bulk("test_no_slop", [company], sync=True)

    # The identifier tokens (de, hrb, 12345) are all present in the doc but
    # separated by other tokens — `slop=0` rejects this.
    result = _percolate("Filed in DE under HRB category as serial 12345 reference.")
    ids = {h["_id"] for h in result["hits"]["hits"]}
    assert "de-company" not in ids


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
    result = _percolate("The vessel 1112223 was sighted near the canal.")

    hits = result["hits"]["hits"]
    by_id = {h["_id"]: h for h in hits}
    assert "vessel-no-hl" in by_id

    hit = by_id["vessel-no-hl"]
    # The highlight block is absent (ES skipped the highlighter entirely)
    assert "highlight" not in hit
    # surface_forms is empty without highlights
    assert hit["_source"]["surface_forms"] == []
    # percolator_match is independent of highlights and still works
    assert hit["_source"]["percolator_match"] == ["identifier"]


def test_percolator_query_constant_score(cleanup_after):
    """All hits get the same _score — server-side scoring is disabled."""
    person = make_entity(
        {
            "id": "scoring-person",
            "schema": "Person",
            "properties": {"name": ["Alexandra Kowalski"]},
        }
    )
    company = make_entity(
        {
            "id": "scoring-company",
            "schema": "Company",
            "properties": {
                "name": ["Quantum Industries Limited"],
                "registrationNumber": ["QI789456"],
            },
        }
    )
    index_bulk("test_scoring", [person, company], sync=True)

    result = _percolate(
        "Alexandra Kowalski signed off on Quantum Industries Limited "
        "(reg. QI789456) at the meeting."
    )

    hits = result["hits"]["hits"]
    scores = {h["_id"]: h["_score"] for h in hits}
    assert "scoring-person" in scores
    assert "scoring-company" in scores

    # Constant_score wrap means every hit shares the same score, even
    # though the company also fired its identifier clause.
    assert scores["scoring-person"] == scores["scoring-company"]
