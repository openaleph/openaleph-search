"""High level search interface"""

from urllib.parse import parse_qsl

from elastic_transport import ObjectApiResponse

from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.queries import EntitiesQuery


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
