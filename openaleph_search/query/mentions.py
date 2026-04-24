"""Mentions queries — find Documents that mention named entities.

Two variants share a common base (`_Mentions`):

- **`MentionsQuery(parser, entity_id)`** — given one entity id, return
  Documents that mention that entity. Inverse of `PercolatorQuery`.
- **`MultiMentionsQuery(parser, source_parser)`** — given a filter on
  any entity set (one or many collections, narrowed by property
  filters), collect the matching entities' names and return Documents
  that mention **any** of them.

Both build the same mention-clause shape — phrase-match on CONTENT +
TEXT, `terms` on `Field.NAMES` for structured mentions, optional
synonym expansion under `parser.synonyms=true` — the only difference
is how `self.names` is populated (one entity's matchable names vs. a
scroll-and-collect over a filtered entity set).

Scale (MultiMentionsQuery only): supports up to `MAX_SOURCE_NAMES`
collected names (10k). Larger sets raise `ValueError`.
"""

from functools import cached_property
from typing import Any

from followthemoney import model
from followthemoney.types import registry

from openaleph_search.core import get_es
from openaleph_search.index.indexes import entities_read_index
from openaleph_search.index.mapping import Field
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.queries import EntitiesQuery
from openaleph_search.query.util import bool_query, none_query
from openaleph_search.transform.util import index_name_keys
from openaleph_search.util import SchemaType

# --- source-name collection (MultiMentionsQuery only) ---------------------

MAX_SOURCE_NAMES = 10_000
SCROLL_PAGE_SIZE = 500
SCROLL_KEEPALIVE = "2m"
# Which name-typed properties to pull from the source-side scroll.
SOURCE_NAME_PROPS: tuple[str, ...] = ("name",)


def collect_source_names(
    parser: SearchQueryParser,
    *,
    max_names: int = MAX_SOURCE_NAMES,
) -> list[str]:
    """Scroll the source-side filter and return deduped matchable names.

    Reads only the configured name-typed property arrays from `_source`
    (no full-proxy load). Dataset ACL applies via the parser's auth;
    the source parser can filter across one or many collections.
    Raises `ValueError` if the filter yields more than `max_names`.
    """
    query = EntitiesQuery(parser)
    es = get_es()
    names: set[str] = set()
    index = query.get_index()
    source_query = query.get_query()

    # Short-circuit before the scroll: every entity contributes ≥1 name, so
    # if the filter matches more entities than the name budget we can bail
    # out immediately. `es.count` is near-free (single integer from shard
    # metadata after applying filters); `track_total_hits` with an integer
    # bound isn't allowed inside a scroll context, so a separate count call
    # is the right shape here.
    total = es.count(index=index, body={"query": source_query}).get("count", 0)
    if total > max_names:
        raise ValueError(
            f"Source filter matched {total} entities "
            f"(> {max_names} names budget). Narrow the source filter."
        )

    body = {
        "query": source_query,
        "_source": {
            "includes": [f"properties.{p}" for p in SOURCE_NAME_PROPS],
        },
        "size": SCROLL_PAGE_SIZE,
        "sort": ["_doc"],  # cheapest scroll order
    }
    resp = es.search(index=index, body=body, scroll=SCROLL_KEEPALIVE)
    try:
        while resp["hits"]["hits"]:
            for hit in resp["hits"]["hits"]:
                props = (hit.get("_source") or {}).get("properties", {}) or {}
                for prop in SOURCE_NAME_PROPS:
                    names.update(props.get(prop) or [])
                    # Multi-valued `name` arrays are common (FtM Persons
                    # often carry several variants: "Jane Doe", "Doe,
                    # Jane", "J. Doe", …). The deduped name set routinely
                    # grows faster than the entity count, so this
                    # per-hit check is the primary budget enforcement —
                    # the entity-count short-circuit above is only a
                    # fast upper-bound gate.
                    if len(names) > max_names:
                        raise ValueError(
                            f"Source filter yielded > {max_names} names. "
                            "Narrow the source filter."
                        )
            scroll_id = resp.get("_scroll_id")
            if not scroll_id:
                break
            resp = es.scroll(scroll_id=scroll_id, scroll=SCROLL_KEEPALIVE)
    finally:
        scroll_id = resp.get("_scroll_id")
        if scroll_id:
            try:
                es.clear_scroll(scroll_id=scroll_id)
            except Exception:
                pass
    return sorted(names)


