from typing import Any, ClassVar

from anystore.logging import get_logger
from banal import ensure_list
from elastic_transport import ObjectApiResponse
from followthemoney.types import registry

from openaleph_search.core import get_es
from openaleph_search.index.mapping import (
    DATE_FORMAT,
    GROUPS,
    NUMERIC_TYPES,
    Field,
    get_field_type,
    get_index_field_type,
)
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.highlight import get_highlighter
from openaleph_search.query.util import (
    BoolQuery,
    bool_query,
    field_filter_query,
    filter_text,
    range_filter_query,
)
from openaleph_search.settings import Settings

log = get_logger(__name__)
settings = Settings()


class Query:
    TEXT_FIELDS: ClassVar[list[str]] = [Field.TEXT]
    PREFIX_FIELD: ClassVar[str] = Field.NAME
    SKIP_FILTERS: ClassVar[list[str]] = []
    AUTHZ_FIELD: ClassVar[str | None] = settings.search_auth_field
    HIGHLIGHT_FIELD: ClassVar[str] = Field.TEXT
    SORT_FIELDS: ClassVar[dict[str, str]] = {
        "label": "label.kw",
        "score": "_score",
    }
    SORT_DEFAULT: ClassVar[list[str | dict[str, Any]]] = ["_score"]
    SOURCE: ClassVar[dict[str, Any]] = {}

    def __init__(self, parser: SearchQueryParser) -> None:
        self.parser = parser

    def get_query_string(self) -> dict[str, Any] | None:
        if self.parser.text:
            return {
                "query_string": {
                    "query": self.parser.text,
                    "lenient": True,
                    "fields": self.TEXT_FIELDS,
                    "default_operator": "AND",
                    "minimum_should_match": "66%",
                }
            }

    def get_text_query(self) -> list[dict[str, Any]]:
        query = []
        if self.parser.text:
            query.append(self.get_query_string())
        if self.parser.prefix:
            query.append({"prefix": {self.PREFIX_FIELD: self.parser.prefix}})
        if not len(query):
            query.append({"match_all": {}})
        return query

    def get_filters_list(self, skip: set[str]) -> list[dict[str, Any]]:
        filters = []
        range_filters = dict()
        for field, values in self.parser.filters.items():
            if field in skip:
                continue
            # Collect all range query filters for a field in a single query
            if field.startswith(("gt:", "gte:", "lt:", "lte:")):
                op, field = field.split(":", 1)
                if range_filters.get(field) is None:
                    range_filters[field] = {op: list(values)[0]}
                else:
                    range_filters[field][op] = list(values)[0]
                continue
            filters.append(field_filter_query(field, values))

        for field, ops in range_filters.items():
            filters.append(range_filter_query(field, ops))

        return filters

    def get_filters(self) -> list[dict[str, Any]]:
        """Apply query filters from the user interface."""
        skip = {*self.SKIP_FILTERS, *self.parser.facet_names}
        # important as we don't have schema indexes anymore:
        skip.discard("schema")
        skip.discard("schemata")

        filters = self.get_filters_list(skip)

        if self.AUTHZ_FIELD is not None:
            # This enforces the authorization (access control) rules on
            # a particular query by comparing the datasets a user is
            # authorized for with the one on the document.
            if self.parser.auth and not self.parser.auth.is_admin:
                datasets = self.parser.auth.datasets_query(self.AUTHZ_FIELD)
                filters.append(datasets)
        return filters

    def get_post_filters(self, exclude: str | None = None) -> dict[str, dict[str, Any]]:
        """Apply post-aggregation query filters."""
        pre = set(self.parser.filters.keys())
        pre = pre.difference(self.parser.facet_names)
        skip = {*pre, *self.SKIP_FILTERS, exclude}
        filters = self.get_filters_list(skip)
        return {"bool": {"filter": filters}}

    def get_negative_filters(self) -> list[dict[str, Any]]:
        """Apply negative filters."""
        filters = []
        for field, _ in self.parser.empties.items():
            filters.append({"exists": {"field": field}})

        for field, values in self.parser.excludes.items():
            filters.append(field_filter_query(field, values))
        return filters

    def get_query(self) -> dict[str, Any]:
        return {
            "bool": {
                "should": self.get_text_query(),
                "must": [],
                "must_not": self.get_negative_filters(),
                "filter": self.get_filters(),
                "minimum_should_match": 1,
            }
        }

    def get_aggregations(self) -> dict[str, Any]:
        """Aggregate the query in order to generate faceted results."""
        aggregations = {}

        # Regular facet aggregations
        for facet_name in self.parser.facet_names:
            facet_aggregations = {}
            if self.parser.get_facet_values(facet_name):
                agg_name = "%s.values" % facet_name
                terms = {
                    "field": facet_name,
                    "size": self.parser.get_facet_size(facet_name),
                    "execution_hint": "map",
                }
                facet_aggregations[agg_name] = {"terms": terms}

            if self.parser.get_facet_total(facet_name):
                # Option to return total distinct value counts for
                # a given facet, instead of the top buckets.
                agg_name = "%s.cardinality" % facet_name
                facet_aggregations[agg_name] = {"cardinality": {"field": facet_name}}

            interval = self.parser.get_facet_interval(facet_name)
            if interval is not None:
                agg_name = "%s.intervals" % facet_name
                facet_aggregations[agg_name] = {
                    "date_histogram": {
                        "field": facet_name,
                        "calendar_interval": interval,
                        "format": DATE_FORMAT,
                        "min_doc_count": 0,
                    }
                }
                # Make sure we return empty buckets in the whole filter range
                filters = self.parser.filters
                min_val = filters.get("gte:%s" % facet_name) or filters.get(
                    "gt:%s" % facet_name
                )
                max_val = filters.get("lte:%s" % facet_name) or filters.get(
                    "lt:%s" % facet_name
                )
                if min_val or max_val:
                    extended_bounds = {}
                    if min_val:
                        extended_bounds["min"] = ensure_list(min_val)[0]
                    if max_val:
                        extended_bounds["max"] = ensure_list(max_val)[0]
                    facet_aggregations[agg_name]["date_histogram"][
                        "extended_bounds"
                    ] = extended_bounds

            if len(facet_aggregations):
                # See here for an explanation of the whole post_filters and
                # aggregation filters thing:
                # https://www.elastic.co/guide/en/elasticsearch/reference/6.2/search-request-post-filter.html  # noqa: B950
                other_filters = self.get_post_filters(exclude=facet_name)
                if len(other_filters["bool"]["filter"]):
                    agg_name = "%s.filtered" % facet_name
                    aggregations[agg_name] = {
                        "filter": other_filters,
                        "aggregations": facet_aggregations,
                    }
                else:
                    aggregations.update(facet_aggregations)

        # Significant terms aggregations
        for facet_name in self.parser.facet_significant_names:
            facet_aggregations = {}
            if self.parser.get_facet_significant_values(facet_name):
                agg_name = "%s.significant_terms" % facet_name
                significant_terms_agg = {
                    "field": facet_name,
                    "background_filter": self.get_significant_background(),
                    "size": self.parser.get_facet_significant_size(facet_name),
                    "min_doc_count": 3,
                    "shard_size": max(
                        100, self.parser.get_facet_significant_size(facet_name) * 5
                    ),
                    "execution_hint": "map",
                }
                facet_aggregations[agg_name] = {
                    "significant_terms": significant_terms_agg
                }

                if self.parser.get_facet_significant_type(facet_name) == "nested":
                    facet_aggregations[agg_name]["aggregations"] = {
                        agg_name: {"significant_terms": significant_terms_agg}
                    }

            if self.parser.get_facet_significant_total(facet_name):
                # Option to return total distinct value counts for significant terms
                agg_name = "%s.significant_cardinality" % facet_name
                facet_aggregations[agg_name] = {"cardinality": {"field": facet_name}}

            if len(facet_aggregations):
                # Apply post-filters for significant terms aggregations
                other_filters = self.get_post_filters(exclude=facet_name)
                if len(other_filters["bool"]["filter"]):
                    agg_name = "%s.significant_filtered" % facet_name
                    aggregations[agg_name] = {
                        "filter": other_filters,
                        "aggregations": facet_aggregations,
                    }
                else:
                    aggregations.update(facet_aggregations)

        significant_text_field = self.parser.get_facet_significant_text()
        if significant_text_field:
            aggregations["significant_text"] = {
                **self.get_significant_text_sampler(),
                "aggs": {
                    "significant_text": {
                        "significant_text": {
                            "field": significant_text_field,
                            "background_filter": self.get_significant_background(),
                            "filter_duplicate_text": True,
                            "size": self.parser.get_facet_significant_text_size(),
                            "min_doc_count": self.parser.get_facet_significant_text_min_doc_count(),  # noqa: B950
                            "shard_size": self.parser.get_facet_significant_text_shard_size(),
                        }
                    }
                },
            }

        return aggregations

    def get_significant_background(self) -> BoolQuery | None:
        query = bool_query()
        if self.parser.collection_ids:
            query["bool"]["must"].append(
                field_filter_query(Field.COLLECTION_ID, self.parser.collection_ids)
            )
        elif self.parser.datasets:
            query["bool"]["must"].append(
                field_filter_query(Field.DATASET, self.parser.datasets)
            )
        return query

    def get_sample_for_aggregation(
        self, size: int, agg_name: str, aggregation: dict[str, Any]
    ) -> dict[str, Any]:
        # https://www.elastic.co/docs/reference/aggregations/search-aggregations-bucket-sampler-aggregation
        return {"sampler": {"shard_size": size}, "aggs": {agg_name: aggregation}}

    def get_significant_text_sampler(self) -> dict[str, Any]:
        if self.parser.collection_ids or self.parser.datasets:
            # no sampling on all datasets
            return {"sampler": {"shard_size": 200}}
        return {"diversified_sampler": {"shard_size": 200, "field": self.AUTHZ_FIELD}}

    def get_sort(self) -> list[str | dict[str, dict[str, Any]]]:
        """Pick one of a set of named result orderings."""
        if not len(self.parser.sorts):
            return self.SORT_DEFAULT

        sort_fields = ["_score"]
        for field, direction in self.parser.sorts:
            field = self.SORT_FIELDS.get(field, field)
            type_ = get_field_type(field)
            config = {"order": direction, "missing": "_last"}
            es_type = get_index_field_type(type_, to_numeric=True)
            if es_type:
                config["unmapped_type"] = es_type
            if field == registry.date.group:
                field = "numeric.dates"
                config["mode"] = "min"
            if type_ in NUMERIC_TYPES:
                field = field.replace("properties.", "numeric.")
            sort_fields.append({field: config})
        return list(reversed(sort_fields))

    def get_highlight(self) -> dict[str, Any]:
        if not self.parser.highlight:
            return {}
        query = self.get_query_string()
        if self.parser.filters:
            query = bool_query()
            if self.get_query_string():
                query["bool"]["should"] = [self.get_query_string()]
            for key, values in self.parser.filters.items():
                if key in GROUPS or key == Field.NAME:
                    for value in values:
                        query["bool"]["should"].append(
                            {
                                "multi_match": {
                                    "fields": [Field.CONTENT, Field.TEXT, Field.NAME],
                                    "query": value,
                                    "operator": "AND",
                                }
                            }
                        )
        return {
            "encoder": "html",
            # "max_fragment_length": 1000,
            "require_field_match": False,
            "fields": {
                self.HIGHLIGHT_FIELD: get_highlighter(
                    self.HIGHLIGHT_FIELD, query, self.parser.highlight_count
                ),
                Field.NAMES: get_highlighter(Field.NAME),
                Field.NAMES: get_highlighter(Field.NAMES),
                Field.TEXT: get_highlighter(Field.TEXT, query),
            },
        }

    def get_source(self) -> dict[str, Any]:
        return self.SOURCE

    def has_significant_aggregations(self) -> bool:
        """Check if any significant aggregations are being performed."""
        # Check for significant_text aggregation
        if self.parser.get_facet_significant_text():
            return True

        # Check for significant terms aggregations on facets
        if self.parser.facet_significant_names:
            return True

        return False

    def get_body(self) -> dict[str, Any]:
        # Don't return hits when doing significant aggregations
        size = 0 if self.has_significant_aggregations() else self.parser.limit

        body = {
            "query": self.get_query(),
            "post_filter": self.get_post_filters(),
            "from": self.parser.offset,
            "size": size,
            "aggregations": self.get_aggregations(),
            "sort": self.get_sort(),
            "highlight": self.get_highlight(),
            "_source": self.get_source(),
        }
        # log.info("Query: %s", pformat(body))
        return body

    def get_index(self) -> str:
        raise NotImplementedError

    def to_text(self, empty: str = "*:*") -> str:
        """Generate a string representation of the query."""
        parts = []
        if self.parser.text:
            parts.append(self.parser.text)
        elif self.parser.prefix:
            query = "%s:%s*" % (self.PREFIX_FIELD, self.parser.prefix)
            parts.append(query)
        else:
            parts.append(empty)

        for filter_ in self.get_filters_list([]):
            if filter_.get("term", {}).get("schemata") == "Thing":
                continue
            parts.append(filter_text(filter_))

        for filter_ in self.get_negative_filters():
            parts.append(filter_text(filter_, invert=True))

        if len(parts) > 1 and empty in parts:
            parts.remove(empty)
        return " ".join([p for p in parts if p is not None])

    def search(self) -> ObjectApiResponse:
        """Execute the query as assmbled."""
        log.debug("Search index: %s" % self.get_index())
        es = get_es()
        result = es.search(
            index=self.get_index(),
            body=self.get_body(),
            routing=self.parser.routing_key,
        )
        log.debug(
            f"Elasticsearch query [{self.to_text()}] took {result.get('took')}ms",
            query=self.to_text(),
            routing=self.parser.routing_key,
            body=self.get_body(),
            filters=self.parser.filters,
            took=result.get("took"),
            hits=result.get("hits", {}).get("total", {}).get("value"),
        )
        return result
