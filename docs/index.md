# OpenAleph Search

**OpenAleph Search** is the Elasticsearch-powered search engine component of [OpenAleph](https://openaleph.org), the open-source investigative data platform. This Python library provides the advanced search, entity resolution, and data analysis capabilities that power OpenAleph's ability to help investigators find connections and patterns in complex datasets.

## What is OpenAleph Search?

OpenAleph Search serves as the core search intelligence layer within the broader OpenAleph ecosystem. While **OpenAleph** is a full-stack platform for securely storing, processing, and collaborating on investigative datasets, **OpenAleph Search** specifically handles:

- Advanced entity search across millions of documents and entities
- Sophisticated entity matching and deduplication algorithms
- Content similarity detection and document clustering
- Complex aggregations and analytics for pattern discovery
- Multi-language and cross-dataset search capabilities

As a standalone library, OpenAleph Search can also be integrated into other investigative tools and workflows that require powerful search and entity resolution capabilities.

### Who Uses OpenAleph Search?

- **Investigative Journalists** - Uncover connections between people, organizations, and documents
- **Financial Investigators** - Track complex ownership structures and beneficial ownership
- **Compliance Teams** - Screen entities against sanctions lists and adverse media
- **Researchers** - Analyze large document collections and identify patterns
- **Data Analysts** - Perform entity resolution and deduplication across datasets

## Core Features

### 🔍 Advanced Entity Search

Search across millions of entities with sophisticated query capabilities:

- **Multi-field Search** - Query names, identifiers, addresses, and properties simultaneously
- **Fuzzy Matching** - Find entities even with typos, alternate spellings, or partial information
- **Cross-language Support** - Match entities across different languages and scripts
- **Faceted Search** - Filter and explore results by entity types, countries, datasets, and more

```python
# Find all companies related to "John Smith"
from openaleph_search.query.queries import EntitiesQuery
from openaleph_search.parse.parser import SearchQueryParser

parser = SearchQueryParser([("q", "John Smith"), ("filter:schema", "Company")])
query = EntitiesQuery(parser)
results = query.search()
```

### 🎯 Entity Matching & Deduplication

Identify duplicate entities and potential matches using advanced algorithms:

- **Name-based Matching** - Compare entity names using phonetic encoding and normalization
- **Identifier Matching** - Match on registration numbers, tax IDs, and other unique identifiers
- **Property-based Scoring** - Use email addresses, phone numbers, and addresses for matching
- **Cross-dataset Matching** - Find the same entity across different data sources

```python
# Find entities similar to a known company
from openaleph_search.query.queries import MatchQuery

company = make_entity({
    "schema": "Company",
    "properties": {
        "name": ["Acme Corporation"],
        "registrationNumber": ["12345678"],
        "country": ["us"]
    }
})

query = MatchQuery(parser, company)
similar_entities = query.search()
```

### 📄 Content Discovery

Find similar documents and discover related content:

- **More Like This** - Identify documents with similar content based on text analysis
- **Cross-format Search** - Search across PDFs, emails, web pages, and structured documents
- **Topic Clustering** - Group documents by theme and subject matter
- **Content Recommendation** - Suggest relevant documents based on current research

```python
# Find documents similar to a research paper
from openaleph_search.query.queries import MoreLikeThisQuery

document = make_entity({
    "schema": "Document",
    "properties": {
        "title": ["Machine Learning Research"],
        "bodyText": ["Neural networks and deep learning applications..."]
    }
})

query = MoreLikeThisQuery(parser, document)
similar_docs = query.search()
```

### 📊 Powerful Analytics & Aggregations

Analyze patterns and trends in your data:

- **Faceted Analytics** - Count entities by type, country, dataset, and custom properties
- **Significant Terms** - Identify unusual or important terms that characterize result sets
- **Date Histograms** - Analyze trends over time with flexible date grouping
- **Nested Aggregations** - Build complex multi-dimensional analytics

```python
# Analyze companies by country and incorporation date
parser = SearchQueryParser([
    ("q", "technology companies"),
    ("facet", "countries"),
    ("facet", "incorporationDate"),
    ("facet_interval:incorporationDate", "year")
])
query = EntitiesQuery(parser)
results = query.search()
```

### 🎨 Rich Search Interface

Enhance user experience with advanced search features:

- **Search Highlighting** - Highlight matching terms in search results
- **Auto-complete** - Suggest entities and terms as users type
- **Search History** - Track and revisit previous searches
- **Export Capabilities** - Export results in multiple formats

### ⚙️ Flexible Configuration

Customize search behavior for different use cases:

- **Configurable Parameters** - Tune search algorithms via URL parameters
- **Custom Scoring** - Adjust relevance scoring based on entity importance
- **Index Management** - Organize data across multiple indexes and versions
- **Performance Tuning** - Optimize search performance for large datasets

## Use Cases

### Investigative Research

**Scenario**: Investigating a complex corporate network

```python
# 1. Find the main company
companies = search_entities("Offshore Holdings Ltd", schema="Company")

# 2. Find similar entities (potential duplicates/subsidiaries)
main_company = companies[0]
related = match_entities(main_company)

# 3. Find documents mentioning these entities
for entity in related:
    documents = search_entities(entity.caption, schema="Document")

# 4. Discover similar documents by content
for doc in documents:
    similar_docs = find_similar_documents(doc)
```

### Financial Due Diligence

**Scenario**: Screening a business partner

```python
# Screen against sanctions lists
sanctions_matches = search_entities(
    "Suspicious Company Inc",
    datasets=["sanctions", "adverse_media"]
)

# Check beneficial ownership
owners = search_entities(
    "John Doe",
    filters={"schema": "Person", "role": "shareholder"}
)

# Find related companies
for owner in owners:
    companies = match_entities(owner, target_schema="Company")
```

### Document Analysis

**Scenario**: Analyzing a leaked document collection

```python
# Find key documents
key_docs = search_entities("offshore accounts", schema="Document")

# Cluster similar documents
document_clusters = {}
for doc in key_docs:
    similar = find_similar_documents(doc, threshold=0.7)
    document_clusters[doc.id] = similar

# Extract significant terms
significant_terms = analyze_significant_terms(key_docs)
```

## Integration & Ecosystem

OpenAleph Search is a core component of the OpenAleph investigative platform:

### Within OpenAleph Platform
- **[OpenAleph](https://openaleph.org)** - The main investigative data platform that uses this library
- **Web Application** - User-friendly interface for investigators and journalists
- **Data Ingestion Pipeline** - OCR, transcription, and entity extraction feeding into search
- **Collaboration Features** - Secure sharing and teamwork built on top of search capabilities
- **API Layer** - RESTful APIs that expose OpenAleph Search functionality

### Supporting Technologies
- **[Follow the Money](https://followthemoney.tech)** - Standardized data model for entities and relationships
- **[Investigraph](https://github.com/investigativedata/investigraph)** - ETL pipelines for data processing
- **Elasticsearch** - Battle-tested search engine providing the underlying infrastructure

### Standalone Usage
OpenAleph Search can also be used independently for custom investigative tools, research applications, and specialized search requirements.

### Data Sources

OpenAleph Search works with diverse data sources:

- **Corporate Registries** - Company filings, beneficial ownership data
- **Sanctions Lists** - OFAC, EU, UN sanctions and watch lists
- **News & Media** - Articles, press releases, adverse media coverage
- **Court Records** - Legal filings, judgments, case documents
- **Leaks & Investigations** - Leaked databases, journalistic investigations
- **Government Data** - Public procurement, lobbying records, political donations

## Getting Started

### Installation

```bash
pip install openaleph-search
```

### Basic Search

```python
from openaleph_search.query.queries import EntitiesQuery
from openaleph_search.parse.parser import SearchQueryParser

# Search for entities
parser = SearchQueryParser([("q", "your search term")])
query = EntitiesQuery(parser)
results = query.search()

# Process results
for hit in results["hits"]["hits"]:
    entity = hit["_source"]
    print(f"Found: {entity['caption']} ({entity['schema']})")
```

### Configuration

Set up Elasticsearch connection:

```python
from openaleph_search.settings import Settings

settings = Settings()
settings.elasticsearch_url = "http://localhost:9200"
settings.elasticsearch_index = "your-index"
```

## Architecture

OpenAleph Search is built with modularity and performance in mind:

```
openaleph_search/
├── query/           # Search query implementations
│   ├── queries.py   # Main query classes (EntitiesQuery, MatchQuery, etc.)
│   ├── matching.py  # Entity matching algorithms
│   ├── more_like_this.py # Content similarity search
│   └── util.py      # Query utilities and helpers
├── parse/           # Query parsing and parameter handling
│   └── parser.py    # SearchQueryParser for URL parameters
├── index/           # Index management and mapping
│   ├── mapping.py   # Elasticsearch field mappings
│   ├── indexes.py   # Index configuration and management
│   └── entities.py  # Entity indexing operations
└── transform/       # Data transformation utilities
    └── util.py      # Text processing and normalization
```

## Performance & Scalability

OpenAleph Search is designed to handle large-scale investigations:

- **Elasticsearch Backend** - Proven scalability with billions of documents
- **Optimized Queries** - Efficient query structures for fast response times
- **Index Partitioning** - Separate indexes for different entity types
- **Caching Support** - Built-in caching for frequently accessed data
- **Streaming Results** - Handle large result sets without memory issues

### Benchmark Performance

Typical performance on modern hardware:

- **Simple Search**: < 50ms for millions of entities
- **Complex Matching**: < 200ms for multi-field entity matching
- **Bulk Operations**: 10,000+ entities/second indexing
- **Aggregations**: < 100ms for most faceted queries

## Community & Support

OpenAleph Search is part of the broader OpenAleph project:

- **Documentation** - Comprehensive guides and API reference
- **Examples** - Real-world usage examples and tutorials
- **Community** - Active community of investigators and developers
- **Training** - Workshops and training materials available

### Contributing

We welcome contributions from the community:

- **Bug Reports** - Help us improve reliability and performance
- **Feature Requests** - Suggest new capabilities for investigators
- **Code Contributions** - Contribute new features and improvements
- **Documentation** - Help improve and expand documentation

## Next Steps

Ready to start using OpenAleph Search? Here are some recommended next steps:

1. **[Quick Start Guide](cli.md)** - Set up your first search in minutes
2. **[Query Documentation](query.md)** - Learn about different query types
3. **[Entity Matching](matching.md)** - Master entity deduplication techniques
4. **[Content Discovery](more_like_this.md)** - Find similar documents and content
5. **[API Reference](reference/mapping.md)** - Detailed technical documentation

---

**OpenAleph Search** powers the search intelligence behind OpenAleph, the world's leading open-source investigative platform. As both a core component of OpenAleph and a standalone library, it empowers investigators, journalists, and researchers to uncover truth in complex data by providing the advanced search and entity resolution capabilities needed to find the connections that matter.
