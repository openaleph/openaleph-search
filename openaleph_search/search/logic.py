"""High level search interface"""

from typing import Any
from urllib.parse import parse_qsl

from elastic_transport import ObjectApiResponse

from openaleph_search.core import get_es
from openaleph_search.index.indexes import entities_read_index, schema_index
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.queries import EntitiesQuery


def make_parser(q: str | None = None, args: str | None = None) -> SearchQueryParser:
    """Build a parser object from arbitrary query string and url args"""
    if args:
        _args = parse_qsl(args, keep_blank_values=True)
    else:
        _args = []
    if q:
        _args.insert(0, ("q", q))
    return SearchQueryParser(_args)


def search_query_string(q: str, args: str | None = None) -> ObjectApiResponse:
    """Search using `query_string` with optional parser args"""
    _args = parse_qsl(args, keep_blank_values=True)
    if "q" in dict(_args):
        raise RuntimeError("Invalid query, must not contain `q` in args")
    if "highlight" not in dict(_args):
        _args.append(("highlight", "true"))
    _args.insert(0, ("q", q))
    parser = SearchQueryParser(_args)
    query = EntitiesQuery(parser)
    return query.search()


def search_body(body: dict[str, Any], index: str | None = None) -> ObjectApiResponse:
    es = get_es()
    index = index or entities_read_index()
    return es.search(index=index, body=body)


def analyze_text(
    text: str,
    field: str,
    schema: str = "LegalEntity",
    tokens_only: bool = False,
) -> ObjectApiResponse | set[str]:
    """Analyze text using field mapping for given schema.

    Args:
        text: The text to analyze
        field: Field name to use for analysis
            (e.g., "content", "text", "properties.bodyText")
        schema: Schema to use for field-based analysis
            (default: "LegalEntity")
        tokens_only: If True, return only unique token strings instead of
            full response (default: False)

    Returns:
        ObjectApiResponse with tokens information, or set of unique token
        strings if tokens_only=True
    """
    es = get_es()
    index = schema_index(schema, "v1")
    res = es.indices.analyze(index=index, field=field, text=text)

    if tokens_only:
        return {token["token"] for token in res["tokens"]}
    return res
