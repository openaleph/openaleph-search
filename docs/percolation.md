# Percolation

Find entities mentioned in an arbitrary text by percolating the document against the stored entity index.

[Read more in the Elasticsearch percolator documentation](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-percolate-query)

!!! info "Reverse search"
    Where a normal search runs *one query against many documents*, percolation runs *one document against many stored queries*. Each entity in the things bucket carries its own stored percolator query (built from its name variants at index time), so percolating a document is the same as asking "which of my entities are mentioned in this text?"

!!! warning "Globally opt-in"
    Percolation is **disabled by default**. Enable it by setting `OPENALEPH_SEARCH_PERCOLATION=1` (or `percolation: true` in your `.env`). When disabled, the entity transform skips writing the `query` field on new entities, and `PercolatorQuery.search()` short-circuits to an empty response.

## How it works

There is **no separate percolator index**. The `query` field of ES type `percolator` lives directly on each entity in the things bucket (`{prefix}-entity-things-v1`). At index time, the entity transform builds a `bool.should` of `match_phrase` clauses – one per cleaned name variant.

Clauses come from two name tiers:

- **Primary names** – the entity's canonical `name` values. Tagged `_name: "name"` and boosted at 2.0.
- **Other names** – secondary name signals (`alias`, `previousName`). Tagged `_name: "other_name"` and boosted at 0.8, so canonical-name matches rank above alias-only matches.

All clauses use `match_phrase` with `slop: 2` – tolerant of inserted middle initials (`"Jane Doe"` matches `"Jane A. Doe"`), reversed last-name-first variants (`"Doe, Jane"`), and small token gaps. Performance is essentially the same as `slop: 1`; both fall off the `index_phrases` shingle fast path that `slop: 0` uses, so once you're paying the slop cost the value itself is free.

Percolating a document is then a normal entity search against the things bucket with three extra ingredients:

1. A `percolate` clause inside the bool query, supplying the input text as the percolated document.
2. BM25 scoring is preserved: each matching `match_phrase` clause in a hit's stored percolator bool contributes its score, and `_score` is the sum of those contributions. Hits default to `_score` desc, so entities with more matching name variants (and longer / rarer phrases) rank higher. The `_name` tags still surface per hit via `hit.fields._percolator_document_slot_0_matched_queries` and are post-processed into `_source.percolator_match` (see [Match signal types](#match-signal-types) below).
3. An **opt-in** highlight on the `content` field, gated on the standard `highlight=true` parser arg (same as every other query in this codebase). When enabled, the format mirrors `EntitiesQuery` highlights – a `highlight.content` list of fragment snippets with `<em>…</em>` markup. `parser.highlight_count` controls the fragment count (default 3). The whole `highlight` block stays on each hit, *and* the marked phrases are also parsed into a `surface_forms` list on `_source` as a convenience for callers that only need the matched strings without surrounding context.

When `highlight=true` is **not** set (the default), ES skips the highlighter entirely. The hit has no `highlight` block, and `_source.surface_forms` is empty for every hit. `_source.percolator_match` is independent of highlights and continues to populate correctly in both modes – it comes from `hit.fields._percolator_document_slot_0_matched_queries`, not from the highlight.

## Signal cleaning

The transform runs the name list through `clean_matching_names` (`openaleph_search/transform/util.py`) — the **shared cleaner** also used by `MentionsQuery` / `MultiMentionsQuery` and by `match_query` / `blocking_query` in `query/matching.py`, so all four matching paths share the same recall/precision knob.

- **Multi-token names** are kept as-is (e.g. `"Jane Doe"`, `"J. Doe"`, `"Acme Corporation"`). Phrase matching is specific enough.
- **Single-token names** are only kept when **(a)** they meet the configured minimum length (default **10**, set via `OPENALEPH_SEARCH_MATCHING_SINGLE_TOKEN_MIN_LENGTH`) *and* **(b)** the same input list contains no multi-token variant. So a Person stored as `["Vladimir Putin", "Vladimir"]` percolates only on `"Vladimir Putin"` (the multi-token entry wins outright); a single-token-only entity like `"Microsoft"` is kept; `"Acme"`, `"Doe"`, and `"Banana"` are dropped at the default. Short single tokens produce too many false positives against arbitrary prose, and even the longer ones are skipped whenever a more specific phrase variant is available — the multi-token clause already covers any document that mentions the single-token form too.
- **Empty / whitespace-only** entries are dropped.

The cleaner returns a `set[str]` so callers can rely on uniqueness without re-deduping; only the JSON-construction sites (e.g. the stored percolator `should` clauses) sort it back into a deterministic list.

## Querying

### CLI

By default, the response is the lean shape – no highlight block, no surface forms – just matched entities and their `percolator_match` signal-type tags:

