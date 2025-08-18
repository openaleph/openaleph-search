import logging

from banal import ensure_list

from openaleph_search.index.entities import ENTITY_SOURCE
from openaleph_search.index.indexes import entities_read_index
from openaleph_search.index.xref import XREF_SOURCE, xref_index
from openaleph_search.query.base import Query
from openaleph_search.search.matching import match_query

log = logging.getLogger(__name__)

SCORE_CUTOFF = 0.5


class EntitiesQuery(Query):
    TEXT_FIELDS = ["fingerprints^3", "text"]
    PREFIX_FIELD = "fingerprints"
    HIGHLIGHT_FIELD = "properties.*"
    SKIP_FILTERS = ["schema", "schemata"]
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


class MatchQuery(EntitiesQuery):
    """Given an entity, find the most similar other entities."""

    def __init__(self, parser, entity=None, exclude=None, collection_ids=None):
        self.entity = entity
        self.exclude = ensure_list(exclude)
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

    def get_query(self):
        query = super(MatchQuery, self).get_query()
        query = match_query(
            self.entity, collection_ids=self.collection_ids, query=query
        )
        if len(self.exclude):
            exclude = {"ids": {"values": self.exclude}}
            query["bool"]["must_not"].append(exclude)
        return query


class GeoDistanceQuery(EntitiesQuery):
    """Given an Address entity, find the nearby Address entities via the
    geo_point field"""

    def __init__(self, parser, entity=None, exclude=None, collection_ids=None):
        self.entity = entity
        self.exclude = ensure_list(exclude)
        self.collection_ids = collection_ids
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
    AUTHZ_FIELD = "match_collection_id"
    SCORE_CUTOFF = SCORE_CUTOFF
    SOURCE = XREF_SOURCE

    def __init__(self, parser, collection_id=None):
        self.collection_id = collection_id
        parser.highlight = False
        super(XrefQuery, self).__init__(parser)

    def get_filters(self, **kwargs):
        filters = super(XrefQuery, self).get_filters(**kwargs)
        filters.append({"term": {"collection_id": self.collection_id}})
        sorts = [f for (f, _) in self.parser.sorts]
        if "random" not in sorts and "doubt" not in sorts:
            filters.append({"range": {"score": {"gt": self.SCORE_CUTOFF}}})
        return filters

    def get_index(self):
        return xref_index()
