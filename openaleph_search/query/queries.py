import logging
from typing import Any

from banal import ensure_list

from openaleph_search.index.entities import ENTITY_SOURCE
from openaleph_search.index.indexes import entities_read_index
from openaleph_search.index.xref import XREF_SOURCE, xref_index
from openaleph_search.mapping import Field, property_field
from openaleph_search.query.base import Query
from openaleph_search.query.matching import match_query

log = logging.getLogger(__name__)

SCORE_CUTOFF = 0.5


class EntitiesQuery(Query):
    TEXT_FIELDS = [f"{Field.NAMES}^3", f"{Field.NAME_PARTS}^2", Field.TEXT]
    PREFIX_FIELD = Field.NAME_PARTS
    HIGHLIGHT_FIELD = property_field("*")
    SKIP_FILTERS = [Field.SCHEMA, Field.SCHEMATA]
    SOURCE = ENTITY_SOURCE
    SORT_DEFAULT = []

    def get_index(self):
        schemata = self.parser.getlist("filter:schema")
        if len(schemata):
            return entities_read_index(schema=schemata, expand=False)
        schemata = self.parser.getlist("filter:schemata")
        if not len(schemata):
            schemata = ["Thing"]
        return entities_read_index(schema=schemata)

    def get_query(self) -> dict[str, Any]:
        query = super().get_query()
        return self.wrap_query_function_score(query)

    def wrap_query_function_score(self, query: dict[str, Any]) -> dict[str, Any]:
        # Wrap query in function_score to up-score important entities.
        # (thank you, OpenSanctions/yente :))
        return {
            "function_score": {
                "query": query,
                "functions": [
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
                ],
                "boost_mode": "sum",
            }
        }


class MatchQuery(EntitiesQuery):
    """Given an entity, find the most similar other entities."""

    def __init__(self, parser, entity=None, exclude=None, datasets=None):
        self.entity = entity
        self.exclude = ensure_list(exclude)
        self.datasets = datasets
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

    def get_query(self):
        query = super(MatchQuery, self).get_query()
        query = match_query(self.entity, datasets=self.datasets, query=query)
        if len(self.exclude):
            exclude = {"ids": {"values": self.exclude}}
            query["bool"]["must_not"].append(exclude)
        return query


class GeoDistanceQuery(EntitiesQuery):
    """Given an Address entity, find the nearby Address entities via the
    geo_point field"""

    def __init__(self, parser, entity=None, exclude=None, datasets=None):
        self.entity = entity
        self.exclude = ensure_list(exclude)
        self.datasets = datasets
        super(EntitiesQuery, self).__init__(parser)

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


class XrefQuery(Query):
    TEXT_FIELDS = ["text"]
    SORT_DEFAULT = [{"score": "desc"}]
    SORT_FIELDS = {
        "random": "random",
        "doubt": "doubt",
        "score": "_score",
    }
    AUTHZ_FIELD = "match_dataset"
    SCORE_CUTOFF = SCORE_CUTOFF
    SOURCE = XREF_SOURCE

    def __init__(self, parser, dataset=None):
        self.dataset = dataset
        parser.highlight = False
        super(XrefQuery, self).__init__(parser)

    def get_filters(self, **kwargs):
        filters = super(XrefQuery, self).get_filters(**kwargs)
        filters.append({"term": {"dataset": self.dataset}})
        sorts = [f for (f, _) in self.parser.sorts]
        if "random" not in sorts and "doubt" not in sorts:
            filters.append({"range": {"score": {"gt": self.SCORE_CUTOFF}}})
        return filters

    def get_index(self):
        return xref_index()
