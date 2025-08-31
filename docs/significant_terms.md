# Significant Terms and Text Analysis

Discover unusual terms and meaningful phrases in your search results by comparing them against background datasets. This helps surface important concepts that might be buried in large document collections.

## Quick Start

### What is Significant Analysis?

Significant analysis compares your search results against a background dataset to find terms and phrases that appear unusually frequently. This helps identify what makes your search results unique.

### Basic Usage

```bash
# Find significant terms in names
/search?q=corruption&facet_significant=names

# Extract significant phrases from text
/search?facet_significant_text=content&facet_significant_text_size=10

# Multiple significant analyses
/search?facet_significant=countries&facet_significant_text=content
```

## Significant Terms

Significant terms aggregations identify keywords that appear more frequently in your search results than in the background dataset.

### Basic Usage

```bash
# Find significant terms in entity names
/search?q=corruption&facet_significant=names

# Multiple significant term facets
/search?facet_significant=names&facet_significant=countries
```

### Configuration Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `facet_significant` | string | - | Field name for significant terms analysis |
| `facet_significant_size:FIELD` | int | 20 | Number of significant terms to return |
| `facet_significant_total:FIELD` | bool | false | Return total count of significant terms |
| `facet_significant_values:FIELD` | bool | true | Return actual term values |
| `facet_significant_type:FIELD` | string | - | Aggregation type (e.g., "nested") |

### Response Structure

```json
{
    "aggregations": {
        "names.significant_terms": {
            "buckets": [
                {
                    "key": "offshore",
                    "doc_count": 45,          // Occurrences in search results
                    "score": 0.8745,         // Significance score (0-1)
                    "bg_count": 120          // Occurrences in background
                },
                {
                    "key": "panama",
                    "doc_count": 32,
                    "score": 0.7234,
                    "bg_count": 89
                }
            ]
        }
    }
}
```

### Interpretation

- **Score**: Statistical significance (higher = more unusual)
- **doc_count**: Frequency in search results
- **bg_count**: Frequency in background dataset
- **key**: The significant term

High scores indicate terms that are over-represented in your search compared to the general collection.

## Significant Text

Significant text analysis extracts meaningful phrases and terms directly from text content, identifying key topics and concepts.

### Basic Usage

```bash
# Analyze significant phrases in document content
/search?q=investigation&facet_significant_text=content

# Use custom field and size
/search?facet_significant_text=properties.description&facet_significant_text_size=10
```

### Configuration Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `facet_significant_text` | string | "content" | Text field to analyze |
| `facet_significant_text_size` | int | 5 | Number of significant phrases |
| `facet_significant_text_min_doc_count` | int | 5 | Minimum document frequency |
| `facet_significant_text_shard_size` | int | 200 | Documents sampled per shard |

### Text Field Options

Common fields for significant text analysis:

- `content` - Main document text content
- `text` - Additional searchable text
- `properties.description` - Entity descriptions
- `properties.summary` - Document summaries

