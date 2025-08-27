from functools import cached_property
from typing import Any, Iterator, cast

from anystore.logging import get_logger
from banal import as_bool
from followthemoney.util import sanitize_text
from werkzeug.datastructures import MultiDict, OrderedMultiDict

from openaleph_search.index.mapping import Field
from openaleph_search.model import SearchAuth
from openaleph_search.settings import MAX_PAGE, Settings
from openaleph_search.util import valid_dataset

settings = Settings()
log = get_logger(__name__)


class QueryParser:
    """Hold state for common query parameters."""

    SORT_ASC = "asc"
    SORT_DESC = "desc"
    SORT_DEFAULT = SORT_ASC
    SORTS = [SORT_ASC, SORT_DESC]

    def __init__(
        self,
        args: MultiDict | dict[str, Any],
        auth: SearchAuth | None = None,
        limit: int | None = None,
        max_limit: int | None = MAX_PAGE,
    ):
        if self.settings.search_auth and auth is None:
            raise RuntimeError("An auth object is required.")

        if not isinstance(args, MultiDict):
            args = OrderedMultiDict(args)
        self.args: MultiDict = cast(MultiDict, args)
        self.auth = auth
        self.offset = max(0, self.getint("offset", 0) or 0)
        if limit is None:
            limit = min(max_limit or MAX_PAGE, max(0, self.getint("limit", 20) or 20))
        self.limit = limit
        self.next_limit = self.getint("next_limit", limit)
        self.text = sanitize_text(self.get("q"))
        self.prefix = sanitize_text(self.get("prefix"))

        self.filters = self.prefixed_items("filter:")
        self.excludes = self.prefixed_items("exclude:")
        self.empties = self.prefixed_items("empty:")

    @property
    def page(self) -> int:
        if self.limit == 0:
            return 1
        return (self.offset // self.limit) + 1

    def prefixed_items(self, prefix: str) -> dict[str, set[str]]:
        items = {}
        for key in self.args.keys():
            if not key.startswith(prefix):
                continue
            name = key[len(prefix) :]
            items[name] = set(self.getlist(key))
        return items

    @property
    def sorts(self) -> list[tuple[str, str]]:
        sort = []
        for value in self.getlist("sort"):
            direction = self.SORT_DEFAULT
            if ":" in value:
                value, direction = value.rsplit(":", 1)
            if direction in self.SORTS:
                sort.append((value, direction))
        return sort

    @property
    def items(self) -> Iterator[tuple[str, str]]:
        for key, value in self.args.items(multi=True):
            if key in ("offset", "limit", "next_limit"):
                continue
            value = sanitize_text(value, encoding="utf-8")
            if value is not None:
                yield key, value

    def getlist(self, name: str, default: list[str] | None = None) -> list[str]:
        values = []
        for value in self.args.getlist(name):
            value = sanitize_text(value, encoding="utf-8")
            if value is not None:
                values.append(value)
        return values or (default or [])

    def get(self, name: str, default: str | None = None) -> str | None:
        for value in self.getlist(name):
            return value
        return default

    def getintlist(self, name: str, default: list[str] | None = None) -> list[int]:
        values = []
        for value in self.getlist(name, default=default):
            try:
                values.append(int(value))
            except (ValueError, TypeError):
                pass
        return values

    def getint(self, name: str, default: int | None = None) -> int | None:
        for value in self.getintlist(name):
            return value
        return default

    def getbool(self, name: str, default: bool = False) -> bool:
        return as_bool(self.get(name), default=default)

    def to_dict(self) -> dict[str, Any]:
        parser = {
            "text": self.text,
            "prefix": self.prefix,
            "offset": self.offset,
            "limit": self.limit,
            "filters": {key: list(val) for key, val in self.filters.items()},
            "sorts": self.sorts,
            "empties": {key: list(val) for key, val in self.empties.items()},
            "excludes": {key: list(val) for key, val in self.excludes.items()},
        }
        return parser

    @property
    def settings(self) -> Settings:
        # useful for test runtime to patch env vars
        if settings.testing:
            return Settings()
        return settings


class SearchQueryParser(QueryParser):
    """ElasticSearch-specific query parameters."""

    # Facets with known, limited cardinality:
    SMALL_FACETS = ("schema", "schemata", "dataset", "countries", "languages")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super(SearchQueryParser, self).__init__(*args, **kwargs)
        self.offset = min(MAX_PAGE, self.offset)
        if (self.limit + self.offset) > MAX_PAGE:
            self.limit = max(0, MAX_PAGE - self.offset)

        # Set of field names to facet by (i.e. include the count of distinct
        # values in the result set). These must match 'keyword' fields in the
        # index.
        self.facet_names = set(self.getlist("facet"))

        # Set of field names to use significant terms aggregation for
        self.facet_significant_names = set(self.getlist("facet_significant"))

        # Query to use for highlighting, defaults to the search query
        if self.get("highlight_text"):
            raise RuntimeError("Custom highlight text not supported")
        self.highlight_text = self.text
        # self.highlight_text = self.get("highlight_text", self.text)
        # Include highlighted fragments of matching text in the result.
        self.highlight = self.getbool("highlight", False)
        # self.highlight = self.highlight and self.highlight_text
        # Length of each snippet in characters
        if self.get("highlight_length"):
            raise RuntimeError("Custom highlight length not supported")
        self.highlight_length = 200
        # Number of snippets per document, 0 = return full document text.
        self.highlight_count = self.getint("highlight_count", 3)
        # By default, the maximum number of characters analyzed for a highlight
        # request is bounded by the value defined in the
        # index.highlight.max_analyzed_offset setting (1000000 by default),
        # and when the number of characters exceeds this limit an error is
        # returned. By setting `max_analyzed_offset` to a non-negative value
        # lower than `index.highlight.max_analyzed_offset`, the highlighting
        # stops at this defined maximum limit, and the rest of the text is not
        # processed, thus not highlighted and no error is returned.
        self.max_highlight_analyzed_offset = self.getint(
            "max_highlight_analyzed_offset", 999999
        )

    @cached_property
    def collection_ids(self) -> set[str]:
        collections = self.filters.get("collection_id", set())
        collections.update(self.filters.get("collections", set()))
        if self.auth and not self.auth.is_admin:
            collections = collections & set(self.auth.collection_ids)
        return collections

    @cached_property
    def datasets(self) -> set[str]:
        datasets = self.filters.get("dataset", set())
        datasets.update(self.filters.get("datasets", set()))
        if self.auth and not self.auth.is_admin:
            datasets = datasets & set(self.auth.datasets)
        return {valid_dataset(d) for d in datasets}

    @cached_property
    def routing_key(self) -> str | None:
        # get dataset routing if dataset filter is set
        if self.collection_ids:
            return ",".join(sorted(self.collection_ids))
        if self.datasets:
            return ",".join(sorted(self.datasets))

    def get_facet_size(self, name: str) -> int:
        """Number of distinct values to be included (i.e. top N)."""
        facet_size = self.getint("facet_size:%s" % name, 20) or 20
        # Added to mitigate a DDoS by scripted facet bots (2020-11-24):
        if self.auth:
            if not self.auth.logged_in and name not in self.SMALL_FACETS:
                facet_size = min(50, facet_size)
        return facet_size

    def get_facet_total(self, name: str) -> bool:
        """Flag to perform a count of the total number of distinct values."""
        if self.auth:
            if not self.auth.logged_in and name not in self.SMALL_FACETS:
                return False
        return self.getbool("facet_total:%s" % name, False)

    def get_facet_values(self, name: str) -> bool:
        """Flag to disable returning actual values (i.e. count only)."""
        # Added to mitigate a DDoS by scripted facet bots (2020-11-24):
        if self.get_facet_size(name) == 0:
            return False
        return self.getbool("facet_values:%s" % name, True)

    def get_facet_type(self, name: str) -> str | None:
        return self.get("facet_type:%s" % name)

    def get_facet_interval(self, name: str) -> str | None:
        """Interval to facet on when faceting on date properties

        See https://www.elastic.co/guide/en/elasticsearch/reference/current/search-aggregations-bucket-datehistogram-aggregation.html#calendar_intervals   # noqa: B950
        for available options for possible values
        """
        return self.get("facet_interval:%s" % name)

    def get_facet_significant(self, name: str) -> bool:
        """Flag to use significant terms aggregation for a facet."""
        return name in self.facet_significant_names

    def get_facet_significant_size(self, name: str) -> int:
        """Number of distinct values to be included for significant terms (i.e. top N)."""
        facet_size = self.getint("facet_significant_size:%s" % name, 20) or 20
        # Added to mitigate a DDoS by scripted facet bots (2020-11-24):
        if self.auth:
            if not self.auth.logged_in and name not in self.SMALL_FACETS:
                facet_size = min(50, facet_size)
        return facet_size

    def get_facet_significant_total(self, name: str) -> bool:
        """Flag to perform a count of the total number of distinct values for
        significant terms."""
        if self.auth:
            if not self.auth.logged_in and name not in self.SMALL_FACETS:
                return False
        return self.getbool("facet_significant_total:%s" % name, False)

    def get_facet_significant_values(self, name: str) -> bool:
        """Flag to disable returning actual values for significant terms (i.e. count only)."""
        # Added to mitigate a DDoS by scripted facet bots (2020-11-24):
        if self.get_facet_significant_size(name) == 0:
            return False
        return self.getbool("facet_significant_values:%s" % name, True)

    def get_facet_significant_type(self, name: str) -> str | None:
        return self.get("facet_significant_type:%s" % name)

    def get_facet_significant_text(self) -> str | None:
        """Field to use for significant text aggregation, or None if not specified."""
        field = self.get("facet_significant_text")
        return field or Field.CONTENT if field is not None else None

    def get_facet_significant_text_size(self) -> int:
        """Number of significant text terms to return."""
        return self.getint("facet_significant_text_size", 5) or 5

    def get_facet_significant_text_min_doc_count(self) -> int:
        """Minimum document count for significant text terms."""
        return self.getint("facet_significant_text_min_doc_count", 5) or 5

    def get_facet_significant_text_shard_size(self) -> int:
        """Shard size for significant text aggregation."""
        return self.getint("facet_significant_text_shard_size", 200) or 200

    def to_dict(self) -> dict[str, Any]:
        parser = super().to_dict()
        parser["facet_names"] = list(self.facet_names)
        parser["facet_significant_names"] = list(self.facet_significant_names)
        return parser
