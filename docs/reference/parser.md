# Query Parameters

Control search behavior through URL-style query parameters. Pass parameters via the `--args` flag in CLI commands or through HTTP query strings in API requests. This has the same behaviour than the URL parameters used by the [OpenAleph](https://openaleph.org) search api.

## Basic parameters

### `q`

Main search query text. You can use [Elasticsearch query string query](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-query-string-query#query-string-syntax) here.

```bash
openaleph-search search query-string "jane smith"
```

Supports Lucene query syntax:

- Field queries: `name:jane`
- Phrases: `"exact phrase"`
- Boolean: `AND`, `OR`, `NOT`
- Wildcards: `sm*th`, `sm?th`
- Fuzzy: `smith~0.8`
- Ranges: `date:[2020 TO 2022]`

### `prefix`

Prefix search on name fields.

```bash
--args "prefix=jane"
```

## Pagination

### `offset`

Number of results to skip.

- Type: `int`
- Default: `0`

### `limit`

Maximum results to return.

- Type: `int`
- Default: `20`
- Maximum: `9999`

```bash
--args "offset=100&limit=50"
```

### `next_limit`

Limit for next page (used by pagination controls).

- Type: `int`
- Default: same as `limit`

## Sorting

### `sort`

Sort field and direction.

Format: `field:direction`

Directions: `asc`, `desc`

```bash
# Sort by label ascending
--args "sort=label:asc"

# Multiple sort fields
--args "sort=_score:desc&sort=label:asc"
```

## Filtering

### Basic filters

Format: `filter:FIELD=VALUE`

```bash
# Single filter
--args "filter:schema=Person"

# Multiple values (OR logic)
--args "filter:schema=Person&filter:schema=Company"

# Multiple fields (AND logic)
--args "filter:schema=Person&filter:countries=us"
```

### Range filters

For numeric and date fields:

```bash
# Greater than
--args "filter:gt:date_created=2020-01-01"

# Greater than or equal
--args "filter:gte:date_created=2020-01-01"

# Less than
--args "filter:lt:date_created=2023-01-01"

# Less than or equal
--args "filter:lte:date_created=2023-01-01"

# Date range
--args "filter:gte:date_created=2020-01-01&filter:lte:date_created=2022-12-31"
```

### Exclusion filters

Format: `exclude:FIELD=VALUE`

```bash
# Exclude specific values
--args "exclude:schema=Page"

# Multiple exclusions
--args "exclude:schema=Page&exclude:schema=Thing"
```

### Empty field filters

Format: `empty:FIELD=true`

```bash
# Find documents missing a field
--args "empty:birth_date=true"
```

## Faceting

### Basic facets

Format: `facet=FIELD`

```bash
# Single facet
--args "facet=schema"

# Multiple facets
--args "facet=schema&facet=countries&facet=dataset"
```

### Facet size

Format: `facet_size:FIELD=N`

Number of facet values to return (default: `20`).

```bash
--args "facet=schema&facet_size:schema=50"
```

### Facet total

Format: `facet_total:FIELD=true`

Include total distinct count for facet.

```bash
--args "facet=dataset&facet_total:dataset=true"
```

### Facet values

Format: `facet_values:FIELD=true|false`

Include actual facet values (default: `true`).

```bash
# Only get facet counts, no values
--args "facet=schema&facet_values:schema=false"
```

### Date histograms

Format: `facet_interval:FIELD=INTERVAL`

Group date facets by interval.

Intervals: `year`, `quarter`, `month`, `week`, `day`, `hour`, `minute`

```bash
# Group by year
--args "facet=date_created&facet_interval:date_created=year"

# Group by month
--args "facet=date_created&facet_interval:date_created=month"
```

### Facet type

Format: `facet_type:FIELD=TYPE`

Specify facet aggregation type.

```bash
--args "facet=properties.entity&facet_type:properties.entity=entity"
```

## Significant terms

Find unusual or interesting terms in search results. [Read more](../significant_terms.md)

### `facet_significant`

Field for significant terms aggregation.

```bash
--args "facet_significant=names"
```

### `facet_significant_size`

Format: `facet_significant_size:FIELD=N`

Number of significant terms (default: `20`).

```bash
--args "facet_significant=names&facet_significant_size:names=50"
```

### `facet_significant_total`

Format: `facet_significant_total:FIELD=true`

Include total count.

```bash
--args "facet_significant=names&facet_significant_total:names=true"
```

### Significant text

Extract significant phrases from text content.

!!! warning
    This is a very cpu heavy operation (depending on index and cluster size and resources), use with caution and narrow down the query with filters beforehand.

```bash
# Default: content field, 5 terms
--args "facet_significant_text=content"

# Custom configuration
--args "facet_significant_text=content&facet_significant_text_size=10"
```

Parameters:

- `facet_significant_text` - Field to analyze (default: `content`)
- `facet_significant_text_size` - Number of terms (default: `5`)
- `facet_significant_text_min_doc_count` - Minimum doc count (default: `5`)
- `facet_significant_text_shard_size` - Shard size (default: `200`)

## Highlighting

### `highlight`

Enable search result highlighting. [Read more](../highlighting.md)

- Type: `bool`
- Default: `false`

```bash
--args "highlight=true"
```

### `highlight_count`

Number of highlight snippets per document.

- Type: `int`
- Default: `3`
- Use `0` for full text

```bash
--args "highlight=true&highlight_count=5"
```

### `max_highlight_analyzed_offset`

Maximum characters to analyze for highlighting.

- Type: `int`
- Default: `999999`

```bash
--args "highlight=true&max_highlight_analyzed_offset=500000"
```

## More-Like-This

Parameters for similarity search. [Read more](../more_like_this.md)

### `mlt_min_doc_freq`

Minimum document frequency for query terms.

- Type: `int`
- Default: `5`

### `mlt_min_term_freq`

Minimum term frequency within document.

- Type: `int`
- Default: `5`

### `mlt_max_query_terms`

Maximum number of query terms to use.

- Type: `int`
- Default: `50`

### `mlt_minimum_should_match`

Percentage of terms that must match.

- Type: `str`
- Default: `60%`

```bash
--args "mlt_min_doc_freq=3&mlt_max_query_terms=100&mlt_minimum_should_match=70%"
```

## Performance

### `dehydrate`

Strip down entity payload for faster responses, useful for search results overview lists.

- Type: `bool`
- Default: `false`

When enabled, removes properties from response to reduce payload size.

```bash
--args "dehydrate=true&limit=1000"
```

## Examples

### Basic search with filters

```bash
openaleph-search search query-string "jane doe" \
  --args "filter:schema=Person&filter:countries=us"
```

### Faceted search

```bash
openaleph-search search query-string "darc" \
  --args "facet=schema&facet=countries&facet_size:schema=50"
```

### Date range with highlighting

```bash
openaleph-search search query-string "investigation" \
  --args "filter:gte:date_created=2020-01-01&filter:lte:date_created=2022-12-31&highlight=true"
```

### Pagination and sorting

```bash
openaleph-search search query-string "transaction" \
  --args "offset=100&limit=50&sort=date_created:desc"
```

### Significant terms analysis

```bash
openaleph-search search query-string "offshore" \
  --args "facet_significant=names&facet_significant_text=content&facet_significant_text_size=10"
```

### Complex query

```bash
openaleph-search search query-string "properties.keywords:corruption" \
  --args "filter:schema=Person&filter:schema=Company&filter:countries=us&exclude:schema=Page&facet=dataset&facet=schema&highlight=true&highlight_count=5&sort=_score:desc&limit=100"
```

### Performance-optimized query

Doesn't return entity properties in the payload:

```bash
openaleph-search search query-string "bank" \
  --args "dehydrate=true&limit=1000&facet=schema&facet_values:schema=false"
```

## Field filters in query string

Use Lucene syntax directly in the query text:

```bash
# Field-specific
openaleph-search search query-string "name:jane AND countries:us"

# Phrases
openaleph-search search query-string "name:\"jane smith\""

# Fuzzy search
openaleph-search search query-string "name:smith~0.8"

# Range
openaleph-search search query-string "date:[2020 TO 2022]"

# Wildcards
openaleph-search search query-string "name:jane*"

# Boosting
openaleph-search search query-string "name:jane^2 OR title:jane"

# Boolean
openaleph-search search query-string "(name:jane OR properties.firstName:jane) AND countries:us"

# Negation
openaleph-search search query-string "name:jane -countries:ru"
```

## URL encoding

When building URLs, encode special characters:

```bash
# Space → %20
filter:name=Jane%20Doe

# Colon → %3A
sort=date%3Adesc

# Quote → %22
q=%22money%20laundering%22
```

The CLI handles encoding automatically when using `--args`.
