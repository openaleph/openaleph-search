# More Like This Query

Find similar documents and pages based on text content using Elasticsearch's More Like This functionality. The More Like This query helps identify documents with similar textual content, themes, or topics by analyzing term frequency and distribution patterns.

## Quick Start

### Basic Usage

```python
from openaleph_search.query.queries import MoreLikeThisQuery
from openaleph_search.parse.parser import SearchQueryParser

# Create document entity to find similar documents
entity = make_entity({
    "id": "doc-123",
    "schema": "Document",
    "properties": {
        "title": ["Machine Learning Research"],
        "bodyText": [
            "This research explores neural networks and deep learning "
            "applications in computer vision and natural language processing."
        ]
    }
})

# Find similar documents and pages
parser = SearchQueryParser([])
query = MoreLikeThisQuery(parser, entity)
result = query.search()
```

### Common Use Cases

```bash
# Find documents similar to a research paper
/search?mlt_minimum_should_match=20%  # Adjust similarity threshold

# Find pages similar to a web document
# Targets both Documents and Pages schemas automatically

# Cross-content-type similarity
# Documents can match Pages and vice versa based on textual content
```

## Query Parameters

The More Like This query supports configurable parameters via URL query strings:

### Core Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `mlt_min_doc_freq` | `0` | Minimum document frequency for terms to be considered |
| `mlt_minimum_should_match` | `"10%"` | Minimum percentage of query terms that should match |
| `mlt_min_term_freq` | `1` | Minimum term frequency within the input document |
| `mlt_max_query_terms` | `25` | Maximum number of query terms to use |

### Parameter Usage Examples

```bash
# Strict similarity matching
/search?mlt_minimum_should_match=30%&mlt_min_doc_freq=2

# Broader similarity matching
/search?mlt_minimum_should_match=5%&mlt_max_query_terms=50

# Fine-tuned similarity
/search?mlt_min_term_freq=2&mlt_min_doc_freq=1&mlt_max_query_terms=15
```

## Text Fields Used

The More Like This query analyzes multiple text fields to find similar content:

### 1. `content` - Full Document Content
**Field Type:** `text` with `icu-default` analyzer
**Purpose:** Full textual content for comprehensive similarity analysis

```python
# Example content
"content": [
    "This comprehensive guide covers machine learning algorithms, "
    "including neural networks, decision trees, and support vector machines..."
]
```

**Characteristics:**

- Full document text stored for highlighting
- ICU tokenizer for Unicode support
- Primary field for content similarity
- Supports phrase matching with index_phrases

### 2. `text` - Processed Text Content
**Field Type:** `text` with standard processing
**Purpose:** Processed and normalized text for similarity matching

```python
# Mapped from various source fields like bodyText, indexText
"text": [
    "machine learning neural networks deep learning computer vision"
]
```

**Features:**

- Normalized and processed text
- Copy-to field from bodyText, indexText, etc.
- Standard text analysis pipeline
- Used for term frequency analysis

### 3. `name` and `names` - Entity Names
**Purpose:** Include entity names in similarity calculation for context

```python
# Document titles and names contribute to similarity
"name": ["Machine Learning Research Paper"]
"names": ["ml research", "neural networks study"]
```

**Usage:**

- Provides context for content matching
- Helps differentiate topic areas
- Lower weight in More Like This analysis

## Schema Targeting

The More Like This query specifically targets document and page content:

### Supported Schema Types

```python
DOCUMENTS_BUCKETS = ["documents", "pages"]
```

**Documents Bucket Schemas:**

- `Document` - Primary document entities
- `PlainText` - Text documents
- `HyperText` - HTML/web documents
- `Email` - Email messages
- `Article` - News articles and publications
- `Message` - Chat/messaging content
- `Audio`, `Video`, `Image` - Media with extracted text
- `Table`, `Workbook` - Structured documents
- `Package`, `Folder` - Archive containers

**Pages Bucket Schemas:**
- `Pages` - Web pages and extracted page content
- `Page` - Individual page entities

### Schema Filtering Implementation

```python
def get_index(self):
    # Target only documents and pages buckets for more_like_this queries
    schemata = []
    for bucket in ["documents", "pages"]:
        bucket_schemata = self._get_bucket_schemas(bucket)
        schemata.extend(bucket_schemata)
    return entities_read_index(schema=schemata)
```

## More Like This Algorithm

### Core Elasticsearch More Like This

The system uses Elasticsearch's built-in More Like This query:

```python
def more_like_this_query(entity, parser=None):
    mlt_query = {
        "more_like_this": {
            "fields": ["content", "text", "name", "names"],
            "like": [{"_id": entity.id}],
            "min_term_freq": parser.get_mlt_min_term_freq(),
            "max_query_terms": parser.get_mlt_max_query_terms(),
            "min_doc_freq": parser.get_mlt_min_doc_freq(),
            "minimum_should_match": parser.get_mlt_minimum_should_match()
        }
    }
```

### How It Works

