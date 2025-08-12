from urllib.parse import parse_qsl, urlparse

from openaleph_search.search import EntitiesQuery
from openaleph_search.search.parser import SearchQueryParser


def _url_to_args(url):
    """Convert URL query string to args list for SearchQueryParser"""
    parsed = urlparse(url)
    return parse_qsl(parsed.query, keep_blank_values=True)


def _create_query(url):
    """Create Query from URL string"""
    args = _url_to_args(url)
    parser = SearchQueryParser(args)
    return EntitiesQuery(parser)


def test_search_simplest_search(index_entities):
    query = _create_query("/search?q=kwazulu&facet=collection_id")
    result = query.search()

    assert result["hits"]["total"]["value"] == 2
    assert "aggregations" in result

    query = _create_query("/search?q=banana&facet=collection_id")
    result = query.search()

    assert result["hits"]["total"]["value"] == 3
    assert "aggregations" in result
    assert result["aggregations"]["collection_id.values"]["buckets"][0] == {
        "key": "test_private",
        "doc_count": 3,
    }


def test_search_facet_attribute(index_entities):
    query = _create_query("/search?facet=names")
    result = query.search()

    assert result["hits"]["total"]["value"] > 0
    assert result["aggregations"]["names.values"]["buckets"] == [
        {"key": "Banana", "doc_count": 2},
        {"key": "Vladimir L.", "doc_count": 2},
        {"key": "Banana ba Nana", "doc_count": 1},
        {"key": "KwaZulu", "doc_count": 1},
        {"key": "kwazulu", "doc_count": 1},
    ]


def test_search_facet_counts(index_entities):
    query = _create_query("/search?facet=names&facet_total:names=true")
    result = query.search()

    assert result["hits"]["total"]["value"] > 0
    assert result["aggregations"]["names.values"]["buckets"] == [
        {"key": "Banana", "doc_count": 2},
        {"key": "Vladimir L.", "doc_count": 2},
        {"key": "Banana ba Nana", "doc_count": 1},
        {"key": "KwaZulu", "doc_count": 1},
        {"key": "kwazulu", "doc_count": 1},
    ]


def test_search_facet_schema(index_entities):
    query = _create_query("/search?facet=schema")
    result = query.search()

    assert result["hits"]["total"]["value"] > 0
    assert len(result["aggregations"]["schema.values"]["buckets"]) == 13
    assert result["aggregations"]["schema.values"]["buckets"] == [
        {"key": "Person", "doc_count": 5},
        {"key": "Table", "doc_count": 5},
        {"key": "Document", "doc_count": 3},
        {"key": "PlainText", "doc_count": 3},
        {"key": "Page", "doc_count": 2},
        {"key": "Company", "doc_count": 1},
        {"key": "Email", "doc_count": 1},
        {"key": "Folder", "doc_count": 1},
        {"key": "HyperText", "doc_count": 1},
        {"key": "Note", "doc_count": 1},
        {"key": "Package", "doc_count": 1},
        {"key": "Pages", "doc_count": 1},
        {"key": "Workbook", "doc_count": 1},
    ]

    # Test with schema filter
    query = _create_query("/search?facet=schema&filter:schema=Company")
    result = query.search()

    assert result["aggregations"]["schema.values"]["buckets"] == [
        {"key": "Company", "doc_count": 1}
    ]


def test_search_basic_filters(index_entities):
    # Test source_id filter
    query = _create_query("/search?filter:source_id=23")
    result = query.search()

    assert result["hits"]["total"]["value"] == 0

    # Test emails filter
    query = _create_query("/search?filter:emails=vladimir_l@example.com")
    result = query.search()

    assert result["hits"]["total"]["value"] == 2


def test_search_date_filters(index_entities):
    # Test date range filter
    query = _create_query("/search?q=banana&filter:gte:properties.birthDate=1970-08-08")
    result = query.search()

    assert result["hits"]["total"]["value"] == 1

    # Test date range with year precision
    query = _create_query("/search?filter:gte:dates=1970||/y&filter:lte:dates=1970||/y")
    result = query.search()

    assert result["hits"]["total"]["value"] == 2


