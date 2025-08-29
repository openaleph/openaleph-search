import logging

from followthemoney import EntityProxy

from openaleph_search.index.mapping import Field
from openaleph_search.query.util import BoolQuery, bool_query, none_query

log = logging.getLogger(__name__)


def more_like_this_query(
    entity: EntityProxy,
    datasets: list[str] | None = None,
    collection_ids: list[str] | None = None,
    query: BoolQuery | None = None,
    parser=None,
) -> BoolQuery:
    """Given an entity, build a more_like_this query that will find
    similar documents/pages based on text content using the entity's
    document ID in elasticsearch."""

    if not entity.id:
        return none_query()

    if query is None:
        query = bool_query()

    # Don't match the query entity itself
    must_not = []
    if entity.id is not None:
        must_not.append({"ids": {"values": [entity.id]}})
    if len(must_not):
        query["bool"]["must_not"].extend(must_not)

    # Apply dataset/collection filters
    if collection_ids:
        query["bool"]["filter"].append({"terms": {"collection_id": collection_ids}})
    elif datasets:
        query["bool"]["filter"].append({"terms": {"dataset": datasets}})

    # Get configurable parameters from parser, with sensible defaults
    min_doc_freq = 2
    minimum_should_match = "20%"
    min_term_freq = 2
    max_query_terms = 50

    if parser is not None:
        min_doc_freq = parser.get_mlt_min_doc_freq()
        minimum_should_match = parser.get_mlt_minimum_should_match()
        min_term_freq = parser.get_mlt_min_term_freq()
        max_query_terms = parser.get_mlt_max_query_terms()

    # Build the more_like_this query using document ID
    mlt_query = {
        "more_like_this": {
            "fields": [Field.CONTENT, Field.TEXT, Field.NAME, Field.NAMES],
            "like": [{"_id": entity.id}],
            "min_term_freq": min_term_freq,
            "max_query_terms": max_query_terms,
            "min_doc_freq": min_doc_freq,
            "minimum_should_match": minimum_should_match,
        }
    }

    # Add the more_like_this query to the main query
    query["bool"]["must"].append(mlt_query)

    # exclude Page entities
    query["bool"]["must_not"].append({"term": {"schema": "Page"}})

    return query
