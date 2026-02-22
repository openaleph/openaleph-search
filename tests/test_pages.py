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

    mapping = make_schema_bucket_mapping("page")
    assert mapping["properties"]["content"]["store"] is False


def test_pages(fixture_pages, cleanup_after):
    index_bulk("test_pages", fixture_pages)

    query = _create_query("/search?q=Mit License&highlight=true")
    result = query.search()
    # no page but the parent pages
    assert len(result["hits"]["hits"]) == 1
    assert result["hits"]["hits"][0]["_source"]["schema"] == "Pages"
    assert "<em>MIT</em>" in result["hits"]["hits"][0]["highlight"]["content"][0]


def test_pages_translation(cleanup_after):
    """Test that Pages entities with __translation__-prefixed indexText values
    are searchable via the translation field."""
    from ftmq.util import make_entity

    entity = make_entity(
        {
            "id": "pages-with-translation",
            "schema": "Pages",
            "properties": {
                "fileName": ["bericht.pdf"],
                "indexText": [
                    "Dies ist der Originalbericht auf Deutsch",
                    "__translation__ This is the translated report in English",
                    "__translation__ Ceci est le rapport traduit en français",
                ],
            },
        }
    )

    index_bulk("test_pages_translation", [entity], sync=True)

    # Search for original German text — should match via content field
    query = _create_query(
        "/search?q=Originalbericht&filter:dataset=test_pages_translation"
    )
    result = query.search()
    assert result["hits"]["total"]["value"] == 1
    assert result["hits"]["hits"][0]["_id"] == "pages-with-translation"

    # Search for English translation — should match via translation field
    query = _create_query(
        "/search?q=translated report English&filter:dataset=test_pages_translation"
    )
    result = query.search()
    assert result["hits"]["total"]["value"] == 1
    assert result["hits"]["hits"][0]["_id"] == "pages-with-translation"

    # Search for French translation
    query = _create_query(
        "/search?q=rapport traduit français&filter:dataset=test_pages_translation"
    )
    result = query.search()
    assert result["hits"]["total"]["value"] == 1
    assert result["hits"]["hits"][0]["_id"] == "pages-with-translation"
