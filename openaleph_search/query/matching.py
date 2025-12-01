import logging
from typing import Any, TypeAlias

from followthemoney import EntityProxy, Schema
from followthemoney.types import registry
from ftmq.util import get_name_symbols
from rigour.text import levenshtein

from openaleph_search.index.mapping import Field, property_field_name
from openaleph_search.query.util import BoolQuery, bool_query, none_query
from openaleph_search.transform.util import (
    index_name_keys,
    index_name_parts,
    phonetic_names,
    preprocess_name,
)

log = logging.getLogger(__name__)
Clauses: TypeAlias = list[dict[str, Any]]
MATCH_GROUPS = [
    registry.ip.group,
    registry.url.group,
    registry.email.group,
    registry.phone.group,
]
MAX_CLAUSES = 500


def pick_names(names: list[str], limit: int = 3) -> list[str]:
    """Try to pick a few non-overlapping names to search for when matching
    an entity. The problem here is that if we receive an API query for an
    entity with hundreds of aliases, it becomes prohibitively expensive to
    search. This function decides which ones should be queried as pars pro
    toto in the index before the Python comparison algo later checks all of
    them.

    This is a bit over the top and will come back to haunt us."""
    if len(names) <= limit:
        return names
    picked: list[str] = []
    processed_ = [preprocess_name(n) for n in names]
    names = [n for n in processed_ if n is not None]

    # Centroid:
    picked_name = registry.name.pick(names)
    if picked_name is not None:
        picked.append(picked_name)

    # Pick the least similar:
    for _ in range(1, limit):
        candidates: dict[str, int] = {}
        for cand in names:
            if cand in picked:
                continue
            candidates[cand] = 0
            for pick in picked:
                candidates[cand] += levenshtein(pick, cand)

        if not len(candidates):
            break
        pick, _ = sorted(candidates.items(), key=lambda c: c[1], reverse=True)[0]
        picked.append(pick)

    return picked


def _min_should_match_script(minimum: int = 2) -> dict[str, str]:
    """Generate a script for minimum_should_match in terms_set queries."""
    return {"source": f"Math.min({minimum}, params.num_terms)"}


def names_query(schema: Schema, names: list[str]) -> Clauses:
    """Build name matching clauses for scoring similar entities.

    Uses specialized name fields for matching:
    - names: exact name match with order preserved (highest boost)
    - name_keys: normalized match, order-independent (sorted ASCII tokens)
    - name_parts: partial token overlap (requires 2+ matching tokens)
    - name_phonetic: spelling/transliteration variants
    - name_symbols: synonyms, nicknames, company suffixes
    """
    shoulds: Clauses = []

    # 1. names: exact match with order preserved (keyword field with normalizer)
    # "Jane Doe" scores higher than "Doe Jane" for a query of "Jane Doe"
    picked = pick_names(names, limit=5)
    if picked:
        shoulds.append({"terms": {Field.NAMES: picked, "boost": 5.0}})

    # 2. name_keys: normalized match (order-independent)
    # "Jane Doe" and "Doe Jane" both become "doejane"
    keys = list(index_name_keys(schema, names))
    if keys:
        shoulds.append({"terms": {Field.NAME_KEYS: keys, "boost": 3.0}})

    # 3. name_parts: partial token overlap (requires 2+ matching tokens)
    parts = list(index_name_parts(schema, names))
    if parts:
        shoulds.append(
            {
                "terms_set": {
                    Field.NAME_PARTS: {
                        "terms": parts,
                        "minimum_should_match_script": _min_should_match_script(2),
                        "boost": 1.0,
                    }
                }
            }
        )

    # 4. name_phonetic: spelling/transliteration variants
    phonetics = list(phonetic_names(schema, names))
    if phonetics:
        shoulds.append(
            {
                "terms_set": {
                    Field.NAME_PHONETIC: {
                        "terms": phonetics,
                        "minimum_should_match_script": _min_should_match_script(2),
                        "boost": 0.8,
                    }
                }
            }
        )

    # 5. name_symbols: synonyms, nicknames, company suffixes
    symbols = [str(s) for s in get_name_symbols(schema, *names)]
    if symbols:
        shoulds.append(
            {
                "terms_set": {
                    Field.NAME_SYMBOLS: {
                        "terms": symbols,
                        "minimum_should_match_script": _min_should_match_script(2),
                        "boost": 0.8,
                    }
                }
            }
        )

    return shoulds


def identifiers_query(entity: EntityProxy) -> Clauses:
    shoulds: Clauses = []
    for prop, value in entity.itervalues():
        if prop.type.group == registry.identifier.group:
            term = {property_field_name(prop.name): {"value": value, "boost": 3.0}}
            shoulds.append({"term": term})
    return shoulds


