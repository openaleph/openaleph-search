"""Mentions queries — find Documents that mention named entities.

Two variants share a common base (`_Mentions`):

- **`MentionsQuery(parser, entity_id)`** — given one entity id, return
  Documents that mention that entity. Inverse of `PercolatorQuery`.
- **`MultiMentionsQuery(parser, source_parser)`** — given a filter on
  any entity set (one or many collections, narrowed by property
  filters), collect the matching entities' names and return Documents
  that mention **any** of them.

Both build the same mention-clause shape — a `bool.should` of
per-entity sub-bools, each sub-bool wrapping that entity's phrase
clauses on `Field.CONTENT` and its structured `terms` clause on
`Field.NAMES`. Name-synonym expansion is left to the target-side
`Field.CONTENT` analyzer (search-time synonyms), so an explicit
`name_symbols` / `name_keys` clause is not added — the analyzer
already matches known name variants without diluting per-entity
attribution. The sub-bool is tagged with `_name=<entity_id>` so ES
reports which source entities fired on each hit (surfaced as
`_source.mention_sources` after post-processing).

Scale (MultiMentionsQuery only): supports up to `MAX_SOURCE_NAMES`
collected names (10k). Larger sets raise `ValueError`.
"""

from functools import cached_property
from typing import Any

from elastic_transport import ObjectApiResponse
from followthemoney import model
from followthemoney.types import registry

from openaleph_search.core import get_es
from openaleph_search.index.indexes import entities_read_index
from openaleph_search.index.mapping import Field
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.queries import EntitiesQuery
from openaleph_search.query.util import bool_query, none_query
from openaleph_search.util import SchemaType

MAX_SOURCE_NAMES = 10_000
SCROLL_PAGE_SIZE = 500
SCROLL_KEEPALIVE = "2m"
# Which name-typed properties to pull from the source-side scroll.
SOURCE_NAME_PROPS: tuple[str, ...] = ("name",)


