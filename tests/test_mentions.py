"""Tests for MentionsQuery — the inverse of PercolatorQuery.

Given a named entity (Person, Company, …), MentionsQuery returns
Document-family entities whose indexed text contains the entity's
caption or any of its matchable name variants as a phrase. Standard
`EntitiesQuery` parser knobs apply: `filter:schema` narrows within
the Document hierarchy, `parser.text` ANDs with the mention
requirement. Name-synonym matching is handled by the target-side
`Field.CONTENT` analyzer at search time — `parser.synonyms=true`
adds no extra clauses in the mentions path.
"""

from unittest.mock import patch

import pytest
from ftmq.util import make_entity

from openaleph_search.index.entities import index_bulk
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.mentions import MentionsQuery


def _mentions(entity_id: str, args: list[tuple[str, str]] | None = None):
    parser = SearchQueryParser(args or [])
    return MentionsQuery(parser, entity_id=entity_id).search()


def test_mentions_query_single_name(cleanup_after):
    """Entity with one name matches a document that mentions it."""
    person = make_entity(
        {
            "id": "mentions-p1",
            "schema": "Person",
            "properties": {"name": ["Alexandra Kowalski"]},
        }
    )
    doc = make_entity(
        {
            "id": "mentions-doc-1",
            "schema": "PlainText",
            "properties": {
                "bodyText": ["Alexandra Kowalski signed the contract."],
                "fileName": ["report.txt"],
            },
        }
    )
    index_bulk("test_mentions_single", [person, doc], sync=True)

    result = _mentions("mentions-p1")
    hits = {h["_id"]: h for h in result["hits"]["hits"]}
    assert "mentions-doc-1" in hits
    # The subject entity itself lives in the things bucket and must not
    # appear in the Document-scoped results.
    assert "mentions-p1" not in hits
    # Single-entity attribution: every hit lists just the subject entity.
    assert hits["mentions-doc-1"]["_source"]["mention_sources"] == ["mentions-p1"]


def test_mentions_query_multiple_variants(cleanup_after):
    """All name variants match — each document mentioning any variant
    shows up."""
    person = make_entity(
        {
            "id": "mentions-p2",
            "schema": "Person",
            "properties": {"name": ["Vladimir Ivanov", "V. Ivanov", "Ivanov Vladimir"]},
        }
    )
    doc_full = make_entity(
        {
            "id": "mentions-doc-full",
            "schema": "PlainText",
            "properties": {"bodyText": ["Vladimir Ivanov attended the meeting."]},
        }
    )
    doc_init = make_entity(
        {
            "id": "mentions-doc-init",
            "schema": "PlainText",
            "properties": {"bodyText": ["A cable referenced V. Ivanov as the source."]},
        }
    )
    doc_rev = make_entity(
        {
            "id": "mentions-doc-rev",
            "schema": "PlainText",
            "properties": {"bodyText": ["Registered in the name of Ivanov Vladimir."]},
        }
    )
    index_bulk(
        "test_mentions_variants",
        [person, doc_full, doc_init, doc_rev],
        sync=True,
    )

    result = _mentions("mentions-p2")
    ids = {h["_id"] for h in result["hits"]["hits"]}
    assert {"mentions-doc-full", "mentions-doc-init", "mentions-doc-rev"} <= ids


def test_mentions_query_no_match(cleanup_after):
    """A document that does not mention the entity does not match."""
    person = make_entity(
        {
            "id": "mentions-p3",
            "schema": "Person",
            "properties": {"name": ["Jane Specific Doe"]},
        }
    )
    doc = make_entity(
        {
            "id": "mentions-doc-unrelated",
            "schema": "PlainText",
            "properties": {
                "bodyText": ["The weather forecast predicts rain for the week."]
            },
        }
    )
    index_bulk("test_mentions_no_match", [person, doc], sync=True)

    result = _mentions("mentions-p3")
    assert result["hits"]["total"]["value"] == 0


