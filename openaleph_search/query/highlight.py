from typing import Any

from openaleph_search.index.mapping import Field
from openaleph_search.settings import Settings

settings = Settings()

# Elasticsearch rejects the whole request when a hit is longer than the index
# setting `index.highlight.max_analyzed_offset` (default 1000000) and the
# request asks for more; a value below it truncates the analyzed text instead.
MAX_ANALYZED_OFFSET = 999_999


def get_max_analyzed_offset(value: int | None = None) -> int:
    """Request `max_analyzed_offset`, defaulting to the setting, kept below the
    index limit."""
    if value is None:
        value = settings.highlighter_max_analyzed_offset
    return max(1, min(value, MAX_ANALYZED_OFFSET))


def make_field_highlight_query(
    text: str,
    fields: str | list[str],
    analyzer: str | None = None,
    operator: str = "AND",
) -> dict[str, Any]:
    """Build a query_string scoped to specific field(s) for highlighting."""
    if isinstance(fields, str):
        fields = [fields]
    qs: dict[str, Any] = {
        "query": text,
        "lenient": True,
        "fields": fields,
        "default_operator": operator,
        "allow_leading_wildcard": settings.allow_leading_wildcard,
    }
    if analyzer:
        qs["analyzer"] = analyzer
    return {"query_string": qs}


def get_highlighter(
    field: str,
    text: str | None = None,
    count: int | None = None,
    analyzer: str | None = None,
    max_analyzed_offset: int | None = None,
    operator: str = "AND",
) -> dict[str, Any]:
    """Highlighter for `field`; `operator` is the search query's
    `default_operator`, which the highlight query has to share: a clause
    the hit doesn't match leaves the whole `content` highlight empty."""
    max_analyzed_offset = get_max_analyzed_offset(max_analyzed_offset)
    # Content field - configurable highlighting
    if field == Field.CONTENT:
        # Unified highlighter with sentence boundary scanner
        highlighter = {
            "type": "unified",
            "fragment_size": settings.highlighter_fragment_size,
            "number_of_fragments": count or settings.highlighter_number_of_fragments,
            "order": "score",
            "boundary_scanner": "sentence",  # Use sentence boundary scanner
            "no_match_size": settings.highlighter_no_match_size,
            # "pre_tags": ["<em class='highlight-content'>"],
            # "post_tags": ["</em>"],
            "max_analyzed_offset": max_analyzed_offset,
            # Where `content` has `index_phrases` shingles (things, and indexes
            # created before 5.4) an exact phrase runs against their subfield,
            # which only counts for `content` through `matched_fields`. ES
            # refuses `matched_fields` unless the field requires field
            # matches, whatever the request-level setting.
            "require_field_match": True,
            "matched_fields": [Field.CONTENT, Field.CONTENT_PHRASES],
        }
        if text:
            highlighter["highlight_query"] = make_field_highlight_query(
                text, Field.CONTENT, analyzer=analyzer, operator=operator
            )
        else:
            # Prevent ES from falling back to the main search query for
            # highlighting — that would highlight filter terms (e.g. "4"
            # from collection_id=4) in the document text.
            highlighter["highlight_query"] = {"match_all": {}}
        return highlighter
    # Human-readable names - exact highlighting
    if field == Field.NAME:
        highlighter = {
            "type": "unified",  # Good for mixed content
            "fragment_size": 200,  # Longer to capture full names/titles
            "number_of_fragments": 1,
            "fragmenter": "simple",  # Don't break names awkwardly
            "pre_tags": [""],  # No markup
            "post_tags": [""],  # No markup
            # "pre_tags": ["<em class='highlight-name'>"],
            # "post_tags": ["</em>"],
        }
        return highlighter
    # Keyword names - simple exact matching
    if field == Field.NAMES:
        return {
            "type": "plain",
            "number_of_fragments": 1,
            "pre_tags": [""],  # No markup
            "post_tags": [""],  # No markup
        }
    # other fields - leftovers, minimal highlighting if possible (not important)
    default = {
        "type": "unified",
        "fragment_size": 150,  # Shorter since less important
        "number_of_fragments": 1,  # Just one fragment
        "max_analyzed_offset": max_analyzed_offset,
        # "pre_tags": ["<em class='highlight-text'>"],
        # "post_tags": ["</em>"],
    }
    if text:
        default["highlight_query"] = make_field_highlight_query(
            text, field, analyzer=analyzer, operator=operator
        )
    else:
        default["highlight_query"] = {"match_all": {}}
    return default
