from typing import Iterable

from anystore.types import SDict
from banal import ensure_list, is_mapping


def bool_query() -> SDict:
    return {"bool": {"should": [], "filter": [], "must": [], "must_not": []}}


def none_query(query: SDict | None = None) -> SDict:
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
        field = "fingerprints"
    if len(values) == 1:
        # if field in ['addresses']:
        #     field = '%s.text' % field
        #     return {'match_phrase': {field: values[0]}}
        return {"term": {field: values[0]}}
    return {"terms": {field: values}}


def range_filter_query(field: str, ops) -> SDict:
    return {"range": {field: ops}}


def filter_text(spec, invert=False):
    """Try to convert a given filter to a lucene query string."""
    # CAVEAT: This doesn't cover all filters used by aleph.
    if isinstance(spec, (list, tuple, set)):
        parts = [filter_text(s, invert=invert) for s in spec]
        return " ".join(parts)
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
            text = predicate.join(parts)
            if len(parts) > 1:
                text = "(%s)" % text
            return text
        if op == "exists":
            field = props.get("field")
            field = "-%s" % field if invert else field
            return "%s:*" % field


def datasets_query(
    datasets: list[str], field="collection_id", auth_is_admin: bool | None = False
):
    """Generate a search query filter for the given datasets."""
    # Hot-wire authorization entirely for admins.
    if auth_is_admin:
        return {"match_all": {}}
    if not len(datasets):
        return {"match_none": {}}
    return {"terms": {field: datasets}}
