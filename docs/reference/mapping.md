# Elasticsearch Index Mapping

The index mapping in openaleph-search defines how documents are structured and indexed in Elasticsearch. The mapping is defined in `openaleph_search/index/mapping.py` and provides a comprehensive structure for entity-based search.

## Overview

The mapping system consists of several layers:

1. **Base Mapping** - Core fields present in all documents
2. **Group Mapping** - Combined fields for followthemoney property groups
3. **Property Mapping** - Specific entity property fields
4. **Numeric Mapping** - Optimized numeric fields for sorting and aggregation

## Index Settings

### Analysis Configuration

The index uses sophisticated text analysis with multiple analyzers and normalizers:

```json
{
    "analysis": {
        "char_filter": {
            "remove_special_chars": {
                "type": "pattern_replace",
                "pattern": "[^\\p{L}\\p{N}\\s]",
                "replacement": ""
            },
            "squash_spaces": {
                "type": "pattern_replace",
                "pattern": "[\\r\\n\\s]+",
                "replacement": " "
            },
            "remove_html_tags": {
                "type": "pattern_replace",
                "pattern": "<[^>]*>",
                "replacement": " "
            }
        }
    }
}
```

### Analyzers

| Analyzer | Purpose | Configuration |
|----------|---------|---------------|
| `icu-default` | Primary text analysis with Unicode support | ICU tokenizer + folding + normalization |
| `strip-html` | HTML content processing | Standard tokenizer + HTML stripping |
| `default` | Standard Elasticsearch analysis | Built-in default |

### Normalizers

| Normalizer | Purpose | Configuration |
|------------|---------|---------------|
| `icu-default` | Unicode normalization | ICU folding |
| `name-kw-normalizer` | Name keyword normalization | Special chars removal + lowercase + trim |
| `kw-normalizer` | General keyword normalization | HTML removal + space squashing |

## Base Mapping Fields

Core fields present in all indexed documents:

### Identity Fields

| Field | Type | Description |
|-------|------|-------------|
| `dataset` | keyword | Dataset identifier |
| `schema` | keyword | Entity schema type |
| `schemata` | keyword | All applicable schema types |
| `caption` | keyword | Display label for entity |

### Name Fields

| Field | Type | Description | Purpose |
|-------|------|-------------|---------|
| `name` | text | Original entity names | Full-text matching |
| `names` | keyword | Normalized name keywords | Exact matching and aggregation |
| `name_keys` | keyword | Name normalization keys | Deduplication |
| `name_parts` | keyword | Name components | Partial matching |
| `name_symbols` | keyword | Name symbols/codes | Symbol-based lookup |
| `name_phonetic` | keyword | Phonetic representations | Sound-alike matching |

### Content Fields

| Field | Type | Description | Purpose |
|-------|------|-------------|---------|
| `content` | text | Primary text content | Full-text search with highlighting |
| `text` | text | Additional searchable text | Secondary text search |

### Geographic Fields

| Field | Type | Description |
|-------|------|-------------|
| `geo_point` | geo_point | Geographic coordinates |

### Temporal Fields

| Field | Type | Description |
|-------|------|-------------|
| `created_at` | date | Document creation time |
| `updated_at` | date | Last modification time |
| `first_seen` | date | First occurrence in dataset |
| `last_seen` | date | Last occurrence in dataset |
| `last_change` | date | Last content change |

### Metadata Fields

| Field | Type | Description | Indexed |
|-------|------|-------------|---------|
| `referents` | keyword | Entity references | Yes |
| `origin` | keyword | Data source origin | Yes |
| `num_values` | integer | Value count for normalization | Yes |
| `index_bucket` | keyword | Index bucket identifier | No |
| `index_version` | keyword | Index version | No |
| `indexed_at` | date | Index timestamp | No |

### Legacy Fields (OpenAleph v5 compatibility)

| Field | Type | Description |
|-------|------|-------------|
| `role_id` | keyword | User role identifier |
| `profile_id` | keyword | User profile identifier |
| `collection_id` | keyword | Collection identifier |

## Field Type Definitions

### Specialized Field Types

```python
# Content field - optimized for highlighting and term vectors
{
    "type": "text",
    "analyzer": "icu-default",
    "search_analyzer": "icu-default",
    "index_phrases": True,          # Enable shingle indexing
    "term_vector": "with_positions_offsets"  # For highlighting
}

# Name field - no length normalization
{
    "type": "text",
    "similarity": "weak_length_norm",  # Don't penalize long names
    "store": True                     # Store for highlighting
}

# Name keyword - normalized for aggregation
{
    "type": "keyword",
    "normalizer": "name-kw-normalizer",
    "store": True
}
```

### Date Formatting

Flexible date format supporting various precisions:
```
yyyy-MM-dd'T'HH||yyyy-MM-dd'T'HH:mm||yyyy-MM-dd'T'HH:mm:ss||yyyy-MM-dd||yyyy-MM||yyyy||strict_date_optional_time
```

Supports:

- Full timestamps: `2023-12-25T14:30:45`
- Date only: `2023-12-25`
- Month precision: `2023-12`
- Year precision: `2023`

