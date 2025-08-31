# Search Result Highlighting

Highlight search terms in your results to show users exactly where matches occur. OpenAleph-Search automatically selects the best highlighting method for each field type.

## Quick Start

### Basic Usage

```bash
# Enable highlighting for search results
/search?q=corruption&highlight=true

# Control number of highlight fragments per document
/search?q=investigation&highlight=true&highlight_count=5
```

### URL Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `highlight` | bool | false | Enable search result highlighting |
| `highlight_count` | int | 3 | Number of highlight fragments per document |
| `max_highlight_analyzed_offset` | int | 999999 | Maximum characters to analyze for highlighting |

## Highlighter Types

OpenAleph-Search uses three different Elasticsearch highlighters, each optimized for specific field types:

### 1. Fast Vector Highlighter (FVH) - Content Field

**Field:** `content` (primary document text)
**Type:** `fvh` (Fast Vector Highlighter)

The content field uses the Fast Vector Highlighter, which is the most advanced option available:

```python
{
    "type": "fvh",
    "fragment_size": 400,
    "fragment_offset": 50,
    "number_of_fragments": 3,
    "phrase_limit": 256,
    "order": "score",
    "boundary_scanner": "sentence",
    "boundary_max_scan": 50,
    "max_analyzed_offset": 999999
}
```

**Key Features:**

- **Term Vectors Required**: Uses `term_vector: "with_positions_offsets"` from index mapping
- **Best Quality**: Most accurate highlighting with phrase support
- **Sentence Boundaries**: Breaks fragments at sentence boundaries for readability
- **Score Ordering**: Returns highest-scoring fragments first
- **Large Document Support**: Can handle documents up to ~1MB

**Performance Characteristics:**

- **Speed**: Fast due to pre-computed term vectors
- **Memory**: Higher memory usage due to term vector storage
- **Accuracy**: Highest accuracy for complex queries and phrases

### 2. Unified Highlighter - Name Field

**Field:** `name` (entity names)
**Type:** `unified`

Entity names use the Unified Highlighter for mixed content handling:

```python
{
    "type": "unified",
    "fragment_size": 200,
    "number_of_fragments": 3,
    "fragmenter": "simple",
    "max_analyzed_offset": 999999,
    "pre_tags": [""],
    "post_tags": [""]
}
```

**Key Features:**

- **Mixed Content**: Good for both analyzed and non-analyzed content
- **Name Preservation**: Simple fragmenter avoids breaking names awkwardly
- **Longer Fragments**: 200 characters to capture full names/titles
- **No Markup**: Currently configured without HTML tags

### 3. Plain Highlighter - Other Fields

**Fields:** `names` (keywords), `text`, and other general fields
**Type:** `plain`

For keyword fields and secondary content:

```python
{
    "type": "plain",
    "fragment_size": 150,
    "number_of_fragments": 1,
    "max_analyzed_offset": 999999
}
```

**Key Features:**

- **Fastest Performance**: Minimal processing overhead
- **Simple Highlighting**: Basic term matching
- **Shorter Fragments**: Focused on essential matches
- **Universal Compatibility**: Works with any field type

## Field-Specific Configuration

### Content Field Optimization

The content field is specially configured for optimal highlighting:

**Index Mapping:**
```python
CONTENT = {
    "type": "text",
    "analyzer": "icu-default",
    "search_analyzer": "icu-default",
    "index_phrases": True,           # Enable phrase queries
    "term_vector": "with_positions_offsets"  # Required for FVH
}
```

**Highlighting Benefits:**
- **Phrase Highlighting**: Accurate highlighting of multi-word phrases
- **Position Awareness**: Precise term position tracking
- **Offset Information**: Character-level highlight positioning

### Name Field Configuration

Name fields balance accuracy with performance:

**Index Mapping:**
```python
NAME = {
    "type": "text",
    "similarity": "weak_length_norm",  # Don't penalize long names
    "store": True                     # Store for highlighting
}
```

**Highlighting Benefits:**
- **Full Name Display**: Longer fragments capture complete names
- **Stored Field Access**: Fast retrieval from stored content
- **Simple Fragmentation**: Preserves name integrity

## Highlight Query Integration

### Automatic Query Detection

The highlighter automatically detects and uses the appropriate query:

```python
def get_highlight(self) -> dict[str, Any]:
    query = self.get_query_string()
    if self.parser.filters:
        # Build complex highlight query including filters
        query = bool_query()
        if self.get_query_string():
            query["bool"]["should"] = [self.get_query_string()]
        # Add filter-based highlighting for names and groups
        for key, values in self.parser.filters.items():
            if key in GROUPS or key == Field.NAME:
                for value in values:
                    query["bool"]["should"].append({
                        "multi_match": {
                            "fields": [Field.CONTENT, Field.TEXT, Field.NAME],
                            "query": value,
                            "operator": "AND"
                        }
                    })
```

### Filter-Based Highlighting

