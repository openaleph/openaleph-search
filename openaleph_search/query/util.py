from typing import Any, Iterable, TypedDict

from anystore.types import SDict
from banal import ensure_list, is_mapping

from openaleph_search.mapping import Field


class Bools(TypedDict):
    should: list[Any]
    filter: list[Any]
    must: list[Any]
    must_not: list[Any]


class BoolQuery(TypedDict):
    bool: Bools


def bool_query() -> BoolQuery:
    return {"bool": {"should": [], "filter": [], "must": [], "must_not": []}}


def none_query(query: BoolQuery | None = None) -> BoolQuery:
    if query is None:
        query = bool_query()
    query["bool"]["must"].append({"match_none": {}})
    return query


def field_filter_query(field: str, values: str | Iterable[str]) -> SDict:
    """Need to define work-around for full-text fields."""
    values = ensure_list(values)
    if not len(values):
        return {"match_all": {}}
    if field in ["_id", "id"]:
        return {"ids": {"values": values}}
    if field in ["names"]:
        field = Field.NAME_PARTS
    if len(values) == 1:
        # if field in ['addresses']:
        #     field = '%s.text' % field
        #     return {'match_phrase': {field: values[0]}}
        return {"term": {field: values[0]}}
    return {"terms": {field: values}}


def range_filter_query(field: str, ops: dict[str, Any]) -> SDict:
    return {"range": {field: ops}}


def filter_text(spec: Any, invert: bool = False) -> str | None:
    """Try to convert a given filter to a lucene query string."""
    # CAVEAT: This doesn't cover all filters used by aleph.
    if isinstance(spec, (list, tuple, set)):
        parts = [filter_text(s, invert=invert) for s in spec]
        return " ".join(p for p in parts if p)
    if not is_mapping(spec):
        return spec
    for op, props in spec.items():
        if op == "term":
            field, value = next(iter(props.items()))
            field = "-%s" % field if invert else field
            return '%s:"%s"' % (field, value)
        if op == "terms":
            field, values = next(iter(props.items()))
            parts = [{"term": {field: v}} for v in values]
            parts = [filter_text(p, invert=invert) for p in parts]
            predicate = " AND " if invert else " OR "
            text = predicate.join(p for p in parts if p)
            if len(parts) > 1:
                text = "(%s)" % text
            return text
        if op == "exists":
            field = props.get("field")
            field = "-%s" % field if invert else field
            return "%s:*" % field
    return None


DEFAULT_AUTHZ_FIELD = Field.DATASET


def auth_datasets_query(
    datasets: list[str], field: str = DEFAULT_AUTHZ_FIELD, is_admin: bool | None = False
) -> dict[str, Any]:
    """Generate a search query filter for the given datasets."""
    # Hot-wire authorization entirely for admins.
    if is_admin:
        return {"match_all": {}}
    if not len(datasets):
        return {"match_none": {}}
    return {"terms": {field: datasets}}