### Response Structure

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
                    },
                    {
                        "key": "shell companies",
                        "doc_count": 19,
                        "score": 0.8432,
                        "bg_count": 89
                    }
                ]
            }
        }
    }
}
```

## Background Filtering

Both significant terms and text analysis use background filters to define the comparison dataset:

### Dataset-Specific Background

When filtering by specific datasets:

```python
# Background limited to filtered datasets
{
    "background_filter": {
        "bool": {
            "must": [
                {"terms": {"dataset": ["panama_papers", "paradise_papers"]}}
            ]
        }
    }
}
```

### Collection-Based Background

When using collection IDs:

```python
# Background limited to accessible collections
{
    "background_filter": {
        "bool": {
            "must": [
                {"terms": {"collection_id": ["col1", "col2", "col3"]}}
            ]
        }
    }
}
```

### Full Dataset Background

Without specific filters, the entire accessible dataset serves as background.

## Performance and Sampling

### Sampling Strategy

Significant text analysis uses sampling to handle large datasets efficiently:

**Diversified Sampling** (default):
```json
{
    "diversified_sampler": {
        "shard_size": 200,
        "field": "dataset"
    }
}
```

**Regular Sampling** (when filtering by dataset):
```json
{
    "sampler": {
        "shard_size": 200
    }
}
```

### Shard Size Calculation

For significant terms, shard size is automatically calculated:
```python
shard_size = max(100, requested_size * 5)
```

This ensures sufficient sampling for statistical significance.

## Authorization and Access Control

### Authenticated Users

- Full access to significant analysis features
- Background filters respect user's dataset access
- Can specify custom field names and parameters

### Unauthenticated Users

- Limited to small facets for significant terms
- Restricted shard sizes for performance
- Cannot access total counts

### Dataset Filtering

All significant analysis respects the configured authorization field (default: `dataset`):

```python
# User only sees results from their accessible datasets
accessible_datasets = auth.datasets  # e.g., ["public_data", "user_collection"]
background_filter = {"terms": {"dataset": accessible_datasets}}
```

## Advanced Configuration

### Minimum Document Count

Control the minimum frequency threshold:

```bash
/search?facet_significant_text=content&facet_significant_text_min_doc_count=10
```

Higher values focus on more frequent terms but may miss rare but significant phrases.

### Shard Size Tuning

Adjust sampling for accuracy vs. performance:

```bash
/search?facet_significant_text=content&facet_significant_text_shard_size=500
```

Larger shard sizes improve accuracy but increase query time.

### Duplicate Text Filtering

Significant text automatically filters duplicate content:

```json
{
    "significant_text": {
        "field": "content",
        "filter_duplicate_text": true
    }
}
```

This prevents repetitive content from skewing results.

## Use Cases

### Investigative Journalism

```bash
# Find key terms in corruption investigation
/search?q=minister&filter:countries=br&facet_significant=names&facet_significant_text=content
```

Identifies significant people and phrases related to corruption cases.

### Document Classification

```bash
# Discover document themes by type
/search?filter:schema=Document&filter:mime_type=application/pdf&facet_significant_text=content&facet_significant_text_size=15
```

Extracts key topics from PDF documents.

### Entity Analysis

```bash
# Find significant entity attributes
/search?filter:schema=Company&facet_significant=countries&facet_significant=properties.sector
```

Identifies unusual geographic or sector concentrations.

### Temporal Analysis

```bash
# Significant terms over time periods
/search?filter:gte:created_at=2016-01-01&filter:lt:created_at=2017-01-01&facet_significant=names&facet_significant_text=content
```

Discovers what was significant during specific time periods.

## Statistical Interpretation

### Significance Scores

Scores range from 0 to 1:
- **0.9+**: Highly significant, strong indicator
- **0.7-0.9**: Moderately significant
- **0.5-0.7**: Somewhat significant
- **<0.5**: Low significance

### Document Counts

Consider both absolute and relative frequencies:
- High `doc_count` + high `score` = Important frequent term
- Low `doc_count` + high `score` = Rare but highly relevant term
- High `doc_count` + low `score` = Common but not distinctive

### Background Context

Compare against `bg_count` to understand significance:
- `doc_count` >> `bg_count` (relative to dataset sizes) = Over-represented
- `doc_count` ≈ `bg_count` (relative to dataset sizes) = Normal frequency

## Error Handling and Edge Cases

### No Results

Empty significant analysis returns appropriate structure:

```json
{
    "aggregations": {
        "names.significant_terms": {
            "buckets": []
        }
    }
}
```

### Field Validation

- Non-existent fields return empty results
- Text analysis requires analyzable text fields
- Terms analysis requires keyword fields

### Sampling Edge Cases

- Very small datasets may not provide meaningful significance
- Single-document results cannot generate significance scores
- Cross-shard coordination ensures consistent sampling

## Performance Monitoring

Monitor significant analysis performance through:
- Query `took` times in responses
- Elasticsearch slow query logs
- Resource usage during complex aggregations

Optimize by adjusting shard sizes, minimum document counts, and field selection based on your specific dataset characteristics.

---

## Technical Implementation

### Overview

Significant analysis is implemented through Elasticsearch's significant terms and significant text aggregations, with sophisticated background filtering and sampling strategies to ensure accurate statistical analysis.

### Implementation Details

The system handles:
- **Background Filter Generation**: Automatic creation of comparison datasets
- **Sampling Strategies**: Diversified and regular sampling for different scenarios
- **Statistical Scoring**: Proper significance calculation using document frequencies
- **Authorization Integration**: Background datasets respect user permissions

### Implementation Location

Significant analysis logic is in:

- `openaleph_search/query/base.py:203` - Significant terms aggregations
- `openaleph_search/query/base.py:244` - Significant text aggregations
- `openaleph_search/query/base.py:264` - Background filter generation
- `openaleph_search/query/base.py:282` - Sampling configuration
