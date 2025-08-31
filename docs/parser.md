# SearchQueryParser

The `SearchQueryParser` class allows you to build complex search queries using URL parameters. It supports text search, filtering, faceting, sorting, and highlighting.

## Quick Start

### From Request Arguments

```python
from openaleph_search.parse.parser import SearchQueryParser

# From request arguments (Flask/Werkzeug MultiDict)
parser = SearchQueryParser(request.args)
```

### From Dictionary

```python
# From dictionary
params = {
    "q": "search term",
    "facet": ["dataset", "schema"],
    "filter:dataset": ["collection1", "collection2"]
}
parser = SearchQueryParser(params)
```

### From URL Query String

You can parse URL query strings using the same pattern as shown in the test suite:

```python
from urllib.parse import parse_qsl, urlparse
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.queries import EntitiesQuery

def url_to_args(url):
    """Convert URL query string to args list for SearchQueryParser"""
    parsed = urlparse(url)
    return parse_qsl(parsed.query, keep_blank_values=True)

def create_query_from_url(url, auth=None):
    """Create Query from URL string"""
    args = url_to_args(url)
    parser = SearchQueryParser(args, auth)
    return EntitiesQuery(parser)

# Example usage
query = create_query_from_url("/search?q=money laundering&facet=dataset&filter:schema=Document")
result = query.search()
```

### URL Examples

```bash
# Basic text search with facets
/search?q=test&facet=dataset&facet=schema

# Search with filters
/search?q=investigation&filter:schema=Document&filter:countries=us

# Date range filtering
/search?filter:gte:properties.birthDate=1970-01-01&filter:lt:properties.birthDate=2000-01-01

# Pagination
/search?q=banana&offset=20&limit=10

# Sorting
/search?sort=created_at:desc

# Highlighting
/search?q=corruption&highlight=true&highlight_count=5

# Complex faceting with intervals
/search?facet=properties.birthDate&facet_interval:properties.birthDate=year

# Significant terms analysis
/search?q=offshore&facet_significant=names&facet_significant_text=content
```

## Basic Query Parameters

### Text Search

| Parameter | Type | Description |
|-----------|------|-------------|
| `q` | string | Main search query text |
| `prefix` | string | Prefix search for name fields |

### Pagination

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `offset` | int | 0 | Number of results to skip |
| `limit` | int | 20 | Maximum number of results to return |
| `next_limit` | int | same as limit | Limit for next page requests |

### Sorting

| Parameter | Type | Description |
|-----------|------|-------------|
| `sort` | string | Sort field and direction, format: `field:direction` |

Supported sort directions: `asc`, `desc` (default: `asc`)

Example: `sort=created_at:desc`

## Filtering Parameters

### Basic Filters

Use `filter:` prefix to filter by field values:

```
filter:dataset=collection1
filter:schema=Person
filter:countries=de
```

Multiple values for the same field create an OR condition:
```
filter:dataset=collection1&filter:dataset=collection2
```

### Range Filters

For date and numeric fields, use range operators:

| Operator | Description |
|----------|-------------|
| `gt:` | Greater than |
| `gte:` | Greater than or equal |
| `lt:` | Less than |
| `lte:` | Less than or equal |

```
filter:gte:created_at=2023-01-01
filter:lt:created_at=2024-01-01
```

### Exclusion Filters

Use `exclude:` prefix to exclude results:

```
exclude:dataset=spam_collection
exclude:schema=Thing
```

### Empty Field Filters

Use `empty:` prefix to filter for documents missing specific fields:

```
empty:birthDate=true
```

## Faceting Parameters

### Regular Facets

| Parameter | Type | Description |
|-----------|------|-------------|
| `facet` | string | Field name to create facets for |
| `facet_size:FIELD` | int | Number of facet values to return (default: 20) |
| `facet_total:FIELD` | bool | Return total count of distinct values |
| `facet_values:FIELD` | bool | Return actual facet values (default: true) |
| `facet_type:FIELD` | string | Facet type configuration |
| `facet_interval:FIELD` | string | Date histogram interval for date fields |

Example:
```
facet=dataset&facet=schema
facet_size:dataset=50
facet_total:dataset=true
facet_interval:created_at=month
```

#### Date Histogram Intervals

