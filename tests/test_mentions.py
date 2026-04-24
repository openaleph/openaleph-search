"""Tests for MentionsQuery — the inverse of PercolatorQuery.

Given a named entity (Person, Company, …), MentionsQuery returns
Document-family entities whose indexed text contains the entity's
caption or any of its matchable name variants as a phrase. Standard
`EntitiesQuery` parser knobs apply: `filter:schema` narrows within
the Document hierarchy, `parser.text` ANDs with the mention
requirement, `parser.synonyms=true` folds name_symbols / name_keys
expansions into the should set via `ExpandNameSynonymsMixin`.
"""

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
    ids = {h["_id"] for h in result["hits"]["hits"]}
    assert "mentions-doc-1" in ids
    # The subject entity itself lives in the things bucket and must not
    # appear in the Document-scoped results.
    assert "mentions-p1" not in ids


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


def test_mentions_query_synonyms(cleanup_after):
    """`synonyms=true` matches documents whose extracted name_symbols /
    name_keys overlap with the target entity's, even if the exact
    spelling does not appear in fulltext.

    Documents carry `name_symbols` / `name_keys` derived from their
    `names` group (see `transform.entity._get_symbols`). A document
    that lists a related name (e.g. the same WikiData NAME symbol) will
    match under synonyms even if that exact name string is absent from
    the fulltext."""
    person = make_entity(
        {
            "id": "mentions-p7",
            "schema": "Person",
            "properties": {"name": ["William Synonymtest"]},
        }
    )
    # Document whose bodyText is unrelated but whose `names` property
    # carries a sibling name — this populates Field.NAME_SYMBOLS /
    # Field.NAME_KEYS and should match under synonyms.
    doc = make_entity(
        {
            "id": "mentions-doc-syn",
            "schema": "PlainText",
            "properties": {
                "bodyText": ["The board discussed regulatory compliance."],
                "namesMentioned": ["William Synonymtest"],
            },
        }
    )
    index_bulk("test_mentions_synonyms", [person, doc], sync=True)

    # Without synonyms: no phrase overlap in the bodyText → no hit on
    # the multi_match, but the structured Field.NAMES `terms` clause
    # fires because `namesMentioned` copies into `names`.
    # To isolate the synonym effect, we check that the symbol_clauses
    # get added when synonyms=true by inspecting the compiled body.
    parser_plain = SearchQueryParser([])
    q_plain = MentionsQuery(parser_plain, entity_id="mentions-p7")
    body_plain = q_plain.get_body()
    parser_syn = SearchQueryParser([("synonyms", "true")])
    q_syn = MentionsQuery(parser_syn, entity_id="mentions-p7")
    body_syn = q_syn.get_body()

    # The synonym run must have *more* clauses in the mention-bool should
    # list than the plain run — at minimum one name_symbols terms clause.
    def _count_mention_shoulds(body):
        # walk the bool.must for the bool wrapping the mention should-list
        musts = body["query"]["bool"]["must"]
        for clause in musts:
            if (
                isinstance(clause, dict)
                and "bool" in clause
                and "should" in clause["bool"]
                and clause["bool"].get("minimum_should_match") == 1
            ):
                return len(clause["bool"]["should"])
        return 0

    assert _count_mention_shoulds(body_syn) > _count_mention_shoulds(body_plain)


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
