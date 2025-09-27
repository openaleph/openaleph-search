from typing import Any

from openaleph_search.index.mapping import Field
from openaleph_search.settings import Settings

settings = Settings()


def get_highlighter(
    field: str, query: dict[str, Any] | None = None, count: int | None = None
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
            "max_analyzed_offset": 999999,  # probably many names
            "pre_tags": [""],  # No markup
            "post_tags": [""],  # No markup
        }
    # other fields - leftovers, minimal highlighting if possible (not important)
    plain = {
        "type": "plain",  # Fastest option
        "fragment_size": 150,  # Shorter since less important
        "number_of_fragments": 1,  # Just one fragment
        # "max_analyzed_offset": 999999,  # Handle large documents
        # "pre_tags": ["<em class='highlight-text'>"],
        # "post_tags": ["</em>"],
    }
    if query:
        plain["highlight_query"] = query
    return plain
