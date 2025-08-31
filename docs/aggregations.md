# Aggregations

Extract insights from your search results through faceting, statistical analysis, and significant term detection. Aggregations help you discover patterns and trends in your data.

## Quick Start

### Types of Aggregations

OpenAleph-Search supports three main types of aggregations:

1. **Regular Facet Aggregations** - Count distinct values in fields
2. **Significant Terms Aggregations** - Find statistically unusual terms
3. **Significant Text Aggregations** - Extract meaningful phrases from text content

### Basic Usage

```bash
# Regular facets
/search?facet=dataset&facet=schema

# Significant terms
/search?facet_significant=names&facet_significant=countries

# Significant text
/search?facet_significant_text=content&facet_significant_text_size=10
```

## Regular Facet Aggregations

### Terms Aggregations

Terms aggregations provide counts of distinct values for a field:

```python
# URL parameter
/search?facet=dataset&facet=schema

# Generated Elasticsearch aggregation
{
    "dataset.values": {
        "terms": {
            "field": "dataset",
            "size": 20,
            "execution_hint": "map"
        }
    },
    "schema.values": {
        "terms": {
            "field": "schema",
            "size": 20,
            "execution_hint": "map"
        }
    }
}
```

### Cardinality Aggregations

Get total count of distinct values for a field:

```python
# URL parameter
/search?facet=countries&facet_total:countries=true

# Generated aggregation
{
    "countries.cardinality": {
        "cardinality": {
            "field": "countries"
        }
    }
}
```

### Date Histogram Aggregations

For date fields, you can create time-based histograms:

```python
# URL parameter
/search?facet=created_at&facet_interval:created_at=month

# Generated aggregation
{
    "created_at.intervals": {
        "date_histogram": {
            "field": "created_at",
            "calendar_interval": "month",
            "format": "yyyy-MM-dd'T'HH||yyyy-MM-dd'T'HH:mm||yyyy-MM-dd'T'HH:mm:ss||yyyy-MM-dd||yyyy-MM||yyyy||strict_date_optional_time",
            "min_doc_count": 0
        }
    }
}
```

#### Extended Bounds

Date histograms support extended bounds to ensure empty buckets are returned within filtered ranges:

```python
# URL with date range filters
/search?facet=created_at&facet_interval:created_at=month&filter:gte:created_at=2023-01-01&filter:lte:created_at=2023-12-31

# Adds extended_bounds to ensure all months in 2023 are included
{
    "created_at.intervals": {
        "date_histogram": {
            "field": "created_at",
            "calendar_interval": "month",
            "format": "...",
            "min_doc_count": 0,
            "extended_bounds": {
                "min": "2023-01-01",
                "max": "2023-12-31"
            }
        }
    }
}
```

## Significant Terms Aggregations

Significant terms aggregations identify terms that are statistically over-represented in your search results compared to the background dataset.

```python
# URL parameter
/search?facet_significant=names&facet_significant_size:names=10

# Generated aggregation
{
    "names.significant_terms": {
        "significant_terms": {
            "field": "names",
            "background_filter": {
                "bool": {
                    "must": [
                        {"terms": {"dataset": ["filtered_dataset"]}}
                    ]
                }
            },
            "size": 10,
            "min_doc_count": 3,
            "shard_size": 50,
            "execution_hint": "map"
        }
    }
}
```

### Background Filter

The background filter defines the comparison set for significance calculation. It uses:

- Collection IDs if available (`collection_id` field)
- Dataset names if collection IDs not available (`dataset` field)
- Entire index if no filtering is applied

### Nested Significant Terms

For nested field types, significant terms can be configured with nested aggregations:

```python
# URL parameter
/search?facet_significant=nested_field&facet_significant_type:nested_field=nested

# Generates nested aggregation structure
```

## Significant Text Aggregations

Significant text aggregations extract meaningful phrases and terms from text content:

```python
# URL parameter
/search?facet_significant_text=content&facet_significant_text_size=5

# Generated aggregation
{
    "significant_text": {
        "sampler": {
            "shard_size": 200
        },
        "aggs": {
            "significant_text": {
                "significant_text": {
                    "field": "content",
                    "background_filter": {...},
                    "filter_duplicate_text": true,
                    "size": 5,
                    "min_doc_count": 5,
                    "shard_size": 200
                }
            }
        }
    }
}
```

