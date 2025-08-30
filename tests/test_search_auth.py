from urllib.parse import parse_qsl, urlparse

import pytest

from openaleph_search.model import SearchAuth
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.queries import EntitiesQuery


def _url_to_args(url):
    """Convert URL query string to args list for SearchQueryParser"""
    parsed = urlparse(url)
    return parse_qsl(parsed.query, keep_blank_values=True)


def _create_query(url, auth: SearchAuth | None = None):
    """Create Query from URL string"""
    args = _url_to_args(url)
    parser = SearchQueryParser(args, auth)
    return EntitiesQuery(parser)


def _count(result) -> int:
    return result["hits"]["total"]["value"]


def _dataset_facets(result) -> list:
    return result["aggregations"]["dataset.values"]["buckets"]


def test_search_auth(
    monkeypatch, entities, index_entities, auth_admin, auth_private, auth_public
):
    monkeypatch.setenv("OPENALEPH_SEARCH_AUTH", "true")

    unauthenticated = SearchAuth()

    # simple counts
    PRIVATE = 3
    PUBLIC = 2 + len(entities) - 2  # -Page
    ALL = PRIVATE + PUBLIC
    # no auth obj raises when OPENALEPH_SEARCH_AUTH=true
    with pytest.raises(RuntimeError):
        assert _count(_create_query("/search").search()) == 0
    # unauthenticated
    assert _count(_create_query("/search", unauthenticated).search()) == 0
    # public auth
    assert _count(_create_query("/search", auth_public).search()) == PUBLIC
    # private auth
    assert _count(_create_query("/search", auth_private).search()) == ALL
    assert _count(_create_query("/search", auth_admin).search()) == ALL

    # test with q and filters

    query = _create_query("/search?q=kwazulu&facet=dataset", unauthenticated)
    result = query.search()
    assert _count(result) == 0
    assert _dataset_facets(result) == []

    query = _create_query("/search?q=kwazulu&facet=dataset", auth_public)
    result = query.search()
    assert _count(result) == 1
    assert _dataset_facets(result) == [{"key": "test_public", "doc_count": 1}]

    # public can't see private banana dataset
    query = _create_query("/search?q=banana&facet=dataset", auth_public)
    result = query.search()
    assert _count(result) == 0
    # even when explicitly querying dataset
    query = _create_query(
        "/search?q=banana&facet=dataset&filter:dataset=test_private", auth_public
    )
    result = query.search()
    assert _count(result) == 0
    # but private can
    query = _create_query(
        "/search?q=banana&facet=dataset&filter:dataset=test_private", auth_private
    )
    result = query.search()
    assert _count(result) == 3
    assert _dataset_facets(result) == [{"key": "test_private", "doc_count": 3}]


def test_significant_terms_auth(
    monkeypatch, entities, index_entities, auth_admin, auth_private, auth_public
):
    """Test that significant terms aggregations respect authentication filters"""
    monkeypatch.setenv("OPENALEPH_SEARCH_AUTH", "true")

    unauthenticated = SearchAuth()

    # Test significant terms aggregation on dataset field
    # This should only calculate significance against datasets the user has access to

    # Test that unauthenticated users get no significant terms
    query = _create_query("/search?facet_significant:dataset=1", unauthenticated)
    result = query.search()

    # Should have empty aggregation results for unauthenticated users
    if (
        "aggregations" in result
        and "dataset.significant_terms" in result["aggregations"]
    ):
        buckets = result["aggregations"]["dataset.significant_terms"]["buckets"]
        assert len(buckets) == 0

    # Test that public auth only sees significant terms from accessible datasets
    query = _create_query("/search?facet_significant:dataset=1", auth_public)
    result = query.search()

    public_buckets = []
    if (
        "aggregations" in result
        and "dataset.significant_terms" in result["aggregations"]
    ):
        public_buckets = result["aggregations"]["dataset.significant_terms"]["buckets"]
        # All significant datasets should be ones the user has access to
        for bucket in public_buckets:
            dataset_name = bucket["key"]
            # Public user should only see public datasets
            assert dataset_name == "test_public" or dataset_name in auth_public.datasets

    # Test that private auth sees significant terms from more datasets
    query = _create_query("/search?facet_significant:dataset=1", auth_private)
    result = query.search()

    private_buckets = []
    if (
        "aggregations" in result
        and "dataset.significant_terms" in result["aggregations"]
    ):
        private_buckets = result["aggregations"]["dataset.significant_terms"]["buckets"]
        # Private user should have same or more significant terms than public
        assert len(private_buckets) >= len(public_buckets)

    # Test that admin sees significant terms from all datasets
    query = _create_query("/search?facet_significant:dataset=1", auth_admin)
    result = query.search()

    admin_buckets = []
    if (
        "aggregations" in result
        and "dataset.significant_terms" in result["aggregations"]
    ):
        admin_buckets = result["aggregations"]["dataset.significant_terms"]["buckets"]
        # Admin should have same or more significant terms than private user
        assert len(admin_buckets) >= len(private_buckets)
