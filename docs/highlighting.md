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

Maximum characters to analyze per document.

- Type: `int`
- Default: `999999`

Reduce this value for better performance on large documents:

```bash
--args "highlight=true&max_highlight_analyzed_offset=500000"
```

## Highlighter types

The system uses different Elasticsearch highlighters optimized for each field type:

### Fast Vector Highlighter (FVH)

Used for: `content` field (full-text of source documents)

Best for long text with accurate phrase highlighting. Requires term vectors to be stored in the index.

Configuration (via environment):

- `OPENALEPH_SEARCH_HIGHLIGHTER_FVH_ENABLED=true` (default)
- Requires `OPENALEPH_SEARCH_CONTENT_TERM_VECTORS=true` (default)

If fast vector highlighting is disabled, the unified highlighter is used for the `content` field.

### Unified Highlighter

Used for: `name` field

Balanced performance for entity names and titles.

### Plain Highlighter

Used for: `names` (keywords), `text`, and other fields

Fast highlighting for simple matches.

## Configuration

Control highlighting behavior via environment variables:

### `highlighter_fvh_enabled`

Use Fast Vector Highlighter for content field.

```bash
export OPENALEPH_SEARCH_HIGHLIGHTER_FVH_ENABLED=true
```

When false, uses Unified Highlighter instead.

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

### `highlighter_phrase_limit`

Maximum phrases to analyze per document.

```bash
export OPENALEPH_SEARCH_HIGHLIGHTER_PHRASE_LIMIT=64
```

Default: `64`

Lower values improve performance but may miss some matches.

### `highlighter_boundary_max_scan`

Characters to scan for sentence boundaries.

```bash
export OPENALEPH_SEARCH_HIGHLIGHTER_BOUNDARY_MAX_SCAN=100
```

Default: `100`

### `highlighter_no_match_size`

Fragment size when no match found.

```bash
export OPENALEPH_SEARCH_HIGHLIGHTER_NO_MATCH_SIZE=300
```

Default: `300`

### `highlighter_max_analyzed_offset`

Maximum characters to analyze.

```bash
export OPENALEPH_SEARCH_HIGHLIGHTER_MAX_ANALYZED_OFFSET=999999
```

Default: `999999`

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

- `content` - Main document text
- `name` - Entity names
- `names` - Name keywords
- `text` - Secondary text content

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

### Index size

Fast Vector Highlighter requires term vectors, which increase index size by approximately 20-30%.

Disable term vectors if index storage size is a serious concern:

```bash
export OPENALEPH_SEARCH_CONTENT_TERM_VECTORS=false
```

Requires reindexing to take effect.

### Query performance

- More snippets (`highlight_count`) = slower queries
- Larger documents = slower highlighting
- Lower `phrase_limit` = faster but less accurate
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
- Query may exceed `phrase_limit`
- Field may not have term vectors enabled

### Slow highlighting

- Reduce `highlight_count`
- Lower `max_highlight_analyzed_offset`
- Decrease `phrase_limit`
- (Other than that the name suggests, the FVH seems to be _slower_ than the unified highlighter): Consider disabling FVH: `OPENALEPH_SEARCH_HIGHLIGHTER_FVH_ENABLED=false`
