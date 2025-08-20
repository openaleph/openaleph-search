from anystore.logging import get_logger
from anystore.types import SDict
from banal import ensure_list

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
        data["highlight"] = []
        for value in res.get("highlight", {}).values():
            data["highlight"].extend(value)

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
        "index": {
            "number_of_shards": str(shards),
            "number_of_replicas": str(replicas),
            # "refresh_interval": refresh,
            "similarity": {
                # We use this for names, to avoid over-penalizing entities with many names.
                "weak_length_norm": {
                    # BM25 is the default similarity algorithm.
                    "type": "BM25",
                    # 0.75 is the default
                    "b": 0.25,
                }
            },
        }
    }
