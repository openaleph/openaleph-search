# Percolation

Find entities of interest mentioned in an arbitrary text by running the document
*against* a set of stored name queries, then resolving the matches back to real
FtM entities in the index.

[Read more in the Elasticsearch percolator documentation](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-percolate-query)

!!! info "Reverse search"
    Where a normal search runs *one query against many documents*, percolation
    runs *one document against many stored queries*. This makes it well suited
    to monitoring or screening workflows where you have a watchlist of named
    entities and want to know which ones are mentioned in incoming text.

## How it works

Percolation is a two-phase pipeline:

1. **Percolate** – the input text is matched against the stored percolator
   index. Each stored query is a `match_phrase` query (with a small slop) over
   the document content built from a list of names. Highlighting is enabled on
   the same request, so each percolator hit also carries the actual *surface
   form(s)* the document used for that match – not just the names the query
   was originally configured with.
2. **Resolve** – for each percolator hit, the surface forms are looked up in
   the entity index (`things` bucket) via [`names_query`](./matching.md), with
   the percolator hit's `countries` and `schemata` (if any) applied as soft
   scoring boosts rather than hard filters. The matched entities across all
   percolator hits are deduped, sorted by score, and returned in the same shape
   as a regular entity search.

The whole pipeline costs two Elasticsearch round-trips: one `_search` against
the percolator index in phase 1, and one `_msearch` against the things bucket
in phase 2 (one body per percolator hit).

## Stored percolator queries

A stored percolator query is described by a `PercolatorDoc`:

```python
from openaleph_search.model import PercolatorDoc

PercolatorDoc(
    key="acme-corp",
    names=["Acme Corporation", "ACME Corp"],
    countries=["us"],     # optional
    schemata=["Company"], # optional
)
```

Fields:

- `key` – stable identifier for the stored query (becomes the percolator
  document `_id`).
