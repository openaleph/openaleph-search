from openaleph_search.index.percolator import (
    bulk_index_queries,
    delete_all_queries,
    percolate,
)
from openaleph_search.model import PercolatorDoc
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.queries import PercolatorQuery

QUERIES = [
    PercolatorDoc(key="jane-doe", names=["Jane Doe", "J. Doe"]),
    PercolatorDoc(
        key="acme-corp",
        names=["Acme Corporation", "ACME Corp"],
        countries=["us"],
        schemata=["Company"],
    ),
    PercolatorDoc(
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

    result = percolate(DOC_MATCH)
    hits = result["hits"]["hits"]
    ids = {h["_id"] for h in hits}
    assert "jane-doe" in ids
    assert "acme-corp" not in ids

    delete_all_queries(sync=True)


def test_percolate_name_variant():
    bulk_index_queries(QUERIES, sync=True)

    result = percolate(DOC_MATCH_VARIANT)
    hits = result["hits"]["hits"]
    ids = {h["_id"] for h in hits}
    assert "jane-doe" in ids
    assert "acme-corp" not in ids

    delete_all_queries(sync=True)


def test_percolate_no_match():
    bulk_index_queries(QUERIES, sync=True)

    result = percolate(DOC_NO_MATCH)
    assert len(result["hits"]["hits"]) == 0

    delete_all_queries(sync=True)


def test_percolate_multiple_matches():
    bulk_index_queries(QUERIES, sync=True)

    result = percolate(DOC_MULTI)
    hits = result["hits"]["hits"]
    ids = {h["_id"] for h in hits}
    assert "jane-doe" in ids
    assert "acme-corp" in ids

    delete_all_queries(sync=True)


def test_percolate_hit_contains_surface_forms():
    bulk_index_queries(QUERIES, sync=True)

    result = percolate(DOC_MATCH)
    hits = result["hits"]["hits"]
    hit = next(h for h in hits if h["_id"] == "jane-doe")
    # only "Jane Doe" appears in DOC_MATCH, not "J. Doe"
    assert hit["_source"]["surface_forms"] == ["Jane Doe"]
    assert "names" not in hit["_source"]

    delete_all_queries(sync=True)


def test_percolate_surface_form_variant():
    bulk_index_queries(QUERIES, sync=True)

    result = percolate(DOC_MATCH_VARIANT)
    hits = result["hits"]["hits"]
    hit = next(h for h in hits if h["_id"] == "jane-doe")
    # DOC_MATCH_VARIANT contains "J. Doe", not "Jane Doe"
    assert hit["_source"]["surface_forms"] == ["J. Doe"]

    delete_all_queries(sync=True)


def test_percolate_filter_countries():
    bulk_index_queries(QUERIES, sync=True)

    # acme-corp is scoped to "us", mueller-gmbh to "de", jane-doe has no countries
    result = percolate(DOC_MULTI, countries=["de"])
    hits = result["hits"]["hits"]
    ids = {h["_id"] for h in hits}
    # jane-doe has no countries → matches (unscoped)
    assert "jane-doe" in ids
    # acme-corp is "us" only → filtered out
    assert "acme-corp" not in ids

    delete_all_queries(sync=True)


def test_percolate_filter_countries_match():
    bulk_index_queries(QUERIES, sync=True)

    result = percolate(DOC_MULTI, countries=["us"])
    hits = result["hits"]["hits"]
    ids = {h["_id"] for h in hits}
    assert "jane-doe" in ids
    assert "acme-corp" in ids

    delete_all_queries(sync=True)


def test_percolate_filter_schemata():
    bulk_index_queries(QUERIES, sync=True)

    result = percolate(DOC_MULTI, schemata=["Person"])
    hits = result["hits"]["hits"]
    ids = {h["_id"] for h in hits}
    # jane-doe has no schemata → matches (unscoped)
    assert "jane-doe" in ids
    # acme-corp is "Company" only → filtered out
    assert "acme-corp" not in ids

    delete_all_queries(sync=True)


def test_percolate_filter_combined():
    bulk_index_queries(QUERIES, sync=True)

    result = percolate(DOC_MULTI, countries=["us"], schemata=["Company"])
    hits = result["hits"]["hits"]
    ids = {h["_id"] for h in hits}
    assert "jane-doe" in ids
    assert "acme-corp" in ids

    delete_all_queries(sync=True)


def test_delete_all_queries():
    bulk_index_queries(QUERIES, sync=True)
    delete_all_queries(sync=True)

    result = percolate(DOC_MULTI)
    assert len(result["hits"]["hits"]) == 0


def test_percolator_query_resolves_entities(index_entities):
    """End-to-end PercolatorQuery test against the index_entities fixture.

    The fixture indexes a Company named "KwaZulu" (test_public dataset)
    and a Person named "Banana ba Nana" (test_private dataset). We stash
    a percolator query for each, then run PercolatorQuery on a document
    that mentions both names and assert each percolator hit resolves
    back to its underlying entity with `percolator` metadata in _source.
    """
    docs = [
        PercolatorDoc(
            key="kwazulu-company",
            names=["KwaZulu"],
            schemata=["Company"],
        ),
        PercolatorDoc(
            key="banana-person",
            names=["Banana ba Nana"],
            schemata=["Person"],
        ),
    ]
    bulk_index_queries(docs, sync=True)

    text = (
        "An investigation into KwaZulu revealed that "
        "Banana ba Nana was involved in the affair."
    )

    parser = SearchQueryParser([])
    query = PercolatorQuery(parser, text=text)
    result = query.search()

    hits = result["hits"]["hits"]
    by_id = {h["_id"]: h for h in hits}

    # Each percolator hit resolves to its underlying entity
    assert "id-company" in by_id, f"id-company missing from {list(by_id)}"
    assert "banana3" in by_id, f"banana3 missing from {list(by_id)}"

    company_hit = by_id["id-company"]
    assert company_hit["_source"]["percolator"] == {
        "keys": ["kwazulu-company"],
        "surface_forms": ["KwaZulu"],
    }

    banana_hit = by_id["banana3"]
    assert banana_hit["_source"]["percolator"] == {
        "keys": ["banana-person"],
        "surface_forms": ["Banana ba Nana"],
    }

    # Total count reflects deduped unique entities, not raw msearch hits
    assert result["hits"]["total"]["value"] == len(by_id)

    delete_all_queries(sync=True)
