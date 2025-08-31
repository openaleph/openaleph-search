# Indexes

OpenAleph-Search organizes entities into different index buckets based on their schema types. This bucketing strategy optimizes storage, querying performance, and allows for granular score weighting across different entity types.

## Index Buckets

OpenAleph-Search uses four distinct index buckets to categorize entities:

### Pages
**Bucket:** `pages`
**Index Pattern:** `{prefix}-entity-pages-{version}`
**Entity Types:** Page entities

Pages represent individual web pages or document pages that have been extracted and indexed separately from their parent documents. This bucket is optimized for:

- Full-text content storage and highlighting
- Fast retrieval of page-level content
- Separate scoring from document-level entities

**Characteristics:**

- Content field is stored for highlighting (`"store": true`)
- Optimized for text search and content display
- Lower cardinality compared to other buckets

### Documents
**Bucket:** `documents`
**Index Pattern:** `{prefix}-entity-documents-{version}`
**Entity Types:** Document and Document-derived schemas

Documents encompass all file-based entities including PDFs, Word documents, spreadsheets, emails, and other structured documents. This bucket handles:

- Document metadata and content
- File type-specific properties
- Large-scale document collections

**Characteristics:**

- Contains rich metadata fields (MIME type, file size, etc.)
- Supports document-specific faceting and filtering
- High volume, content-heavy entities

### Things
**Bucket:** `things`
**Index Pattern:** `{prefix}-entity-things-{version}`
**Entity Types:** Thing and Thing-derived schemas (Person, Company, etc.)

Things represent real-world entities including people, organizations, companies, locations, and other conceptual entities. This is the most diverse bucket containing:
- Person entities (individuals, public figures)
- Organization entities (companies, government bodies)
- Asset entities (properties, vehicles, accounts)
- Legal entities and relationships

**Characteristics:**
- Highest entity diversity and complexity
- Rich relationship data between entities
- Core entities for investigative and analytical queries
- Default bucket for unmapped schema types

### Intervals
**Bucket:** `intervals`
**Index Pattern:** `{prefix}-entity-intervals-{version}`
**Entity Types:** Interval and Interval-derived schemas

Intervals represent time-based entities including events, periods, meetings, and temporal relationships. This specialized bucket optimizes for:
- Event timeline analysis
- Date range queries and filtering
- Temporal relationship mapping

**Characteristics:**
- Time-centric entity properties
- Optimized for date range queries
- Lower volume but temporally significant entities

## Index Boosting

OpenAleph-Search allows fine-grained control over search result scoring through index-specific boost weights. This enables you to prioritize certain entity types based on your use case requirements.

### Boost Configuration

Configure boost weights through environment variables or settings:

```bash
# Prioritize documents in search results
export OPENALEPH_INDEX_BOOST_DOCUMENTS=2
export OPENALEPH_INDEX_BOOST_THINGS=1
export OPENALEPH_INDEX_BOOST_INTERVALS=1
export OPENALEPH_INDEX_BOOST_PAGES=1

# Equal weighting (default)
export OPENALEPH_INDEX_BOOST_DOCUMENTS=1
export OPENALEPH_INDEX_BOOST_THINGS=1
export OPENALEPH_INDEX_BOOST_INTERVALS=1
export OPENALEPH_INDEX_BOOST_PAGES=1
```

### Boost Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `index_boost_documents` | int | `1` | Boost weight for Document entities |
| `index_boost_things` | int | `1` | Boost weight for Thing entities (Person, Company, etc.) |
| `index_boost_intervals` | int | `1` | Boost weight for Interval entities (Events, etc.) |
| `index_boost_pages` | int | `1` | Boost weight for Page entities |

### How Boosting Works

Index boosting is implemented through Elasticsearch's `function_score` query with filtered weight functions. When you configure a boost value:

1. **Schema Detection**: The system determines which bucket each queried schema belongs to
2. **Weight Application**: Entities from boosted buckets receive multiplicative score increases
3. **Score Combination**: Boost weights combine with other scoring factors (field matches, num_values factor, etc.)

**Example Boost Application:**
```json
{
  "function_score": {
    "query": { ... },
    "functions": [
      {
        "field_value_factor": {
          "field": "num_values",
          "factor": 0.5,
          "modifier": "sqrt"
        }
      },
      {
        "filter": {"term": {"schema": "Document"}},
        "weight": 2
      },
      {
        "filter": {"term": {"schema": "Person"}},
        "weight": 1
      }
    ],
    "boost_mode": "sum"
  }
}
```

### Boost Use Cases

**Investigative Journalism:**
```bash
# Prioritize people and organizations over documents
export OPENALEPH_INDEX_BOOST_THINGS=3
export OPENALEPH_INDEX_BOOST_DOCUMENTS=1
export OPENALEPH_INDEX_BOOST_INTERVALS=2
export OPENALEPH_INDEX_BOOST_PAGES=1
```

