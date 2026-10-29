# Highlighting

Show where search terms appear in results with highlighted text snippets.

[Elasticsearch documentation highlighters](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/highlighting)

## Basic usage

Enable highlighting via query parameters:

```bash
openaleph-search search query-string "corruption" --args "highlight=true"
```

## Parameters

### `highlight`

Enable highlighting.

- Type: `bool`
- Default: `false`

### `highlight_count`

Number of snippets per document.

- Type: `int`
- Default: `3`
- Use `0` to return full highlighted text

```bash
--args "highlight=true&highlight_count=5"
```

### `max_highlight_analyzed_offset`

Maximum characters to analyze per document. Values above `999999` are lowered to it, as Elasticsearch fails the whole request when a hit is longer than its `index.highlight.max_analyzed_offset` (1000000) and more is asked for.

- Type: `int`
- Default: the `highlighter_max_analyzed_offset` setting (`100000`)

Raise it to highlight further into large documents, at the cost of slower highlighting:

```bash
--args "highlight=true&max_highlight_analyzed_offset=500000"
```

## Highlighter types

The system uses different Elasticsearch highlighters optimized for each field type:

### Unified Highlighter

Used for: `content` (document text), `text` (secondary text), `translation` (translated text), `name` (entity names)

The default highlighter for all fields. Balanced performance with good support for mixed content.

On `content` a phrase is highlighted as one span (`<em>Paul Manafort</em>`). Where `content` has `index_phrases` shingles (the things bucket, and indexes created before 5.4), exact phrases run against them, so its highlighter lists them in `matched_fields`, which Elasticsearch only accepts with `require_field_match: true` on that field.

## Configuration

Control highlighting behavior via environment variables:

### `highlighter_fragment_size`

Characters per snippet.

```bash
export OPENALEPH_SEARCH_HIGHLIGHTER_FRAGMENT_SIZE=200
```

Default: `200`

### `highlighter_number_of_fragments`

Snippets per document.

```bash
export OPENALEPH_SEARCH_HIGHLIGHTER_NUMBER_OF_FRAGMENTS=3
```

Default: `3`

### `highlighter_no_match_size`

Fragment size when no match found.

```bash
export OPENALEPH_SEARCH_HIGHLIGHTER_NO_MATCH_SIZE=300
```

Default: `300`

### `highlighter_max_analyzed_offset`

Maximum characters to analyze.

```bash
export OPENALEPH_SEARCH_HIGHLIGHTER_MAX_ANALYZED_OFFSET=100000
```

Default: `100000`, the default of `max_highlight_analyzed_offset`. Values above `999999` are lowered to it.

## Response format

Highlighted results appear in the `highlight` field:

```json
{
  "hits": {
    "hits": [
      {
        "_id": "doc-123",
        "_source": {...},
        "highlight": {
          "content": [
            "Evidence of <em>corruption</em> was found...",
            "The <em>investigation</em> revealed..."
          ],
          "name": [
            "<em>John Smith</em>"
          ]
        }
      }
    ]
  }
}
```

Matched terms are wrapped in `<em>` tags.

## Fields highlighted

Multiple fields are highlighted automatically:

- `content` - Main document text (primary highlight field for entities)
- `text` - Secondary text content (catch-all `copy_to` target)
- `translation` - Translated text content

The `text` and `translation` highlight fields can be disabled via settings for better performance on search results return:

- `OPENALEPH_SEARCH_HIGHLIGHTER_TEXT_FIELD=false`
- `OPENALEPH_SEARCH_HIGHLIGHTER_TRANSLATION_FIELD=false`

## Examples

### Basic highlighting

```bash
openaleph-search search query-string "money laundering" --args "highlight=true"
```

### More snippets

```bash
openaleph-search search query-string "investigation" \
  --args "highlight=true&highlight_count=5"
```

### Full text highlighting

```bash
openaleph-search search query-string "evidence" \
  --args "highlight=true&highlight_count=0"
```

### Limited document size

```bash
openaleph-search search query-string "report" \
  --args "highlight=true&max_highlight_analyzed_offset=100000"
```

### With filters

```bash
openaleph-search search query-string "corruption" \
  --args "filter:schema=Document&filter:countries=us&highlight=true"
```

## Performance considerations

### Text analysis

`content` is indexed without term vectors, so the unified highlighter re-analyzes the text of each returned hit, up to `max_highlight_analyzed_offset` characters. The cost grows with the number of hits and their size, not with the size of the index. In the pages bucket `content` keeps offsets in the index (`index_options: offsets`), which spares the re-analysis of large documents.

### Query performance

- More snippets (`highlight_count`) = slower queries
- Larger documents = slower highlighting
- Reduce `max_highlight_analyzed_offset` for large documents

### Optimization tips

For better performance:

```bash
# Reduce snippets
--args "highlight=true&highlight_count=2"

# Limit analyzed text
--args "highlight=true&max_highlight_analyzed_offset=500000"

# Use dehydration with highlighting
--args "highlight=true&dehydrate=true"
```

## Troubleshooting

### No highlights returned

Check that:
- `highlight=true` parameter is set
- Query matches terms in highlightable fields
- Terms exist in analyzed fields (not just keyword fields)

### Incomplete highlights

- Document may exceed `max_highlight_analyzed_offset`

### Slow highlighting

- Reduce `highlight_count`
- Lower `max_highlight_analyzed_offset`