# --- shared helpers -------------------------------------------------------


def name_phrase_shoulds(names: list[str]) -> list[dict[str, Any]]:
    """Per-name phrase clauses on Field.CONTENT only.

    Shared by `MentionsQuery` and `MultiMentionsQuery`. `Field.CONTENT`
    is the aggregated, analyzed fulltext field used by `PercolatorQuery`
    too — keeping the match surface identical across the three
    mention-style queries. `Field.TEXT` (the per-property text group)
    is excluded to avoid double-counting the same mention and to align
    with the percolator's single-field matching.

    Clause count is linear in `len(names)`; slop=2 to align with
    `PercolatorQuery`.
    """
    return [
        {
            "match_phrase": {
                Field.CONTENT: {
                    "query": name,
                    "slop": 2,
                }
            }
        }
        for name in names
    ]


# --- shared base ----------------------------------------------------------


class _Mentions(EntitiesQuery):
    """Internal base: builds the mention-clause + default sort/highlight
    from `self.names`. Subclasses populate `self.names` in `__init__`
    before calling `super().__init__(parser)`.
    """

    _SCHEMA = "Document"

    names: list[str]

    @cached_property
    def schemata(self) -> list[SchemaType]:
        # Default to [_SCHEMA] rather than EntitiesQuery's ["Thing"] so
        # downstream schema-sensitive logic (e.g. get_negative_filters)
        # operates against the Document hierarchy. A caller-supplied
        # filter:schema / filter:schemata still wins.
        schemata = self.parser.getlist("filter:schema")
        if schemata:
            return schemata
        schemata = self.parser.getlist("filter:schemata")
        if schemata:
            return schemata
        return [self._SCHEMA]

    def get_index(self) -> str:
        return entities_read_index(schema=self.schemata)

    def get_inner_query(self) -> dict[str, Any]:
        # Parent builds parser text + filters + negative filters + auth.
        # AND in a mention_clause requiring at least one of the tracked
        # names (or synonym expansions) to appear as a phrase in a
        # document text field.
        inner = super().get_inner_query()
        if not self.names:
            return none_query()

        mention_clause = bool_query()
        mention_clause["bool"]["should"].extend(name_phrase_shoulds(self.names))
        # Structured-mention bonus: the target Document already carries
        # one of these names as a name property (extracted into Field.NAMES).
        # Field.NAMES is a keyword field — exact-match `terms` across
        # every matchable name variant.
        mention_clause["bool"]["should"].append(
            {"terms": {Field.NAMES: self.names, "boost": 2.0}}
        )

        if self.parser.synonyms:
            # Synonym expansion is shared with EntitiesQuery via
            # ExpandNameSynonymsMixin. Mentions queries have discrete
            # entity names, so `index_name_keys` is a direct hash (no
            # n-gram walk needed).
            symbols_clause = self.name_symbols_clause(*self.names)
            if symbols_clause is not None:
                mention_clause["bool"]["should"].append(symbols_clause)
            name_keys = list(index_name_keys(model["LegalEntity"], self.names))
            keys_clause = self.name_keys_clause(name_keys)
            if keys_clause is not None:
                mention_clause["bool"]["should"].append(keys_clause)

        mention_clause["bool"]["minimum_should_match"] = 1
        inner.setdefault("bool", {}).setdefault("must", []).append(mention_clause)
        return inner

    def get_sort(self) -> list[str | dict[str, dict[str, Any]]]:
        # The mention-clause carries scoring signals even when the parser
        # has no user text (`is_empty_query=True`), so the base
        # `Query.get_sort` fallback of `["_doc"]` for empty queries
        # would hide the best matches. Force `_score` when the caller
        # didn't pass an explicit sort; otherwise respect it.
        if not len(self.parser.sorts):
            return ["_score"]
        return super().get_sort()

    def get_highlight(self) -> dict[str, Any]:
        # Base `get_highlight` builds highlight_queries from `parser.text`
        # via `get_highlighter(..., text, ...)`. Mentions queries carry
        # their signals in the mention-clause, not in `parser.text`, so
        # when no `q=` is passed the base helper substitutes
        # `{match_all: {}}` and the highlighter returns unmarked
        # `no_match_size` fallback snippets. Replace the highlight_query
        # on text-oriented field configs with the same phrase shoulds
        # the mention-clause uses, preserving any filter-value clauses
        # the base class merged in.
        highlight = super().get_highlight()
        if not highlight or not self.names:
            return highlight
        name_shoulds = name_phrase_shoulds(self.names)
        # Only CONTENT: matches are phrase-constrained to Field.CONTENT, so
        # injecting the phrase clauses into TEXT / TRANSLATION highlight
        # configs would produce no highlights (those fields weren't
        # matched against). Leave their highlight_query alone so any
        # parser.text highlighting the base helper built there survives.
        for field_name in (self.HIGHLIGHT_FIELD,):
            cfg = highlight["fields"].get(field_name)
            if cfg is None:
                continue
            existing = cfg.get("highlight_query")
            extra: list[dict[str, Any]] = []
            if existing and existing != {"match_all": {}}:
                existing_shoulds = existing.get("bool", {}).get("should")
                if existing_shoulds is not None:
                    extra = [c for c in existing_shoulds if c != {"match_all": {}}]
                else:
                    extra = [existing]
            cfg["highlight_query"] = {
                "bool": {
                    "should": name_shoulds + extra,
                    "minimum_should_match": 1,
                }
            }
        return highlight


