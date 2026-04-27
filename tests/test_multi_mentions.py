"""End-to-end tests for MultiMentionsQuery (batch list search)."""

import pytest
from ftmq.util import make_entity

from openaleph_search.index.admin import clear_index
from openaleph_search.index.entities import index_bulk
from openaleph_search.model import SearchAuth
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.mentions import MultiMentionsQuery, collect_source_entities

SOURCE_DATASET = "test_watchlist"
TARGET_DATASET = "test_news"


WATCHLIST_PERSONS = [
    {
        "id": "p-merkel",
        "schema": "Person",
        "properties": {"name": ["Angela Merkel"], "country": ["de"]},
    },
    {
        "id": "p-putin",
        "schema": "Person",
        "properties": {"name": ["Vladimir Putin"], "country": ["ru"]},
    },
    {
        "id": "p-smith",
        "schema": "Person",
        "properties": {"name": ["John Smith"], "country": ["us"]},
    },
]

NEWS_DOCS = [
    {
        "id": "d-merkel",
        "schema": "PlainText",
        "properties": {
            "bodyText": ["Angela Merkel gave a speech today in Berlin."],
            "namesMentioned": ["Angela Merkel"],
        },
    },
    {
        "id": "d-putin",
        "schema": "PlainText",
        "properties": {
            "bodyText": ["Vladimir Putin attended a summit yesterday."],
            "namesMentioned": ["Vladimir Putin"],
        },
    },
    {
        "id": "d-both",
        "schema": "PlainText",
        "properties": {
            "bodyText": ["Angela Merkel and Vladimir Putin met in Moscow."],
            "namesMentioned": ["Angela Merkel", "Vladimir Putin"],
        },
    },
    {
        "id": "d-smith",
        "schema": "PlainText",
        "properties": {
            "bodyText": ["John Smith testified before the committee."],
            "namesMentioned": ["John Smith"],
        },
    },
    {
        "id": "d-unrelated",
        "schema": "PlainText",
        "properties": {
            "bodyText": ["The weather in Paris was pleasant."],
        },
    },
    # Synonym test: reversed-order surface form — same name_keys as
    # "Angela Merkel" but won't match a phrase query with slop=0.
    {
        "id": "d-merkel-reversed",
        "schema": "PlainText",
        "properties": {
            "bodyText": ["Merkel Angela signed the document at the event."],
            "namesMentioned": ["Merkel Angela"],
        },
    },
]


@pytest.fixture(scope="module")
def index_multi_mentions_fixtures():
    index_bulk(SOURCE_DATASET, map(make_entity, WATCHLIST_PERSONS), sync=True)
    index_bulk(TARGET_DATASET, map(make_entity, NEWS_DOCS), sync=True)
    yield
    clear_index()


def _parser(
    pairs: list[tuple[str, str]], auth: SearchAuth | None = None
) -> SearchQueryParser:
    return SearchQueryParser(pairs, auth=auth)


def _admin() -> SearchAuth:
    return SearchAuth(is_admin=True)


def _ids(result) -> list[str]:
    return [h["_id"] for h in result["hits"]["hits"]]


# --- collect_source_entities --------------------------------------------


def test_collect_source_entities_country_filter(index_multi_mentions_fixtures):
    parser = _parser(
        [
            ("filter:dataset", SOURCE_DATASET),
            ("filter:countries", "de"),
        ],
        auth=_admin(),
    )
    assert collect_source_entities(parser) == [("p-merkel", ["Angela Merkel"])]


def test_collect_source_entities_multi_country(index_multi_mentions_fixtures):
    parser = _parser(
        [
            ("filter:dataset", SOURCE_DATASET),
            ("filter:countries", "de"),
            ("filter:countries", "ru"),
        ],
        auth=_admin(),
    )
    entities = collect_source_entities(parser)
    ids = {eid for eid, _ in entities}
    assert ids == {"p-merkel", "p-putin"}
    names = {n for _, ns in entities for n in ns}
    assert "Angela Merkel" in names
    assert "Vladimir Putin" in names
    assert "John Smith" not in names


def test_collect_source_entities_empty(index_multi_mentions_fixtures):
    parser = _parser(
        [
            ("filter:dataset", SOURCE_DATASET),
            ("filter:countries", "xx"),
        ],
        auth=_admin(),
    )
    assert collect_source_entities(parser) == []