### Sampling

Significant text aggregations use sampling to improve performance:

- **Diversified Sampling**: When no specific dataset filter is applied, samples across datasets using the auth field
- **Regular Sampling**: When filtering by specific datasets/collections, uses regular sampling

## Post-Filters and Facet Isolation

Aggregations use post-filters to ensure each facet reflects the impact of all other filters except its own:

```python
# Example: faceting on 'schema' while filtering by 'dataset'
# The schema facet will see all documents matching the dataset filter
# but not any schema filters

{
    "schema.filtered": {
        "filter": {
            "bool": {
                "filter": [
                    {"terms": {"dataset": ["selected_dataset"]}}
                    # Note: no schema filters here
                ]
            }
        },
        "aggregations": {
            "schema.values": {
                "terms": {"field": "schema", "size": 20}
            }
        }
    }
}
```

## Authentication and Authorization

Aggregations respect authentication settings:

### Unauthenticated Users

For unauthenticated users and large facets (not in `SMALL_FACETS`):

- Maximum facet size limited to 50
- Total counts disabled for performance
- Applies to facets not in: `schema`, `schemata`, `dataset`, `countries`, `languages`

### Dataset Filtering

When authentication is enabled:

- Background filters automatically include user's accessible datasets
- Aggregation results filtered by user permissions
- Uses `search_auth_field` (default: "dataset") for access control

## Performance Optimizations

### Execution Hints

All term aggregations use `"execution_hint": "map"` for better performance on keyword fields.

### Shard Sizing

Significant terms and text aggregations use calculated shard sizes:
- Significant terms: `max(100, requested_size * 5)`
- Significant text: configurable via `facet_significant_text_shard_size` (default: 200)

### Sampling

Large-scale significant text analysis uses sampling to balance performance and accuracy:
- Default shard size: 200 documents per shard
- Diversified sampling when analyzing across multiple datasets

## Field Type Considerations

### Keyword Fields
- Used for exact-match faceting
- Suitable for: datasets, schema names, countries, languages

### Text Fields
- Used for significant text analysis
- Analyzed content fields like `content` and `text`

### Date Fields
- Support histogram aggregations with calendar intervals
- Automatic format handling for various date precisions

### Numeric Fields
- Can be used in range aggregations
- Automatically handled in the numeric field mapping

## Error Handling

The aggregation system handles various edge cases:
- Empty result sets return appropriate empty aggregation structures
- Invalid interval specifications fall back to safe defaults
- Missing fields return zero counts rather than errors
- Authentication failures restrict aggregation scope rather than failing

## Example Response Structure

```json
{
    "aggregations": {
        "dataset.values": {
            "buckets": [
                {"key": "collection1", "doc_count": 150},
                {"key": "collection2", "doc_count": 75}
            ]
        },
        "schema.cardinality": {
            "value": 12
        },
        "dates.intervals": {
            "buckets": [
                {
                    "key": 1609459200000,
                    "key_as_string": "2021-01-01T00:00:00.000Z",
                    "doc_count": 45
                }
            ]
        },
        "names.significant_terms": {
            "buckets": [
                {
                    "key": "offshore",
                    "doc_count": 25,
                    "score": 0.8745,
                    "bg_count": 100
                }
            ]
        },
        "significant_text": {
            "significant_text": {
                "buckets": [
                    {
                        "key": "money laundering",
                        "doc_count": 15,
                        "score": 0.9234,
                        "bg_count": 50
                    }
                ]
            }
        }
    }
}
```

---

## Technical Implementation

### Overview

Aggregations in openaleph-search are implemented in the `Query.get_aggregations()` method in `openaleph_search/query/base.py:138`. The system provides sophisticated post-filtering, authorization controls, and performance optimizations.

### Implementation Details

The aggregation system handles:
- **Post-filter isolation**: Each facet excludes its own filters
- **Authorization integration**: Results respect user permissions
- **Performance limits**: Query clause limits and sampling strategies
- **Background filtering**: Significant analysis uses appropriate comparison datasets

### Implementation Location

Core aggregation logic is in:
- `openaleph_search/query/base.py:138` - Main aggregation implementation
- `openaleph_search/query/base.py:264` - Background filter generation
- `openaleph_search/query/base.py:276` - Sampling configuration
