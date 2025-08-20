from anystore.logging import get_logger

from openaleph_search.core import get_es
from openaleph_search.index.indexes import (
    configure_entities,
    entities_read_index,
)

log = get_logger(__name__)


def upgrade_search():
    """Add any missing properties to the index mappings."""
    configure_entities()


def delete_index():
    es = get_es()
    log.warning("🔥 Deleting all indices 🔥")
    for index in entities_read_index().split(","):
        if es.indices.exists(index=index):
            es.indices.delete(index=index)


def clear_index():
    es = get_es()
    log.warning("🔥 Deleting all data 🔥")
    es.delete_by_query(
        index=entities_read_index(),
        body={"query": {"match_all": {}}},
        refresh=True,
        wait_for_completion=True,
        conflicts="proceed",
    )
