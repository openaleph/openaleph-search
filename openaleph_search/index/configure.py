"""Create and reconcile Elasticsearch index mappings.

Split out from `index.indexer` so that `index.indexes` can import
`configure_index` without pulling in the bulk indexer, which imports
`transform.entity`, which imports `index.indexes` right back.
"""

from anystore.decorators import error_handler
from anystore.logging import get_logger

from openaleph_search.core import get_es
from openaleph_search.index.util import (
    MAX_TIMEOUT,
    check_response,
    check_settings_changed,
)
from openaleph_search.settings import Settings

log = get_logger(__name__)
settings = Settings()


IMMUTABLE_MAPPING_PARAMS = ("type", "analyzer", "normalizer", "index", "store")


@error_handler(logger=log, max_retries=settings.max_retries)
def rewrite_mapping_safe(pending, existing):
    """Reconcile a pending mapping against the one ES is already serving.

    For every IMMUTABLE_MAPPING_PARAMS key (``type``, ``analyzer``,
    ``normalizer``, ``index``, ``store``) ES will reject any field-level
    change after creation. We handle two cases:

    1. The existing field spec carries an explicit value for the key →
       keep that value, drop whatever the pending mapping wanted to flip
       it to.
    2. The existing field spec is present but the key is absent → ES
       applied its default at creation time and that default is now
       immutable just like an explicit one. The ``_mapping`` API does not
       echo defaults back, so ``old_value is None`` here is *not* an
       invitation to push a new value — it means ES will refuse the
       change. Drop the pending key so the put_mapping call succeeds and
       the field keeps its (now-frozen) default behaviour. This is the
       case that bites text/html/json properties created before the
       ``index: false`` bugfix (commit e864564) landed; existing indexes
       have those fields with the default ``index: true``, and any
       attempt to push ``index: false`` raises
       ``illegal_argument_exception``. Cut-over to the intended value
       requires a coordinated reindex; that's deferred to v6.

    Non-immutable keys flow through normally, and any keys that exist on
    the live mapping but are missing from pending are copied over so the
    put_mapping body is a strict superset.
    """
    # This is a pretty bad idea long-term. We need to make it easier
    # to use multiple index generations instead.
    if not isinstance(pending, dict) or not isinstance(existing, dict):
        return pending
    for key, value in list(pending.items()):
        old_value = existing.get(key)
        value = rewrite_mapping_safe(value, old_value)
        if key in IMMUTABLE_MAPPING_PARAMS:
            if old_value is not None:
                pending[key] = old_value
            else:
                # Field exists; key absent → ES default is in effect and
                # immutable. Drop the pending override so ES doesn't 400.
                pending.pop(key, None)
            continue
        pending[key] = value
    for key, value in existing.items():
        if key not in pending:
            pending[key] = value
    return pending


@error_handler(logger=log, max_retries=settings.max_retries)
def configure_index(index, mapping, settings_):
    """Create or update a search index with the given mapping and
    SETTINGS. This will try to make a new index, or update an
    existing mapping with new properties.
    """
    es = get_es()
    if es.indices.exists(index=index):
        log.info("Configuring index: %s..." % index)
        options = {
            "index": index,
            "timeout": MAX_TIMEOUT,
            "master_timeout": MAX_TIMEOUT,
        }
        # `index` may be an alias (the bucket suffix is usually an alias onto a
        # versioned concrete index). es.indices.get keys its response by the
        # concrete backing index name, so `.get(index)` would miss it and hand
        # rewrite_mapping_safe an empty existing mapping — silently turning it
        # into a no-op pass-through that drops every immutability guard (e.g.
        # pushing `index: false` / `format` onto frozen fields → 400). Take the
        # sole resolved index's config instead.
        config = next(iter(es.indices.get(index=index).values()), {})
        settings_.get("index").pop("number_of_shards", settings.index_shards)
        if check_settings_changed(settings_, config.get("settings")):
            res = es.indices.close(ignore_unavailable=True, **options)
            res = es.indices.put_settings(body=settings_, **options)
            if not check_response(index, res):
                return False
        mapping = rewrite_mapping_safe(mapping, config.get("mappings"))
        # _source config (e.g. excludes) is immutable after index creation,
        # so we strip it when updating existing indexes
        mapping.pop("_source", None)
        res = es.indices.put_mapping(body=mapping, **options)
        if not check_response(index, res):
            return False
        res = es.indices.open(**options)
        return True
    else:
        log.info("Creating index: %s..." % index)
        body = {"settings": settings_, "mappings": mapping}
        res = es.indices.create(index=index, body=body)
        if not check_response(index, res):
            return False
        return True
