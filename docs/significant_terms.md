# Significant Terms

Discover statistically unusual terms and phrases by comparing search results against background datasets.

[Read more in Elasticsearch documentation](https://www.elastic.co/docs/reference/aggregations/search-aggregations-bucket-significantterms-aggregation)

[Blog post for discovery in OpenAleph](https://openaleph.org/blog/2025/09/Behind-the-Update/86038fe7-a661-4eeb-a274-82321e156caa/)

## What is significant analysis

Significant analysis identifies terms that appear more frequently in search results than expected based on the background dataset. This surfaces important concepts that distinguish your results.

## Significant terms

Find keywords over-represented in search results.

### Basic usage

```bash
# Find significant mentions in names
openaleph-search search query-string "corruption" --args "facet_significant=names"

# Multiple fields
openaleph-search search query-string "investigation" \
  --args "facet_significant=names&facet_significant=countries"
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `facet_significant` | string | - | Field name |
| `facet_significant_size:FIELD` | int | 20 | Number of terms |
| `facet_significant_total:FIELD` | bool | false | Include total count |
| `facet_significant_values:FIELD` | bool | true | Return values |
| `facet_significant_type:FIELD` | string | - | Aggregation type |

### Response structure

```json
{
  "aggregations": {
    "names.significant_terms": {
      "buckets": [
        {
          "key": "jane doe",
          "doc_count": 45,
          "score": 0.8745,
          "bg_count": 120
        }
      ]
    }
  }
}
```

- `score`: Statistical significance (0-1, higher = more unusual)
- `doc_count`: Frequency in search results
- `bg_count`: Frequency in background dataset
- `key`: The significant term

## Significant text

Extract meaningful phrases from text content.

### Basic usage

```bash
# Analyze document content
openaleph-search search query-string "laundering" \
  --args "facet_significant_text=content"

# Custom configuration
openaleph-search search query-string "investigation" \
  --args "facet_significant_text=content&facet_significant_text_size=10"
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `facet_significant_text` | string | content | Text field to analyze |
| `facet_significant_text_size` | int | 5 | Number of phrases |
| `facet_significant_text_min_doc_count` | int | 5 | Minimum document frequency |
| `facet_significant_text_shard_size` | int | 200 | Documents sampled per shard |


### Response structure

```json
{
  "aggregations": {
    "significant_text": {
      "significant_text": {
        "buckets": [
          {
            "key": "money laundering",
            "doc_count": 28,
            "score": 0.9156,
            "bg_count": 145
          }
        ]
      }
    }
  }
}
```

## Background filtering

Background datasets define the comparison baseline:

### Dataset-specific

When filtering by datasets:
```json
{
  "background_filter": {
    "terms": {"dataset": ["panama_papers", "paradise_papers"]}
  }
}
```

!!! info "OpenAleph"
    Currently, OpenAleph uses `collection_id` filter here with the numeric IDs instead.


### Full dataset

Without filters, uses entire accessible datasets.

## Sampling

### Significant text sampling

**Diversified sampling** (default):
```json
{
  "diversified_sampler": {
    "shard_size": 200,
    "field": "dataset"
  }
}
```

Samples across datasets for representative analysis.

**Regular sampling** (when filtering by dataset):
```json
{
  "sampler": {
    "shard_size": 200
  }
}
```

### Shard size calculation

For significant terms:
```
shard_size = max(100, requested_size * 5)
```

Ensures sufficient sampling for statistical significance.

## Interpretation

### Significance scores

Score ranges:

- **0.9+**: Highly significant
- **0.7-0.9**: Moderately significant
- **0.5-0.7**: Somewhat significant
- **<0.5**: Low significance

### Document counts

Consider both absolute and relative frequencies:

- High `doc_count` + high `score` = Important frequent term
- Low `doc_count` + high `score` = Rare but highly relevant
- High `doc_count` + low `score` = Common but not distinctive

### Background comparison

Compare `doc_count` vs `bg_count`:

- `doc_count` >> `bg_count` (relative to sizes) = Over-represented
- `doc_count` ≈ `bg_count` = Normal frequency

## Configuration

### Minimum document count

```bash
openaleph-search search query-string "report" \
  --args "facet_significant_text=content&facet_significant_text_min_doc_count=10"
```

Higher values focus on more frequent terms.

### Shard size tuning

```bash
openaleph-search search query-string "evidence" \
  --args "facet_significant_text=content&facet_significant_text_shard_size=500"
```

Larger sizes improve accuracy but increase query time.

### Duplicate filtering

Significant text automatically filters duplicate content to prevent skewing results.

## Examples

### Investigative journalism

```bash
# Key terms in corruption investigation
openaleph-search search query-string "minister" \
  --args "filter:countries=us&facet_significant=names&facet_significant_text=content"
```

### Document classification

```bash
# Discover PDF document themes
openaleph-search search query-string "*" \
  --args "filter:schema=Document&filter:properties.mimeType=application/pdf&facet_significant_text=content&facet_significant_text_size=15"
```

### Entity analysis

```bash
# Significant company attributes
openaleph-search search query-string "*" \
  --args "filter:schema=Company&facet_significant=countries&facet_significant=properties.sector"
```

### Temporal analysis

```bash
# Significant terms in time period
openaleph-search search query-string "event" \
  --args "filter:gte:dates=2016-01-01&filter:lt:dates=2017-01-01&facet_significant=names&facet_significant_text=content"
```

## Performance

### Sampling efficiency

Sampling balances performance and accuracy:

- Default 200 documents per shard
- Diversified sampling across datasets
- Configurable via shard_size parameters

### Query optimization

Monitor performance through:

- Query `took` times in responses
- Elasticsearch slow query logs
- Resource usage during aggregations

Adjust shard sizes and minimum document counts based on dataset characteristics.

## Error handling

### No results

Empty analysis returns appropriate structure:
```json
{
  "aggregations": {
    "names.significant_terms": {
      "buckets": []
    }
  }
}
```

### Field validation

- Non-existent fields return empty results
- Text analysis requires analyzable text fields (usually full text in `content` field)
- Terms analysis requires keyword fields

### Edge cases

- Very small datasets may not provide meaningful significance
- Single-document results cannot generate scores
- Cross-shard coordination ensures consistent sampling
