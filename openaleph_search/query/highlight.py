from typing import Any

from openaleph_search.index.mapping import Field


def get_highlighter(
    field: str, query: dict[str, Any] | None = None, count: int | None = None
) -> dict[str, Any]:
    # Content field - best UX with term vectors
    if field == Field.CONTENT:
        highlighter = {
            "type": "fvh",
            "fragment_size": 400,
            "fragment_offset": 50,
            "number_of_fragments": count or 3,
            "phrase_limit": 256,
            "order": "score",  # Best fragments first
            "boundary_scanner": "sentence",  # Break at sentences
            "boundary_max_scan": 300,  # better sentence detection
            "boundary_chars": r".,!?;\n|,{}\s",  # Explicit boundary for csv/json raw text
            "no_match_size": 300,  # Hard limit when no boundary found
            "fragmenter": "span",  # More precise fragment boundaries
            # "pre_tags": ["<em class='highlight-content'>"],
            # "post_tags": ["</em>"],
            "max_analyzed_offset": 999999,  # Handle large documents
        }
        if query:
            highlighter["highlight_query"] = query
        return highlighter
    # Human-readable names - exact highlighting
    if field == Field.NAME:
        highlighter = {
            "type": "unified",  # Good for mixed content
            "fragment_size": 200,  # Longer to capture full names/titles
            "number_of_fragments": 3,
            "fragmenter": "simple",  # Don't break names awkwardly
            "max_analyzed_offset": 999999,  # Handle large documents
            "pre_tags": [""],  # No markup
            "post_tags": [""],  # No markup
            # "pre_tags": ["<em class='highlight-name'>"],
            # "post_tags": ["</em>"],
        }
        return highlighter
    # Keyword names - simple exact matching
    if field == Field.NAMES:
        return {
            "type": "plain",  # Fast for keyword fields
            "number_of_fragments": 3,
            "max_analyzed_offset": 1000,  # Limit for keyword fields
            "pre_tags": [""],  # No markup
            "post_tags": [""],  # No markup
        }
    # other fields - leftovers, minimal highlighting if possible (not important)
    plain = {
        "type": "plain",  # Fastest option
        "fragment_size": 150,  # Shorter since less important
        "number_of_fragments": 1,  # Just one fragment
        "max_analyzed_offset": 999999,  # Handle large documents
        # "pre_tags": ["<em class='highlight-text'>"],
        # "post_tags": ["</em>"],
    }
    if query:
        plain["highlight_query"] = query
    return plain
