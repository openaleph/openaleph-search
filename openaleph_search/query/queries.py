import logging
from functools import cached_property
from typing import Any

from banal import ensure_list
from followthemoney import EntityProxy, model

from openaleph_search.index.entities import ENTITY_SOURCE
from openaleph_search.index.indexes import entities_read_index, schema_bucket
from openaleph_search.index.mapping import Field
from openaleph_search.query.base import Query
from openaleph_search.query.matching import match_query
from openaleph_search.query.more_like_this import more_like_this_query
from openaleph_search.query.util import field_filter_query
from openaleph_search.settings import Settings

log = logging.getLogger(__name__)

EXCLUDE_SCHEMATA = [
    s.name for s in model.schemata.values() if s.hidden
]  # Page, Mention


class EntitiesQuery(Query):
    TEXT_FIELDS = [
        f"{Field.NAME}^4",
        f"{Field.NAMES}^3",
        f"{Field.NAME_PARTS}^2",
        Field.CONTENT,
        f"{Field.TEXT}^0.8",
    ]
    PREFIX_FIELD = Field.NAME_PARTS
    HIGHLIGHT_FIELD = Field.CONTENT
    SKIP_FILTERS = [Field.SCHEMA, Field.SCHEMATA]
    SOURCE = ENTITY_SOURCE
    SORT_DEFAULT = []

    @cached_property
    def schemata(self) -> list[str]:
        schemata = self.parser.getlist("filter:schema")
        if len(schemata):
            return schemata
        schemata = self.parser.getlist("filter:schemata")
        if not len(schemata):
            schemata = ["Thing"]
        return schemata

    def get_index(self):
        return entities_read_index(schema=self.schemata)

    def get_query(self) -> dict[str, Any]:
        return self.wrap_query_function_score(self.get_inner_query())

    def get_inner_query(self) -> dict[str, Any]:
        return super().get_query()

    def get_negative_filters(self) -> list[dict[str, Any]]:
        # exclude hidden schemata unless we explicitly want them
        filters = super().get_negative_filters()
        exclude_schemata = set(EXCLUDE_SCHEMATA) - set(self.schemata)
        filters.append(field_filter_query("schema", exclude_schemata))
        return filters

    def get_index_weight_functions(self) -> list[dict[str, Any]]:
        """Generate index weight functions based on schema bucket settings"""
        settings = Settings()
        functions = []

        # Map bucket names to their boost settings
        bucket_boosts = {
            "pages": settings.index_boost_pages,
            "documents": settings.index_boost_documents,
            "intervals": settings.index_boost_intervals,
            "things": settings.index_boost_things,
        }

        # Create boost functions for each schema in the query
        for schema_name in self.schemata:
            try:
                bucket = schema_bucket(schema_name)
                boost_value = bucket_boosts.get(bucket, 1)

                if boost_value != 1:  # Only add function if boost differs from default
                    functions.append(
                        {
                            "filter": {"term": {"schema": schema_name}},
                            "weight": boost_value,
                        }
                    )
            except (ValueError, KeyError):
                # Skip invalid schemas
                continue

        return functions

    def wrap_query_function_score(self, query: dict[str, Any]) -> dict[str, Any]:
        # Wrap query in function_score to up-score important entities.
        # (thank you, OpenSanctions/yente :))
        functions = [
            {
                "field_value_factor": {
                    "field": Field.NUM_VALUES,
                    # This is a bit of a jiggle factor. Currently, very
                    # large documents (like Vladimir Putin) have a
                    # num_values of ~200, so get a +10 boost.  The order
                    # is modifier(factor * value)
                    "factor": 0.5,
                    "modifier": "sqrt",
                }
            }
        ]

        # Add index weight functions
        functions.extend(self.get_index_weight_functions())

        return {
            "function_score": {
                "query": query,
                "functions": functions,
                "boost_mode": "sum",
            }
        }


class MatchQuery(EntitiesQuery):
    """Given an entity, find the most similar other entities."""

    def __init__(
        self,
        parser,
        entity: EntityProxy | None = None,
        exclude=None,
        datasets=None,
        collection_ids=None,
    ):
        self.entity = entity
        self.exclude = ensure_list(exclude)
        self.datasets = datasets
        self.collection_ids = collection_ids
        super(MatchQuery, self).__init__(parser)

    def get_index(self):
        # Attempt to find only matches within the "matchable" set of
        # entity schemata. For example, a Company and be matched to
        # another company or a LegalEntity, but not a Person.
        # Real estate is "unmatchable", i.e. even if two plots of land
        # have almost the same name and criteria, it does not make
        # sense to suggest they are the same.
        schemata = list(self.entity.schema.matchable_schemata)
        return entities_read_index(schema=schemata)

    def get_inner_query(self) -> dict[str, Any]:
        query = match_query(
            self.entity,
            datasets=self.datasets,
            collection_ids=self.collection_ids,
            query=super().get_inner_query(),
        )
        if len(self.exclude):
            exclude = {"ids": {"values": self.exclude}}
            query["bool"]["must_not"].append(exclude)
        return query


class MoreLikeThisQuery(EntitiesQuery):
    """Given an entity, find similar documents/pages based on text content using
    elasticsearch more_like_this query."""

    def __init__(
        self,
        parser,
        entity: EntityProxy | None = None,
        exclude=None,
        datasets=None,
        collection_ids=None,
    ):
        self.entity = entity
        self.exclude = ensure_list(exclude)
        self.datasets = datasets
        self.collection_ids = collection_ids
        super(MoreLikeThisQuery, self).__init__(parser)

    def get_index(self):
        # Target only documents and pages buckets for more_like_this queries
        return entities_read_index(schema="Document")

    def get_inner_query(self) -> dict[str, Any]:
        if not self.entity:
            return {"match_none": {}}

        # Get base query with auth filters from parent class
        base_query = super().get_inner_query()

        # Apply more_like_this query
        mlt_query = more_like_this_query(
            self.entity,
            datasets=self.datasets,
            collection_ids=self.collection_ids,
            parser=self.parser,
            query=base_query,
        )

        if len(self.exclude):
            exclude = {"ids": {"values": self.exclude}}
            mlt_query["bool"]["must_not"].append(exclude)
        return mlt_query


class GeoDistanceQuery(EntitiesQuery):
    """Given an Address entity, find the nearby Address entities via the
    geo_point field"""

    def __init__(self, parser, entity=None, exclude=None, datasets=None):
        self.entity = entity
        self.exclude = ensure_list(exclude)
        self.datasets = datasets
        super().__init__(parser)

    def is_valid(self) -> bool:
        return (
            self.entity is not None
            and self.entity.first("latitude") is not None
            and self.entity.first("longitude") is not None
        )

    def get_query(self):
        if not self.is_valid():
            return {"match_none": {}}
        query = super(GeoDistanceQuery, self).get_query()
        exclude = {"ids": {"values": self.exclude + [self.entity.id]}}
        query["bool"]["must_not"].append(exclude)
        query["bool"]["must"].append({"exists": {"field": "geo_point"}})
        return query

    def get_sort(self):
        """Always sort by calculated distance"""
        if not self.is_valid():
            return []
        return [
            {
                "_geo_distance": {
                    "geo_point": {
                        "lat": self.entity.first("latitude"),
                        "lon": self.entity.first("longitude"),
                    },
                    "order": "asc",
                    "unit": "km",
                    "mode": "min",
                    "distance_type": "plane",  # faster
                }
            }
        ]