```bash
openaleph-search percolate -i document.txt
```

```json
{
  "_id": "vessel-12345",
  "_index": "openaleph-entity-things-v1",
  "_score": 1.0,
  "_source": {
    "schema": "Vessel",
    "caption": "MV Example",
    "properties": {"name": ["MV Example"], "imoNumber": ["9123456"]},
    "surface_forms": [],
    "percolator_match": ["name"]
  }
}
```

To get highlight snippets and parsed surface forms, opt in with `highlight=true`:

```bash
openaleph-search percolate -i document.txt --args "highlight=true"
```

Each hit then carries:

- A standard `highlight.content` block – a list of fragment snippets with `<em>…</em>` markup, same shape as `EntitiesQuery` highlights.
- A populated `_source.surface_forms` list – the matched phrases parsed out of the highlight, deduped and sorted alphabetically.

```json
{
  "took": 12,
  "hits": {
    "total": {"value": 1, "relation": "eq"},
    "max_score": 1.0,
    "hits": [
      {
        "_id": "vessel-12345",
        "_index": "openaleph-entity-things-v1",
        "_score": 1.0,
        "_source": {
          "schema": "Vessel",
          "caption": "MV Example",
          "properties": {"name": ["MV Example"], "imoNumber": ["9123456"]},
          "surface_forms": ["MV Example"],
          "percolator_match": ["name"]
        },
        "highlight": {
          "content": [
            "The vessel <em>MV Example</em> was sighted near the canal."
          ]
        }
      }
    ]
  }
}
```

A hit matched by both tiers would have `"percolator_match": ["name", "other_name"]` (deduped, sorted alphabetically). `_score` is BM25 over the matched stored clauses, so entities with more name variants hitting – or rarer phrases matching – rank higher.

All standard query parser arguments apply via `--args`:

```bash
# Scope to a single dataset
openaleph-search percolate -i leak.txt \
  --args "filter:dataset=peps_watchlist"

# Add highlights + control fragment count
openaleph-search percolate -i leak.txt \
  --args "filter:dataset=peps_watchlist&highlight=true&highlight_count=5"

# Combine filters with dehydration to slim the response
openaleph-search percolate -i leak.txt \
  --args "filter:dataset=peps_watchlist&filter:countries=us&dehydrate=true&limit=50"
```

### Programmatic

`PercolatorQuery` is a thin `EntitiesQuery` subclass – it slots into any code that already consumes the standard `Query.search()` contract:

```python
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.queries import PercolatorQuery

parser = SearchQueryParser([("filter:dataset", "peps_watchlist"),
                            ("dehydrate", "true"),
                            ("limit", "50")])
query = PercolatorQuery(parser, text=document_text)
result = query.search()

for hit in result["hits"]["hits"]:
    entity = hit["_source"]
    print(entity["caption"], "→", entity["surface_forms"], entity["percolator_match"])

# Filter to canonical-name hits only (skip alias / previousName-only matches):
canonical_only = [
    hit for hit in result["hits"]["hits"]
    if "name" in hit["_source"]["percolator_match"]
]
```

Standard parser knobs flow through automatically:

- `filter:*` – applied as filters on the entity search (dataset, countries, schema, etc.).
- `dehydrate=true` – strips the bulky `properties` field from the response.
- `limit` / `offset` – pagination over the entity results.
- `sort` – overrides the default `_score` sort. `_score` is BM25 over the matched name clauses, so the default ranks entities with more / rarer name matches higher.
- `auth` – same auth filters as any other entity query.

## Match signal types

Each clause in the stored percolator query is tagged with a `_name` of either `"name"` (canonical) or `"other_name"` (alias / previousName). When the percolator fires, ES surfaces the tags of the matching clauses per hit, and `PercolatorQuery.search` post-processes them into a `percolator_match` list on the hit's `_source`:

| `percolator_match` | What it means |
|---|---|
| `["name"]` | Only a canonical-name clause fired. |
| `["other_name"]` | Only an alias / previousName clause fired. |
| `["name", "other_name"]` | Both tiers matched (deduped, sorted alphabetically). |

Ranking is BM25: per-clause boosts (`name` = 2.0, `other_name` = 0.8) create a soft tier so canonical-name matches rank above alias-only matches, but every matching clause still contributes to `_score`. Downstream apps can read `percolator_match` directly to apply hard filters (e.g. only alert on canonical-name matches) on top of the BM25 ranking.

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `OPENALEPH_SEARCH_PERCOLATION` | `false` | Globally enable per-entity stored percolator queries. When false, the entity transform skips the `query` field, and `PercolatorQuery.search()` returns an empty response. |