def collect_source_entities(
    parser: SearchQueryParser,
    *,
    max_names: int = MAX_SOURCE_NAMES,
) -> list[tuple[str, list[str]]]:
    """Scroll the source-side filter and return matchable names per entity.

    Returns `[(entity_id, sorted(unique_names)), ...]` sorted by
    `entity_id` for stable query hashes. Names are NOT deduped *across*
    entities — a name shared by two source entities appears once under
    each of their IDs, so the downstream mention-clause emits a separate
    tagged sub-bool per entity (each contributing its own attribution).

    Reads only the configured name-typed property arrays from `_source`
    (no full-proxy load). Dataset ACL applies via the parser's auth;
    the source parser can filter across one or many collections.
    Raises `ValueError` if the filter yields more than `max_names`
    total name occurrences (summed across entities), or if the source
    entity count alone exceeds the budget.
    """
    query = EntitiesQuery(parser)
    es = get_es()
    entities: list[tuple[str, list[str]]] = []
    total_names = 0
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
                entity_id = hit["_id"]
                props = (hit.get("_source") or {}).get("properties", {}) or {}
                per_entity: set[str] = set()
                for prop in SOURCE_NAME_PROPS:
                    per_entity.update(props.get(prop) or [])
                if not per_entity:
                    continue
                entities.append((entity_id, sorted(per_entity)))
                total_names += len(per_entity)
                # Multi-valued `name` arrays are common (FtM Persons
                # often carry several variants: "Jane Doe", "Doe,
                # Jane", "J. Doe", …). The summed name count routinely
                # grows faster than the entity count, so this per-hit
                # check is the primary budget enforcement — the
                # entity-count short-circuit above is only a fast
                # upper-bound gate.
                if total_names > max_names:
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
    return sorted(entities, key=lambda e: e[0])


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
    from `self.source_entities`. Subclasses populate
    `self.source_entities` (and the flat `self.names` used for
    highlighting) in `__init__` before calling `super().__init__(parser)`.
    """

    _SCHEMA = "Document"

    # Per-entity (id, names) tuples driving the mention-clause shape.
    # Each tuple produces one `_name`-tagged sub-bool so ES can report
    # which source entities fired on each hit via `hit.matched_queries`.
    source_entities: list[tuple[str, list[str]]]
    # Flat, deduped list of all names across source_entities. Retained
    # because `get_highlight` and any name-aggregating post-processing
    # want to work over the union rather than per-entity.
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

    def get_text_query(self) -> list[dict[str, Any]]:
        # Bypass `EntitiesQuery.get_text_query`'s `parser.synonyms`-gated
        # user-text expansion. Name-synonym matching on `Field.CONTENT`
        # is provided by the target index's analyzer at search time, so
        # the explicit `name_symbols` / `name_keys` terms clauses add
        # nothing for mention queries and would dilute per-entity
        # attribution.
        return super(EntitiesQuery, self).get_text_query()

    def get_inner_query(self) -> dict[str, Any]:
        # Parent builds parser text + filters + negative filters + auth.
        # AND in a mention_clause whose should list holds one sub-bool
        # per source entity; each sub-bool carries that entity's phrase
        # clauses + structured-names clause, tagged with
        # `_name=<entity_id>` so ES reports which entities fired on each
        # hit via `hit.matched_queries`.
        #
        # No explicit name-symbols / name-keys synonym expansion is added
        # here — the target-side `Field.CONTENT` analyzer already applies
        # search-time name synonyms to phrase matches, so an explicit
        # terms-on-keyword synonym clause would only duplicate what the
        # analyzer provides (and dilute per-entity attribution).
        inner = super().get_inner_query()
        if not self.source_entities:
            return none_query()

        per_entity: list[dict[str, Any]] = []
        for entity_id, names in self.source_entities:
            if not names:
                continue
            sub = bool_query()
            sub["bool"]["should"].extend(name_phrase_shoulds(names))
            # Structured-mention bonus: the target Document already carries
            # one of these names as a name property (extracted into
            # Field.NAMES). Field.NAMES is a keyword field — exact-match
            # `terms` across the entity's name variants.
            sub["bool"]["should"].append({"terms": {Field.NAMES: names, "boost": 2.0}})
            sub["bool"]["minimum_should_match"] = 1
            # `_name` on a bool fires when the bool matches as a whole,
            # so a single entity_id tag covers all of its sub-clauses
            # without having to tag each one individually.
            sub["bool"]["_name"] = entity_id
            per_entity.append(sub)

        if not per_entity:
            return none_query()

        mention_clause = bool_query()
        mention_clause["bool"]["should"] = per_entity
        mention_clause["bool"]["minimum_should_match"] = 1
        inner.setdefault("bool", {}).setdefault("must", []).append(mention_clause)
        return inner

    def search(self) -> ObjectApiResponse:
        # Attach per-hit source-entity attribution. ES populates
        # `hit.matched_queries` with the `_name` tags of every named
        # clause that fired on that hit — for mentions queries that's
        # the per-entity sub-bool tags, i.e. the source entity IDs.
        # (Note: `hit.matched_queries` is the TOP-level named-queries
        # slot; the percolator path reads from
        # `hit.fields._percolator_document_slot_0_matched_queries`
        # instead — see comment at
        # openaleph_search/query/queries.py:515–517.)
        result = super().search()
        for hit in result.get("hits", {}).get("hits", []) or []:
            matched = hit.get("matched_queries") or []
            hit.setdefault("_source", {})["mention_sources"] = sorted(matched)
        return result

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
    requirement (free-text narrowing of mention hits). Name-synonym
    matching is provided by the target-side `Field.CONTENT` analyzer at
    search time; `parser.synonyms=true` no longer adds any extra
    clauses to the mention path.

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
        self.names = sorted(set(names))
        self.source_entities = [(entity_id, self.names)]
        super().__init__(parser)


class MultiMentionsQuery(_Mentions):
    """Find Document-family entities that mention any named entity in
    a filtered source set.

    The source set is produced by a standard `EntitiesQuery` — any
    filter that narrows it below `MAX_SOURCE_NAMES` works, across one
    or multiple collections (`filter:dataset=a&filter:dataset=b` etc.).

    Construction does Stage 1 eagerly (one ES scroll) to materialize
    the `self.source_entities` list; Stage 2 runs on `.search()`.

    Each hit returned by `.search()` carries a
    `_source.mention_sources` list — the source entity IDs whose
    per-entity sub-bool fired on that document. Name collisions across
    source entities (e.g. two Persons both named "John Smith") surface
    all matching IDs.
    """

    def __init__(
        self,
        parser: SearchQueryParser,
        source_parser: SearchQueryParser,
    ):
        self.source_parser = source_parser
        self.source_entities = collect_source_entities(source_parser)
        self.names = sorted({n for _, names in self.source_entities for n in names})
        super().__init__(parser)