def test_search_facet_interval(index_entities):
    query = _create_query(
        "/search?q=banana&facet=properties.birthDate"
        "&facet_interval:properties.birthDate=year"
        "&filter:gte:properties.birthDate=1969||/y"
        "&filter:lte:properties.birthDate=1971||/y"
    )
    result = query.search()

    assert result["hits"]["total"]["value"] == 3
    assert result["aggregations"]["properties.birthDate.values"]["buckets"] == [
        {"key": -19440000000, "key_as_string": "1969-05-21T00:00:00", "doc_count": 1},
        {"key": 6825600000, "key_as_string": "1970-03-21T00:00:00", "doc_count": 1},
        {"key": 20044800000, "key_as_string": "1970-08-21T00:00:00", "doc_count": 1},
    ]


def test_search_boolean_query(index_entities):
    # Test OR query
    query = _create_query("/search?q=banana OR kwazulu")
    result = query.search()

    assert result["hits"]["total"]["value"] == 5
    or_total = result["hits"]["total"]["value"]

    # Test AND query
    query = _create_query("/search?q=banana AND nana")
    result = query.search()

    assert result["hits"]["total"]["value"] == 1
    and_total = result["hits"]["total"]["value"]

    # AND query should typically return fewer or equal results than OR
    assert and_total <= or_total


def test_search_entity_facet(index_entities):
    query = _create_query(
        "/search?facet=properties.entity&facet_type:properties.entity=entity"
    )
    result = query.search()

    assert result["hits"]["total"]["value"] >= 0
    assert result["aggregations"]["properties.entity.values"]["buckets"] == [
        {"key": "id-kwazulu", "doc_count": 1}
    ]


def test_search_highlight(index_entities):
    query = _create_query("/search?q=test&highlight=true")
    result = query.search()

    assert result["hits"]["total"]["value"] >= 0
    # Check if any results have highlights
    for hit in result["hits"].get("hits", []):
        if "highlight" in hit:
            assert isinstance(hit["highlight"], dict)


def test_search_highlight_custom_text(index_entities):
    query = _create_query("/search?q=test&highlight=true&highlight_text=custom")
    result = query.search()

    assert result["hits"]["total"]["value"] >= 0


def test_search_pagination(index_entities):
    # Test offset and limit
    query = _create_query("/search?offset=5&limit=10")
    result = query.search()

    assert result["hits"]["total"]["value"] >= 0
    assert len(result["hits"].get("hits", [])) <= 10


def test_search_empty_query(index_entities):
    query = _create_query("/search")
    result = query.search()

    assert result["hits"]["total"]["value"] >= 0
    assert "hits" in result["hits"]


def test_search_url_to_args_conversion():
    """Test URL parsing utility function"""
    args = _url_to_args("/search?q=test&filter:schema=Document&facet=collection_id")

    expected = [
        ("q", "test"),
        ("filter:schema", "Document"),
        ("facet", "collection_id"),
    ]

    assert args == expected


def test_search_query_parser_from_url():
    """Test SearchQueryParser creation from URL"""
    url = "/search?q=test query&offset=10&limit=50&filter:schema=Document&facet=collection_id"
    args = _url_to_args(url)
    parser = SearchQueryParser(args, None)

    assert parser.text == "test query"
    assert parser.offset == 10
    assert parser.limit == 50
    assert "schema" in parser.filters
    assert parser.filters["schema"] == {"Document"}
    assert "collection_id" in parser.facet_names


def test_search_symbols():
    symbol = "47200243"  # vladimir
    query = _create_query(f"/search?filter:symbols={symbol}")
    result = query.search()

    assert result["hits"]["total"]["value"] == 1
    assert (
        result["hits"]["hits"][0]["_id"] == "6cb6066ec282d5f8ddf9ca28a0d20c1713ac0a5b"
    )


def test_search_fingerprints():
    fp = "l vladimir"
    query = _create_query(f"/search?filter:fingerprints={fp}")
    result = query.search()

    assert result["hits"]["total"]["value"] == 1
    assert (
        result["hits"]["hits"][0]["_id"] == "6cb6066ec282d5f8ddf9ca28a0d20c1713ac0a5b"
    )


def test_search_prefix():
    query = _create_query("/search?prefix=vla")
    result = query.search()
    assert result["hits"]["total"]["value"] == 2


def test_search_nonlatin():
    query = _create_query("/search?q=Українська")
    result = query.search()
    assert result["hits"]["total"]["value"] == 1
