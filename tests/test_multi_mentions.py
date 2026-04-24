"""End-to-end tests for MultiMentionsQuery (batch list search)."""

import pytest
from ftmq.util import make_entity

from openaleph_search.index.admin import clear_index
from openaleph_search.index.entities import index_bulk
from openaleph_search.model import SearchAuth
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.mentions import (
    MultiMentionsQuery,
    collect_source_names,
)

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


# --- collect_source_names -----------------------------------------------


def test_collect_source_names_country_filter(index_multi_mentions_fixtures):
    parser = _parser(
        [
            ("filter:dataset", SOURCE_DATASET),
            ("filter:countries", "de"),
        ],
        auth=_admin(),
    )
    assert collect_source_names(parser) == ["Angela Merkel"]


def test_collect_source_names_multi_country(index_multi_mentions_fixtures):
    parser = _parser(
        [
            ("filter:dataset", SOURCE_DATASET),
            ("filter:countries", "de"),
            ("filter:countries", "ru"),
        ],
        auth=_admin(),
    )
    names = collect_source_names(parser)
    assert "Angela Merkel" in names
    assert "Vladimir Putin" in names
    assert "John Smith" not in names


def test_collect_source_names_empty(index_multi_mentions_fixtures):
    parser = _parser(
        [
            ("filter:dataset", SOURCE_DATASET),
            ("filter:countries", "xx"),
        ],
        auth=_admin(),
    )
    assert collect_source_names(parser) == []


def test_collect_source_names_cap(index_multi_mentions_fixtures):
    parser = _parser(
        [("filter:dataset", SOURCE_DATASET)],
        auth=_admin(),
    )
    # The count-based short-circuit fires pre-scroll ("matched N entities");
    # the per-hit check ("yielded > N names") fires during the scroll when
    # multi-valued names push past the cap. Either trip is valid at cap=1.
    with pytest.raises(ValueError, match=r"Source filter (matched|yielded)"):
        collect_source_names(parser, max_names=1)


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
    ids = set(_ids(result))
    assert "d-merkel" in ids
    assert "d-both" in ids  # also mentions Merkel (plus Putin)
    assert "d-putin" not in ids
    assert "d-smith" not in ids
    assert "d-unrelated" not in ids


def test_multi_mentions_multi_country_ranking(
    index_multi_mentions_fixtures,
):
    """Docs mentioning multiple filtered persons rank highest."""
    source = _parser(
        [
            ("filter:dataset", SOURCE_DATASET),
            ("filter:countries", "de"),
            ("filter:countries", "ru"),
        ],
        auth=_admin(),
    )
    result = MultiMentionsQuery(_target(), source).search()
    ids = _ids(result)
    assert ids[0] == "d-both"  # mentions both Merkel AND Putin
    assert "d-merkel" in ids
    assert "d-putin" in ids
    assert "d-smith" not in ids


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


def test_multi_mentions_synonyms_monotone(index_multi_mentions_fixtures):
    """`parser.synonyms=true` flows through without error and only adds
    recall — every non-synonym hit remains a synonym hit."""
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
    assert ids_no_syn <= ids_syn
    assert "d-merkel" in ids_syn
    assert "d-merkel-reversed" in ids_syn


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