def test_mentions_query_schema_narrow(cleanup_after):
    """`filter:schema` narrows within the Document hierarchy."""
    person = make_entity(
        {
            "id": "mentions-p4",
            "schema": "Person",
            "properties": {"name": ["Kasia Narrowcast"]},
        }
    )
    plain = make_entity(
        {
            "id": "mentions-plain",
            "schema": "PlainText",
            "properties": {"bodyText": ["Kasia Narrowcast filed a report."]},
        }
    )
    html = make_entity(
        {
            "id": "mentions-html",
            "schema": "HyperText",
            "properties": {
                "bodyText": ["Kasia Narrowcast was quoted on page two."],
                "fileName": ["article.html"],
            },
        }
    )
    index_bulk("test_mentions_schema", [person, plain, html], sync=True)

    # narrow to HyperText only — PlainText should be excluded
    result = _mentions("mentions-p4", args=[("filter:schema", "HyperText")])
    ids = {h["_id"] for h in result["hits"]["hits"]}
    assert "mentions-html" in ids
    assert "mentions-plain" not in ids


def test_mentions_query_text_and(cleanup_after):
    """`parser.text` (q=…) ANDs with the mention requirement."""
    person = make_entity(
        {
            "id": "mentions-p5",
            "schema": "Person",
            "properties": {"name": ["Roberto Contractsigner"]},
        }
    )
    doc_a = make_entity(
        {
            "id": "mentions-doc-a",
            "schema": "PlainText",
            "properties": {
                "bodyText": ["Roberto Contractsigner signed the contract yesterday."]
            },
        }
    )
    doc_b = make_entity(
        {
            "id": "mentions-doc-b",
            "schema": "PlainText",
            "properties": {
                "bodyText": ["Roberto Contractsigner attended a board meeting."]
            },
        }
    )
    index_bulk("test_mentions_text", [person, doc_a, doc_b], sync=True)

    # With no q: both docs.
    result_all = _mentions("mentions-p5")
    ids_all = {h["_id"] for h in result_all["hits"]["hits"]}
    assert {"mentions-doc-a", "mentions-doc-b"} <= ids_all

    # With q=contract: only doc_a.
    result_q = _mentions("mentions-p5", args=[("q", "contract")])
    ids_q = {h["_id"] for h in result_q["hits"]["hits"]}
    assert "mentions-doc-a" in ids_q
    assert "mentions-doc-b" not in ids_q


def test_mentions_query_highlight(cleanup_after):
    """`highlight=true` populates the standard highlight block. No
    `surface_forms` is attached (that's PercolatorQuery-only)."""
    person = make_entity(
        {
            "id": "mentions-p6",
            "schema": "Person",
            "properties": {"name": ["Henrietta Highlightworthy"]},
        }
    )
    doc = make_entity(
        {
            "id": "mentions-doc-hl",
            "schema": "PlainText",
            "properties": {
                "bodyText": [
                    "At the summit, Henrietta Highlightworthy delivered the keynote."
                ]
            },
        }
    )
    index_bulk("test_mentions_highlight", [person, doc], sync=True)

    result = _mentions("mentions-p6", args=[("highlight", "true")])
    hits = {h["_id"]: h for h in result["hits"]["hits"]}
    assert "mentions-doc-hl" in hits

    hit = hits["mentions-doc-hl"]
    # Standard highlight block present — content snippets with <em>…</em>.
    assert "highlight" in hit
    snippets = hit["highlight"].get("content") or hit["highlight"].get("text")
    assert snippets, f"expected highlight snippets, got {hit['highlight']!r}"
    assert any("<em>" in s and "</em>" in s for s in snippets)
    # No PercolatorQuery-style surface_forms key on _source.
    assert "surface_forms" not in hit.get("_source", {})