The `query` percolator field is *always* present in the things bucket mapping regardless of this setting, so toggling percolation on later only requires a re-index of the affected entities – no remap.

## Reindexing

Existing entities indexed before percolation was enabled will not have a `query` field. To populate it:

1. Set `OPENALEPH_SEARCH_PERCOLATION=1`.
2. Run `openaleph-search upgrade` to ensure the things bucket mapping has the `query` percolator field (it does by default after this change, but `upgrade` is idempotent).
3. Re-index the entities for any datasets you want to be percolatable.

New entity writes pick up the `query` field automatically once the setting is enabled.

## Index

The percolator field lives on the existing things bucket index:

```
{prefix}-entity-things-v1
```

Mapping snippet:

```json
{
  "properties": {
    "query": {"type": "percolator"},
    "content": {"type": "text", "analyzer": "icu-default", ...},
    ...
  }
}
```

## Performance

Percolator latency is dominated by **how many stored queries ES has to re-evaluate** for each percolation request. Without filtering, that's *every* matchable entity in the things bucket – for an [OpenSanctions](https://www.opensanctions.org/datasets/default/)- sized index (~2M entities) that's roughly **1.5–2 seconds per request** even with the candidate-selection optimization, because the candidate selection narrows the set by less than an order of magnitude on long percolated documents.

**Always pair `percolate` with a selective filter.** ES pushes filter clauses *down* into the percolate evaluation: the filter is applied first, and the percolate clause only runs against the docs that survive it. Latency scales linearly with the size of the filtered set.

Real numbers from a 2.1M-entity OpenSanctions index, percolating a ~700-word German news article:

| Filter | Filtered set size | Candidates per shard | Latency |
|---|---|---|---|
| (none) | 2.1M | ~39,000 | **~1800ms** |
| `filter:topics=role.pep` | 662K | ~70 | **~13ms** |
| `filter:topics=poi` | 32K | ~5 | **~6ms** |
| `filter:topics=sanction` | 72K | ~10 | **~10ms** |
| `filter:dataset=opensanctions` (everything) | 2.1M | ~39,000 | **~1800ms** |

### Recommended filter strategies for common workflows

**Watchlist screening** – pair with the topic that defines your watchlist:

```bash
openaleph-search percolate -i incoming.txt \
  --args "filter:topics=role.pep&highlight=true"
```

**Sanctions screening** – same pattern with the sanction topic:

```bash
openaleph-search percolate -i incoming.txt \
  --args "filter:topics=sanction&highlight=true"
```

**Multi-dataset deployments** – when you maintain several distinct percolatable datasets, scope to the one you actually want to screen against:

```bash
openaleph-search percolate -i incoming.txt \
  --args "filter:dataset=peps_watchlist&highlight=true"
```

**Schema-scoped screening** – restrict to one schema if your workflow only cares about people or only about companies:

```bash
openaleph-search percolate -i incoming.txt \
  --args "filter:schema=Person&filter:topics=role.pep"
```

**Multi-scope screening** – if you want to screen against several narrow scopes (e.g. PEPs *and* sanctions *and* wanted persons), running them as **separate percolate requests in parallel** and merging client-side is faster than one unscoped request, because each scoped request hits its own pruned candidate set.

## Limits and trade-offs

### Recall is bounded by the entity's stored names

The stored query is a `match_phrase` over `content`, built from the entity's `names` group (FtM `name` + `alias` + `previousName` etc.).

Variants the entity doesn't know about won't be matched: a doc that says `"Müller"` against an entity stored only as `"Mueller"` will not fire. Phonetic, transliteration, and name-symbol fuzzy matching (which the [matching](./matching.md) flow uses for entity-to-entity comparison) is not part of the percolator path.

If you need rich variants, encode them as entity aliases explicitly.

### Indexing cost

Every entity in the things bucket now also stores a parsed percolator query. ES has to compile it on write, and entity write throughput goes down somewhat. Acceptable for most workflows; benchmark on your hot path if it matters.

### Memory at percolate time

ES caches parsed percolator queries in heap when percolating. The candidate-selection optimization built into the percolator type narrows the set of stored queries that get re-evaluated, but on long percolated documents the surviving candidate set can still be tens of thousands per shard for an index with millions of stored queries – enough to dominate latency. See the [Performance](#performance) section above for the recommended filter-based mitigation.

### Things bucket only

Documents, Pages, and Intervals never get a `query` field. They have no matchable names, and percolator-style "is this entity mentioned" matching is not meaningful for them.

### Short single-token names are dropped

See [Signal cleaning](#signal-cleaning). If a watchlist needs to match a short single-token name reliably, store it as part of a longer phrase (e.g. `"Acme Corporation"` instead of `"Acme"`).
