# Configuration Settings

OpenAleph-Search uses Pydantic Settings for configuration management, providing type-safe, environment-variable-based configuration with validation. The settings are defined in `openaleph_search/settings.py`.

## Overview

The `Settings` class inherits from `BaseSettings` (anystore.settings) and uses Pydantic for validation:

```python
from openaleph_search.settings import Settings

settings = Settings()
# Settings automatically loaded from environment variables
```

## Environment Configuration

### Environment Variable Prefix

All settings can be configured using environment variables with the `OPENALEPH_` prefix:

```bash
# Example environment variables
export OPENALEPH_ELASTICSEARCH_URL=http://localhost:9200
export OPENALEPH_INDEX_SHARDS=10
export OPENALEPH_SEARCH_AUTH=true
```

### Configuration Files

Settings can also be loaded from a `.env` file in the project root:

```bash
# .env file
OPENALEPH_ELASTICSEARCH_URL=http://elasticsearch:9200
OPENALEPH_INDEX_SHARDS=25
OPENALEPH_TESTING=false
```

## Core Settings

### Application Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `testing` | bool | `False` | Enable testing mode |

**Environment Variables:**

- `OPENALEPH_TESTING` or `OPENALEPH_DEBUG`

**Testing Mode Effects:**

- Disables settings caching for test isolation
- May affect other components' behavior

## Search Authorization

Controls access control and authentication integration:

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `search_auth` | bool | `False` | Enable search authorization |
| `search_auth_field` | str | `"dataset"` | Field used for authorization filtering |

### Usage

When `search_auth=True`:

- Queries require an `auth` object
- Results filtered by user's accessible datasets/collections
- Facet limits applied for unauthenticated users
- Background filters respect user permissions

```python
# Authorization enabled
settings.search_auth = True
parser = SearchQueryParser(args, auth=user_auth)  # auth required

# Authorization disabled
settings.search_auth = False
parser = SearchQueryParser(args)  # auth optional
```

## Elasticsearch Configuration

### Connection Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `elasticsearch_url` | HttpUrl \| list[HttpUrl] | `http://localhost:9200` | Elasticsearch cluster URLs |
| `elasticsearch_timeout` | int | `60` | Request timeout in seconds |
| `elasticsearch_max_retries` | int | `3` | Maximum retry attempts |
| `elasticsearch_retry_on_timeout` | bool | `True` | Retry on timeout errors |

### Multiple Elasticsearch Nodes

```python
# Single node
OPENALEPH_ELASTICSEARCH_URL=http://localhost:9200

# Multiple nodes
OPENALEPH_ELASTICSEARCH_URL=["http://es1:9200", "http://es2:9200", "http://es3:9200"]
```

### Connection Examples

```bash
# Local development
export OPENALEPH_ELASTICSEARCH_URL=http://localhost:9200

# Docker compose
export OPENALEPH_ELASTICSEARCH_URL=http://elasticsearch:9200

# Elastic Cloud
export OPENALEPH_ELASTICSEARCH_URL=https://my-cluster.es.io:9243

# Multiple nodes with authentication
export OPENALEPH_ELASTICSEARCH_URL=https://user:pass@es1.example.com:9200,https://user:pass@es2.example.com:9200
```

## Indexing Configuration

### Concurrency and Performance

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `indexer_concurrency` | int | `8` | Number of concurrent indexing workers |
| `indexer_chunk_size` | int | `1000` | Documents per indexing batch |
| `indexer_max_chunk_bytes` | int | `52,428,800` | Maximum batch size in bytes (50MB) |

### Tuning Guidelines

**Indexer Concurrency:**

- Increase for better indexing throughput
- Decrease if experiencing memory pressure
- Should not exceed available CPU cores

**Chunk Size:**

- Larger chunks = better throughput, more memory usage
- Smaller chunks = lower memory, more network overhead
- Optimal range: 500-2000 documents

**Max Chunk Bytes:**
- Prevents oversized requests to Elasticsearch
- Elasticsearch has default limits (~100MB)
- Adjust based on document sizes

```bash
# High-performance indexing
export OPENALEPH_INDEXER_CONCURRENCY=16
export OPENALEPH_INDEXER_CHUNK_SIZE=2000
export OPENALEPH_INDEXER_MAX_CHUNK_BYTES=104857600  # 100MB

# Memory-constrained environment
export OPENALEPH_INDEXER_CONCURRENCY=4
export OPENALEPH_INDEXER_CHUNK_SIZE=500
export OPENALEPH_INDEXER_MAX_CHUNK_BYTES=26214400   # 25MB
```

## Index Management

### Index Structure

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `index_shards` | int | `25` | Number of primary shards |
| `index_replicas` | int | `0` | Number of replica shards |
| `index_prefix` | str | `"openaleph"` | Index name prefix |
| `index_write` | str | `"v1"` | Current write index version |
| `index_read` | list[str] | `["v1"]` | Read index versions |

### Index Naming

Indexes follow the pattern: `{prefix}-{type}-{version}`

Examples:
- `openaleph-entities-v1` - Main entities index
- `openaleph-entities-v2` - New version during migration

### Sharding Strategy