When filters are applied, the system extends highlighting to include filter terms:
- **Name Filters**: Highlight name matches in content
- **Group Filters**: Highlight country names, organization names, etc.
- **Multi-Field Matching**: Search across content, text, and name fields

## Response Structure

### Highlight Response Format

```json
{
    "hits": {
        "hits": [
            {
                "_id": "document-123",
                "_source": {...},
                "highlight": {
                    "content": [
                        "The <em>corruption</em> investigation revealed...",
                        "Evidence of <em>money laundering</em> was found..."
                    ],
                    "names": [
                        "<em>John Smith</em>"
                    ],
                    "text": [
                        "Additional <em>evidence</em> suggests..."
                    ]
                }
            }
        ]
    }
}
```

### Highlighted Fields

The system highlights multiple fields simultaneously:

| Field | Content | Highlighter | Purpose |
|-------|---------|-------------|---------|
| `content` | Primary document text | FVH | Main content highlighting |
| `names` | Entity name keywords | Plain | Name matching |
| `name` | Original entity names | Unified | Full name display |
| `text` | Secondary text content | Plain | Additional context |

## Performance Considerations

### Term Vector Storage

The content field's term vectors require additional storage:
- **Index Size**: ~20-30% larger due to term vectors
- **Query Speed**: Significantly faster highlighting
- **Memory Usage**: Higher during indexing and highlighting

### Boundary Scanning

Sentence boundary detection improves readability:
- **Processing Cost**: Minimal overhead for better UX
- **Fragment Quality**: More coherent text snippets
- **Max Scan Limit**: 50 characters to prevent performance issues

### Large Document Handling

All highlighters support large documents:
- **Max Analyzed Offset**: 999,999 characters (~1MB)
- **Fragment Prioritization**: Best matches first
- **Memory Management**: Streaming analysis for large content

## Configuration Examples

### High-Performance Setup

For maximum highlighting performance:

```python
# Increase fragment limits for detailed highlighting
{
    "highlight_count": 10,
    "max_highlight_analyzed_offset": 2000000
}
```

### Memory-Conscious Setup

For memory-constrained environments:

```python
# Reduce fragment counts and analysis limits
{
    "highlight_count": 2,
    "max_highlight_analyzed_offset": 500000
}
```

## Advanced Features

### Phrase Limit Control

Content highlighting includes phrase limit protection:
```python
"phrase_limit": 256  # Maximum phrases to analyze
```

This prevents performance degradation on documents with excessive phrase matches.

### Fragment Ordering

Fragments are ordered by relevance score:
```python
"order": "score"  # Best matches first
```

Users see the most relevant highlighted content immediately.

### HTML Tag Configuration

Currently disabled but configurable:
```python
# Disabled tags
"pre_tags": [""],
"post_tags": [""]

# Could be enabled with:
"pre_tags": ["<em class='highlight'>"],
"post_tags": ["</em>"]
```

## Integration with Search Queries

### Query String Highlighting

For simple text queries:
```bash
/search?q=corruption investigation&highlight=true
```

Highlights both "corruption" and "investigation" terms.

### Boolean Query Highlighting

For complex queries:
```bash
/search?q=money AND laundering&highlight=true
```

Highlights the complete phrase context.

### Filter Integration

Filters contribute to highlighting:
```bash
/search?q=investigation&filter:names=John Smith&highlight=true
```

Highlights both "investigation" and "John Smith" across relevant fields.

## Troubleshooting

### No Highlights Returned

Common causes:
- `highlight=false` parameter
- No matching terms in highlightable fields
- Terms only in non-analyzed fields

### Incomplete Highlights

Potential issues:
- `max_analyzed_offset` limit reached
- Complex queries exceeding phrase limits
- Memory constraints during highlighting

### Performance Issues

Optimization strategies:
- Reduce `highlight_count` for faster queries
- Lower `max_analyzed_offset` for memory savings
- Consider disabling highlighting for bulk operations

## Testing Highlighting

The test suite includes highlighting verification:

```python
def test_highlighting():
    # Basic term highlighting
    result = search_with_highlight("corruption")
    assert "<em>corruption</em>" in result

    # Phrase highlighting
    result = search_with_highlight('"money laundering"')
    assert "<em>money laundering</em>" in result

    # Unicode support
    result = search_with_highlight("Українська")
    assert "<em>Українська</em>" in result
```

This ensures highlighting works correctly across different languages and query types.

---

## Technical Implementation

### Overview

Highlighting is implemented in `openaleph_search/query/highlight.py` using the `get_highlighter()` function. The system automatically selects the optimal highlighter type based on the field being highlighted, providing the best performance and user experience for each content type.

### Implementation Location

The highlighting system is implemented in:
- `openaleph_search/query/highlight.py` - Core highlighting logic
- `openaleph_search/query/base.py:309` - Query integration
- `openaleph_search/index/mapping.py:146` - Term vector configuration