For date fields, you can specify histogram intervals using `facet_interval:FIELD`:


- Calendar intervals: `year`, `quarter`, `month`, `week`, `day`, `hour`, `minute`
- Fixed intervals: `30d`, `1h`, `10m`

### Significant Terms Facets

Significant terms find unusual or interesting terms in your search results compared to the background dataset.

| Parameter | Type | Description |
|-----------|------|-------------|
| `facet_significant` | string | Field name for significant terms aggregation |
| `facet_significant_size:FIELD` | int | Number of significant terms to return (default: 20) |
| `facet_significant_total:FIELD` | bool | Return total count for significant terms |
| `facet_significant_values:FIELD` | bool | Return actual significant term values |
| `facet_significant_type:FIELD` | string | Significant terms type configuration |

### Significant Text Analysis

Extract significant phrases from text content:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `facet_significant_text` | string | "content" | Text field to analyze |
| `facet_significant_text_size` | int | 5 | Number of significant text terms |
| `facet_significant_text_min_doc_count` | int | 5 | Minimum document count |
| `facet_significant_text_shard_size` | int | 200 | Shard size for aggregation |

## Highlighting Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `highlight` | bool | false | Enable search result highlighting |
| `highlight_count` | int | 3 | Number of highlight snippets per document |
| `max_highlight_analyzed_offset` | int | 999999 | Maximum characters to analyze for highlighting |

## Authentication and Authorization

When `search_auth` is enabled in settings, the parser integrates with authorization:

- Filters results based on user's dataset/collection access
- Applies stricter limits for unauthenticated users on large facets
- Uses the configured `search_auth_field` (default: "dataset") for access control

## Parser Properties

### Computed Properties

| Property | Type | Description |
|----------|------|-------------|
| `page` | int | Current page number |
| `collection_ids` | set[str] | Filtered collection IDs based on auth |
| `datasets` | set[str] | Filtered dataset names based on auth |
| `routing_key` | str | Elasticsearch routing key for sharding |

### Methods

| Method | Description |
|--------|-------------|
| `get_facet_size(name)` | Get facet size for specific field |
| `get_facet_total(name)` | Check if total count requested for facet |
| `get_facet_values(name)` | Check if facet values should be returned |
| `get_facet_significant_*()` | Various methods for significant terms configuration |
| `to_dict()` | Convert parser state to dictionary |

## Small Facets

The following facets are considered "small" and have relaxed limits for unauthenticated users:

- `schema`
- `schemata`
- `dataset`
- `countries`
- `languages`

## Special Field Types

### Entity References

Use `facet_type:properties.entity=entity` for entity reference fields.

### Name Matching

Special name-related filters are available:

- `filter:name_parts` - Match name components
- `filter:name_symbols` - Match name symbols/codes (e.g., `[NAME:47200243]`)

## URL Encoding

When building URLs, remember to URL-encode special characters:
- Colon (`:`) in sort parameters: `sort=dates%3Adesc`
- Spaces in queries: `q=money%20laundering`
- Special characters in filters

## Example Usage

```python
# Complex search with facets and filters
params = {
    "q": "money laundering",
    "facet": ["dataset", "countries", "schema"],
    "facet_significant": ["names"],
    "facet_significant_text": "content",
    "filter:countries": ["us", "uk"],
    "exclude:schema": ["Thing"],
    "sort": "created_at:desc",
    "highlight": "true",
    "offset": 20,
    "limit": 10
}

parser = SearchQueryParser(params)
# Use parser with Query classes for Elasticsearch search
```

---

## Technical Implementation

### Class Hierarchy

The `SearchQueryParser` class extends the base `QueryParser` class with ElasticSearch-specific functionality:

```python
class SearchQueryParser(QueryParser):
    """ElasticSearch-specific query parameters."""
```

### Internal Processing

The parser processes parameters through several stages:

1. **Parameter Extraction**: Extracts prefixed parameters using `prefixed_items()`
2. **Type Conversion**: Converts strings to appropriate types (`getint`, `getbool`, `getlist`)
3. **Authorization Integration**: Filters datasets/collections based on user permissions
4. **Validation**: Ensures parameters are within acceptable limits

### Implementation Location

The SearchQueryParser is implemented in `openaleph_search/parse/parser.py:138` and provides the foundation for all search functionality in the system.