def test_mentions_query_synonyms_noop():
    """`parser.synonyms=true` is accepted for parser compatibility but
    does not add any clauses in the mentions path — name-synonym
    matching is left to the `Field.CONTENT` analyzer at search time,
    so the compiled body is identical with and without the flag."""
    fake_entity = {
        "id": "mentions-p-syn",
        "schema": "Person",
        "properties": {"name": ["William Synonymtest"]},
    }
    with patch(
        "openaleph_search.index.entities.get_entity",
        return_value=fake_entity,
    ):
        body_plain = MentionsQuery(
            SearchQueryParser([]), entity_id="mentions-p-syn"
        ).get_body()
        body_syn = MentionsQuery(
            SearchQueryParser([("synonyms", "true")]),
            entity_id="mentions-p-syn",
        ).get_body()
    assert body_plain["query"] == body_syn["query"]


def test_mentions_query_entity_without_names_raises(cleanup_after):
    """An indexed entity with no name properties cannot be used as the
    source of a MentionsQuery — raises ValueError."""
    nameless = make_entity(
        {
            "id": "mentions-nameless",
            "schema": "Note",
            "properties": {"description": ["A note without any named subject."]},
        }
    )
    index_bulk("test_mentions_nameless", [nameless], sync=True)

    parser = SearchQueryParser([])
    with pytest.raises(ValueError, match="no matchable names"):
        MentionsQuery(parser, entity_id="mentions-nameless")


def test_mentions_query_entity_id_not_found():
    """Unknown entity id raises ValueError."""
    parser = SearchQueryParser([])
    with pytest.raises(ValueError, match="not found"):
        MentionsQuery(parser, entity_id="this-id-does-not-exist")


def test_mentions_query_missing_entity_id():
    """An empty entity_id is rejected."""
    parser = SearchQueryParser([])
    with pytest.raises(ValueError, match="entity_id"):
        MentionsQuery(parser, entity_id="")


def test_mentions_query_structured_names_match(cleanup_after):
    """Documents that carry the entity's name as a structured `names`
    property (e.g. extracted mentions) match via the Field.NAMES terms
    clause, even if the bodyText is silent."""
    person = make_entity(
        {
            "id": "mentions-p8",
            "schema": "Person",
            "properties": {"name": ["Structured Names Person"]},
        }
    )
    # A document whose bodyText does not mention the person, but whose
    # `namesMentioned` property (a FtM "name"-group property) does.
    doc = make_entity(
        {
            "id": "mentions-doc-structured",
            "schema": "PlainText",
            "properties": {
                "bodyText": ["The report describes routine operations."],
                "namesMentioned": ["Structured Names Person"],
            },
        }
    )
    index_bulk("test_mentions_structured", [person, doc], sync=True)

    result = _mentions("mentions-p8")
    ids = {h["_id"] for h in result["hits"]["hits"]}
    assert "mentions-doc-structured" in ids


def test_mentions_query_default_schema_documents(cleanup_after):
    """Without `filter:schema`, the query targets Document-family entities
    — Thing-family entities (Person/Company/…) are not returned even if
    they contain the matched name as their own name."""
    person = make_entity(
        {
            "id": "mentions-p9",
            "schema": "Person",
            "properties": {"name": ["Defaultschema Subject"]},
        }
    )
    # A sibling Person that also has the same name — must not appear in
    # Document-default results.
    sibling = make_entity(
        {
            "id": "mentions-sibling",
            "schema": "Person",
            "properties": {"name": ["Defaultschema Subject"]},
        }
    )
    doc = make_entity(
        {
            "id": "mentions-doc-default",
            "schema": "PlainText",
            "properties": {
                "bodyText": ["Defaultschema Subject was the keynote speaker."]
            },
        }
    )
    index_bulk(
        "test_mentions_default_schema",
        [person, sibling, doc],
        sync=True,
    )

    result = _mentions("mentions-p9")
    ids = {h["_id"] for h in result["hits"]["hits"]}
    assert "mentions-doc-default" in ids
    assert "mentions-sibling" not in ids
