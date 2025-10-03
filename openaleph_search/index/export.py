from typing import Generator

from anystore.logging import get_logger
from elasticsearch.helpers import scan

from openaleph_search.core import get_es
from openaleph_search.index.indexer import Action
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.base import Query
from openaleph_search.settings import Settings

log = get_logger(__name__)


def export_index_actions(
    index: str | None = None,
    parser: SearchQueryParser | None = None,
    include_excluded_fields: bool = False,
) -> Generator[Action, None, None]:
    """Export all documents from an index as Action objects.

    Note: By default, this exports only fields stored in _source. For entities,
    several fields are excluded from _source for storage optimization:
    - name_keys, name_parts, name_symbols, name_phonetic (retrievable via docvalues)
    - content (retrievable via stored_fields if the entity schema was
        `Document`). If the entity schema is not a Document and has had a value in
        `indexText` during indexing, this data is NOT retrievable (and therefore not
        recoverable) via this export and can't be used to fully re-index from this
        exported data!
    - text (NOT retrievable - excluded and not stored, but populated from other
        properties via copy_to, so can be regenerated)
    - name (NOT retrievable - excluded and not stored, but populated from other
        properties via copy_to, so can be regenerated)
    - property groups (NOT exported - populated via copy_to, can be regenerated)

    Given this limitation about `text` and `content` fields, this function CAN'T
    be used to back up and restore an entity index reliable.

    Args:
        index: Index name, pattern, or prefix to export from (e.g., "my-index",
            "my-index-*"), defaults to index prefix from settings
        parser: Optional SearchQueryParser to filter documents (defaults to match_all)
        include_excluded_fields: If True, retrieve fields excluded from _source:
            - Keyword fields via docvalues (name_keys, name_parts, etc.)
            - Full-text content via stored_fields
            - Note: 'text' field is NOT retrievable

    Yields:
        Action objects for each document in the index
    """
    from openaleph_search.index.mapping import Field

    es = get_es()
    settings = Settings()
    index = index or f"{settings.index_prefix}-*"

    if parser is None:
        query = {"match_all": {}}
    else:
        query = Query(parser).get_query()

    log.info("Starting index export: %s" % index)

    # Build query body
    query_body = {"query": query}

    # If we need excluded fields, request them via docvalues and stored_fields
    # - Keyword fields (name_keys, etc.) use docvalues
    # - Full-text content field uses stored_fields (has store: true)
    # - text field is NOT retrievable (excluded from _source, not stored)
    # - property groups (addresses, dates, etc.) are NOT exported (populated via copy_to)
    if include_excluded_fields:
        docvalue_fields = [
            Field.NAME_KEYS,
            Field.NAME_PARTS,
            Field.NAME_SYMBOLS,
            Field.NAME_PHONETIC,
        ]
        query_body["docvalue_fields"] = docvalue_fields
        query_body["stored_fields"] = [Field.CONTENT]
        query_body["_source"] = True

    for hit in scan(es, index=index, query=query_body, preserve_order=False):
        action: Action = {
            "_id": hit["_id"],
            "_index": hit["_index"],
            "_source": hit["_source"],
        }

        # Merge excluded fields back into _source if requested
        if include_excluded_fields and "fields" in hit:
            for field_name, field_values in hit["fields"].items():
                # Docvalues always return arrays
                action["_source"][field_name] = field_values

        yield action