def test_collect_source_entities_cap(index_multi_mentions_fixtures):
    parser = _parser(
        [("filter:dataset", SOURCE_DATASET)],
        auth=_admin(),
    )
    # The count-based short-circuit fires pre-scroll ("matched N entities");
    # the per-hit check ("yielded > N names") fires during the scroll when
    # multi-valued names push past the cap. Either trip is valid at cap=1.
    with pytest.raises(ValueError, match=r"Source filter (matched|yielded)"):
        collect_source_entities(parser, max_names=1)


# --- MultiMentionsQuery --------------------------------------------


def _target(pairs=None, auth=None):
    return _parser(
        [("filter:dataset", TARGET_DATASET), *(pairs or [])],
        auth=auth or _admin(),
    )


def test_multi_mentions_single_country(index_multi_mentions_fixtures):
    """Filter source by country → only docs mentioning those persons return."""
    source = _parser(
        [
            ("filter:dataset", SOURCE_DATASET),
            ("filter:countries", "de"),
        ],
        auth=_admin(),
    )
    result = MultiMentionsQuery(_target(), source).search()
    by_id = {h["_id"]: h for h in result["hits"]["hits"]}
    assert "d-merkel" in by_id
    assert "d-both" in by_id  # also mentions Merkel (plus Putin)
    assert "d-putin" not in by_id
    assert "d-smith" not in by_id
    assert "d-unrelated" not in by_id
    # Single source entity → every hit attributes to p-merkel.
    assert by_id["d-merkel"]["_source"]["mention_sources"] == ["p-merkel"]
    assert by_id["d-both"]["_source"]["mention_sources"] == ["p-merkel"]


def test_multi_mentions_multi_country_ranking(
    index_multi_mentions_fixtures,
):
    """Docs mentioning multiple filtered persons rank highest, and each
    hit's `mention_sources` lists exactly the source entities it matched."""
    source = _parser(
        [
            ("filter:dataset", SOURCE_DATASET),
            ("filter:countries", "de"),
            ("filter:countries", "ru"),
        ],
        auth=_admin(),
    )
    result = MultiMentionsQuery(_target(), source).search()
    hits = result["hits"]["hits"]
    by_id = {h["_id"]: h for h in hits}
    ids = [h["_id"] for h in hits]
    assert ids[0] == "d-both"  # mentions both Merkel AND Putin
    assert "d-merkel" in by_id
    assert "d-putin" in by_id
    assert "d-smith" not in by_id
    # Per-hit attribution: each document lists the specific source
    # entities whose sub-bool fired on it.
    assert by_id["d-both"]["_source"]["mention_sources"] == ["p-merkel", "p-putin"]
    assert by_id["d-merkel"]["_source"]["mention_sources"] == ["p-merkel"]
    assert by_id["d-putin"]["_source"]["mention_sources"] == ["p-putin"]
    # Defensive: the key is always present.
    for hit in hits:
        assert "mention_sources" in hit["_source"]


def test_multi_mentions_empty_source(index_multi_mentions_fixtures):
    """Source filter with no hits → match_none on the target."""
    source = _parser(
        [
            ("filter:dataset", SOURCE_DATASET),
            ("filter:countries", "xx"),
        ],
        auth=_admin(),
    )
    result = MultiMentionsQuery(_target(), source).search()
    assert result["hits"]["total"]["value"] == 0


def test_multi_mentions_reversed_order_via_slop(index_multi_mentions_fixtures):
    """slop=2 phrase matching catches reversed token order — "Merkel Angela"
    is matched by the "Angela Merkel" phrase clause without needing synonyms."""
    source = _parser(
        [
            ("filter:dataset", SOURCE_DATASET),
            ("filter:countries", "de"),
        ],
        auth=_admin(),
    )
    ids = set(_ids(MultiMentionsQuery(_target(), source).search()))
    assert "d-merkel" in ids
    assert "d-merkel-reversed" in ids


