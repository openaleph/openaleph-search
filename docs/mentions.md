# Mentions

Find documents that mention a given named entity – or a filtered *set* of named entities – by phrase-matching name variants against the documents bucket.

!!! info "Reverse percolation"
    Where [Percolation](./percolation.md) runs *one document against many stored queries* ("which of my entities are mentioned in this text?"), the mentions queries run the inverse: *one or many entities against many stored documents* ("which of my documents mention this entity?"). Same signal – names as phrases in fulltext – applied from the other direction, with no precomputed stored queries involved.

Two flavours, sharing a common mention clause:

- **`MentionsQuery(parser, entity_id)`** – single entity. Loads the entity, pulls its matchable names, runs the mention clause against the Document hierarchy.
- **`MultiMentionsQuery(parser, source_parser)`** – filtered set. Scrolls a second parser over any entity population (one or several collections, narrowed by property filters), collects every matching entity's names, and runs the same mention clause over the union. Capped at 10k names – see [Multi-entity variant](#multi-entity-variant-multimentionsquery) below.

Both return entities from the Document hierarchy (Document, PlainText, HyperText, Pages, Page, …) whose indexed text contains one of those names as a phrase.

## How it works

At query time, `MentionsQuery` loads the target entity via `get_entity` and extracts its matchable names (`registry.name`, `matchable=True` – typically `name`, `alias`, `previousName` …). The names go through the shared `clean_matching_names` cleaner – the same one applied to the percolator and to entity-vs-entity matching – so short single tokens (e.g. `"Doe"`) and singles shadowed by a multi-token variant (e.g. `"Vladimir"` when `"Vladimir Putin"` is also present) are dropped before any phrase clause is built. The cleaner threshold is governed by `OPENALEPH_SEARCH_MATCHING_SINGLE_TOKEN_MIN_LENGTH` (default `10`); see [Matching](./matching.md#name-selection) for the full rules. The cleaned set then drives a `mention_clause` ANDed into the bool body of the same shape of search query a user would write against the documents bucket.

The mention clause is a `bool.should` of **per-entity sub-bools** with `minimum_should_match: 1` at the outer level. Each source entity contributes one sub-bool — itself a `bool.should` with `minimum_should_match: 1` — tagged with `_name=<entity_id>` so ES reports on each hit which entities fired (via `hit.matched_queries`; the mentions search post-processing writes this into `_source.mention_sources`, see [Attribution](#attribution) below).

Each per-entity sub-bool combines two clauses:

1. **Fulltext phrase match** – one `match_phrase` clause per matchable name on `Field.CONTENT`, with `slop: 2`. Slop 2 matches the percolator's ingest clauses, tolerating inserted middle initials (`"Jane Doe"` matches `"Jane A. Doe"`) and reversed last-name-first variants (`"Doe, Jane"`). `Field.TEXT` (the per-property text group) is deliberately excluded – `content` already aggregates every text-type value, and matching both fields double-counts the same mention. Name-synonym matching is handled by the `Field.CONTENT` analyzer at search time (ICU + rigour name synonyms), so an explicit `name_symbols` / `name_keys` keyword expansion is *not* added.
2. **Structured-name bonus** – a `terms` clause over `Field.NAMES` (keyword) across this entity's matchable name variants, boosted to `2.0`. This catches documents that carry the entity's name as an extracted property value (`names` group) rather than only as free text.

The mention clause is ANDed (`bool.must`) with the rest of the query built by `EntitiesQuery` – `parser.text`, filters, negative filters, auth – so `parser.text` narrows mention hits instead of replacing them.

`parser.synonyms=true` is a no-op for the mention path: the name-synonym clauses `EntitiesQuery` adds on user text (`name_symbols` / `name_keys` terms over the user's `q=` tokens) are suppressed here because the analyzer already performs synonym expansion against `Field.CONTENT` at search time.

### Attribution

Every hit carries `_source.mention_sources`: a sorted list of source entity IDs whose sub-bool fired on that document. For `MentionsQuery` the list is always the single subject entity's ID; for `MultiMentionsQuery` it lists every source entity whose name matched. Name collisions across source entities (e.g. two Persons both called "John Smith") surface all matching IDs — ES can't disambiguate from a text match alone, so the full candidate set is returned.

### Default schema scope

Default `schemata` is `["Document"]` (not `["Thing"]` as in `EntitiesQuery`), which covers Document and all its descendants. The index resolver uses the Document-hierarchy buckets (`documents`, `pages`, `page`) accordingly. A caller-supplied `filter:schema` or `filter:schemata` overrides it – e.g. `filter:schema=Pages` to scope to page entities only.

### Sort and highlights

- **Sort.** When no explicit `sort` is passed, `MentionsQuery` forces `_score` rather than falling back to `_doc`. The mention clause carries all the scoring signal even when `parser.text` is empty, so the base "empty query → no ranking" heuristic would hide the best hits. An explicit `sort` from the parser still wins.
- **Highlights.** With `highlight=true`, the `content` highlight config has its `highlight_query` replaced with the same phrase shoulds used by the mention clause (merged with any filter-value clauses the base class added). `text` and `translation` highlight configs are left untouched so any `parser.text` highlighting the base helper built there survives – the mention clause only matches `content`, so injecting the phrase shoulds into `text`/`translation` wouldn't produce highlights anyway.

## Querying – `MentionsQuery`

Via Python:

```python
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.mentions import MentionsQuery

parser = SearchQueryParser([("highlight", "true"),
                            ("limit", "50")])
query = MentionsQuery(parser, entity_id="person-abc")
result = query.search()

for hit in result["hits"]["hits"]:
    doc = hit["_source"]
    sources = doc["mention_sources"]  # always ["person-abc"] for MentionsQuery
    snippets = hit.get("highlight", {}).get("content", [])
    print(doc["caption"], "←", sources, "→", snippets)
```

Or via CLI:

```bash
openaleph-search search mentions person-abc \
    --args "filter:dataset=news_archive&highlight=true&limit=50"
```

Standard parser knobs flow through automatically:

- `filter:*` – applied as filters on the document search (`filter:dataset`, `filter:countries`, `filter:schema=Pages`, …).
- `q=…` – free-text narrowing that ANDs with the mention requirement (e.g. "documents that mention this person *and* contain the word 'invoice'").
- `synonyms=true` – accepted for parser compatibility but does not add any clauses in the mentions path; name synonyms are provided by the target-side `Field.CONTENT` analyzer at search time.
- `highlight=true` + `highlight_count=N` – fragment snippets with `<em>…</em>` markup around matched phrases, same shape as `EntitiesQuery` highlights.
- `limit` / `offset` – pagination.
- `sort` – overrides the default `_score` sort.
- `dehydrate=true` – strips bulky `properties` from the response.
- `auth` – same auth filters as any other entity query.

### Errors

`MentionsQuery(parser, entity_id=...)` raises `ValueError` if:

- `entity_id` is falsy.
- The entity is not found in the index.
- The entity has no matchable names (`registry.name`, `matchable=True`). A Document or a nameless schema cannot be the subject of a mentions search – there is nothing to phrase-match on.
- The entity's names are all dropped by `clean_matching_names` – e.g. an entity with only short single-token names like `"Doe"`. Lower `OPENALEPH_SEARCH_MATCHING_SINGLE_TOKEN_MIN_LENGTH` or enrich the entity with longer / multi-token variants.

## Multi-entity variant – `MultiMentionsQuery`

`MultiMentionsQuery` generalizes the same mention clause from one entity to a **filtered set of entities**. Instead of a single `entity_id`, it takes a second `SearchQueryParser` – the *source parser* – that narrows the entity population by property filters (country, topic, schema, dataset…). The names from every matching entity are scrolled, deduped, and fed into the same mention-clause shape the single-entity path uses.

Use this when you want to screen one or many collections (a watchlist, a sanctions list, a PEP roster) against a target document set in a single call.

### Shape of the call

```python
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.mentions import MultiMentionsQuery

# Source: any watchlist Person on a sanctions topic, across multiple collections.
source = SearchQueryParser([
    ("filter:schema", "Person"),
    ("filter:dataset", "watchlist_a"),
    ("filter:dataset", "watchlist_b"),
    ("filter:topics", "sanction"),
])

# Target: news documents, ranked + highlighted.
target = SearchQueryParser([
    ("filter:dataset", "news_archive"),
    ("highlight", "true"),
    ("limit", "50"),
])

query = MultiMentionsQuery(target, source)
result = query.search()

for hit in result["hits"]["hits"]:
    doc = hit["_source"]
    # Which source entities caused this document to match?
    sources = doc["mention_sources"]  # e.g. ["watchlist-p1", "watchlist-p7"]
    print(hit["_id"], "←", sources)
```

Also exposed via the CLI:

```bash
openaleph-search search multi-mentions \
    --source-args "filter:schema=Person&filter:dataset=watchlist_a&filter:topics=sanction" \
    --args       "filter:dataset=news_archive&highlight=true&limit=50"
```

The source parser can span **multiple datasets** at once (repeat `filter:dataset=...`) – it's a plain `EntitiesQuery` on the source side. Any filter valid on `EntitiesQuery` works.

### What it shares with `MentionsQuery`

The match surface, ranking, and highlight behaviour are identical:

- Same `match_phrase` clauses on `Field.CONTENT` (slop 2), with the same reliance on the analyzer for name-synonym matching.
- Same structured-name bonus on `Field.NAMES` (boost 2.0).
- Same default schema scope (`["Document"]`), overridable via `filter:schema`.
- Same `_score` default sort and same `content` highlight injection.

A target document that mentions *more* of the filtered entities' names ranks higher (sub-bool scores sum at the outer `should` level), so the natural answer to "which news doc is most relevant to my watchlist?" falls out of the default ordering.

### What differs

- **Name source.** Stage 1 scrolls the source parser and pulls `(entity_id, names)` tuples from each hit, reading only the configured name-typed property arrays (`SOURCE_NAME_PROPS` in `query/mentions.py`, currently `("name",)` – primary names only). Aliases / previousNames are intentionally excluded at the source side to keep recall deliberate; they're available on the matchable-names side via `MentionsQuery` on a single entity. Each entity's names go through `clean_matching_names` per-entity (entities whose names are entirely cleaned away are skipped). Names are not deduped *across* entities, so a name shared by two source entities produces two separate tagged sub-bools (one per entity) and both IDs surface on any hit that fires on that name.
- **Scale budget.** `MAX_SOURCE_NAMES = 10_000`. Two guards:
    1. An `es.count` short-circuit before the scroll fires when the source filter matches more entities than the name budget can ever accommodate (every entity contributes ≥1 name).
    2. During the scroll, a running sum of name occurrences across all entities catches the case where multi-valued `name` arrays push total names past the cap even if entity count is below it.
    Either trip raises `ValueError` with a message pointing at the source filter.
- **Response shape.** Each hit carries `_source.mention_sources` — the sorted list of source entity IDs whose sub-bool fired on that document, same as the single-entity path but with more than one ID possible per hit. See [Attribution](#attribution) above.

### Limits specific to the multi variant

- **10k names cap.** Sources that exceed the cap raise before running Stage 2. Narrow the source filter.
- **Clause count.** Each source entity contributes one sub-bool containing its phrase clauses plus one `terms` clause. For a 10k-entity source filter this is on the order of `2 × MAX_SOURCE_NAMES` recursive bool clauses; the cluster's `indices.query.bool.max_clause_count` must accommodate it.
- **Stage 1 cost.** One `es.count` request upfront (shard-level; near-free) followed by one scroll session (with continuations if the filter is large). The count fail-fasts when the source filter is grossly oversized without touching the scroll at all.

## Limits and trade-offs

### Recall is bounded by the entity's stored names

The mention clause is built from the entity's matchable name properties only, after they pass through `clean_matching_names` (see [Matching → Name selection](./matching.md#name-selection)). Variants the entity doesn't know about won't match a document unless the `Field.CONTENT` analyzer bridges them at search time (ICU + rigour name synonyms handle the common transliteration / accent cases — e.g. `"Müller"` ↔ `"Mueller"`).

Two specific cleaner effects worth knowing here: (1) any single-token name shorter than `OPENALEPH_SEARCH_MATCHING_SINGLE_TOKEN_MIN_LENGTH` (default 10) is dropped, and (2) single-token variants are dropped entirely whenever the same entity also carries a multi-token variant — so an entity with `["Vladimir Putin", "Vladimir"]` only mention-matches on the multi-token form.

If recall matters beyond what the analyzer + cleaner allow, enrich the entity with longer / multi-token aliases / `previousName` values on the source side, or lower the cleaner threshold globally.

### Phrase matching tolerates small slop

`match_phrase` clauses use `slop: 2`, matching the percolator's ingest side. That tolerates inserted middle initials (`"Jane Doe"` matches `"Jane A. Doe"`) and reversed last-name-first variants (`"Doe, Jane"` / `"Doe Jane"`). It does *not* tolerate large token gaps or out-of-order rearrangements beyond two positions – for those, store explicit alias variants on the source side.

### No identifier signal

The percolator also fires on exact identifier matches (IMO, VAT, registration numbers, …). `MentionsQuery` does *not* – it is name-only. If you need identifier-based document discovery, run a plain `EntitiesQuery` with the identifier value as free text, or build a dedicated query against `Field.IDENTIFIERS`.

### Document hierarchy only

Results are scoped to the Document bucket family by default. Things (Person, Company, …) and Intervals (Ownership, Sanction, …) are not searched – they have no meaningful fulltext for a mention clause to fire against. The subject entity itself, which lives in the things bucket, is naturally absent from results.

### Scaling beyond one entity

`MentionsQuery` takes a single `entity_id`. To screen a **filtered population** of entities in one call, use [`MultiMentionsQuery`](#multi-entity-variant-multimentionsquery) (up to 10k names). To screen a single text against many stored entities, use [Percolation](./percolation.md) instead.
