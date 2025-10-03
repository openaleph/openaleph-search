"""High level search interface"""

from typing import Any
from urllib.parse import parse_qsl

from elastic_transport import ObjectApiResponse

from openaleph_search.core import get_es
from openaleph_search.index.indexes import entities_read_index
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
