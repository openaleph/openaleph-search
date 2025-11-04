# Facets & Aggregations

Analyze search results through aggregations to understand data distribution and patterns.

See [significant terms aggregations](./significant_terms.md) as well.

## Basic usage

```bash
# Single facet
openaleph-search search query-string "corruption" --args "facet=dataset"

# Multiple facets
openaleph-search search query-string "investigation" \
  --args "facet=dataset&facet=schema&facet=countries"
```

## Types

### Terms aggregations

Count distinct values in keyword fields.

```bash
openaleph-search search query-string "corruption" \
  --args "facet=dataset&facet=schema"
```

### Cardinality aggregations

Get total count of distinct values.

```bash
openaleph-search search query-string "investigation" \
  --args "facet=countries&facet_total:countries=true"
```

### Date histogram aggregations

Group results by time intervals.

```bash
openaleph-search search query-string "transaction" \
  --args "facet=created_at&facet_interval:created_at=month"
```

## Parameters

### `facet`

Field name to facet on.

```bash
--args "facet=schema"
```

### `facet_size:FIELD`

Number of values to return (default: 20).

```bash
--args "facet=countries&facet_size:countries=50"
```

### `facet_total:FIELD`

Include total distinct count.

```bash
--args "facet=languages&facet_total:languages=true"
```

### `facet_values:FIELD`

Return actual values (default: true).

```bash
# Only counts, no values
--args "facet=entities&facet_values:entities=false&facet_total:entities=true"
```

### `facet_interval:FIELD`

Time interval for date fields.

```bash
--args "facet=created_at&facet_interval:created_at=month"
```

Intervals: `year`, `quarter`, `month`, `week`, `day`, `hour`, `minute`

### `facet_type:FIELD`

Aggregation type for special fields.

```bash
--args "facet=properties.entity&facet_type:properties.entity=entity"
```

## Response format

Aggregations appear in the `aggregations` section:

```json
{
  "hits": {...},
  "aggregations": {
    "dataset.values": {
      "buckets": [
        {"key": "panama_papers", "doc_count": 1250},
        {"key": "paradise_papers", "doc_count": 890}
      ]
    },
    "schema.cardinality": {
      "value": 12
    },
    "created_at.intervals": {
      "buckets": [
        {
          "key": 1609459200000,
          "key_as_string": "2021-01-01",
          "doc_count": 145
        }
      ]
    },
    "names.significant_terms": {
      "buckets": [
        {
          "key": "mossack fonseca",
          "doc_count": 25,
          "score": 0.8745,
          "bg_count": 100
        }
      ]
    }
  }
}
```

## Common fields

Apart from the common group fields, individual [FollowTheMoney](https://followthemoney.tech) properties can be used as well via `properties.<prop>`

### Entity fields

- `schema` - Entity schema type
- `schemata` - Schema inheritance (e.g. `schemata=LegalEntity` includes all its descendants)
- `dataset` - Dataset identifier

### Group fields

[FollowTheMoney property types](https://followthemoney.tech/explorer/types/)

These groups are part of the index as keyword fields:

- `addresses`
- `checksums`
- `countries`
- `dates`
- `emails`
- `entities`
- `genders`
- `identifiers`
- `ips`
- `languages`
- `mimetypes`
- `names`
- `phones`
- `topics`
- `urls`

### Name fields

- `names` - Normalized entity names (includes the NER mentions from [`Analyzable`](https://followthemoney.tech/explorer/schemata/Analyzable/) entities.)
- `name_symbols` - Name symbols (extracted from `names`)

## Date histograms

[See allowed interval values](https://www.elastic.co/docs/reference/aggregations/search-aggregations-bucket-datehistogram-aggregation#calendar_intervals)

### Calendar intervals

```bash
openaleph-search search query-string "transaction" \
  --args "facet=dates&facet_interval:dates=month"
```

Example values: `year`, `quarter`, `month`, `week`, `day`

### Fixed intervals

```bash
openaleph-search search query-string "activity" \
  --args "facet=dates&facet_interval:dates=30d"
```

Examples: `1h`, `15m`, `7d`, `1M`

### Date range with histogram

```bash
openaleph-search search query-string "event" \
  --args "filter:gte:properties.startDate=2020-01-01&filter:lte:properties.startDate=2023-12-31&facet=properties.startDate&facet_interval:properties.startDate=quarter"
```

Includes empty buckets within range.

## Post-filters

Each facet excludes its own filters to show alternative options:

```bash
# Dataset facet shows ALL datasets, not just filtered ones
openaleph-search search query-string "company" \
  --args "filter:dataset=collection1&filter:dataset=collection2&facet=dataset"
```

This allows users to see alternative filter options.

## Performance

### Execution strategy

All facets use `execution_hint: map` for keyword fields.

### High cardinality

Fields with many unique values:

- Use facet size limits
- Monitor query performance
- Consider sampling for large datasets

## Examples

### Multi-facet analysis

```bash
openaleph-search search query-string "investigation" \
  --args "facet=dataset&facet=schema&facet=countries&facet=created_at&facet_interval:created_at=month"
```

### Document classification

```bash
openaleph-search search query-string "*" \
  --args "filter:schemata=Document&facet=properties.mimeType&facet=languages&facet_size:properties.mimeType=100"
```

### Entity network

```bash
openaleph-search search query-string "person" \
  --args "filter:schema=Person&facet=dataset&facet=countries"
```

### Temporal trends

```bash
openaleph-search search query-string "company" \
  --args "facet=schema&facet=created_at&facet_interval:created_at=year&facet_size:schema=50"
```

## Error handling

### Invalid fields

Non-existent fields return empty results:

```json
{
  "aggregations": {
    "nonexistent_field.values": {
      "buckets": []
    }
  }
}
```

### Type mismatches

Requesting histograms on non-date fields falls back to term aggregation.

### Authorization failures

Restricted fields return empty results while maintaining query functionality.