# --- public subclasses ----------------------------------------------------


class MentionsQuery(_Mentions):
    """Find Document-family entities that mention a given named entity.

    Inverse of `PercolatorQuery`. Given a named entity (Person, Company,
    Organization, Vessel, …) identified by `entity_id`, returns Documents
    (and their descendants — PlainText, HyperText, Pages, …) whose
    indexed text contains the entity's caption or any of its matchable
    name variants as a phrase.

    All standard `EntitiesQuery` parser knobs apply: `filter:schema`
    narrows within the Document hierarchy (e.g. to `Pages`),
    `filter:dataset`, `filter:countries`, `highlight`, `highlight_count`,
    `limit`, `offset`, `sort`, auth. `parser.text` ANDs with the mention
    requirement (free-text narrowing of mention hits).
    `parser.synonyms=true` mirrors `EntitiesQuery.get_text_query` by
    adding `terms` clauses on the indexed `Field.NAME_SYMBOLS` and
    `Field.NAME_KEYS` keyword fields derived from the entity's names —
    these fields are populated on Documents too (see
    `transform.entity._get_symbols`) from extracted name properties.

    Unlike `PercolatorQuery`, no `surface_forms` post-processing is
    performed — the standard `EntitiesQuery` highlight block is
    returned untouched.
    """

    def __init__(self, parser: SearchQueryParser, entity_id: str):
        if not entity_id:
            raise ValueError("MentionsQuery requires an `entity_id`.")
        # Local import mirrors the PercolatorQuery pattern; avoids the
        # index/entities.py → query/base.py circular dependency.
        from openaleph_search.index.entities import get_entity

        data = get_entity(entity_id)
        if data is None:
            raise ValueError(f"Entity {entity_id!r} not found.")
        proxy = model.get_proxy(data)
        names = proxy.get_type_values(registry.name, matchable=True)
        if not names:
            raise ValueError(
                f"Entity {entity_id!r} has no matchable names — "
                f"MentionsQuery requires a named entity (Person, Company, ...)."
            )
        self.entity_id = entity_id
        self.entity = proxy
        self.names = names
        super().__init__(parser)


class MultiMentionsQuery(_Mentions):
    """Find Document-family entities that mention any named entity in
    a filtered source set.

    The source set is produced by a standard `EntitiesQuery` — any
    filter that narrows it below `MAX_SOURCE_NAMES` works, across one
    or multiple collections (`filter:dataset=a&filter:dataset=b` etc.).

    Construction does Stage 1 eagerly (one ES scroll) to materialize
    the `self.names` list; Stage 2 runs on `.search()`.
    """

    def __init__(
        self,
        parser: SearchQueryParser,
        source_parser: SearchQueryParser,
    ):
        self.source_parser = source_parser
        self.names = collect_source_names(source_parser)
        super().__init__(parser)
