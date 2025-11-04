# More Like This

Find documents and pages with similar text content using Elasticsearch's More Like This algorithm.

[Read more in the Elasticsearch documentation](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-mlt-query)

!!! info "Indexing with term vectors"
    According to Elasticsearch documentation, indexing the `content` field with term vectors enabled (which is the default setting) helps to get better results. But if index storage size is a serious concern and term vectors are disabled (`OPENALEPH_SEARCH_CONTENT_TERM_VECTORS=0`) "more like this" still works.

## How it works

More Like This analyzes text fields to find documents with similar content:

1. Extracts important terms from source document
2. Generates query using selected terms
3. Ranks results by similarity
4. Returns similar documents and pages

## Target schemas

Searches only [document entities](https://followthemoney.tech/explorer/schemata/Document/).

Other entity types (Person, Company, etc.) are excluded.

## Fields analyzed

- `content` - Primary text content
- `text` - Secondary text content
- `name` - Entity names (to spot similar file names)

## Parameters

### `mlt_min_doc_freq`

Minimum document frequency corpus-wide.

- Type: `int`
- Default: `0`

```bash
--args "mlt_min_doc_freq=2"
```

### `mlt_min_term_freq`

Minimum term frequency within source document.

- Type: `int`
- Default: `1`

```bash
--args "mlt_min_term_freq=2"
```

### `mlt_max_query_terms`

Maximum terms to use in query.

- Type: `int`
- Default: `25`

```bash
--args "mlt_max_query_terms=50"
```

### `mlt_minimum_should_match`

Percentage of query terms that must match.

- Type: `str`
- Default: `10%`

```bash
--args "mlt_minimum_should_match=25%"
```

## Parameter effects

### `min_term_freq`

Higher values focus on more important terms:

- Higher = considers only frequently mentioned terms
- Lower = includes more terms from source

### `min_doc_freq`

Controls term commonality:

- Higher = focuses on common terms
- Lower = includes rare/specific terms

### `minimum_should_match`

Controls similarity strictness:

- Higher percentages = stricter similarity
- Lower percentages = broader similarity

### `max_query_terms`

Affects query comprehensiveness:

- Higher = more comprehensive matching
- Lower = focus on most important terms

## Query structure

```json
{
  "more_like_this": {
    "fields": ["content", "text", "name"],
    "like": [{"_id": "doc-123"}],
    "min_term_freq": 1,
    "max_query_terms": 25,
    "min_doc_freq": 0,
    "minimum_should_match": "10%"
  }
}
```

Source entity is automatically excluded from results.
