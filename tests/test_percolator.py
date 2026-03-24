from openaleph_search.index.percolator import (
    bulk_index_queries,
    delete_all_queries,
    percolate,
)
from openaleph_search.model import PercolatorQuery

QUERIES = [
    PercolatorQuery(key="jane-doe", names=["Jane Doe", "J. Doe"]),
    PercolatorQuery(
        key="acme-corp",
        names=["Acme Corporation", "ACME Corp"],
        countries=["us"],
        schemata=["Company"],
    ),
    PercolatorQuery(
        key="mueller-gmbh",
        names=["Müller GmbH"],
        countries=["de"],
        schemata=["Company"],
    ),
]

DOC_MATCH = "In a recent meeting, Jane Doe presented the quarterly results."
DOC_MATCH_VARIANT = "The report was signed by J. Doe on behalf of the board."
DOC_NO_MATCH = "The weather forecast predicts rain for the entire week."
DOC_MULTI = "Jane Doe signed the contract with Acme Corporation."


def test_percolate_match():
    bulk_index_queries(QUERIES, sync=True)

    hits = percolate(DOC_MATCH)
    ids = {h["_id"] for h in hits}
    assert "jane-doe" in ids
    assert "acme-corp" not in ids

    delete_all_queries(sync=True)


def test_percolate_name_variant():
    bulk_index_queries(QUERIES, sync=True)

    hits = percolate(DOC_MATCH_VARIANT)
    ids = {h["_id"] for h in hits}
    assert "jane-doe" in ids
    assert "acme-corp" not in ids

    delete_all_queries(sync=True)


def test_percolate_no_match():
    bulk_index_queries(QUERIES, sync=True)

    hits = percolate(DOC_NO_MATCH)
    assert len(hits) == 0

    delete_all_queries(sync=True)


def test_percolate_multiple_matches():
    bulk_index_queries(QUERIES, sync=True)

    hits = percolate(DOC_MULTI)
    ids = {h["_id"] for h in hits}
    assert "jane-doe" in ids
    assert "acme-corp" in ids

    delete_all_queries(sync=True)


def test_percolate_hit_contains_names():
    bulk_index_queries(QUERIES, sync=True)

    hits = percolate(DOC_MATCH)
    hit = next(h for h in hits if h["_id"] == "jane-doe")
    assert hit["_source"]["names"] == ["Jane Doe", "J. Doe"]

    delete_all_queries(sync=True)


def test_percolate_filter_countries():
    bulk_index_queries(QUERIES, sync=True)

    # acme-corp is scoped to "us", mueller-gmbh to "de", jane-doe has no countries
    hits = percolate(DOC_MULTI, countries=["de"])
    ids = {h["_id"] for h in hits}
    # jane-doe has no countries → matches (unscoped)
    assert "jane-doe" in ids
    # acme-corp is "us" only → filtered out
    assert "acme-corp" not in ids

    delete_all_queries(sync=True)


def test_percolate_filter_countries_match():
    bulk_index_queries(QUERIES, sync=True)

    hits = percolate(DOC_MULTI, countries=["us"])
    ids = {h["_id"] for h in hits}
    assert "jane-doe" in ids
    assert "acme-corp" in ids

    delete_all_queries(sync=True)


def test_percolate_filter_schemata():
    bulk_index_queries(QUERIES, sync=True)

    hits = percolate(DOC_MULTI, schemata=["Person"])
    ids = {h["_id"] for h in hits}
    # jane-doe has no schemata → matches (unscoped)
    assert "jane-doe" in ids
    # acme-corp is "Company" only → filtered out
    assert "acme-corp" not in ids

    delete_all_queries(sync=True)


def test_percolate_filter_combined():
    bulk_index_queries(QUERIES, sync=True)

    hits = percolate(DOC_MULTI, countries=["us"], schemata=["Company"])
    ids = {h["_id"] for h in hits}
    assert "jane-doe" in ids
    assert "acme-corp" in ids

    delete_all_queries(sync=True)


def test_delete_all_queries():
    bulk_index_queries(QUERIES, sync=True)
    delete_all_queries(sync=True)

    hits = percolate(DOC_MULTI)
    assert len(hits) == 0
