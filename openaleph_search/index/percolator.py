from typing import Any, Iterable

from anystore.logging import get_logger

from openaleph_search.core import get_es
from openaleph_search.index.indexer import Actions, bulk_actions, configure_index
from openaleph_search.index.mapping import Field, FieldType
from openaleph_search.index.util import index_name, index_settings, refresh_sync
from openaleph_search.model import PercolatorQuery
from openaleph_search.query.util import bool_query, field_filter_query

log = get_logger(__name__)
PERCOLATOR_VERSION = "v1"

COUNTRIES = "countries"
SCHEMATA = "schemata"


def percolator_index() -> str:
    return index_name("percolator", PERCOLATOR_VERSION)


def configure_percolator():
    """Create or update the percolator index mapping."""
    mapping = {
        "date_detection": False,
        "dynamic": False,
        "properties": {
            "query": {"type": "percolator"},
            Field.CONTENT: {**FieldType.CONTENT},
            "names": {**FieldType.KEYWORD},
            COUNTRIES: {**FieldType.KEYWORD},
            SCHEMATA: {**FieldType.KEYWORD},
        },
    }
    settings_ = index_settings(shards=1)
    return configure_index(percolator_index(), mapping, settings_)


def bulk_index_queries(items: Iterable[PercolatorQuery], sync: bool = False):
    """Bulk upsert percolator docs from PercolatorQuery objects.

    Each item becomes a percolator doc with:
    - _id = key
    - query = bool.should of match_phrase clauses for each name variant
    - names, countries, schemata = stored metadata for filtering
    """

    def _actions() -> Actions:
        for item in items:
            query = bool_query()
            query["bool"]["minimum_should_match"] = 1
            query["bool"]["should"] = [
                {"match_phrase": {Field.CONTENT: {"query": name, "slop": 2}}}
                for name in item.names
            ]
            source: dict[str, Any] = {
                "query": query,
                "names": item.names,
            }
            if item.countries:
                source[COUNTRIES] = item.countries
            if item.schemata:
                source[SCHEMATA] = item.schemata
            yield {
                "_index": percolator_index(),
                "_id": item.key,
                "_source": source,
            }

    bulk_actions(_actions(), sync=sync)


def percolate(
    text: str,
    countries: list[str] | None = None,
    schemata: list[str] | None = None,
    size: int = 100,
) -> list[dict[str, Any]]:
    """Run a percolate query to find matching stored queries for the given text.

    Optionally filter by countries and/or schemata to only return queries that
    have matching metadata (or no metadata set for that field).

    Returns a list of hits, each containing the matched query _id and _source.
    """
    percolate_clause: dict[str, Any] = {
        "percolate": {
            "field": "query",
            "document": {Field.CONTENT: text},
        }
    }

    filters = _build_filters(countries=countries, schemata=schemata)
    if filters:
        inner = bool_query()
        inner["bool"]["must"].append(percolate_clause)
        inner["bool"]["filter"] = filters
    else:
        inner = percolate_clause

    # Wrap in constant_score to skip scoring — we only care about matches,
    # not relevance. This avoids deserializing each matching query for scoring.
    query: dict[str, Any] = {"constant_score": {"filter": inner}}

    es = get_es()
    body: dict[str, Any] = {"size": size, "query": query}
    res = es.search(index=percolator_index(), body=body)
    return res.get("hits", {}).get("hits", [])


def _build_filters(
    countries: list[str] | None = None,
    schemata: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build optional term filters for percolation.

    Each filter matches documents that either have a matching value OR have no
    value set for the field (so unscoped queries always match).
    """
    filters: list[dict[str, Any]] = []
    for field, values in ((COUNTRIES, countries), (SCHEMATA, schemata)):
        if values:
            clause = bool_query()
            clause["bool"]["minimum_should_match"] = 1
            clause["bool"]["should"].append(field_filter_query(field, values))
            clause["bool"]["should"].append(
                {"bool": {"must_not": {"exists": {"field": field}}}}
            )
            filters.append(clause)
    return filters


def delete_all_queries(sync: bool = False):
    """Clear entire percolator index."""
    es = get_es()
    es.delete_by_query(
        index=percolator_index(),
        body={"query": {"match_all": {}}},
        refresh=refresh_sync(sync),
        conflicts="proceed",
    )
