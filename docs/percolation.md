# Percolation

Find entities mentioned in an arbitrary text by percolating the document against the stored entity index.

[Read more in the Elasticsearch percolator documentation](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-percolate-query)

!!! info "Reverse search"
    Where a normal search runs *one query against many documents*, percolation runs *one document against many stored queries*. Each entity in the things bucket carries its own stored percolator query (built from its name variants at index time), so percolating a document is the same as asking "which of my entities are mentioned in this text?"

!!! warning "Globally opt-in"
    Percolation is **disabled by default**. Enable it by setting `OPENALEPH_SEARCH_PERCOLATION=1` (or `percolation: true` in your `.env`). When disabled, the entity transform skips writing the `query` field on new entities, and `PercolatorQuery.search()` short-circuits to an empty response.

## How it works

There is **no separate percolator index**. The `query` field of ES type `percolator` lives directly on each entity in the things bucket (`{prefix}-entity-things-v1`). At index time, the entity transform builds a `bool.should` of `match_phrase` clauses – one per cleaned name variant *and* one per cleaned identifier value – and stores it on the entity.

Two signal types live in the same stored query:

- **Names** are matched with `slop: 2` – tolerant of inserted middle initials (`"Jane Doe"` matches `"Jane A. Doe"`), reversed last-name-first variants (`"Doe, Jane"`), and small token gaps. Performance is essentially the same as `slop: 1`; both fall off the `index_phrases` shingle fast path that `slop: 0` uses, so once you're paying the slop cost the value itself is free.
- **Identifiers** (the `registry.identifier` group: IMO numbers, VATs, registration numbers, passport numbers, etc.) are matched with `slop: 0` – they must appear exactly as stored. Identifiers should never tolerate token reordering.

Each clause is tagged with `_name: "name"` or `_name: "identifier"` so the percolate response can surface *which* signal fired per hit (see [Match signal types](#match-signal-types) below).

Percolating a document is then a normal entity search against the things bucket with three extra ingredients:

1. A `percolate` clause inside the bool query, supplying the input text as the percolated document.
2. The whole inner query is wrapped in `constant_score.filter` – ES skips relevance scoring entirely. All hits get the same `_score`. Downstream apps decide their own weighting from the named-query signal types.
3. An **opt-in** highlight on the `content` field, gated on the standard `highlight=true` parser arg (same as every other query in this codebase). When enabled, the format mirrors `EntitiesQuery` highlights – a `highlight.content` list of fragment snippets with `<em>…</em>` markup. `parser.highlight_count` controls the fragment count (default 3). The whole `highlight` block stays on each hit, *and* the marked phrases are also parsed into a `surface_forms` list on `_source` as a convenience for callers that only need the matched strings without surrounding context.

When `highlight=true` is **not** set (the default), ES skips the highlighter entirely. The hit has no `highlight` block, and `_source.surface_forms` is empty for every hit. `_source.percolator_match` is independent of highlights and continues to populate correctly in both modes – it comes from `hit.fields._percolator_document_slot_0_matched_queries`, not from the highlight.

## Signal cleaning

The transform runs both signal lists through dedicated cleaners (`openaleph_search/transform/util.py`) before building the stored query.

### Names – `clean_percolator_names`

- **Multi-token names** are kept as-is (e.g. `"Jane Doe"`, `"J. Doe"`, `"Acme Corporation"`). Phrase matching is specific enough.
- **Single-token names** are kept only if they are at least **7 characters** long (e.g. `"Microsoft"` is kept, `"Acme"` is dropped). Short single tokens produce too many false positives when matched against arbitrary prose.
- **Empty / whitespace-only** entries are dropped.

### Identifiers – `clean_percolator_identifiers`

- **Strip whitespace** and drop empty entries.
- **Drop very short identifiers** (< 5 characters), which are too generic to be useful as percolator triggers (`"GB"`, `"X1"`, …).

Entities whose cleaned name *and* identifier lists are both empty get *no* `query` field at all and stay out of the percolator candidate set. An entity with only a usable identifier (and no usable name) is still percolatable.

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
    "percolator_match": ["identifier"]
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
          "surface_forms": ["9123456"],
          "percolator_match": ["identifier"]
        },
        "highlight": {
          "content": [
            "The vessel <em>9123456</em> was sighted near the canal."
          ]
        }
      }
    ]
  }
}
```

A hit matched by both signals would have `"percolator_match": ["identifier", "name"]`. The `_score` is constant (`1.0`) for every hit because the inner query is wrapped in `constant_score` – server-side ranking is disabled by design.

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

# Filter to high-confidence (identifier-matched) hits only:
high_confidence = [
    hit for hit in result["hits"]["hits"]
    if "identifier" in hit["_source"]["percolator_match"]
]
```

