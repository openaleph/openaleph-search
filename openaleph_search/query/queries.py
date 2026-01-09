import logging
from functools import cached_property
from typing import Any

from banal import ensure_list
from followthemoney import EntityProxy, model
from ftmq.util import get_name_symbols

from openaleph_search.index.entities import ENTITY_SOURCE, PROXY_INCLUDES
from openaleph_search.index.indexes import entities_read_index
from openaleph_search.index.mapping import Field
from openaleph_search.query.base import Query
from openaleph_search.query.matching import match_query
from openaleph_search.query.more_like_this import more_like_this_query
from openaleph_search.query.util import field_filter_query
from openaleph_search.settings import Settings
from openaleph_search.transform.util import index_name_keys

log = logging.getLogger(__name__)
settings = Settings()


EXCLUDE_SCHEMATA = [
    s.name for s in model.schemata.values() if s.hidden
]  # Page, Mention
EXCLUDE_DEHYDRATE = ["properties"]


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
        query = self.get_inner_query()
        if settings.query_function_score:
            return self.wrap_query_function_score(query)
        return query

    def get_inner_query(self) -> dict[str, Any]:
        return super().get_query()

    def get_query_string(self) -> dict[str, Any] | None:
        query = super().get_query_string()
        if self.schemata != ["Page"]:
            return query
        if query:
            # special case for Page (children of Pages) queries, where filter
            # syntax would not match (e.g. 'names:"Jane" foo')
            query["query_string"]["default_operator"] = "OR"
            return query

    def get_text_query(self) -> list[dict[str, Any]]:
        query = super().get_text_query()

        # Add optional name_symbols and name_keys matches if synonyms is enabled
        if self.parser.synonyms and self.parser.text:
            schema = model["LegalEntity"]
            # Extract symbols and filter only NAME category symbols
            symbols = get_name_symbols(schema, self.parser.text)
            name_symbols = [str(s) for s in symbols if s.category.name == "NAME"]
            if name_symbols:
                query.append(
                    {"terms": {Field.NAME_SYMBOLS: name_symbols, "boost": 0.5}}
                )

            # Generate name_keys from n-grams of query tokens
            # For a query like "acme corporation corruption", we want to match
            # entities with name_keys like "acmecorporation" (ACME Corporation)
            name_keys = self._get_name_keys_ngrams(schema, self.parser.text)
            if name_keys:
                query.append(
                    {"terms": {Field.NAME_KEYS: list(name_keys), "boost": 0.3}}
                )

        return query

    def _get_name_keys_ngrams(self, schema, text: str) -> set[str]:
        """Generate name_keys from n-grams of query tokens.

        For query "acme corporation corruption", generates:
        - "acmecorporation" (2-gram)
        - "acmecorporationcorruption" (3-gram)
        - "corporationcorruption" (2-gram)

        This allows matching entity names that are subsets of the query.
        We focus on 2-4 token combinations as single tokens are already
        covered by name_parts field.
        """
        from openaleph_search.transform.util import clean_tokenize_name

        tokens = clean_tokenize_name(schema, text)
        if not tokens:
            return set()

        name_keys = set()

        # Generate n-grams of length 2-4 tokens
        for start_idx in range(len(tokens)):
            for length in range(2, min(5, len(tokens) - start_idx + 1)):
                end_idx = start_idx + length
                ngram_tokens = tokens[start_idx:end_idx]

                # Pre-check: ensure combined length is reasonable before calling
                # index_name_keys. This avoids processing very short n-grams that
                # won't pass index_name_keys filter
                estimated_length = sum(len(t) for t in ngram_tokens)
                if estimated_length < 6:
                    continue

                # Join tokens with space and use index_name_keys to get the key
                # This ensures we use the same logic as the indexer
                ngram_text = " ".join(ngram_tokens)
                ngram_keys = index_name_keys(schema, [ngram_text])
                name_keys.update(ngram_keys)

        return name_keys

    def get_negative_filters(self) -> list[dict[str, Any]]:
        # exclude hidden schemata unless we explicitly want them
        filters = super().get_negative_filters()
        exclude_schemata = set(EXCLUDE_SCHEMATA) - set(self.schemata)
        filters.append(field_filter_query("schema", exclude_schemata))
        return filters

    def get_index_weight_functions(self) -> list[dict[str, Any]]:
        """Generate index weight functions based on index bucket settings"""
        functions = []

        # Map bucket names to their boost settings
        bucket_boosts = {
            "pages": settings.index_boost_pages,
            "documents": settings.index_boost_documents,
            "intervals": settings.index_boost_intervals,
            "things": settings.index_boost_things,
        }

        # Create boost functions for each bucket with non-default boost
        for bucket_name, boost_value in bucket_boosts.items():
            if boost_value != 1:  # Only add function if boost differs from default
                functions.append(
                    {
                        "filter": {"wildcard": {"_index": f"*entity-{bucket_name}*"}},
                        "weight": boost_value,
                    }
                )

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

    def get_source(self) -> dict[str, Any]:
        """If the parser gets `dehydrate=true`, don't include properties payload
        in the response. This is used in the search views where no detail data
        is needed.

        The `include_fields` parameter can be used to add specific fields back even
        when dehydrating (e.g. `include_fields=properties.startDate` or
        `include_fields=emails`).
        """
        if self.parser.dehydrate:
            includes = [k for k in PROXY_INCLUDES if k not in EXCLUDE_DEHYDRATE]
            # Add any explicitly requested fields
            if self.parser.include_fields:
                includes.extend(self.parser.include_fields)
            return {"includes": includes}
        return super().get_source()


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
        # Attempt to find only matches within the "matchable" set of entity
        # schemata. In practice this should always return the "things" index.
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
