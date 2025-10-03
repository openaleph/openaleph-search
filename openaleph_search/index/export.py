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
    index: str | None = None, parser: SearchQueryParser | None = None
) -> Generator[Action, None, None]:
    """Export all documents from an index as Action objects. For entities, this
    DOESN'T include all necessary data (e.g. name tokens, partly full-text) that
    is needed to fully re-index!

    Args:
        index: Index name, pattern, or prefix to export from (e.g., "my-index",
            "my-index-*"), defaults to index prefix from settings
        parser: Optional SearchQueryParser to filter documents (defaults to match_all)

    Yields:
        Action objects for each document in the index
    """
    es = get_es()
    settings = Settings()
    index = index or f"{settings.index_prefix}-*"

    if parser is None:
        query = {"match_all": {}}
    else:
        query = Query(parser).get_query()

    log.info("Starting index export: %s" % index)

    for hit in scan(es, index=index, query={"query": query}, preserve_order=False):
        action: Action = {
            "_id": hit["_id"],
            "_index": hit["_index"],
            "_source": hit["_source"],
        }
        yield action
