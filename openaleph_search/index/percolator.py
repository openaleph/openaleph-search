import re
from typing import Any, Iterable, Iterator

from anystore.logging import get_logger
from anystore.types import SDict
from anystore.util import clean_dict
from elastic_transport import ObjectApiResponse

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
SURFACE_FORMS = "surface_forms"

_MARK_RE = re.compile(r"<mark>(.*?)</mark>", re.DOTALL)


def _extract_surface_forms(highlight: dict[str, list[str]] | None) -> list[str]:
    """Pull <mark>…</mark> spans from a hit's highlight block, deduped."""
    if not highlight:
        return []
    return sorted(
        {
            match
            for fragment in highlight.get(Field.CONTENT, [])
            for match in _MARK_RE.findall(fragment)
        }
    )


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
            query = clean_dict(query)
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


def unpack_percolation_result(res: ObjectApiResponse) -> SDict:
    data = dict(res)
    hits = data.get("hits", {}).get("hits", [])
    if not hits:
        return data
    data["hits"] = data.pop("hits", {})
    data["hits"]["hits"] = []
    for hit in hits:
        hit.pop("_score", None)
        source = hit.get("_source", {})
        new_source: dict[str, Any] = {
            SURFACE_FORMS: _extract_surface_forms(hit.pop("highlight", None)),
        }
        if source.get(COUNTRIES):
            new_source[COUNTRIES] = source[COUNTRIES]
        if source.get(SCHEMATA):
            new_source[SCHEMATA] = source[SCHEMATA]
        hit["_source"] = new_source
        data["hits"]["hits"].append(hit)
    return data


def percolate(
    text: str,
    countries: list[str] | None = None,
    schemata: list[str] | None = None,
    size: int = 100,
) -> SDict:
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
    body: dict[str, Any] = {
        "size": size,
        "query": query,
        "highlight": {
            "pre_tags": ["<mark>"],
            "post_tags": ["</mark>"],
            "fields": {
                Field.CONTENT: {"number_of_fragments": 0},
            },
        },
    }
    res = es.search(index=percolator_index(), body=body)
    return unpack_percolation_result(res)


def resolve_percolation(res: ObjectApiResponse) -> Iterator[SDict]:
    for hit in res.get("hits", {}).get("hits", []):
        names = hit.get("_source", {}).get("names", [])
        if names:
            # search entities schemata=LegalEntity and names=names
            yield


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
