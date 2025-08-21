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


def names_query(schema: Schema, names: list[str]) -> Clauses:
    shoulds: Clauses = []
    for name in pick_names(names, limit=5):
        match = {
            Field.NAMES: {
                "query": name,
                "operator": "AND",
                "boost": 3.0,
                "fuzziness": "AUTO",
            }
        }
        shoulds.append({"match": match})
    for key in index_name_keys(schema, names):
        term = {Field.NAME_KEYS: {"value": key, "boost": 4.0}}
        shoulds.append({"term": term})
    for token in index_name_parts(schema, names):
        term = {Field.NAME_PARTS: {"value": token, "boost": 1.0}}
        shoulds.append({"term": term})
    for phoneme in phonetic_names(schema, names):
        term = {Field.NAME_PHONETIC: {"value": phoneme, "boost": 0.8}}
        shoulds.append({"term": term})
    for symbol in get_name_symbols(schema, names):
        shoulds.append({"term": {Field.NAME_SYMBOLS: symbol}})

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

    if datasets:
        query["bool"]["filter"].append({"terms": {"dataset": datasets}})

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