def match_query(
    entity: EntityProxy,
    datasets: list[str] | None = None,
    collection_ids: list[str] | None = None,
    query: BoolQuery | None = None,
):
    """Given a matchable entity in indexed form, build a query that will find
    similar entities based on a variety of criteria. For other entities with
    more full text (e.g. documents), there is a "more_like_this" query in the
    `similar.py` query module"""

    if not entity.schema.matchable:
        return none_query()

    if query is None:
        query = bool_query()

    # Don't match the query entity
    must_not = []
    if entity.id is not None:
        must_not.append({"ids": {"values": [entity.id]}})
    if len(must_not):
        query["bool"]["must_not"].extend(must_not)

    # Only matchable schemata:
    schemata = [s.name for s in entity.schema.matchable_schemata]
    query["bool"]["filter"].append({"terms": {Field.SCHEMA: schemata}})

    if collection_ids:
        query["bool"]["filter"].append({"terms": {Field.COLLECTION_ID: collection_ids}})
    elif datasets:
        query["bool"]["filter"].append({"terms": {Field.DATASET: datasets}})

    # match on magic names
    names = entity.get_type_values(registry.name, matchable=True)
    names_lookup = names_query(entity.schema, names)
    if names_lookup:
        query["bool"]["must"].append(
            {"bool": {"should": names_lookup, "minimum_should_match": 1}}
        )

    # match on identifiers
    identifiers_lookup = identifiers_query(entity)
    if identifiers_lookup:
        query["bool"]["must"].append(
            {"bool": {"should": identifiers_lookup, "minimum_should_match": 0}}
        )

    # num clauses so far, if we have nothing, not useful to match at all
    num_clauses = len(names_lookup) + len(identifiers_lookup)
    if not num_clauses:
        return none_query()

    # match on other useful properties, sorted by specificity
    filters = set()
    for prop, value in entity.itervalues():
        specificity = prop.specificity(value)
        if specificity > 0:
            filters.add((prop.type, value, specificity))
    filters = sorted(filters, key=lambda p: p[2], reverse=True)
    groups = []
    for type_, value, _ in filters:
        if type_.group in MATCH_GROUPS and num_clauses <= MAX_CLAUSES:
            groups.append({"term": {type_.group: {"value": value, "boost": 2.0}}})
            num_clauses += 1

    scoring = []
    for type_, value, _ in filters:
        if type_.group not in MATCH_GROUPS and num_clauses <= MAX_CLAUSES:
            scoring.append({"term": {type_.group: {"value": value}}})
            num_clauses += 1

    query["bool"]["should"].extend(groups)
    query["bool"]["should"].extend(scoring)

    return query


def blocking_query(
    entity: EntityProxy,
    datasets: list[str] | None = None,
    collection_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build an efficient blocking query for candidate retrieval.

    This query is optimized for speed, not scoring. It uses filter context
    (no scoring, cacheable) and minimal blocking keys to find potential
    duplicates. Use this for bulk clustering operations where candidates
    will be scored separately (e.g., with nomenklatura.compare()).

    Blocking strategy:
    - name_keys: exact match on sorted ASCII tokens (high precision)
    - name_phonetic: phonetic match for spelling variants (high recall)
    - name_symbols: WikiData name IDs, nicknames, company suffixes (synonyms)
    - identifiers: exact match on tax IDs, registration numbers, etc.
    """
    if not entity.schema.matchable:
        return {"match_none": {}}

    names = entity.get_type_values(registry.name, matchable=True)
    if not names:
        return {"match_none": {}}

    # Build blocking keys
    name_keys = list(index_name_keys(entity.schema, names))
    phonetics = list(phonetic_names(entity.schema, names))
    symbols = [str(s) for s in get_name_symbols(entity.schema, *names)]

    # Collect identifiers (tax IDs, registration numbers, etc.)
    identifiers: list[str] = []
    identifier_field: str | None = None
    for prop, value in entity.itervalues():
        if prop.type.group == registry.identifier.group:
            identifiers.append(value)
            # All identifiers go to the same group field
            if identifier_field is None:
                identifier_field = prop.type.group

    # Build blocking filter: must match at least one blocking key
    blocking_shoulds: list[dict[str, Any]] = []
    if name_keys:
        blocking_shoulds.append({"terms": {Field.NAME_KEYS: name_keys}})
    if phonetics:
        blocking_shoulds.append({"terms": {Field.NAME_PHONETIC: phonetics}})
    if symbols:
        blocking_shoulds.append({"terms": {Field.NAME_SYMBOLS: symbols}})
    if identifiers and identifier_field:
        blocking_shoulds.append({"terms": {identifier_field: identifiers}})

    if not blocking_shoulds:
        return {"match_none": {}}

    # Build the query using filter context (no scoring, cacheable)
    filters: list[dict[str, Any]] = [
        # Schema filter
        {"terms": {Field.SCHEMA: [s.name for s in entity.schema.matchable_schemata]}},
        # Blocking filter: OR of blocking keys
        {"bool": {"should": blocking_shoulds, "minimum_should_match": 1}},
    ]

    # Dataset/collection filter
    if collection_ids:
        filters.append({"terms": {Field.COLLECTION_ID: collection_ids}})
    elif datasets:
        filters.append({"terms": {Field.DATASET: datasets}})

    # Exclude self
    must_not: list[dict[str, Any]] = []
    if entity.id is not None:
        must_not.append({"ids": {"values": [entity.id]}})

    return {
        "bool": {
            "filter": filters,
            "must_not": must_not,
        }
    }
