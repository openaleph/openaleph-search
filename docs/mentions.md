# Mentions

Find documents that mention a given named entity – or a filtered *set* of named entities – by phrase-matching name variants against the documents bucket.

!!! info "Reverse percolation"
    Where [Percolation](./percolation.md) runs *one document against many stored queries* ("which of my entities are mentioned in this text?"), the mentions queries run the inverse: *one or many entities against many stored documents* ("which of my documents mention this entity?"). Same signal – names as phrases in fulltext – applied from the other direction, with no precomputed stored queries involved.

Two flavours, sharing a common mention clause:

- **`MentionsQuery(parser, entity_id)`** – single entity. Loads the entity, pulls its matchable names, runs the mention clause against the Document hierarchy.
- **`MultiMentionsQuery(parser, source_parser)`** – filtered set. Scrolls a second parser over any entity population (one or several collections, narrowed by property filters), collects every matching entity's names, and runs the same mention clause over the union. Capped at 10k names – see [Multi-entity variant](#multi-entity-variant-multimentionsquery) below.

Both return entities from the Document hierarchy (Document, PlainText, HyperText, Pages, Page, …) whose indexed text contains one of those names as a phrase.

## How it works

At query time, `MentionsQuery` loads the target entity via `get_entity` and extracts its matchable names (`registry.name`, `matchable=True` – typically `name`, `alias`, `previousName` …). It then builds the same shape of search query a user would write against the documents bucket, with a `mention_clause` ANDed into the bool body.

The mention clause is a `bool.should` with `minimum_should_match: 1` combining:

1. **Fulltext phrase match** – one `match_phrase` clause per matchable name on `Field.CONTENT`, with `slop: 2`. Slop 2 matches the percolator's ingest clauses, tolerating inserted middle initials (`"Jane Doe"` matches `"Jane A. Doe"`) and reversed last-name-first variants (`"Doe, Jane"`). `Field.TEXT` (the per-property text group) is deliberately excluded – `content` already aggregates every text-type value, and matching both fields double-counts the same mention.
2. **Structured-name bonus** – a `terms` clause over `Field.NAMES` (keyword) across all matchable name variants, boosted to `2.0`. This catches documents that carry the entity's name as an extracted property value (`names` group) rather than only as free text.
3. **Optional synonym expansion** – when `parser.synonyms=true`, two extra clauses are added via `ExpandNameSynonymsMixin` (shared with `EntitiesQuery`): a `terms` clause over `Field.NAME_SYMBOLS` from the entity's NAME-category symbols (boost `0.5`), and a `terms` clause over `Field.NAME_KEYS` from `index_name_keys` of the entity's names (boost `0.3`). Mirrors the user-text synonyms path in `EntitiesQuery.get_text_query` – same fields, same boosts – but derives keys directly from the entity's discrete names rather than n-gramming user query tokens.

The mention clause is ANDed (`bool.must`) with the rest of the query built by `EntitiesQuery` – `parser.text`, filters, negative filters, auth – so `parser.text` narrows mention hits instead of replacing them.

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
    print(doc["caption"], "→", hit.get("highlight", {}).get("content", []))
```

Or via CLI:

```bash
openaleph-search search mentions person-abc \
    --args "filter:dataset=news_archive&highlight=true&limit=50"
```

Standard parser knobs flow through automatically:

- `filter:*` – applied as filters on the document search (`filter:dataset`, `filter:countries`, `filter:schema=Pages`, …).
- `q=…` – free-text narrowing that ANDs with the mention requirement (e.g. "documents that mention this person *and* contain the word 'invoice'").
- `synonyms=true` – opt-in symbol / name-key expansion of the entity's names (see above).
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

- Same `match_phrase` clauses on `Field.CONTENT` (slop 2).
- Same structured-name bonus on `Field.NAMES` (boost 2.0).
- Same optional `synonyms=true` expansion (`Field.NAME_SYMBOLS` + `Field.NAME_KEYS`).
- Same default schema scope (`["Document"]`), overridable via `filter:schema`.
- Same `_score` default sort and same `content` highlight injection.

A target document that mentions *more* of the filtered entities' names ranks higher (BM25 summing over the matched phrase clauses), so the natural answer to "which news doc is most relevant to my watchlist?" falls out of the default ordering.

### What differs

- **Name source.** Stage 1 scrolls the source parser and extracts values from a small subset of name-typed properties (`SOURCE_NAME_PROPS` in `query/mentions.py`, currently `("name",)` – primary names only). Aliases / previousNames are intentionally excluded at the source side to keep recall deliberate; they're available on the matchable-names side via `MentionsQuery` on a single entity.
- **Scale budget.** `MAX_SOURCE_NAMES = 10_000`. Two guards:
    1. On the first response, `track_total_hits: max_names + 1` short-circuits if the source filter matches more entities than the budget can ever accommodate.
    2. During the scroll, a per-hit check on the deduped name set catches the case where multi-valued `name` arrays push name count past entity count.
    Either trip raises `ValueError` with a message pointing at the source filter.
- **Response shape.** The response is a flat ranked list of matching documents. It does *not* say *which* of the filtered entities each document mentioned – for that attribution, use the [Percolation](./percolation.md) path with its `percolator_match` signal on each hit.

### Limits specific to the multi variant

- **10k names cap.** Sources that exceed the cap raise before running Stage 2. Narrow the source filter.
- **No per-document attribution.** As noted above.
- **Stage 1 cost.** One `es.count` request upfront (shard-level; near-free) followed by one scroll session (with continuations if the filter is large). The count fail-fasts when the source filter is grossly oversized without touching the scroll at all.

## Limits and trade-offs

### Recall is bounded by the entity's stored names

The mention clause is built from the entity's matchable name properties only. Variants the entity doesn't know about won't match a document: a PDF that says `"Müller"` against an entity stored only as `"Mueller"` will not fire unless `synonyms=true` lifts them into the same name-symbol / name-key bucket.

If recall matters, either enrich the entity with aliases / `previousName` values, or opt in to `synonyms=true`.

### Phrase matching tolerates small slop

`match_phrase` clauses use `slop: 2`, matching the percolator's ingest side. That tolerates inserted middle initials (`"Jane Doe"` matches `"Jane A. Doe"`) and reversed last-name-first variants (`"Doe, Jane"` / `"Doe Jane"`). It does *not* tolerate large token gaps or out-of-order rearrangements beyond two positions – for those, store explicit alias variants or opt in to `synonyms=true`.

### No identifier signal

The percolator also fires on exact identifier matches (IMO, VAT, registration numbers, …). `MentionsQuery` does *not* – it is name-only. If you need identifier-based document discovery, run a plain `EntitiesQuery` with the identifier value as free text, or build a dedicated query against `Field.IDENTIFIERS`.

### Document hierarchy only

Results are scoped to the Document bucket family by default. Things (Person, Company, …) and Intervals (Ownership, Sanction, …) are not searched – they have no meaningful fulltext for a mention clause to fire against. The subject entity itself, which lives in the things bucket, is naturally absent from results.

### Scaling beyond one entity

`MentionsQuery` takes a single `entity_id`. To screen a **filtered population** of entities in one call, use [`MultiMentionsQuery`](#multi-entity-variant-multimentionsquery) (up to 10k names). To screen a single text against many stored entities, use [Percolation](./percolation.md) instead.