## Property Mapping

Entity properties are dynamically mapped based on FollowTheMoney schemas:

### Property Field Structure

Properties are stored under `properties.{property_name}`:

- `properties.birthDate` - Birth date values
- `properties.nationality` - Nationality values
- `properties.address` - Address information

### Copy-to Targets

Properties are automatically copied to appropriate search fields:

| Property Type | Copy Target | Purpose |
|---------------|-------------|---------|
| `text` | `content` | Full-text search in primary content field |
| Other types | `text` | Full-text search in secondary text field |
| Groups | `{group_name}` | Grouped field aggregation |

Example:
```python
# A "nationality" property copies to:
# 1. properties.nationality (exact field)
# 2. text (searchable text)
# 3. countries (grouped field for aggregation)
```

## Group Mapping

FollowTheMoney property groups are mapped as unified fields:

### Common Groups

| Group | Type | Description | Example Properties |
|-------|------|-------------|-------------------|
| `countries` | keyword | Country codes | nationality, jurisdiction |
| `languages` | keyword | Language codes | language |
| `emails` | keyword | Email addresses | email |
| `phones` | keyword | Phone numbers | phone |
| `dates` | date | Date values | birthDate, startDate |
| `addresses` | text | Address information | address |

## Numeric Mapping

Numeric fields are duplicated in the `numeric` object for efficient sorting:

```json
{
    "numeric": {
        "properties": {
            "dates": {"type": "double"},        // All date fields as timestamps
            "birthDate": {"type": "double"},    // Specific date properties
            "amount": {"type": "double"},       // Monetary amounts
            "shares": {"type": "double"}        // Share counts
        }
    }
}
```

### Numeric Types

Fields are considered numeric if they use these FollowTheMoney types:

- `registry.number` - General numeric values
- `registry.date` - Date/timestamp values

## Source Field Configuration

### Excluded Fields

The following fields are excluded from the stored `_source` to save space:

```python
SOURCE_EXCLUDES = [
    # Group fields (reconstructed from properties)
    "countries", "languages", "emails", "phones", "dates", "addresses",
    # Search-optimized fields (reconstructed from source)
    "text", "content", "name", "name_keys", "name_parts",
    "name_symbols", "name_phonetic"
]
```

These fields remain searchable but are not returned in search results, reducing storage requirements.

## Dynamic Mapping

### Schema-Based Generation

Mappings are generated dynamically based on FollowTheMoney schemas:

```python
def make_schema_mapping(schemata):
    """Generate mapping for specific entity schemas"""
    # Analyzes all properties across schemas
    # Resolves type conflicts (keyword takes precedence)
    # Generates copy_to configurations
    # Returns property mapping
```

### Type Resolution

When multiple schemas define the same property:
1. **Keyword** type takes precedence over **text**
2. **Copy-to** targets are merged
3. Group assignments are unified

Example:
```python
# Schema A: "authority" as text field
# Schema B: "authority" as entity reference (keyword)
# Result: keyword field with copy_to both content and text
```

## Mapping Generation Functions

### Core Functions

| Function | Purpose | Location |
|----------|---------|----------|
| `make_mapping(properties)` | Generate complete index mapping | mapping.py:272 |
| `make_schema_mapping(schemata)` | Create property mapping for schemas | mapping.py:286 |
| `get_index_field_type(type_)` | Get Elasticsearch field type | mapping.py:323 |
| `property_field_name(prop)` | Generate property field name | mapping.py:264 |

### Usage Example

```python
from openaleph_search.index.mapping import make_schema_mapping, make_mapping

# Generate mapping for specific schemas
schemata = ["Person", "Company", "Document"]
properties = make_schema_mapping(schemata)
complete_mapping = make_mapping(properties)
```

## Index Management

### Index Settings

```python
{
    "date_detection": False,        # Disable automatic date detection
    "dynamic": False,              # Strict mapping enforcement
    "_source": {
        "excludes": SOURCE_EXCLUDES  # Optimize storage
    }
}
```

### Sharding and Replication

Configured through settings:

- Default: 25 shards (optimized for dataset routing)
- Default: 0 replicas (single-node development)
- Routing by dataset for performance

## Field Usage Guidelines

### Search Fields

- Use `content` for primary full-text search
- Use `text` for secondary/additional text search
- Use `name` for entity name matching

### Filtering Fields

- Use keyword fields for exact matching
- Use group fields for category aggregation
- Use numeric fields for range queries

### Aggregation Fields

- Prefer keyword fields for term aggregations
- Use group fields for cross-property aggregation
- Use numeric fields for statistical aggregation

## Performance Considerations

### Field Storage

- Only essential fields are stored in `_source`
- Search-optimized fields are reconstructed on query
- Reduces index size by ~30-40%

### Analysis Performance

- ICU analyzer provides better Unicode support
- Name normalization improves deduplication
- Term vectors enable fast highlighting

### Query Optimization

- Numeric duplicates enable efficient sorting
- Group fields reduce cross-property query complexity
- Copy-to configuration eliminates multi-field queries
