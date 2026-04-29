from typing import Any

from openaleph_search.index.mapping import Field
from openaleph_search.settings import Settings

settings = Settings()


def make_field_highlight_query(
    text: str, fields: str | list[str], analyzer: str | None = None
) -> dict[str, Any]:
    """Build a query_string scoped to specific field(s) for highlighting."""
    if isinstance(fields, str):
        fields = [fields]
    qs: dict[str, Any] = {
        "query": text,
        "lenient": True,
        "fields": fields,
        "default_operator": "AND",
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
) -> dict[str, Any]:
    # Content field - configurable highlighting
    if field == Field.CONTENT:
        if settings.highlighter_fvh_enabled:
            # FVH (Fast Vector Highlighter) configuration
            highlighter = {
                "type": "fvh",
                "fragment_size": settings.highlighter_fragment_size,
                # "fragment_offset": 50,
                "number_of_fragments": count
                or settings.highlighter_number_of_fragments,
                "phrase_limit": settings.highlighter_phrase_limit,  # lower than default (256) for better memory performance  # noqa: B950
                "order": "score",  # Best fragments first
                "boundary_scanner": "chars",  # FVH needs 'chars'
                "boundary_max_scan": settings.highlighter_boundary_max_scan,  # better sentence detection  # noqa: B950
                # Explicit boundary chars added for csv/json/html/code raw text
                "boundary_chars": '.\t\n ,!?;_-=(){}[]<>|"',
                "no_match_size": settings.highlighter_no_match_size,  # Hard limit when no boundary/match found  # noqa: B950
                "fragmenter": "span",  # More precise fragment boundaries
                # "pre_tags": ["<em class='highlight-content'>"],
                # "post_tags": ["</em>"],
                "max_analyzed_offset": settings.highlighter_max_analyzed_offset,  # Handle large documents  # noqa: B950
            }
        else:
            # Unified highlighter with sentence boundary scanner
            highlighter = {
                "type": "unified",
                "fragment_size": settings.highlighter_fragment_size,
                "number_of_fragments": count
                or settings.highlighter_number_of_fragments,
                "order": "score",
                "boundary_scanner": "sentence",  # Use sentence boundary scanner
                "no_match_size": settings.highlighter_no_match_size,
                # "pre_tags": ["<em class='highlight-content'>"],
                # "post_tags": ["</em>"],
                "max_analyzed_offset": settings.highlighter_max_analyzed_offset,
            }
        if text:
            # Use [content, text] because content has term_vectors but is
            # excluded from _source and not stored.  ES's FVH/unified
            # highlighters fail on phrase queries with a single-field
            # query_string in this configuration; adding a second field
            # triggers an internal multi-field code path that works.
            highlighter["highlight_query"] = make_field_highlight_query(
                text, [Field.CONTENT, Field.TEXT], analyzer=analyzer
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
        "max_analyzed_offset": settings.highlighter_max_analyzed_offset,
        # "pre_tags": ["<em class='highlight-text'>"],
        # "post_tags": ["</em>"],
    }
    if text:
        default["highlight_query"] = make_field_highlight_query(
            text, field, analyzer=analyzer
        )
    else:
        default["highlight_query"] = {"match_all": {}}
    return default
