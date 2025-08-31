# Facets

Explore your search results by showing the distribution of values across different fields. Facets help you understand your data and refine searches.

## Quick Start

### Enabling Facets

Add the `facet` parameter to enable faceting on specific fields:

```bash
# Single facet
/search?q=corruption&facet=dataset

# Multiple facets
/search?facet=dataset&facet=schema&facet=countries
```

### Facet Response Structure

Facets appear in the `aggregations` section of search results:

```json
{
    "hits": {...},
    "aggregations": {
        "dataset.values": {
            "buckets": [
                {"key": "panama_papers", "doc_count": 1250},
                {"key": "paradise_papers", "doc_count": 890},
                {"key": "offshore_leaks", "doc_count": 654}
            ]
        }
    }
}
```

## Facet Configuration

### Facet Size

Control the number of facet values returned:

```bash
# Default: 20 values
/search?facet=countries&facet_size:countries=50
```

### Facet Totals

Get the total count of distinct values:

```bash
/search?facet=languages&facet_total:languages=true
```

Response includes cardinality aggregation:
```json
{
    "aggregations": {
        "languages.cardinality": {
            "value": 87
        }
    }
}
```

### Disable Facet Values

Return only counts without actual values:

```bash
/search?facet=entities&facet_values:entities=false&facet_total:entities=true
```

## Date Facets

Date fields support histogram aggregations for time-based analysis:

### Calendar Intervals

```bash
/search?facet=created_at&facet_interval:created_at=month
```

Supported intervals:

- `year`, `quarter`, `month`, `week`, `day`
- `hour`, `minute`, `second`

### Fixed Intervals

```bash
/search?facet=last_seen&facet_interval:last_seen=30d
```

Examples: `1h`, `15m`, `7d`, `1M`

### Date Facet Response

```json
{
    "aggregations": {
        "created_at.intervals": {
            "buckets": [
                {
                    "key": 1609459200000,
                    "key_as_string": "2021-01-01T00:00:00.000Z",
                    "doc_count": 145
                },
                {
                    "key": 1612137600000,
                    "key_as_string": "2021-02-01T00:00:00.000Z",
                    "doc_count": 98
                }
            ]
        }
    }
}
```

## Facet Filtering

Facets automatically exclude their own filters to show the impact of other filters:

```bash
# Searching for documents in multiple datasets
/search?filter:dataset=collection1&filter:dataset=collection2&facet=dataset
```

The dataset facet will show counts for ALL datasets, not just the filtered ones, allowing users to see alternative choices.

## Special Facet Types

### Entity Reference Facets

For fields containing entity references:

```bash
/search?facet=properties.entity&facet_type:properties.entity=entity
```

### Nested Field Facets

For nested document structures:

```bash
/search?facet=nested_field&facet_type:nested_field=nested
```

## Authorization and Facets

### Small Facets

These facets have relaxed limits for unauthenticated users:

- `schema` - Entity schema types
- `schemata` - Multiple schema types
- `dataset` - Dataset identifiers
- `countries` - Country codes
- `languages` - Language codes

### Authenticated vs Unauthenticated

**Unauthenticated users:**

- Limited to 50 values for non-small facets
- Cannot access total counts for large facets
- Results filtered by publicly accessible datasets

**Authenticated users:**

- Full access to configured facet sizes
- Can request total counts
- See results filtered by their permissions

### Dataset Authorization

When `search_auth` is enabled:

```python
# Facet results automatically filtered by user's dataset access
user_datasets = ["dataset1", "dataset2", "dataset3"]
# Facet results will only include values from these datasets
```

## Common Facet Fields

### Entity Fields

| Field | Description | Type |
|-------|-------------|------|
| `schema` | Entity schema (Person, Company, etc.) | keyword |
| `schemata` | Multiple schema types | keyword |
| `dataset` | Dataset identifier | keyword |
| `datasets` | Multiple datasets | keyword |

### Geographic Fields

| Field | Description | Type |
|-------|-------------|------|
| `countries` | Country codes | keyword |
| `addresses` | Address text | keyword |

### Content Fields

| Field | Description | Type |
|-------|-------------|------|
| `languages` | Document languages | keyword |
| `mime_type` | File MIME types | keyword |
| `file_extension` | File extensions | keyword |

### Temporal Fields

| Field | Description | Type |
|-------|-------------|------|
| `created_at` | Creation timestamp | date |
| `updated_at` | Last update timestamp | date |
| `dates` | Extracted date values | date |

### Name Fields

| Field | Description | Type |
|-------|-------------|------|
| `names` | Normalized entity names | keyword |
| `name_parts` | Name components | keyword |

## Performance Considerations

### Execution Strategy

All facet aggregations use `"execution_hint": "map"` for optimal performance on keyword fields.

### Cardinality Impact

High cardinality fields (many unique values) can impact performance:
- Consider using facet size limits
- Use sampling for very large datasets
- Monitor query performance with `took` values

### Shard Distribution

Facet accuracy depends on proper shard distribution:
- Use routing keys for dataset-specific queries
- Consider shard size when interpreting results

## Facet Combinations

### Multiple Facets with Filters

```bash
/search?q=investigation&facet=dataset&facet=schema&facet=countries&filter:created_at_gte=2020-01-01
```

Each facet reflects the impact of:
- The search query (`q=investigation`)
- Date filter (`created_at_gte=2020-01-01`)
- Other facet selections (but not its own)

### Date Range with Histogram

```bash
/search?filter:gte:created_at=2020-01-01&filter:lte:created_at=2023-12-31&facet=created_at&facet_interval:created_at=quarter
```

Shows quarterly distribution within the specified date range, including empty quarters.

## Error Handling

### Invalid Fields

Non-existent fields return empty facet results rather than errors:

```json
{
    "aggregations": {
        "nonexistent_field.values": {
            "buckets": []
        }
    }
}
```

### Type Mismatches

Requesting histograms on non-date fields falls back to term aggregation:

```bash
# This will work as a regular facet even though interval is specified
/search?facet=schema&facet_interval:schema=month
```

### Authorization Failures

Restricted fields return empty results rather than authorization errors, maintaining query functionality while respecting access controls.

## Advanced Usage Examples

### Investigative Analysis

```bash
# Find entities by type and location in specific time period
/search?q=offshore&facet=schema&facet=countries&facet=created_at&facet_interval:created_at=month&filter:gte:created_at=2016-01-01&filter:lte:created_at=2016-12-31
```

### Document Classification

```bash
# Analyze document types and languages
/search?filter:schemata=Document&facet=mime_type&facet=languages&facet_size:mime_type=100
```

### Entity Network Analysis

```bash
# Explore entity relationships by dataset and type
/search?filter:schema=Person&facet=dataset&facet=countries&facet=properties.entity&facet_type:properties.entity=entity
```

### Temporal Trends

```bash
# Track entity creation over time by type
/search?facet=schema&facet=created_at&facet_interval:created_at=year&facet_size:schema=50
```

---

## Technical Implementation

### Overview

OpenAleph-Search implements faceting through Elasticsearch aggregations with sophisticated filtering and authorization controls. The system automatically handles facet isolation, performance optimization, and access control.

### Implementation Location

Faceting is implemented in:
- `openaleph_search/query/base.py:138` - Core aggregation logic
- `openaleph_search/parse/parser.py` - Parameter parsing
- `openaleph_search/index/mapping.py` - Field type definitions
