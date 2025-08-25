from urllib.parse import parse_qsl, urlparse

from openaleph_search.index.entities import index_bulk
from openaleph_search.index.indexes import make_schema_bucket_mapping
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.queries import EntitiesQuery


def _url_to_args(url):
    """Convert URL query string to args list for SearchQueryParser"""
    parsed = urlparse(url)
    return parse_qsl(parsed.query, keep_blank_values=True)


def _create_query(url):
    """Create Query from URL string"""
    args = _url_to_args(url)
    parser = SearchQueryParser(args)
    return EntitiesQuery(parser)


def test_pages_mapping():
    # pages special case: we store the content field

    mapping = make_schema_bucket_mapping("pages")
    assert mapping["properties"]["content"]["store"] is True


def test_pages(fixture_pages, cleanup_after):
    index_bulk("test_pages", fixture_pages)

    query = _create_query("/search?q=Mit License&highlight=true")
    result = query.search()
    # no page but the parent pages
    assert len(result["hits"]["hits"]) == 1
    assert result["hits"]["hits"][0]["_source"]["schema"] == "Pages"
    assert "<em>MIT</em>" in result["hits"]["hits"][0]["highlight"]["content"][0]