1. **Term Extraction:** Elasticsearch analyzes the source document's text fields
2. **Term Selection:** Selects most interesting terms based on TF-IDF scores
3. **Query Generation:** Creates a query using selected terms
4. **Similarity Scoring:** Ranks results by similarity to source document
5. **Schema Filtering:** Limits results to documents and pages only

### Parameter Effects

**`min_term_freq`**: Terms must appear this many times in source document
- Higher values = focus on more important terms
- Lower values = consider more terms from source

**`min_doc_freq`**: Terms must appear in this many documents corpus-wide
- Higher values = focus on common terms
- Lower values = include rare/specific terms

**`minimum_should_match`**: Percentage of query terms that must match
- Higher percentages = more strict similarity
- Lower percentages = broader similarity

**`max_query_terms`**: Maximum terms to use in generated query
- Higher limits = more comprehensive matching
- Lower limits = focus on most important terms

## MoreLikeThisQuery Implementation

### Basic Usage

```python
from openaleph_search.query.queries import MoreLikeThisQuery
from openaleph_search.parse.parser import SearchQueryParser

# Create document to find similar content
document = make_entity({
    "id": "research-paper-001",
    "schema": "Document",
    "properties": {
        "title": ["Deep Learning in Computer Vision"],
        "bodyText": [
            "Convolutional neural networks have revolutionized computer vision "
            "by learning hierarchical feature representations from raw pixels."
        ]
    }
})

# Find similar documents and pages
parser = SearchQueryParser([
    ("mlt_minimum_should_match", "25%"),
    ("mlt_max_query_terms", "20")
])
query = MoreLikeThisQuery(parser, document)
result = query.search()
```

### Advanced Configuration

```python
# Fine-tuned similarity search
parser = SearchQueryParser([
    ("mlt_min_doc_freq", "2"),          # Terms in at least 2 docs
    ("mlt_minimum_should_match", "20%"), # 20% of terms must match
    ("mlt_min_term_freq", "1"),         # Terms appear once in source
    ("mlt_max_query_terms", "30"),      # Use up to 30 terms
])

query = MoreLikeThisQuery(
    parser,
    entity=document,
    exclude=["doc-456"],  # Exclude specific documents
    datasets=["research_papers"]  # Limit to specific dataset
)
```

## Entity Exclusion and Filtering

### Automatic Self-Exclusion

```python
# Source entity automatically excluded from results
must_not = [{"ids": {"values": [entity.id]}}]
```

### Manual Exclusions

```python
# Exclude specific entities
query = MoreLikeThisQuery(
    parser,
    entity,
    exclude=["doc-123", "doc-456"]
)
```

### Dataset Filtering

```python
# Filter by dataset
query = MoreLikeThisQuery(
    parser,
    entity,
    datasets=["research_papers", "technical_docs"]
)

# Filter by collection
query = MoreLikeThisQuery(
    parser,
    entity,
    collection_ids=["collection-abc"]
)
```

## Query Structure

A complete More Like This query combines Elasticsearch MLT with filtering:

```python
{
    "bool": {
        "must": [
            {
                "more_like_this": {
                    "fields": ["content", "text", "name", "names"],
                    "like": [{"_id": "doc-123"}],
                    "min_term_freq": 1,
                    "max_query_terms": 25,
                    "min_doc_freq": 0,
                    "minimum_should_match": "10%"
                }
            }
        ],
        "must_not": [
            {"ids": {"values": ["doc-123"]}}  # Exclude source
        ],
        "filter": [
            {"terms": {"schema": ["Document", "Pages", "PlainText", "HyperText"]}},
            {"terms": {"dataset": ["allowed_datasets"]}}
        ]
    }
}
```

## Function Score Integration

More Like This results use function scoring for entity importance:

```python
{
    "function_score": {
        "query": more_like_this_query,
        "functions": [
            {
                "field_value_factor": {
                    "field": "num_values",
                    "factor": 0.5,
                    "modifier": "sqrt"
                }
            }
        ],
        "boost_mode": "sum"
    }
}
```

This ensures documents with more complete metadata rank higher.

## Performance Considerations

### Query Complexity

More Like This queries are generally less complex than multi-field matching:

- Single Elasticsearch MLT query vs. multiple boolean clauses
- Built-in term selection prevents query explosion
- Schema filtering limits search scope

### Parameter Tuning Guidelines

**For Large Corpora:**
```bash
mlt_min_doc_freq=5&mlt_minimum_should_match=25%
```

**For Small Collections:**
```bash
mlt_min_doc_freq=0&mlt_minimum_should_match=10%
```

**For Strict Similarity:**
```bash
mlt_minimum_should_match=40%&mlt_min_term_freq=2
```

**For Broad Discovery:**
```bash
mlt_minimum_should_match=5%&mlt_max_query_terms=50
```

## Usage Examples

### Research Paper Similarity