- `names` – list of name variants. Each variant becomes a `match_phrase` clause
  in the stored query. See [Name cleaning](#name-cleaning) below.
- `countries` *(optional)* – country scope. Used by the `percolate` step to
  restrict which stored queries fire (queries with no `countries` always
  fire, queries with `countries` set only fire if the percolation request also
  specifies a matching country). Used by the `resolve` step as a soft scoring
  boost.
- `schemata` *(optional)* – same semantics as `countries`, but for FtM schema
  scoping.

### Name cleaning

`PercolatorDoc.names` runs through a Pydantic validator that drops names too
noisy to percolate:

- Multi-token names (e.g. `"Jane Doe"`, `"J. Doe"`) are kept as-is – phrase
  matching is specific enough.
- Single-token names are kept only if they are at least 7 characters long
  (e.g. `"Microsoft"` is kept, `"Acme"` is dropped). Short single tokens
  produce too many false positives when matched against arbitrary prose.
- Empty / whitespace-only entries are dropped.

```python
PercolatorDoc(key="x", names=["Jane Doe", "Doe", "Microsoft", "Acme"])
# → names = ["Jane Doe", "Microsoft"]
```

## Indexing percolator queries

Use the `load-percolator` CLI command. It reads a JSON-lines stream of objects
matching the `PercolatorDoc` shape and bulk-upserts them into the percolator
index.

```bash
openaleph-search load-percolator -i queries.jsonl
```

Each line in `queries.jsonl`:

```json
{"key": "jane-doe",  "names": ["Jane Doe", "J. Doe"]}
{"key": "acme-corp", "names": ["Acme Corporation", "ACME Corp"], "countries": ["us"], "schemata": ["Company"]}
```

To clear all stored percolator queries:

```python
from openaleph_search.index.percolator import delete_all_queries
delete_all_queries(sync=True)
```

## Querying

There are two CLI modes, depending on whether you want only the matched
percolator hits or also their resolved entities.

### Phase 1 only – raw percolation

```bash
openaleph-search percolate -i document.txt
```

Returns the raw percolation response. Each hit's `_source` carries:

- `surface_forms` – the actual span(s) the document used (parsed from the
  percolator highlight, deduped, sorted).
- `countries`, `schemata` – passed through from the stored query if set.

```json
{
  "hits": {
    "total": {"value": 2, "relation": "eq"},
    "hits": [
      {
        "_id": "jane-doe",
        "_index": "openaleph-percolator-v1",
        "_source": {"surface_forms": ["J. Doe"]}
      },
      {
        "_id": "acme-corp",
        "_index": "openaleph-percolator-v1",
        "_source": {
          "surface_forms": ["Acme Corporation"],
          "countries": ["us"],
          "schemata": ["Company"]
        }
      }
    ]
  }
}
```

### Phase 1 + 2 – resolve to entities

Add `--resolve` to also run the entity-side `_msearch` and return matched FtM
entities:

```bash
openaleph-search percolate -i document.txt --resolve
```

The response shape now mirrors a regular entity search response (`hits.hits[]`
of unpacked entities). Each entity carries an extra `percolator` block in its
`_source` recording which stored queries matched it and with what surface form:

```json
{
  "took": 12,
  "hits": {
    "total": {"value": 2, "relation": "eq"},
    "max_score": 5.0,
    "hits": [
      {
        "_id": "id-company",
        "_index": "openaleph-entity-things-v1",
        "_score": 5.0,
        "_source": {
          "schema": "Company",
          "caption": "KwaZulu",
          "properties": {"name": ["KwaZulu"]},
          "percolator": {
            "keys": ["kwazulu-company"],
            "surface_forms": ["KwaZulu"]
          }
        }
      }
    ]
  }
}
```

If the same entity is matched by multiple percolator hits it appears once,
with all matching keys and surface forms accumulated under
`_source.percolator`, and the score widened to the maximum across hits.

## CLI parameters

```bash
openaleph-search percolate -i <text> [OPTIONS]
```

| Option | Type | Default | Description |
|---|---|---|---|
| `-i` | path | stdin | Input document text |
| `-o` | path | stdout | Output destination |
| `--country` | str (repeatable) | – | Phase 1: only fire stored queries scoped to a matching country (or unscoped) |
| `--schema` | str (repeatable) | – | Phase 1: only fire stored queries scoped to a matching schema (or unscoped) |
| `--size` | int | `100` | Phase 1: maximum number of percolator hits to return |
| `--resolve` / `--no-resolve` | bool | `--no-resolve` | Run phase 2 (entity resolution) |
| `--resolve-size` | int | `10` | Phase 2: max entities returned (after dedupe) |
| `--dehydrate` / `--no-dehydrate` | bool | `--no-dehydrate` | Phase 2: strip the bulky `properties` field from resolved entities |

The `--country` and `--schema` flags affect phase 1 (which stored queries
fire). They have *no effect* on phase 2 – entity resolution always queries
the things bucket and uses the percolator hit's metadata as a soft scoring
boost only.

## Programmatic use

For non-CLI callers, the canonical interface is the `PercolatorQuery` class.
It inherits from `EntitiesQuery`, so it slots into existing code that consumes
the standard `Query.search()` contract:

```python
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.queries import PercolatorQuery

parser = SearchQueryParser([("limit", "20"), ("dehydrate", "true")])
query = PercolatorQuery(parser, text=document_text)
result = query.search()

for hit in result["hits"]["hits"]:
    entity = hit["_source"]
    print(entity["caption"], entity["percolator"]["keys"])
```

Standard parser knobs flow through:

- `limit` / `offset` – applied to the final deduped entity list.
- `dehydrate` – strips `properties` from resolved entities.
- `filter:countries` / `filter:schemata` – applied to *phase 1* (which stored
  queries fire). They become the `--country` / `--schema` CLI args.

The lower-level `percolate()` function in
`openaleph_search.index.percolator` runs phase 1 only and returns the raw
Elasticsearch response.

## Resolution scoring

The phase 2 query applied to each percolator hit's surface forms looks like:

```json
{
  "bool": {
    // Names are mandatory: at least one names_query clause must fire.
    "must": [{
      "bool": {
        "should": [<names_query(LegalEntity, surface_forms) clauses>],
        "minimum_should_match": 1
      }
    }],
    // Country and schema are score-only soft boosts. They live at the outer
    // bool's `should` level so they contribute to _score without being
    // counted toward minimum_should_match.
    "should": [
      {"terms": {"countries": ["us"],     "boost": 2.0}},
      {"terms": {"schema":    ["Person"], "boost": 2.0}}
    ]
  }
}
```

The inner-bool wrapping is what keeps the names match mandatory. If country
and schema sat at the outer `should` together with the name clauses, a
country-only match could satisfy `minimum_should_match: 1` with no name
match at all.

The result: an entity with the right name from the wrong country *still
shows up*, just at a lower score than an entity with both the right name
and the right country.

The `names_query` itself is the same one used by [entity matching](./matching.md)
– see that page for the full description of the name fields and boosts.

## Index

Stored percolator queries live in their own dedicated index:

```
{prefix}-percolator-v1
```

The index uses a single shard (percolator queries are usually a small set
relative to entity data). Mappings are configured via
`openaleph_search.index.percolator.configure_percolator`, which is invoked by
`openaleph-search upgrade` alongside the entity indexes.

## Limits and trade-offs

- **Phase 1 size cap**: `--size` / `percolate_size` caps the number of stored
  queries that can fire on a single document. Increase if your watchlist is
  larger than the default 100.
- **Phase 2 size cap**: `--resolve-size` / `parser.limit` caps the number of
  entities per per-hit `_msearch` body. Some hits get deduped, so the final
  list is sliced to `parser.limit` after aggregation.
- **Entity bucket**: phase 2 only queries the `things` bucket
  (`LegalEntity` and descendants). Documents, pages, and intervals are never
  searched, since percolator-style name matching is not meaningful for those
  schemata.
- **Short single-token names**: dropped at validation time. If you need to
  match a short single token, combine it with another token (e.g. `"Acme"` →
  `"Acme Corporation"`).