Standard parser knobs flow through automatically:

- `filter:*` – applied as filters on the entity search (dataset, countries, schema, etc.).
- `dehydrate=true` – strips the bulky `properties` field from the response.
- `limit` / `offset` – pagination over the entity results.
- `sort` – overrides the default `_score` sort. Note that `_score` is constant under the percolator (see [Match signal types](#match-signal-types) below), so you'll usually want to either sort by another field or sort client-side using `percolator_match`.
- `auth` – same auth filters as any other entity query.

## Match signal types

Each clause in the stored percolator query is tagged with a `_name` of either `"name"` or `"identifier"`. When the percolator fires, ES surfaces the tags of the matching clauses per hit, and `PercolatorQuery.search` post-processes them into a `percolator_match` list on the hit's `_source`:

| `percolator_match` | What it means | Confidence |
|---|---|---|
| `["name"]` | Only a name variant fired. The doc mentions a string that matches one of the entity's names. | Medium – names can collide ("John Smith" matches everywhere). |
| `["identifier"]` | Only an identifier fired. The doc mentions a string that exactly matches one of the entity's identifiers (IMO, VAT, registration number, …). | High – identifiers are essentially unique. |
| `["identifier", "name"]` | Both a name and an identifier matched (deduped, sorted alphabetically). | Highest. |

There is **no server-side ranking** of these signal types. ES wraps the percolate query in `constant_score`, so every hit shares the same `_score` and ES doesn't pay the CPU cost of deserializing matched stored queries to compute relevance. Downstream apps consume `percolator_match` directly and decide their own weighting / filtering – for example, only surfacing identifier-matched hits as alerts, or scoring name+identifier hits higher than name-only hits in a UI.

This is a deliberate trade-off: scoring is cheap to do client-side and expensive to do server-side at percolate scale, and the static `_name` tags carry all the information a downstream weighting function needs.

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

### Recall is bounded by the entity's stored signals

The stored query is a `match_phrase` over `content`, built from the entity's `names` group (FtM `name` + `alias` + `previousName` etc.) and the entity's `registry.identifier` properties (`registrationNumber`, `vatNumber`, `imoNumber`, `passportNumber`, etc.).

Variants the entity doesn't know about won't be matched: a doc that says `"Müller"` against an entity stored only as `"Mueller"` will not fire, and a doc that says `"FR-12345678"` against an entity stored as `"FR12345678"` will not fire either (since the analyzer tokenizes them differently). Phonetic, transliteration, and name-symbol fuzzy matching (which the [matching](./matching.md) flow uses for entity-to-entity comparison) is not part of the percolator path.

If you need rich variants, encode them as entity aliases or as additional identifier values explicitly.

### Indexing cost

Every entity in the things bucket now also stores a parsed percolator query. ES has to compile it on write, and entity write throughput goes down somewhat. Acceptable for most workflows; benchmark on your hot path if it matters.

### Memory at percolate time

ES caches parsed percolator queries in heap when percolating. The candidate-selection optimization built into the percolator type narrows the set of stored queries that get re-evaluated, but on long percolated documents the surviving candidate set can still be tens of thousands per shard for an index with millions of stored queries – enough to dominate latency. See the [Performance](#performance) section above for the recommended filter-based mitigation.

### Things bucket only

Documents, Pages, and Intervals never get a `query` field. They have no matchable names, and percolator-style "is this entity mentioned" matching is not meaningful for them.

### Short single-token names and short identifiers are dropped

See [Signal cleaning](#signal-cleaning). If a watchlist needs to match a short single-token name reliably, store it as part of a longer phrase (e.g. `"Acme Corporation"` instead of `"Acme"`). Short identifiers (< 5 chars) are dropped for the same reason – they're too generic to be useful percolator triggers.

### Identifiers must match exactly (no slop)

Identifier clauses use `slop: 0`, so a stored identifier value like `"DE HRB 12345"` will *not* match a document where its tokens are split across other words (e.g. `"filed in DE under HRB 12345"`). This is intentional: identifiers should never tolerate token reordering or insertions, where names tolerate `slop: 2` for minor variations like `"Jane A. Doe"` vs `"Jane Doe"`.

Single-token identifiers (the common case – IMO numbers, VAT numbers, passport numbers) are unaffected: there's nothing to slop over.
