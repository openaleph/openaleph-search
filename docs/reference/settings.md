# Configuration

Configure openaleph-search via environment variables. All settings use the `OPENALEPH_SEARCH_` prefix.

## Connection

### `uri`

Elasticsearch server URL(s).

- Type: `HttpUrl | list[HttpUrl]`
- Default: `http://localhost:9200`
- Environment: `OPENALEPH_SEARCH_URI` or `OPENALEPH_ELASTICSEARCH_URI`

```bash
# Single node
export OPENALEPH_SEARCH_URI=http://localhost:9200

# Multiple nodes
export OPENALEPH_SEARCH_URI=http://es1:9200,http://es2:9200
```

### `ingest_uri`

Optional dedicated URI(s) for ingest operations. Falls back to `uri` if not set.

- Type: `HttpUrl | list[HttpUrl] | None`
- Default: `None`
- Environment: `OPENALEPH_SEARCH_INGEST_URI` or `OPENALEPH_ELASTICSEARCH_INGEST_URI`

### `timeout`

Request timeout in seconds.

- Type: `int`
- Default: `60`

### `max_retries`

Maximum retry attempts for failed requests.

- Type: `int`
- Default: `3`

### `retry_on_timeout`

Retry on timeout errors.

- Type: `bool`
- Default: `true`

### `connection_pool_limit_per_host`

Connection pool limit for AsyncElasticsearch.

- Type: `int`
- Default: `25`

## Indexing

### `indexer_concurrency`

Number of concurrent indexing workers. For pre-processing entity data, python's `ProcessPoolExecuter` is used, as this is a cpu-bound computation. For indexing, `ThreadPoolExecutor` is used to make concurrent async network calls to the Elasticsearch cluster. Keep this in mind when allocating resources to multiple index workers.

- Type: `int`
- Default: `8`

### `indexer_chunk_size`

Documents per indexing batch.

For document-heavy data (much full text payload) or when experiencing Elasticsearch time-outs, reduce this number.

- Type: `int`
- Default: `1000`

### `indexer_max_chunk_bytes`

Maximum batch size in bytes.

- Type: `int`
- Default: `5242880` (5 MB)

## Index structure

### `index_prefix`

Prefix for index names.

- Type: `str`
- Default: `openaleph`

Index names follow the pattern: `{prefix}-{type}-{version}`

Example: `openaleph-entity-things-v1`

### `index_write`

Current write index version.

- Type: `str`
- Default: `v1`

### `index_read`

Read index version(s).

- Type: `str | list[str]`
- Default: `["v1"]`

Accepts a json string for multiple values:

```bash
export OPENALEPH_SEARCH_INDEX_READ=["v1","v2"]
```

### `index_shards`

Number of primary shards. [Read more about the different shard distributions for different indexes used](mapping.md#shard-distribution)

- Type: `int`
- Default: `10`

### `index_replicas`

Number of index replicas.

- Type: `int`
- Default: `0`

### `index_namespace_ids`

Enable ID namespacing by dataset name. This appends a hash value to the original entity id. [OpenAleph](https://openaleph.org) relies on this currently with the strict dataset separation approach.

- Type: `bool`
- Default: `true`

### `index_refresh_interval`

Elasticsearch refresh interval for near-realtime search.

- Type: `str`
- Default: `1s`

Valid values: time units like `1s`, `5s`, `1m`, or `-1` to disable.

```bash
# Disable for bulk indexing performance
export OPENALEPH_SEARCH_INDEX_REFRESH_INTERVAL=-1

# Re-enable after bulk operations
export OPENALEPH_SEARCH_INDEX_REFRESH_INTERVAL=1s
```

### `index_expand_clause_limit`

Maximum query clause expansion.

- Type: `int`
- Default: `10`

### `index_delete_by_query_batchsize`

Batch size for delete operations.

- Type: `int`
- Default: `100`

## Index boosting

Control scoring weights for different entity types. By default, no weights are applied.

### `index_boost_intervals`

Boost for interval entities.

- Type: `int`
- Default: `1`

### `index_boost_things`

Boost for Thing entities.

- Type: `int`
- Default: `1`

### `index_boost_documents`

Boost for Document entities.

- Type: `int`
- Default: `1`

### `index_boost_pages`

Boost for Page entities.

- Type: `int`
- Default: `1`

```bash
# Prioritize documents in search results
export OPENALEPH_SEARCH_INDEX_BOOST_DOCUMENTS=2
```

## Search behavior

### `query_function_score`

Enable function_score wrapper for scoring.

- Type: `bool`
- Default: `false`

When enabled, wraps queries with Elasticsearch function_score to apply a scoring that de-penalizes entity matches with many names. In practice this means, for a term "Jane Doe" Person entity results with this name are considered more relevant as mentions of that name in documents full-text. This has effect on search performance in big clusters.

### `content_term_vectors`

Enable term vectors and offsets for content field.

- Type: `bool`
- Default: `true`

Required for [Fast Vector Highlighter](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/highlighting#fast-vector-highlighter) and improves [more like this](../more_like_this.md) matching queries. Disable to reduce index storage size.

## Highlighting

[Read more](../highlighting.md)

### `highlighter_fvh_enabled`

Use Fast Vector Highlighter for content field.

- Type: `bool`
- Default: `true`

When false, uses Unified Highlighter instead. FVH requires `content_term_vectors=true`.

### `highlighter_fragment_size`

Characters per highlight snippet.

- Type: `int`
- Default: `200`

### `highlighter_number_of_fragments`

Snippets per document.

- Type: `int`
- Default: `3`

### `highlighter_phrase_limit`

Maximum phrases to analyze per document.

- Type: `int`
- Default: `64`

Prevents performance issues with documents containing many phrase matches.

### `highlighter_boundary_max_scan`

Characters to scan for sentence boundaries.

- Type: `int`
- Default: `100`

### `highlighter_no_match_size`

Fragment size when no match found.

- Type: `int`
- Default: `300`

### `highlighter_max_analyzed_offset`

Maximum characters to analyze for highlighting.

- Type: `int`
- Default: `999999`

## Authorization

[Read more](./authorization.md)

### `auth`

Enable authorization mode.

- Type: `bool`
- Default: `false`

Set to `true` when using with [OpenAleph](https://openaleph.org) platform for dataset-based access control.

### `auth_field`

Field to filter/apply auth on.

- Type: `str`
- Default: `dataset`

For OpenAleph, the auth field (currently) is `collection_id`.

## Environment file

Create a `.env` file in your project directory:

```bash
# .env
OPENALEPH_SEARCH_URI=http://localhost:9200
OPENALEPH_SEARCH_INDEX_PREFIX=myproject
OPENALEPH_SEARCH_INDEX_SHARDS=5
OPENALEPH_SEARCH_INDEXER_CONCURRENCY=4
```

Settings are automatically loaded from `.env` files.
