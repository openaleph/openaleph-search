# Command Line Interface

The CLI provides commands for indexing, searching, and debugging queries.

!!! info
    The `--args` parameter is designed to accept the same URL-like arguments that are used in [OpenAleph](https://openaleph.org) api calls to the search backend.

## Search commands

### query-string

Search using Elasticsearch query_string syntax. [Read more](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-query-string-query#query-string-syntax)

```bash
openaleph-search search query-string "jane doe"
```

Parameters:

- `q` - Query text (required)
- `--args` - Query parameters (optional)
- `-o, --output-uri` - Output destination (default: stdout)
- `--output-format` - Output format: `raw` or `parsed` (default: `raw`)

Examples:

```bash
# Basic search
openaleph-search search query-string "corruption"

# With filters
openaleph-search search query-string "darc" --args "filter:schema=Company"

# Multiple filters
openaleph-search search query-string "person" \
  --args "filter:schema=Person&filter:countries=us&highlight=true"

# With facets
openaleph-search search query-string "bank" \
  --args "facet=schema&facet=countries&facet_size:schema=20"

# Date range filter
openaleph-search search query-string "transaction" \
  --args "filter:gte:date_created=2020-01-01&filter:lte:date_created=2022-12-31"

# Pagination
openaleph-search search query-string "investigation" \
  --args "offset=20&limit=50"

# Save to file
openaleph-search search query-string "evidence" -o results.json
```

### body

Execute search with raw JSON query body.

```bash
openaleph-search search body -i query.json
```

Parameters:

- `-i, --input-uri` - JSON query body (default: stdin)
- `-o, --output-uri` - Output destination (default: stdout)
- `--index` - Target index (optional)
- `--output-format` - Output format (default: `raw`)

Example:

```bash
# From file
openaleph-search search body -i custom_query.json -o results.json

# From stdin
cat query.json | openaleph-search search body
```

## Index management

### upgrade

Create or upgrade index mappings.

```bash
openaleph-search upgrade
```

Run this after installing or upgrading the package to ensure index mappings are up to date.

### reset

Drop all data and indexes, then recreate mappings.

!!! warning
    This deletes all indexed data and requires a complete re-index.

```bash
openaleph-search reset
```

## Indexing commands

### format-entities

Transform entities into index actions.

```bash
openaleph-search format-entities -d mydataset -i entities.ijson -o actions.json
```

Parameters:

- `-d, --dataset` - Dataset identifier (required)
- `-i, --input-uri` - Input URI with entity data (default: stdin)
- `-o, --output-uri` - Output URI for formatted actions (default: stdout)

Example:

```bash
# Format entities from file
openaleph-search format-entities -d companies -i companies.ijson -o actions.json

# From stdin
cat entities.ijson | openaleph-search format-entities -d mydata > actions.json
```

### index-entities

Index entities into a dataset.

```bash
openaleph-search index-entities -d mydataset -i entities.ijson
```

Parameters:

- `-d, --dataset` - Dataset identifier (required)
- `-i, --input-uri` - Input source with entities (default: stdin)

Examples:

```bash
# Index from file
openaleph-search index-entities -d companies -i companies.ijson

# Index from stdin
cat entities.ijson | openaleph-search index-entities -d mydata

# With debug output
OPENALEPH_SEARCH_INDEXER_DEBUG=1 openaleph-search index-entities \
  -d test -i tests/fixtures/samples.ijson
```

### index-actions

Index pre-formatted actions.

```bash
openaleph-search index-actions -i actions.json
```

Parameters:

- `-i, --input-uri` - Stream of JSON actions (default: stdin)

Use this when you've already formatted entities into index actions using `format-entities`.

### dump-actions

Export index documents by criteria.

```bash
openaleph-search dump-actions --args "filter:dataset=mydata" -o export.json
```

Parameters:

- `-o, --output-uri` - Output destination (default: stdout)
- `--index` - Specific index to export from (optional)
- `--args` - Query parser args and filters (optional)

Examples:

```bash
# Export entire dataset
openaleph-search dump-actions --args "filter:dataset=companies" -o backup.json

# Export specific schema
openaleph-search dump-actions \
  --args "filter:dataset=mydata&filter:schema=Person" \
  -o persons.json

# Export to stdout
openaleph-search dump-actions --args "filter:dataset=test"
```

## Analysis command

### analyze

Analyze text using Elasticsearch analyzers.

```bash
echo "John Smith" | openaleph-search analyze --field content
```

Parameters:

- `-i, --input-uri` - Text input to analyze (default: stdin)
- `--field` - Field to analyze with (default: `content`)
- `--schema` - Schema to use for field analysis (default: `LegalEntity`)
- `--tokens-only` - Return only unique token strings (flag)
- `-o, --output-uri` - Output destination (default: stdout)

Examples:

```bash
# Analyze text from stdin
echo "The quick brown fox" | openaleph-search analyze --field content

# Get tokens only
echo "John Smith & Associates" | openaleph-search analyze --tokens-only

# Analyze name field
echo "María José García" | openaleph-search analyze --field name --schema Person

# From file
openaleph-search analyze --field content -i document.txt

# Different analyzers by field
echo "john@example.com" | openaleph-search analyze --field properties.email
```

Use this to understand how text is tokenized and normalized for search.

## Query parameters (`--args`)

The `--args` parameter accepts URL query string format:

```
key1=value1&key2=value2&key3=value3
```

### Common parameters

```bash
# Filters
filter:schema=Person
filter:countries=us
filter:dataset=mydata

# Multiple values (OR logic)
filter:schema=Person&filter:schema=Company

# Exclusions
exclude:schema=Page

# Range filters
filter:gte:date_created=2020-01-01
filter:lte:date_created=2022-12-31

# Empty field check
empty:birth_date=true

# Facets
facet=schema&facet=countries
facet_size:schema=50
facet_total:dataset=true

# Pagination
offset=100
limit=50

# Sorting
sort=label:asc
sort=_score:desc

# Highlighting
highlight=true
highlight_count=5

# Performance
dehydrate=true
```

### Field syntax in queries

Use Lucene syntax in query strings:

```bash
# Field-specific search
openaleph-search search query-string "name:john AND countries:us"

# Phrase search
openaleph-search search query-string '"money laundering"'

# Fuzzy search
openaleph-search search query-string "john~0.8"

# Range search
openaleph-search search query-string "date:[2020 TO 2022]"

# Boosting
openaleph-search search query-string "company^2 person"

# Boolean operators
openaleph-search search query-string "john AND smith OR doe"
```

## Output formats

### raw (default)

Raw Elasticsearch JSON response.

```json
{
  "took": 15,
  "hits": {
    "total": {"value": 1234},
    "hits": [...]
  }
}
```

### parsed

Simplified output with just results.

## Environment variables

Set these before running commands:

```bash
# Elasticsearch connection
export OPENALEPH_SEARCH_URI=http://localhost:9200

# Index settings
export OPENALEPH_SEARCH_INDEX_PREFIX=myproject
export OPENALEPH_SEARCH_INDEX_WRITE=v1
export OPENALEPH_SEARCH_INDEX_READ=v1

# Indexer performance
export OPENALEPH_SEARCH_INDEXER_CONCURRENCY=8
export OPENALEPH_SEARCH_INDEXER_CHUNK_SIZE=1000

# Debug mode
export OPENALEPH_SEARCH_INDEXER_DEBUG=1
```

## Examples

### Search workflow

```bash
# 1. Find companies
openaleph-search search query-string "offshore" \
  --args "filter:schema=Company&facet=countries"

# 2. Get similar entities
openaleph-search search match "Acme Corporation"

# 3. Search with highlighting
openaleph-search search query-string "investigation" \
  --args "highlight=true&highlight_count=3"
```

### Indexing workflow

```bash
# 1. Format entities
openaleph-search format-entities -d companies -i data.ijson -o actions.json

# 2. Index actions
openaleph-search index-actions -i actions.json

# 3. Verify indexed data
openaleph-search search query-string "*" --args "filter:dataset=companies&limit=10"
```

### Analysis workflow

```bash
# Check how names are tokenized
echo "Dr. John A. Smith Jr." | openaleph-search analyze --field name --tokens-only

# Understand content analysis
echo "The investigation revealed evidence of corruption" | \
  openaleph-search analyze --field content

# Test different fields
echo "+1-555-123-4567" | openaleph-search analyze --field properties.phone
```

### Export workflow

```bash
# Export full dataset
openaleph-search dump-actions --args "filter:dataset=mydata" -o backup.json

# Export specific entities
openaleph-search dump-actions \
  --args "filter:dataset=mydata&filter:schema=Person&filter:countries=us" \
  -o us_persons.json
```
