import contextlib

from anystore.logging import get_logger
from anystore.types import SDict
from banal import ensure_list

from openaleph_search.core import get_es
from openaleph_search.index.mapping import ANALYZE_SETTINGS  # , Field
from openaleph_search.settings import Settings

log = get_logger(__name__)
settings = Settings()


def index_name(name: str, version: str) -> str:
    return "-".join((settings.index_prefix, name, version))


def check_response(index, res):
    """Check if a request succeeded."""
    if res.get("status", 0) > 399 and not res.get("acknowledged"):
        error = res.get("error", {}).get("reason")
        log.error("Index [%s] error: %s" % (index, error))
        return False
    return True


def refresh_sync(sync: bool | None = False) -> bool:
    return settings.testing or bool(sync)


def unpack_result(res: SDict) -> SDict | None:
    """Turn a document hit from ES into a more traditional JSON object."""
    error = res.get("error")
    if error is not None:
        raise RuntimeError("Query error: %r" % error)
    if res.get("found") is False:
        return
    data = res.get("_source", {})
    data["id"] = res.get("_id")
    data["_index"] = res.get("_index")

    _score = res.get("_score")
    if _score is not None and _score != 0.0 and "score" not in data:
        data["score"] = _score

    if "highlight" in res:
        data["highlight"] = res["highlight"]
        # data["highlight"] = []
        # for value in res.get("highlight", {}).values():
        #     data["highlight"].extend(value)

    data["_sort"] = ensure_list(res.get("sort"))
    return data


def check_settings_changed(updated, existing):
    """Since updating the settings requires closing the index, we don't
    want to do it unless it's really needed. This will check if all the
    updated settings are already in effect."""
    if not isinstance(updated, dict) or not isinstance(existing, dict):
        return updated != existing
    for key, value in list(updated.items()):
        if check_settings_changed(value, existing.get(key)):
            return True
    return False


def index_settings(
    shards: int | None = settings.index_shards,
    replicas: int | None = settings.index_replicas,
):
    """Configure an index in ES with support for text transliteration."""
    if settings.testing:
        shards = 1
        replicas = 0
    return {
        **ANALYZE_SETTINGS,
        "index": {
            "number_of_shards": str(shards),
            "number_of_replicas": str(replicas),
            "refresh_interval": (
                "10ms" if settings.testing else settings.index_refresh_interval
            ),
            "similarity": {
                # We use this for names, to avoid over-penalizing entities with many names.
                "weak_length_norm": {
                    # BM25 is the default similarity algorithm.
                    "type": "BM25",
                    # 0.75 is the default
                    "b": 0.25,
                }
            },
            # storage optimization to put similar docs together for better compression:
            # https://www.elastic.co/docs/reference/elasticsearch/index-settings/sorting
            # "sort": {
            #     "field": [Field.SCHEMA, Field.DATASET]
            # }
        },
    }


@contextlib.contextmanager
def bulk_indexing_mode(refresh_interval: str = "600s"):
    """Context manager for bulk indexing with optimized settings.

    Phase 1: Sets optimized settings for maximum bulk indexing performance:
    - Async translog for better write performance
    - Longer sync and refresh intervals
    - No replicas during bulk load

    Phase 2: Restores normal production settings after bulk operations complete:
    - Request-level translog durability
    - Normal refresh interval
    - Configured number of replicas

    Args:
        refresh_interval: The refresh interval to use during bulk operations (default: "600s")

    Example:
        with bulk_indexing_mode():
            # Perform bulk operations with optimized settings
            bulk_index_entities(large_entity_batch)
        # Settings are automatically restored to normal production values
    """
    es = get_es()
    index_pattern = f"{settings.index_prefix}-entity-*"

    log.info("Entering bulk indexing mode with optimized settings")

    # Phase 1: Set bulk indexing settings
    bulk_settings = {
        "index": {
            "translog.durability": "async",
            "translog.sync_interval": "60s",
            "refresh_interval": refresh_interval,
            "number_of_replicas": 0,
        }
    }

    try:
        res = es.indices.put_settings(index=index_pattern, body=bulk_settings)
        if not check_response(index_pattern, res):
            raise RuntimeError("Failed to set bulk indexing settings")

        log.info(f"Set bulk indexing settings for entity indices: {index_pattern}")
        yield

    except Exception as e:
        log.error(
            f"Failed to set bulk indexing settings for entity indices {index_pattern}: {e}"
        )
        raise
    finally:
        # Phase 2: Restore normal settings
        log.info("Exiting bulk indexing mode, restoring normal settings")

        normal_settings = {
            "index": {
                "translog.durability": "request",
                "refresh_interval": settings.index_refresh_interval,
                "number_of_replicas": settings.index_replicas,
            }
        }

        try:
            res = es.indices.put_settings(index=index_pattern, body=normal_settings)
            if check_response(index_pattern, res):
                log.info(
                    f"Restored normal settings for entity indices: {index_pattern}"
                )
            else:
                log.error("Failed to restore normal settings after bulk indexing")
        except Exception as e:
            log.error(
                f"Failed to restore normal settings for entity indices {index_pattern}: {e}"
            )
