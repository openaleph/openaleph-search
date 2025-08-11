from anystore.logging import get_logger

from openaleph_search.core import get_es
from openaleph_search.index.indexes import (
    configure_entities,
    entities_read_index,
)
from openaleph_search.index.xref import configure_xref, xref_index

log = get_logger(__name__)


def upgrade_search():
    """Add any missing properties to the index mappings."""
    configure_entities()
    configure_xref()


def all_indexes():
    return ",".join((xref_index(), entities_read_index()))


def delete_index():
    es = get_es()
    log.warning("🔥 Deleting all indices 🔥")
    es.indices.delete(index=all_indexes(), ignore=[404, 400])


def clear_index():
    es = get_es()
    es.delete_by_query(
        index=all_indexes(),
        body={"query": {"match_all": {}}},
        refresh=True,
        wait_for_completion=True,
        conflicts="proceed",
        ignore=[404],
    )