**Document Discovery:**
```bash
# Emphasize documents and their pages
export OPENALEPH_INDEX_BOOST_DOCUMENTS=2
export OPENALEPH_INDEX_BOOST_PAGES=2
export OPENALEPH_INDEX_BOOST_THINGS=1
export OPENALEPH_INDEX_BOOST_INTERVALS=1
```

**Timeline Analysis:**
```bash
# Highlight events and temporal data
export OPENALEPH_INDEX_BOOST_INTERVALS=3
export OPENALEPH_INDEX_BOOST_THINGS=2
export OPENALEPH_INDEX_BOOST_DOCUMENTS=1
export OPENALEPH_INDEX_BOOST_PAGES=1
```

### Performance Considerations

**Boost Impact on Performance:**
- Boost values only affect scoring, not filtering or aggregations
- Higher boost values don't impact query execution time
- Boost functions are applied efficiently through Elasticsearch's native scoring

**Optimization Guidelines:**
- Use boost values sparingly (1-5 range typically sufficient)
- Consider your user's typical search patterns
- Test boost effectiveness with real queries and data
- Monitor query performance with different boost configurations

## Technical Implementation

### Bucket Assignment Logic

Bucket assignment follows a hierarchical schema inheritance pattern:

```python
def schema_bucket(schema: SchemaType) -> Bucket:
    schema = ensure_schema(schema)
    if schema.name in ("Page", "Pages"):
        return "pages"
    if schema.is_a("Document"):
        return "documents"
    if schema.is_a("Thing"):
        return "things"
    if schema.is_a("Interval"):
        return "intervals"
    return "things"  # Default fallback
```

**Assignment Priority:**
1. Explicit Page schema names → `pages`
2. Document inheritance → `documents`
3. Thing inheritance → `things`
4. Interval inheritance → `intervals`
5. Default fallback → `things`

### Index Naming Convention

Indexes follow a consistent naming pattern:
```
{index_prefix}-entity-{bucket}-{version}
```

**Examples:**
- `openaleph-entity-documents-v1`
- `openaleph-entity-things-v1`
- `openaleph-entity-intervals-v1`
- `openaleph-entity-pages-v1`

### Schema Distribution

**Typical Schema Distribution by Bucket:**

| Bucket | Common Schemas | Volume | Use Cases |
|--------|---------------|---------|-----------|
| `documents` | Document, Email, PDF, Spreadsheet | High | Document analysis, content search |
| `things` | Person, Company, Organization, Asset | Very High | Entity relationships, investigations |
| `intervals` | Event, Meeting, Transaction | Medium | Timeline analysis, temporal queries |
| `pages` | Page | High | Content highlighting, page-level search |

### Index Configuration

Each bucket uses identical Elasticsearch settings but with bucket-specific property mappings:

```python
# Shared index settings
{
    "number_of_shards": settings.index_shards,
    "number_of_replicas": settings.index_replicas,
    "routing": {
        "allocation": {
            "include": {
                "_tier_preference": "data_content"
            }
        }
    }
}

# Bucket-specific property mappings generated from schema definitions
```

### Query Integration

Bucket-aware querying is handled automatically:

1. **Schema Analysis**: Query parser determines target schemas
2. **Index Selection**: System selects relevant bucket indexes
3. **Boost Application**: Configured weights applied per bucket
4. **Result Aggregation**: Results combined across bucket indexes

**Implementation Location:**
- `openaleph_search/index/indexes.py` - Bucket logic and index management
- `openaleph_search/query/queries.py:63` - Boost weight functions
- `openaleph_search/settings.py:44` - Boost configuration settings

## Migration and Versioning

### Index Version Management

Bucket indexes support independent versioning:

```bash
# Create new version for specific bucket
curl -X PUT "localhost:9200/openaleph-entity-documents-v2"

# Update read configuration
export OPENALEPH_INDEX_READ=v1,v2

# Switch write target
export OPENALEPH_INDEX_WRITE=v2
```

### Cross-Bucket Consistency

When migrating index versions:
1. All buckets should use consistent version numbers
2. Migration can be performed per-bucket for large datasets
3. Read configuration supports multiple versions during transition

### Rollback Strategy

Bucket-based architecture enables selective rollbacks:
- Roll back specific entity types without affecting others
- Test schema changes on single buckets
- Maintain service availability during migrations

---

## Conclusion

The four-bucket index architecture provides OpenAleph-Search with:
- **Optimized Performance**: Schema-specific optimizations per bucket
- **Flexible Scoring**: Granular boost control for different entity types
- **Scalable Architecture**: Independent scaling and management per bucket
- **Operational Flexibility**: Bucket-specific migrations and maintenance

Understanding and properly configuring index buckets and boosting enables you to optimize OpenAleph-Search for your specific use case, whether focused on document discovery, entity analysis, or investigative research.