**Default Configuration (25 shards):**
- Designed for dataset-based routing
- Supports large collections efficiently
- Allows horizontal scaling

**Customization:**
```bash
# Small deployment
export OPENALEPH_INDEX_SHARDS=5
export OPENALEPH_INDEX_REPLICAS=1

# Large deployment
export OPENALEPH_INDEX_SHARDS=50
export OPENALEPH_INDEX_REPLICAS=2
```

### Query Optimization

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `index_expand_clause_limit` | int | `10` | Maximum query clause expansion |
| `index_delete_by_query_batchsize` | int | `100` | Batch size for delete operations |
| `index_namespace_ids` | bool | `True` | Enable ID namespacing |

**Expand Clause Limit:**
- Prevents query explosion with wildcard expansions
- Protects against performance issues
- Increase cautiously for complex queries

**Delete Batch Size:**
- Controls bulk delete operation size
- Smaller batches = less resource usage
- Larger batches = faster bulk operations

## Index Boosting

Control relative scoring weights for different index types:

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `index_boost_intervals` | int | `1` | Boost for interval-based entities |
| `index_boost_things` | int | `1` | Boost for Thing entities |
| `index_boost_documents` | int | `1` | Boost for Document entities |
| `index_boost_pages` | int | `1` | Boost for Page entities |

### Boost Usage

Adjust relative importance of different entity types in search results:

```bash
# Prioritize documents over other entity types
export OPENALEPH_INDEX_BOOST_DOCUMENTS=2
export OPENALEPH_INDEX_BOOST_THINGS=1

# Equal weighting (default)
export OPENALEPH_INDEX_BOOST_DOCUMENTS=1
export OPENALEPH_INDEX_BOOST_THINGS=1
```

## Constants and Limits

### Application Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `MAX_PAGE` | `9999` | Maximum pagination offset + limit |
| `BULK_PAGE` | `1000` | Default bulk operation page size |

These constants are used throughout the application and cannot be configured via environment variables.

## Configuration Examples

### Development Environment

```bash
# .env for local development
OPENALEPH_TESTING=false
OPENALEPH_ELASTICSEARCH_URL=http://localhost:9200
OPENALEPH_INDEX_SHARDS=5
OPENALEPH_INDEX_REPLICAS=0
OPENALEPH_INDEXER_CONCURRENCY=4
OPENALEPH_SEARCH_AUTH=false
```

### Production Environment

```bash
# Production configuration
OPENALEPH_ELASTICSEARCH_URL=https://es-cluster.internal:9200
OPENALEPH_ELASTICSEARCH_TIMEOUT=120
OPENALEPH_ELASTICSEARCH_MAX_RETRIES=5
OPENALEPH_INDEX_SHARDS=25
OPENALEPH_INDEX_REPLICAS=2
OPENALEPH_INDEXER_CONCURRENCY=16
OPENALEPH_INDEXER_CHUNK_SIZE=1500
OPENALEPH_SEARCH_AUTH=true
OPENALEPH_SEARCH_AUTH_FIELD=dataset
```

### Testing Environment

```bash
# Testing configuration
OPENALEPH_TESTING=true
OPENALEPH_ELASTICSEARCH_URL=http://localhost:9200
OPENALEPH_INDEX_SHARDS=1
OPENALEPH_INDEX_REPLICAS=0
OPENALEPH_INDEXER_CONCURRENCY=2
OPENALEPH_SEARCH_AUTH=false
```

## Validation and Type Safety

### Pydantic Validation

Settings use Pydantic for automatic validation:

```python
# Automatic type conversion
OPENALEPH_INDEX_SHARDS=25        # string -> int
OPENALEPH_SEARCH_AUTH=true       # string -> bool

# URL validation
OPENALEPH_ELASTICSEARCH_URL=http://localhost:9200  # validated as HttpUrl

# List handling
OPENALEPH_INDEX_READ=v1,v2       # string -> list[str]
```

### Validation Errors

Invalid settings raise clear validation errors:

```python
# Invalid URL
OPENALEPH_ELASTICSEARCH_URL=not-a-url
# ValidationError: invalid URL format

# Invalid integer
OPENALEPH_INDEX_SHARDS=not-a-number
# ValidationError: value is not a valid integer
```

## Accessing Settings

### Application Usage

```python
from openaleph_search.settings import Settings

# Get settings instance
settings = Settings()

# Access configuration
es_url = settings.elasticsearch_url
shard_count = settings.index_shards
auth_enabled = settings.search_auth
```

### Testing Override

In testing mode, settings are reloaded for each access:

```python
settings.testing = True
# Settings will be refreshed from environment on each access
# Allows test-specific configuration changes
```

## Migration and Versioning

### Index Version Management

Use `index_write` and `index_read` for rolling deployments:

```bash
# Phase 1: Prepare new version
export OPENALEPH_INDEX_WRITE=v2
export OPENALEPH_INDEX_READ=v1,v2

# Phase 2: Switch to new version
export OPENALEPH_INDEX_WRITE=v2
export OPENALEPH_INDEX_READ=v2

# Phase 3: Clean up old version (remove v1)
```

This enables zero-downtime index migrations and rollback capabilities.