```python
# Find papers on similar topics
paper = make_entity({
    "schema": "Document",
    "properties": {
        "title": ["Neural Network Architectures for NLP"],
        "bodyText": [
            "Transformer models have become the dominant architecture "
            "for natural language processing tasks, achieving state-of-the-art "
            "results on language understanding and generation benchmarks."
        ]
    }
})

# Find similar research with moderate similarity threshold
parser = SearchQueryParser([("mlt_minimum_should_match", "20%")])
query = MoreLikeThisQuery(parser, paper)
results = query.search()
```

### News Article Clustering

```python
# Find related news articles
article = make_entity({
    "schema": "Article",
    "properties": {
        "title": ["Climate Change Impact on Agriculture"],
        "bodyText": [
            "Rising temperatures and changing precipitation patterns "
            "are affecting crop yields worldwide, threatening food security."
        ]
    }
})

# Broader similarity for news discovery
parser = SearchQueryParser([
    ("mlt_minimum_should_match", "15%"),
    ("mlt_max_query_terms", "35")
])
query = MoreLikeThisQuery(parser, article, datasets=["news_articles"])
```

### Web Page Content Discovery

```python
# Find similar web pages
page = make_entity({
    "schema": "Pages",
    "properties": {
        "title": ["Machine Learning Tutorial"],
        "indexText": [
            "Learn the fundamentals of supervised and unsupervised learning "
            "algorithms including linear regression, decision trees, and clustering."
        ]
    }
})

# Cross-schema similarity (pages finding documents)
parser = SearchQueryParser([("mlt_minimum_should_match", "12%")])
query = MoreLikeThisQuery(parser, page)
# Can find both Pages and Document entities with similar content
```

## Testing and Validation

The More Like This system includes comprehensive tests:

```python
def test_more_like_this():
    # Create documents with similar content
    ml_doc1 = make_entity("Document", "ML Research",
                         bodyText="neural networks deep learning")
    ml_doc2 = make_entity("Document", "AI Survey",
                         bodyText="artificial intelligence machine learning")
    cooking_doc = make_entity("Document", "Recipes",
                             bodyText="italian pasta french pastries")

    # Test finds similar ML documents, not cooking
    query = MoreLikeThisQuery(parser, ml_doc1)
    results = query.search()
    # Should find ml_doc2, not cooking_doc
```

### Parameter Testing

```python
def test_configurable_parameters():
    # Test custom parameters applied correctly
    parser = SearchQueryParser([
        ("mlt_min_doc_freq", "2"),
        ("mlt_minimum_should_match", "30%")
    ])

    query = MoreLikeThisQuery(parser, entity)
    inner_query = query.get_inner_query()

    mlt_params = inner_query["bool"]["must"][0]["more_like_this"]
    assert mlt_params["min_doc_freq"] == 2
    assert mlt_params["minimum_should_match"] == "30%"
```

## Comparison with Entity Matching

| Feature | MoreLikeThisQuery | MatchQuery |
|---------|-------------------|------------|
| **Purpose** | Text content similarity | Entity deduplication |
| **Target** | Documents/Pages only | All matchable entities |
| **Method** | TF-IDF text analysis | Multi-field exact matching |
| **Use Case** | Content discovery | Duplicate detection |
| **Performance** | Single MLT query | Multiple boolean clauses |
| **Precision** | Moderate (content-based) | High (structured matching) |

### When to Use Each

**Use MoreLikeThisQuery for:**
- Finding topically similar documents
- Content recommendation systems
- Research paper clustering
- News article grouping
- Tutorial/documentation discovery

**Use MatchQuery for:**
- Entity deduplication
- Identity resolution
- Person/organization matching
- Structured data linking
- Data quality improvement

---

## Technical Implementation

### Overview

The More Like This functionality is implemented through the `MoreLikeThisQuery` class in `openaleph_search/query/queries.py:165` and the `more_like_this_query` function in `openaleph_search/query/more_like_this.py:15`. The system leverages Elasticsearch's built-in More Like This capability with custom parameter configuration and schema filtering.

### Implementation Details

The More Like This system provides:
- **Elasticsearch MLT Integration**: Direct use of Elasticsearch's more_like_this query
- **Configurable Parameters**: URL-based parameter tuning for similarity thresholds
- **Schema Targeting**: Automatic filtering to documents and pages buckets only
- **Cross-Schema Matching**: Documents can match Pages and vice versa based on content

### Implementation Location

More Like This query logic is in:
- `openaleph_search/query/more_like_this.py:15` - Core MLT query function
- `openaleph_search/query/queries.py:165` - MoreLikeThisQuery class
- `openaleph_search/parse/parser.py:290` - Parameter parsing methods
- `tests/test_more_like_this.py` - Comprehensive test coverage

### Configuration Methods

Parameter parsing methods in SearchQueryParser:
- `get_mlt_min_doc_freq()` - Document frequency threshold
- `get_mlt_minimum_should_match()` - Match percentage requirement
- `get_mlt_min_term_freq()` - Term frequency in source document
- `get_mlt_max_query_terms()` - Maximum terms for query generation