def test_multi_mentions_synonyms_noop(index_multi_mentions_fixtures):
    """`parser.synonyms=true` is a no-op for the mention path — the
    result set is identical because name synonyms are resolved by the
    target-side analyzer at search time rather than via explicit
    `name_symbols` / `name_keys` clauses."""
    source = _parser(
        [
            ("filter:dataset", SOURCE_DATASET),
            ("filter:countries", "de"),
        ],
        auth=_admin(),
    )
    ids_no_syn = set(_ids(MultiMentionsQuery(_target(), source).search()))
    ids_syn = set(
        _ids(MultiMentionsQuery(_target([("synonyms", "true")]), source).search())
    )
    assert ids_no_syn == ids_syn


def test_multi_mentions_parity_with_mentions_query(
    index_multi_mentions_fixtures,
):
    """Single source Person → MultiMentionsQuery hits match
    MentionsQuery hits (as a set of document IDs)."""
    from openaleph_search.query.mentions import MentionsQuery

    source = _parser(
        [
            ("filter:dataset", SOURCE_DATASET),
            ("filter:countries", "de"),
        ],
        auth=_admin(),
    )
    collection_ids = set(_ids(MultiMentionsQuery(_target(), source).search()))

    target_single = _parser(
        [("filter:dataset", TARGET_DATASET)],
        auth=_admin(),
    )
    mentions_ids = set(_ids(MentionsQuery(target_single, "p-merkel").search()))

    assert collection_ids == mentions_ids


def test_multi_mentions_auth_on_target(index_multi_mentions_fixtures):
    """Target-side auth excludes docs outside the user's dataset set —
    even if the source-side filter matched fine."""
    source = _parser(
        [
            ("filter:dataset", SOURCE_DATASET),
            ("filter:countries", "de"),
        ],
        auth=SearchAuth(datasets={SOURCE_DATASET, TARGET_DATASET}, logged_in=True),
    )
    target = _parser(
        [("filter:dataset", TARGET_DATASET)],
        auth=SearchAuth(datasets={SOURCE_DATASET}, logged_in=True),
    )
    result = MultiMentionsQuery(target, source).search()
    assert result["hits"]["total"]["value"] == 0


# --- shared-name attribution --------------------------------------------


SHARED_DATASET = "test_watchlist_shared"
SHARED_TARGET_DATASET = "test_news_shared"

SHARED_SOURCES = [
    {
        "id": "p-smith-a",
        "schema": "Person",
        "properties": {"name": ["John Smith"], "country": ["us"]},
    },
    {
        "id": "p-smith-b",
        "schema": "Person",
        "properties": {"name": ["John Smith"], "country": ["gb"]},
    },
    {
        "id": "p-jones",
        "schema": "Person",
        "properties": {"name": ["Mary Jones"], "country": ["us"]},
    },
]

SHARED_TARGETS = [
    {
        "id": "d-shared-smith",
        "schema": "PlainText",
        "properties": {
            "bodyText": ["John Smith signed the declaration at the event."],
        },
    },
    {
        "id": "d-shared-jones",
        "schema": "PlainText",
        "properties": {
            "bodyText": ["Mary Jones replied to the inquiry on Tuesday."],
        },
    },
]


def test_multi_mentions_shared_name_attribution(cleanup_after):
    """Two source entities share a name — both IDs surface on hits
    matching that name. ES can't disambiguate from a text match alone,
    so the full candidate set is returned."""
    index_bulk(SHARED_DATASET, map(make_entity, SHARED_SOURCES), sync=True)
    index_bulk(SHARED_TARGET_DATASET, map(make_entity, SHARED_TARGETS), sync=True)

    source = _parser(
        [("filter:dataset", SHARED_DATASET)],
        auth=_admin(),
    )
    target = _parser(
        [("filter:dataset", SHARED_TARGET_DATASET)],
        auth=_admin(),
    )
    result = MultiMentionsQuery(target, source).search()
    by_id = {h["_id"]: h for h in result["hits"]["hits"]}

    # Both John Smith source entities attribute to the shared-name hit.
    assert by_id["d-shared-smith"]["_source"]["mention_sources"] == [
        "p-smith-a",
        "p-smith-b",
    ]
    # Jones hit attributes to p-jones only — collision logic doesn't
    # bleed across non-overlapping names.
    assert by_id["d-shared-jones"]["_source"]["mention_sources"] == ["p-jones"]
