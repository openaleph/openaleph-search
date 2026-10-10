# Query Parameters

Control search behavior through URL-style query parameters. Pass parameters via the `--args` flag in CLI commands or through HTTP query strings in API requests. This has the same behaviour than the URL parameters used by the [OpenAleph](https://openaleph.org) search api.

The filter half of this grammar is [ftmq's](https://docs.investigraph.dev/lib/ftmq/query/): `filter:` / `exclude:` / `empty:`, `facet=`, `metric:`, `sort`, `limit` and `offset` are parsed by `ftmq.Query.from_params`, and the resulting query object is compiled to Elasticsearch by `openaleph_search.query.elastic.Elastic`. Everything else on this page — `q`, `prefix`, highlighting, the per-facet rendering knobs, `mlt_*` — is Elasticsearch-specific and lives in `SearchOptions`.

```python
from openaleph_search import EntitiesQuery, parse_string

query, options = parse_string("filter:schema=Person&facet=group.countries", q="jane")
result = EntitiesQuery(query, options).search()
```

## Naming fields

**Every field is named by its family.** A bare name is refused, because the same word can mean two different things: `topics` is both a followthemoney property and a property-type group, and only the spelling says which was meant.

| Spelling | Means | Example |
| --- | --- | --- |
| `properties.<name>` | one followthemoney property | `filter:properties.nationality=mt` |
| `group.<name>` | a property-type group — `names`, `countries`, `dates`, `emails`, `addresses`, `identifiers`, `phones`, `ips`, `languages`, `topics`, `urls`, `entities`, … | `filter:group.countries=de` |
| `context.<name>` | an index field that is not a followthemoney concept | `filter:context.tags=politician` |
| `schema` | exact schema | `filter:schema=Person` |
| `schemata` | is-a schema (matches every descendant) | `filter:schemata=LegalEntity` |
| `dataset` | dataset membership | `filter:dataset=my_dataset` |
| `id` / `_id` | entity id | `filter:id=abc123` |
| `year` | the year of any date value | `facet=year` |

`context.` is the escape hatch for everything the index holds that followthemoney does not model: `context.tags`, `context.name_symbols`, `context.name_parts`, `context.name_keys`, `context.source_id`, `context.collection_id`, `context.role_id`, `context.origin`, `context.created_at`, `context.caption`.

!!! warning "`collection_id`"
    Spell it `context.collection_id`. A bare `filter:collection_id=` is refused with a `QueryError`: ftmq's grammar aliases that key to `dataset`, while openaleph indexes a collection id as its own field, so accepting it would silently answer a different question.

An unknown field raises `QueryError` rather than quietly matching nothing.

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

## Sorting

### `sort`

Sort field and direction.

Format: `field:direction`

Directions: `asc`, `desc`

Fields are named the same way filters are, so a numeric or date field automatically sorts on its `numeric.*` twin rather than lexicographically.

```bash
# Sort by name ascending
--args "sort=properties.name:asc"

# Multiple sort fields — the last one given wins, `_score` breaks ties
--args "sort=group.dates:desc&sort=properties.name:asc"
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
--args "filter:schema=Person&filter:group.countries=us"
```

### Range filters

For numeric and date fields:

```bash
# Greater than
--args "filter:gt:properties.date=2020-01-01"

# Greater than or equal
--args "filter:gte:properties.date=2020-01-01"

# Less than
--args "filter:lt:properties.date=2023-01-01"

# Less than or equal
--args "filter:lte:properties.date=2023-01-01"

# Date range — one value inside the window, not one below and one above
--args "filter:gte:properties.date=2020-01-01&filter:lte:properties.date=2022-12-31"
```

Two bounds on the same field compile to a *single* `range` clause. That is deliberate: on a multi-valued field, two separate range clauses would also match an entity holding one date below the window and another above it.

### Substring and prefix filters

An ftmq extension of the grammar; `like` is case sensitive, `ilike` is not. Both match a literal substring — `*` and `?` in the value are escaped, not treated as wildcards.

```bash
--args "filter:ilike:properties.name=jan"
--args "filter:startswith:properties.name=Ja"
--args "filter:endswith:properties.name=son"
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

Format: `empty:FIELD`

```bash
# Find entities missing a field
--args "empty:properties.birthDate"
```

### `rql` — boolean queries

The flat `filter:` grammar is an AND of terms; it cannot express a cross-field `OR` or a negated group. Pass an [RQL](https://docs.investigraph.dev/lib/ftmq/query/#rql) string to send an arbitrary boolean tree, which overrides the flat filter params:

```bash
--args "rql=and(eq(schema,Person),or(eq(group.countries,de),eq(group.countries,at)))"
```

This compiles straight to a nested Elasticsearch `bool` query — `and` becomes `filter`, `or` becomes `should` with `minimum_should_match: 1`, `not` becomes `must_not`.

## Faceting

### Basic facets

Format: `facet=FIELD`

```bash
# Single facet
--args "facet=schema"

# Multiple facets
--args "facet=schema&facet=group.countries&facet=dataset"
```

Response keys follow the field's own spelling: `facet=group.countries` returns `group.countries.values`, `group.countries.cardinality` and — when other filters are active — `group.countries.filtered`.

A filter naming a field that is also a facet is moved into `post_filter`, so the facet still reports every value rather than only the selected one. That only applies to a flat conjunction: a query using `rql=` with an `OR` binds whole in the main query and produces no post filter.

### Facet size

Format: `facet_size:FIELD=N`

Number of facet values to return (default: `20`). `0` returns the count only.

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
--args "facet=group.dates&facet_interval:group.dates=year"

# Group by month
--args "facet=group.dates&facet_interval:group.dates=month"
```

`facet=year` is a yearly histogram by definition and needs no interval.

Range filters on the same field become the histogram's `extended_bounds`, so empty buckets are returned across the whole filtered window.

### Facet type

Format: `facet_type:FIELD=TYPE`

Caller-supplied hint, passed through to the response.

```bash
--args "facet=properties.entity&facet_type:properties.entity=entity"
```

## Metric aggregations

Compute numeric metrics on numeric fields. [Read more](../aggregations.md#metric-aggregations)

### `metric:TYPE`

Format: `metric:TYPE=FIELD`

Types: `sum`, `avg`, `min`, `max`

The field is named the same way filters are; the `numeric.` index prefix is resolved internally. An unknown function or an unknown property raises `QueryError`.

```bash
# Sum of amounts
--args "metric:sum=properties.amount"

# Multiple metrics
--args "metric:sum=properties.amount&metric:avg=properties.amount&metric:min=properties.area"
```

Response keys follow the `{field}.{type}` pattern (e.g. `properties.amount.sum`).

## Significant terms

Find unusual or interesting terms in search results. [Read more](../significant_terms.md)

### `facet_significant`

Field for significant terms aggregation.

```bash
--args "facet_significant=group.names"
```

### `facet_significant_size`

Format: `facet_significant_size:FIELD=N`

Number of significant terms (default: `20`).

```bash
--args "facet_significant=group.names&facet_significant_size:group.names=50"
```

### `facet_significant_total`

Format: `facet_significant_total:FIELD=true`

Include total count.

```bash
--args "facet_significant=group.names&facet_significant_total:group.names=true"
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

## Synonyms

### `synonyms`

Expand the query with name synonyms (`name_symbols` and `name_keys`). [Read more](../synonyms.md)

- Type: `bool`
- Default: `false`

```bash
--args "q=DARC Ltd&synonyms=true"
```

## More-Like-This

Parameters for similarity search. [Read more](../more_like_this.md)

### `mlt_min_doc_freq`

Minimum document frequency for query terms.

- Type: `int`
- Default: `1`

### `mlt_min_term_freq`

Minimum term frequency within document.

- Type: `int`
- Default: `1`

### `mlt_max_query_terms`

Maximum number of query terms to use.

- Type: `int`
- Default: `200`

### `mlt_minimum_should_match`

Percentage of terms that must match.

- Type: `str`
- Default: `10%`

### `mlt_min_word_length`

Minimum word length for query terms.

- Type: `int`
- Default: `5`

### `mlt_max_doc_freq`

Maximum document frequency for query terms.

- Type: `int`
- Default: `500`

```bash
--args "mlt_min_doc_freq=3&mlt_max_query_terms=100&mlt_minimum_should_match=25%"
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

### `include_fields`

Fields to keep in the response even when dehydrating. These are `_source` paths, not filter fields, so group names are spelled bare and expand to their property paths.

```bash
--args "dehydrate=true&include_fields=properties.birthDate&include_fields=emails"
```

## Examples

### Basic search with filters

```bash
openaleph-search search query-string "jane doe" \
  --args "filter:schema=Person&filter:group.countries=us"
```

### Faceted search

```bash
openaleph-search search query-string "darc" \
  --args "facet=schema&facet=group.countries&facet_size:schema=50"
```

### Date range with highlighting

```bash
openaleph-search search query-string "investigation" \
  --args "filter:gte:properties.date=2020-01-01&filter:lte:properties.date=2022-12-31&highlight=true"
```

### Pagination and sorting

```bash
openaleph-search search query-string "transaction" \
  --args "offset=100&limit=50&sort=group.dates:desc"
```

### Significant terms analysis

```bash
openaleph-search search query-string "offshore" \
  --args "facet_significant=group.names&facet_significant_text=content&facet_significant_text_size=10"
```

### Complex query

```bash
openaleph-search search query-string "properties.keywords:corruption" \
  --args "filter:schema=Person&filter:schema=Company&filter:group.countries=us&exclude:schema=Page&facet=dataset&facet=schema&highlight=true&highlight_count=5&limit=100"
```

### Boolean query

```bash
openaleph-search search query-string "sanctions" \
  --args "rql=and(eq(schemata,LegalEntity),or(eq(group.countries,de),eq(group.countries,at)))&facet=dataset"
```

### Performance-optimized query

Doesn't return entity properties in the payload:

```bash
openaleph-search search query-string "bank" \
  --args "dehydrate=true&limit=1000&facet=schema&facet_values:schema=false"
```

## Field filters in query string

Use Lucene syntax directly in the query text. This is the *Elasticsearch* query string, so it addresses index fields directly and is unrelated to the `filter:` grammar above:

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
filter:properties.name=Jane%20Doe

# Colon → %3A
sort=group.dates%3Adesc

# Quote → %22
q=%22money%20laundering%22
```

The CLI handles encoding automatically when using `--args`.
