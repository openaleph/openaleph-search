from urllib.parse import parse_qsl, urlparse

import pytest
from ftmq.util import make_entity

from openaleph_search.index.entities import index_bulk
from openaleph_search.model import SearchAuth
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.queries import EntitiesQuery
from openaleph_search.transform.entity import format_entity


def _url_to_args(url):
    """Convert URL query string to args list for SearchQueryParser"""
    parsed = urlparse(url)
    return parse_qsl(parsed.query, keep_blank_values=True)


def _create_query(url, auth: SearchAuth | None = None):
    """Create Query from URL string"""
    args = _url_to_args(url)
    parser = SearchQueryParser(args, auth)
    return EntitiesQuery(parser)


def test_search_simplest_search(index_entities):
    query = _create_query("/search?q=kwazulu&facet=dataset")
    result = query.search()

    assert result["hits"]["total"]["value"] == 1
    assert "aggregations" in result

    query = _create_query("/search?q=banana&facet=dataset")
    result = query.search()

    assert result["hits"]["total"]["value"] == 3
    assert "aggregations" in result
    assert result["aggregations"]["dataset.values"]["buckets"][0] == {
        "key": "test_private",
        "doc_count": 3,
    }


def test_search_facet_attribute(index_entities):
    query = _create_query("/search?facet=names")
    result = query.search()

    assert result["hits"]["total"]["value"] > 0
    assert result["aggregations"]["names.values"]["buckets"] == [
        {"key": "banana", "doc_count": 2},
        {"key": "vladimir l", "doc_count": 2},
        {"key": "banana ba nana", "doc_count": 1},
        {"key": "kwazulu", "doc_count": 1},
    ]


def test_search_facet_counts(index_entities):
    query = _create_query("/search?facet=names&facet_total:names=true")
    result = query.search()

    assert result["hits"]["total"]["value"] > 0
    assert result["aggregations"]["names.values"]["buckets"] == [
        {"key": "banana", "doc_count": 2},
        {"key": "vladimir l", "doc_count": 2},
        {"key": "banana ba nana", "doc_count": 1},
        {"key": "kwazulu", "doc_count": 1},
    ]


def test_search_facet_schema(index_entities):
    query = _create_query("/search?facet=schema")
    result = query.search()

    assert result["hits"]["total"]["value"] > 0
    assert len(result["aggregations"]["schema.values"]["buckets"]) == 12
    assert result["aggregations"]["schema.values"]["buckets"] == [
        {"key": "Person", "doc_count": 5},
        {"key": "Table", "doc_count": 5},
        {"key": "Document", "doc_count": 3},
        {"key": "PlainText", "doc_count": 3},
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
        {
            "key": -19440000000,
            "key_as_string": "1969-05-21T00:00:00.000Z",
            "doc_count": 1,
        },
        {
            "key": 6825600000,
            "key_as_string": "1970-03-21T00:00:00.000Z",
            "doc_count": 1,
        },
        {
            "key": 20044800000,
            "key_as_string": "1970-08-21T00:00:00.000Z",
            "doc_count": 1,
        },
    ]


def test_search_boolean_query(index_entities):
    # Test OR query
    query = _create_query("/search?q=banana OR kwazulu")
    result = query.search()

    assert result["hits"]["total"]["value"] == 4
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
        {"key": "id-company", "doc_count": 1}
    ]


def test_search_highlight(index_entities):
    query = _create_query("/search?q=test&highlight=true")
    result = query.search()

    assert result["hits"]["total"]["value"] >= 0
    # Check if any results have highlights
    for hit in result["hits"].get("hits", []):
        if "highlight" in hit:
            assert isinstance(hit["highlight"], dict)


@pytest.mark.skip("Not supported anymore")
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
    args = _url_to_args("/search?q=test&filter:schema=Document&facet=dataset")

    expected = [
        ("q", "test"),
        ("filter:schema", "Document"),
        ("facet", "dataset"),
    ]

    assert args == expected


def test_search_query_parser_from_url():
    """Test SearchQueryParser creation from URL"""
    url = "/search?q=test query&offset=10&limit=50&filter:schema=Document&facet=dataset"
    args = _url_to_args(url)
    parser = SearchQueryParser(args, None)

    assert parser.text == "test query"
    assert parser.offset == 10
    assert parser.limit == 50
    assert "schema" in parser.filters
    assert parser.filters["schema"] == {"Document"}
    assert "dataset" in parser.facet_names


def test_search_symbols():
    symbol = "[NAME:47200243]"  # vladimir
    query = _create_query(
        f"/search?filter:schemata=LegalEntity&filter:name_symbols={symbol}"
    )
    result = query.search()
    assert result["hits"]["total"]["value"] == 1
    assert (
        result["hits"]["hits"][0]["_id"] == "6cb6066ec282d5f8ddf9ca28a0d20c1713ac0a5b"
    )

    # as well found in 1 document
    query = _create_query(
        f"/search?filter:schemata=Document&filter:name_symbols={symbol}"
    )
    result = query.search()
    assert result["hits"]["total"]["value"] == 1


