# Index Mapping

Elasticsearch index structure, field types, and analyzers used in openaleph-search.

## Index buckets

Entities are organized into buckets based on schema type:

| Bucket | Schemas | Purpose |
|--------|---------|---------|
| `things` | [Thing and descendants](https://followthemoney.tech/explorer/schemata/Thing/) | Entities ([Person](https://followthemoney.tech/explorer/schemata/Person/), [Company](https://followthemoney.tech/explorer/schemata/Company/), ...) |
| `intervals` | [Interval and descendants](https://followthemoney.tech/explorer/schemata/Interval/) | Time-based entity connections ([Ownership](https://followthemoney.tech/explorer/schemata/Ownership/), [Sanction](https://followthemoney.tech/explorer/schemata/Sanction/), ...) |
| `documents` | [Document and descendants](https://followthemoney.tech/explorer/schemata/Document/) | File-like entities with full-text |
| `pages` | [Pages](https://followthemoney.tech/explorer/schemata/Pages/) | Multi-page (Word/PDF) documents with full-text |
| `page` | [Page](https://followthemoney.tech/explorer/schemata/Page/) | Single page entities (children of `Pages`) for page-level lookups |

Index names follow the pattern: `{prefix}-entity-{bucket}-{version}`

Example: `openaleph-entity-things-v1`

### Shard distribution

Different buckets get different shard allocations:

- `documents`, `pages`: Full configured shards (default: 10)
- `things`: 50% of configured shards (default: 5)
- `intervals`: 33% of configured shards (default: 3)

Set via `OPENALEPH_SEARCH_INDEX_SHARDS` environment variable.

!!! info "What's the best number here?"
    It is hard to predict how many shards an index needs. Best practice is shard sizes between 15-50 GB. Monitor your cluster and adjust the number of shards. This requires re-indexing with the new sharding configuration.

## Analyzers

For the `content` (full-text) field, the [ICU analysis plugin](https://www.elastic.co/docs/reference/elasticsearch/plugins/analysis-icu) is used and needs to be installed. openaleph-search ships with a customized [docker image](https://github.com/openaleph/openaleph-search/pkgs/container/elasticsearch) that includes the plugin.

### Text analyzers

**icu-default** - Primary text analysis

- Tokenizer: `icu_tokenizer`
- Character filters: `html_strip`
- Token filters: `icu_folding`, `icu_normalizer`
- Purpose: Unicode-aware multilingual text analysis

**strip-html** - HTML content analysis

- Tokenizer: `standard`
- Character filters: `html_strip`
- Token filters: `lowercase`, `asciifolding`, `trim`
- Purpose: HTML stripping with ASCII normalization

### Normalizers

**icu-default** - ICU folding

- Filter: `icu_folding`
- Purpose: Unicode normalization for keywords

**name-kw-normalizer** - Aggressive name normalization

- Character filters: Remove punctuation, collapse whitespace
- Filters: `lowercase`, `asciifolding`, `trim`
- Purpose: Name keyword normalization for aggregations

**kw-normalizer** - Minimal normalization

- Filter: `trim`
- Purpose: Basic keyword cleanup

### Character filters

- **remove_punctuation**: Pattern `[^\p{L}\p{N}]` → space
- **squash_spaces**: Pattern `\s+` → single space

## Base fields

Core fields present in all entities:

### Identity

| Field | Type | Description |
|-------|------|-------------|
| `dataset` | keyword | Dataset identifier |
| `collection_id` | keyword | [OpenAleph](https://openaleph.org) Collection ID |
| `schema` | keyword | Primary schema name |
| `schemata` | keyword | All schema names (including ancestors) |
| `caption` | keyword | Display label |

### Names

| Field | Type | Purpose |
|-------|------|---------|
| `name` | text | Original names (full-text search) |
| `names` | keyword | Normalized keywords (aggregation) |
| `name_keys` | keyword | Sorted tokens (deduplication) |
| `name_parts` | keyword | Individual tokens (partial matching) |
| `name_symbols` | keyword | Name symbols (cross-language) |
| `name_phonetic` | keyword | Phonetic codes (sound-alike) |

### Entity data / Content

| Field | Type | Purpose |
|-------|------|---------|
| `properties.*` | mixed | _(see below)_ |
| `content` | text | Primary text content |
| `text` | text | Secondary text content |

### Geographic

| Field | Type | Description |
|-------|------|-------------|
| `geo_point` | geo_point | Latitude/longitude coordinates |

### Metadata

| Field | Type | Indexed | Description |
|-------|------|---------|-------------|
| `referents` | keyword | yes | Entity references |
| `origin` | keyword | yes | Data source origin |
| `created_at` | date | Creation timestamp |
| `updated_at` | date | Last modification |
| `first_seen` | date | First occurrence |
| `last_seen` | date | Last occurrence |
| `last_change` | date | Last content change |
| `num_values` | integer | yes | Property value count |
| `index_bucket` | keyword | no | Bucket type |
| `index_version` | keyword | no | Index version |
| `indexed_at` | date | yes | Index timestamp |

## Field type configurations

### Content field

```json
{
  "type": "text",
  "analyzer": "icu-default",
  "index_phrases": true,
  "term_vector": "with_positions_offsets",
  "store": false
}
```

- `index_phrases`: Enable phrase queries
- `term_vector`: Required for fast vector highlighter (if enabled via settings)
- `store`: true only for pages bucket

### Name field

```json
{
  "type": "text",
  "analyzer": "icu-default",
  "similarity": "weak_length_norm",
  "store": true
}
```

- `similarity`: BM25 with `b=0.25` (reduced length penalty)
- `store`: Enabled for highlighting on this field

### Name keyword field

```json
{
  "type": "keyword",
  "normalizer": "name-kw-normalizer",
  "store": true
}
```

### Date fields

```json
{
  "type": "date",
  "format": "yyyy-MM-dd'T'HH||yyyy-MM-dd'T'HH:mm||yyyy-MM-dd'T'HH:mm:ss||yyyy-MM-dd||yyyy-MM||yyyy||strict_date_optional_time"
}
```

Supports multiple precisions:
- Full timestamp: `2023-12-25T14:30:45`
- Date: `2023-12-25`
- Month: `2023-12`
- Year: `2023`

## Property fields

Entity properties are stored under `properties.*`:

- `properties.birthDate`
- `properties.nationality`
- `properties.address`

### Property type mapping

Follow the Money property types map to Elasticsearch types:

| FtM Type | ES Type | Notes |
|----------|---------|-------|
| `text` | text | Not indexed |
| `html` | text | Not indexed |
| `json` | text | Not indexed |
| `date` | date | With flexible format |
| Others | keyword | Default |

### Copy-to mechanism

Properties are copied to aggregation fields:

- `text` type properties → copied to `content`
- Other properties → copied to `text`
- Properties with type groups → copied to group field

Example:
```
properties.nationality → text + countries (group field)
properties.bodyText → content
properties.email → text + emails (group field)
```

## Group fields

Follow the Money type groups create unified aggregation fields:

| Group | Type | Example Properties |
|-------|------|-------------------|
| `countries` | keyword | nationality, jurisdiction |
| `languages` | keyword | language |
| `emails` | keyword | email |
| `phones` | keyword | phone |
| `dates` | date | birthDate, startDate |
| `addresses` | text | address |

## Numeric fields

Numeric properties are duplicated in the `numeric` object for efficient sorting:

```json
{
  "numeric": {
    "properties": {
      "dates": {"type": "double"},
      "birthDate": {"type": "double"},
      "amount": {"type": "double"}
    }
  }
}
```

Numeric types: `registry.number`, `registry.date`

Dates are stored as Unix timestamps (seconds since epoch).

## Similarity configuration

### weak_length_norm

BM25 similarity with reduced length normalization:

```json
{
  "similarity": {
    "weak_length_norm": {
      "type": "BM25",
      "b": 0.25
    }
  }
}
```

- Default BM25 `b`: 0.75
- Reduced `b`: 0.25
- Purpose: Don't penalize merged entities with many names
- Applied to: `name` field only

## Index settings

### Source exclusion

Fields excluded from stored `_source` to reduce index size:

Fields remain searchable but are not returned in results.

```json
{
  "_source": {
    "excludes": [
      "content", "text", "name",
      "name_keys", "name_parts", "name_symbols", "name_phonetic"
    ]
  }
}
```

Also excludes all group fields (countries, emails, etc.).


### Refresh interval

```json
{
  "index": {
    "refresh_interval": "1s"
  }
}
```

Configurable via `OPENALEPH_SEARCH_INDEX_REFRESH_INTERVAL`.

Set to `-1` during bulk indexing for better performance.

## Derived fields

When indexing, these fields are computed:

| Field | Source | Processing |
|-------|--------|-----------|
| `name_keys` | Entity names | Sort ASCII tokens, concatenate (>5 chars) |
| `name_parts` | Entity names | Tokenize, keep tokens ≥2 chars |
| `name_phonetic` | Entity names | Metaphone encoding (≥3 chars) |
| `name_symbols` | Entity schema | Pattern extraction |
| `numeric.*` | Properties | Type-specific conversion |
| `geo_point` | Properties | Lat/lon pair extraction |
| `num_values` | All properties | Total value count |

## Performance considerations

Why are we indexing some properties in multiple fields via `copy_to` ?

### Storage optimization

- Source excludes reduce index size
- Only essential fields stored
- Search fields reconstructed on query

### Query optimization

- Numeric duplicates enable efficient sorting
- Group fields reduce cross-property query complexity
- Copy-to eliminates multi-field queries

### Analysis performance

- ICU analyzer: Better Unicode support
- Name normalization: Improved deduplication
- Term vectors: Fast highlighting (if enabled) and better [more like this](../more_like_this.md)

## Index management

### Replication

Default: 0 replicas. Replication allows node failure (if using more than 1 node) and improves search speed.

Production: Set via `OPENALEPH_SEARCH_INDEX_REPLICAS`

### Versioning

Use `index_write` and `index_read` settings for rolling deployments:

```bash
# Phase 1: Write to v2, read from v1 and v2
export OPENALEPH_SEARCH_INDEX_WRITE=v2
export OPENALEPH_SEARCH_INDEX_READ=v1,v2

# Phase 2: Switch to v2 only
export OPENALEPH_SEARCH_INDEX_READ=v2
```

Enables zero-downtime migrations.
