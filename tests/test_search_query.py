from unittest import TestCase

import pytest

from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.highlight import MAX_ANALYZED_OFFSET
from openaleph_search.query.queries import EntitiesQuery, Query
from openaleph_search.query.util import schema_query
from openaleph_search.settings import Settings

settings = Settings()


def query(args):
    return Query(SearchQueryParser(args, None))


class QueryTestCase(TestCase):
    def setUp(self):
        # Allow list elements to be in any order
        self.addTypeEqualityFunc(list, self.assertItemsEqual)

    # The standard assertDictEqual doesn't compare values
    # using assertEquals, so it fails to allow lists to be
    # in any order
    def assertDictEqual(self, d1, d2, msg=None):
        for k, v1 in d1.items():
            self.assertIn(k, d2, msg)
            v2 = d2[k]
            self.assertEqual(v1, v2, msg)

    # The standard assertItemsEqual doesn't use assertEquals
    # so fails to correctly compare complex data types
    def assertItemsEqual(self, items1, items2, msg=None):
        for item1 in items1:
            has_equal = False
            for item2 in items2:
                try:
                    self.assertEqual(item1, item2)
                    has_equal = True
                    break
                except Exception:
                    pass
            if not has_equal:
                self.fail("Item %r missing" % item1)

    def test_no_text(self):
        q = query([])
        self.assertEqual(q.get_text_query(), [{"match_all": {}}])

    def test_has_text(self):
        q = query([("q", "search text")])
        text_q = q.get_text_query()
        self.assertEqual(text_q[0]["query_string"]["query"], "search text")

    def test_has_prefix(self):
        q = query([("prefix", "tex")])
        text_q = q.get_text_query()
        self.assertEqual(text_q[0]["prefix"]["name"], "tex")

    def test_id_filter(self):
        q = query(
            [
                ("filter:id", "5"),
                ("filter:id", "8"),
                ("filter:id", "2"),
                ("filter:_id", "3"),
            ]
        )

        self.assertEqual(q.get_filters(), [{"ids": {"values": ["8", "5", "2", "3"]}}])

    def test_filters(self):
        q = query(
            [
                ("filter:key1", "foo"),
                ("filter:key1", "bar"),
                ("filter:key2", "blah"),
                ("filter:key2", "blahblah"),
                ("filter:gte:date", "2018"),
            ]
        )

        self.assertEqual(
            q.get_filters(),
            [
                {"terms": {"key1": ["foo", "bar"]}},
                {"terms": {"key2": ["blah", "blahblah"]}},
                {"range": {"date": {"gte": "2018"}}},
            ],
        )

    def test_offset(self):
        q = query([("offset", 10), ("limit", 100)])
        body = q.get_body()
        # https://stackoverflow.com/questions/20050913/python-unittests-assertdictcontainssubset-recommended-alternative
        self.assertEqual(body, body | {"from": 10, "size": 100})

    def test_post_filters(self):
        q = query(
            [
                ("filter:key1", "foo"),
                ("filter:key2", "foo"),
                ("filter:key2", "bar"),
                ("facet", "key2"),
                ("filter:key3", "blah"),
                ("filter:key3", "blahblah"),
                ("facet", "key3"),
            ]
        )
        self.assertEqual(q.get_filters(), [{"term": {"key1": "foo"}}])
        self.assertEqual(
            q.get_post_filters(),
            {
                "bool": {
                    "filter": [
                        {"terms": {"key2": ["foo", "bar"]}},
                        {"terms": {"key3": ["blah", "blahblah"]}},
                    ]
                }
            },
        )

    def test_highlight(self):
        q = query([("q", "foo"), ("highlight", "true")])

        self.assertEqual(
            q.get_highlight(),
            {
                "encoder": "html",
                "require_field_match": False,
                "fields": {
                    "text": {
                        "type": "unified",
                        "fragment_size": 150,
                        "number_of_fragments": 1,
                        "max_analyzed_offset": settings.highlighter_max_analyzed_offset,
                        "highlight_query": {
                            "query_string": {
                                "query": "foo",
                                "lenient": True,
                                "fields": ["text"],
                                "default_operator": "AND",
                                "allow_leading_wildcard": False,
                            }
                        },
                    },
                    "translation": {
                        "type": "unified",
                        "fragment_size": 150,
                        "number_of_fragments": 1,
                        "max_analyzed_offset": settings.highlighter_max_analyzed_offset,
                        "highlight_query": {
                            "query_string": {
                                "query": "foo",
                                "lenient": True,
                                "fields": ["translation"],
                                "default_operator": "AND",
                                "allow_leading_wildcard": False,
                            }
                        },
                    },
                },
            },
        )

    def test_highlight_max_analyzed_offset(self):
        def offsets(args):
            q = query([("q", "foo"), ("highlight", "true"), *args])
            fields = q.get_highlight()["fields"].values()
            return {
                f["max_analyzed_offset"] for f in fields if "max_analyzed_offset" in f
            }

        self.assertEqual(offsets([]), {settings.highlighter_max_analyzed_offset})
        self.assertEqual(offsets([("max_highlight_analyzed_offset", "5000")]), {5000})
        # kept below ES's `index.highlight.max_analyzed_offset`, which fails
        # the request for longer values
        self.assertEqual(
            offsets([("max_highlight_analyzed_offset", "5000000")]),
            {MAX_ANALYZED_OFFSET},
        )

    def test_highlight_content_phrases(self):
        q = EntitiesQuery(
            SearchQueryParser([("q", '"foo bar"'), ("highlight", "true")])
        )
        content = q.get_highlight()["fields"]["content"]
        self.assertTrue(content["require_field_match"])
        self.assertEqual(
            content["matched_fields"], ["content", "content._index_phrase"]
        )
        self.assertEqual(
            content["highlight_query"]["query_string"]["fields"], ["content"]
        )

    @pytest.mark.skip("Not supported anymore")
    def test_highlight_text(self):
        q = query([("q", "foo"), ("highlight", "true"), ("highlight_text", "bar")])
        highlight = q.get_highlight()

        self.assertEqual(
            highlight["fields"]["text"]["highlight_query"]["query_string"]["query"],
            "bar",
        )

    def test_metric_aggregations(self):
        q = query(
            [
                ("metric:sum", "amount"),
                ("metric:avg", "amount"),
                ("metric:min", "registrationArea"),
            ]
        )
        aggs = q.get_aggregations()
        self.assertEqual(aggs["amount.sum"], {"sum": {"field": "numeric.amount"}})
        self.assertEqual(aggs["amount.avg"], {"avg": {"field": "numeric.amount"}})
        self.assertEqual(
            aggs["registrationArea.min"],
            {"min": {"field": "numeric.registrationArea"}},
        )

    def test_metric_invalid_type(self):
        q = query([("metric:percentile", "amount")])
        aggs = q.get_aggregations()
        self.assertNotIn("amount.percentile", aggs)

    def test_schema_filter(self):
        q = query([("filter:schema", "Person")])
        assert q.get_filters() == [{"term": {"schema": "Person"}}]

    def test_schema_query(self):
        assert schema_query("Person") == {"terms": {"schema": ["Person"]}}
        assert schema_query(["Person", "Company"]) == {
            "terms": {"schema": ["Company", "Person"]}
        }
        assert schema_query(["Person", "Analyzable"]) == {
            "terms": {"schema": ["Person"]}
        }
        assert schema_query([]) == {"match_none": {}}
        assert schema_query(["Analyzable"]) == {"match_none": {}}
        assert schema_query(["Organization"], include_descendants=True) == {
            "terms": {"schema": ["Company", "Organization", "PublicBody"]}
        }