def test_search_name_parts():
    fp = "vladimir"
    query = _create_query(f"/search?filter:name_parts={fp}")
    result = query.search()
    assert result["hits"]["total"]["value"] == 1


def test_search_prefix():
    query = _create_query("/search?prefix=vla")
    result = query.search()
    assert result["hits"]["total"]["value"] == 1


def test_search_nonlatin():
    query = _create_query("/search?q=Українська")
    result = query.search()
    assert result["hits"]["total"]["value"] == 1


def test_search_sort(cleanup_after):
    e1 = make_entity(
        {"id": "event1", "schema": "Event", "properties": {"date": ["2020"]}}
    )
    e2 = make_entity(
        {"id": "event2", "schema": "Event", "properties": {"date": ["2021"]}}
    )

    # test numeric props
    action = format_entity("test", e1)
    assert action["_source"]["numeric"]["dates"] == [1577836800.0]
    assert action["_source"]["numeric"]["date"] == [1577836800.0]

    index_bulk("test_dates", [e1, e2], sync=True)

    query = _create_query("/search?filter:dataset=test_dates&sort=dates")
    result = query.search()
    assert len(result["hits"]["hits"]) == 2
    assert result["hits"]["hits"][0]["_id"] == "event1"

    query = _create_query("/search?filter:dataset=test_dates&sort=dates%3Adesc")
    assert query.get_sort() == [
        {
            "numeric.dates": {
                "order": "desc",
                "missing": "_last",
                "unmapped_type": "keyword",
                "mode": "min",
            }
        },
        "_score",
    ]
    result = query.search()
    assert len(result["hits"]["hits"]) == 2
    assert result["hits"]["hits"][0]["_id"] == "event2"


def test_search_tag_filter(cleanup_after):
    # Create entity with tags in context
    entity_data = {
        "id": "jane-doe-tagged",
        "schema": "Person",
        "properties": {"name": ["Jane Doe"], "birthDate": ["1980-01-01"]},
    }
    entity = make_entity(entity_data)
    entity.context["tags"] = ["politician", "businessman", "controversial"]

    index_bulk("test_tagged", [entity], sync=True)

    # Test search with tag filter
    query = _create_query("/search?filter:dataset=test_tagged&filter:tags=politician")
    result = query.search()

    assert result["hits"]["total"]["value"] == 1
    assert result["hits"]["hits"][0]["_id"] == "jane-doe-tagged"

    # Test search with non-existent tag
    query = _create_query("/search?filter:dataset=test_tagged&filter:tags=nonexistent")
    result = query.search()

    assert result["hits"]["total"]["value"] == 0

    # Test search with multiple tag values
    query = _create_query("/search?filter:dataset=test_tagged&filter:tags=businessman")
    result = query.search()

    assert result["hits"]["total"]["value"] == 1
    assert result["hits"]["hits"][0]["_id"] == "jane-doe-tagged"

    # Test tags facet aggregation
    query = _create_query("/search?filter:dataset=test_tagged&facet=tags")
    result = query.search()

    assert result["hits"]["total"]["value"] == 1
    assert "aggregations" in result
    assert result["aggregations"]["tags.values"]["buckets"] == [
        {"key": "businessman", "doc_count": 1},
        {"key": "controversial", "doc_count": 1},
        {"key": "politician", "doc_count": 1},
    ]


def test_search_dehydrate(index_entities):
    """Test that dehydrate=true excludes properties from response"""
    # Test with dehydrate=true - properties should be excluded
    query = _create_query("/search?q=banana&dehydrate=true")
    result = query.search()

    assert result["hits"]["total"]["value"] >= 1
    # Check that at least one hit exists
    assert len(result["hits"]["hits"]) > 0

    # Verify properties are excluded from all results
    for hit in result["hits"]["hits"]:
        assert "_source" in hit
        assert (
            "properties" not in hit["_source"]
        ), "properties field should be excluded when dehydrate=true"
        # Other fields should still be present
        assert "schema" in hit["_source"]
        assert "caption" in hit["_source"]
        assert "dataset" in hit["_source"]


def test_search_dehydrate_false(index_entities):
    """Test that dehydrate=false (default) includes properties in response"""
    # Test with explicit dehydrate=false
    query = _create_query("/search?q=banana&dehydrate=false")
    result = query.search()

    assert result["hits"]["total"]["value"] >= 1
    assert len(result["hits"]["hits"]) > 0

    # Verify properties are included in results
    for hit in result["hits"]["hits"]:
        assert "_source" in hit
        assert (
            "properties" in hit["_source"]
        ), "properties field should be included when dehydrate=false"
        assert "schema" in hit["_source"]


def test_search_dehydrate_default(index_entities):
    """Test that without dehydrate parameter, properties are included by default"""
    # Test without dehydrate parameter (default behavior)
    query = _create_query("/search?q=banana")
    result = query.search()

    assert result["hits"]["total"]["value"] >= 1
    assert len(result["hits"]["hits"]) > 0

    # Verify properties are included by default
    for hit in result["hits"]["hits"]:
        assert "_source" in hit
        assert (
            "properties" in hit["_source"]
        ), "properties field should be included by default"
        assert "schema" in hit["_source"]
