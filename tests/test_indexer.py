import asyncio

import orjson
import pytest
from elastic_transport import (
    ApiResponseMeta,
    HttpHeaders,
    NodeConfig,
    ObjectApiResponse,
)
from elasticsearch import ApiError, AsyncElasticsearch
from elasticsearch import ConnectionError as ESConnectionError
from elasticsearch.helpers import BulkIndexError
from ftmq.util import make_entity

from openaleph_search.index import indexer as indexer_module
from openaleph_search.index.admin import clear_index
from openaleph_search.index.configure import rewrite_mapping_safe
from openaleph_search.index.entities import (
    EntityVersion,
    get_entity_version,
    index_bulk,
    index_proxy,
    iter_entities,
    iter_entity_ids,
)
from openaleph_search.index.indexer import (
    Indexer,
    _bulk,
    _Gate,
    iter_action_batches,
)
from openaleph_search.settings import Settings
from openaleph_search.transform import entity as transform_module
from openaleph_search.transform.entity import _cap_text, format_entity, iter_batches


def test_indexer(entities, cleanup_after):
    # clear
    clear_index()

    index_bulk("test_dataset", entities)
    assert len(list(iter_entities())) == 21

    # overwrite
    index_bulk("test_dataset", entities)
    assert len(list(iter_entities())) == 21


def test_indexer_with_tags(cleanup_after):
    # clear
    clear_index()

    # Create entity with tags in context
    entity_data = {
        "id": "test-person-with-tags",
        "schema": "Person",
        "properties": {"name": ["Jane Doe"], "birthDate": ["1980-01-01"]},
    }
    entity = make_entity(entity_data)
    entity.context["tags"] = ["politician", "businessman", "controversial"]

    # Verify format_entity includes the tags
    formatted = format_entity("test_dataset", entity)
    assert formatted is not None
    assert "tags" in formatted["_source"]
    assert formatted["_source"]["tags"] == [
        "politician",
        "businessman",
        "controversial",
    ]

    index_bulk("test_dataset", [entity])

    # Verify entity was indexed
    indexed_entities = list(iter_entities())
    assert len(indexed_entities) == 1

    # Verify tags are in the indexed document
    indexed_entity = indexed_entities[0]
    assert "tags" in indexed_entity
    assert indexed_entity["tags"] == ["politician", "businessman", "controversial"]


def test_indexer_with_context(cleanup_after):
    # clear
    clear_index()

    # Create entity with OpenAleph metadata in context
    entity_data = {
        "id": "test-person-with-tags",
        "schema": "Person",
        "properties": {"name": ["Jane Doe"], "birthDate": ["1980-01-01"]},
    }
    entity = make_entity(entity_data)
    entity.context = {"role_id": 3, "mutable": True, "created_at": "2023-04-26"}

    # Verify format_entity includes the context
    formatted = format_entity("test_dataset", entity)
    assert formatted is not None
    assert formatted["_source"]["role_id"] == 3
    assert formatted["_source"]["mutable"] is True
    assert formatted["_source"]["created_at"] == "2023-04-26"

    index_bulk("test_dataset", [entity])

    # Verify entity was indexed
    indexed_entities = list(iter_entities())
    assert len(indexed_entities) == 1

    # Verify context is in the indexed document
    indexed_entity = indexed_entities[0]
    assert indexed_entity["role_id"] == 3
    assert indexed_entity["mutable"] is True
    assert indexed_entity["created_at"] == "2023-04-26"


def test_indexer_with_merged_fragment_context(cleanup_after):
    # Entities aggregated from multiple fragments (e.g. origins ingest +
    # analyze) arrive with merged context: followthemoney's
    # ``merge_context`` turns every scalar context value into a list
    # (role_id: [36], mutable: [False], ...). The formatter must fold
    # those back to scalars — only ``origin`` stays multi-valued.
    clear_index()

    entity_data = {
        "id": "test-doc-merged",
        "schema": "Folder",
        "properties": {"fileName": ["stuff"]},
    }
    ingest = make_entity(entity_data)
    ingest.context = {
        "role_id": 36,
        "mutable": False,
        "origin": "ingest",
        "created_at": "2023-04-26",
        "updated_at": "2023-04-26",
        "collection_id": 7,
    }
    analyze = make_entity(entity_data)
    analyze.context = {
        "role_id": 36,
        "mutable": False,
        "origin": "analyze",
        "created_at": "2023-04-27",
        "updated_at": "2023-04-27",
        "collection_id": 7,
    }
    # the real aggregation path: fragment merge list-ifies the context
    ingest.merge(analyze)
    assert ingest.context["role_id"] == [36]
    assert ingest.context["mutable"] == [False]

    formatted = format_entity("test_dataset", ingest)
    assert formatted is not None
    source = formatted["_source"]
    assert source["role_id"] == 36
    assert source["mutable"] is False
    assert sorted(source["origin"]) == ["analyze", "ingest"]
    assert source["created_at"] == "2023-04-26"  # min
    assert source["updated_at"] == "2023-04-27"  # max

    # conflicting mutable flags fold conservatively: immutable wins
    conflicted = make_entity(entity_data)
    conflicted.context = {"mutable": [True, False], "collection_id": 7}
    formatted = format_entity("test_dataset", conflicted, collection_id=17)
    assert formatted is not None
    assert formatted["_source"]["mutable"] is False
    assert formatted["_source"]["collection_id"] == 17

    # round-trip through the index keeps the folded shape (``origin`` is
    # not part of ENTITY_SOURCE includes, so it is absent on this read)
    index_bulk("test_dataset", [ingest], collection_id=17)
    indexed = list(iter_entities())
    assert len(indexed) == 1
    assert indexed[0]["role_id"] == 36
    assert indexed[0]["collection_id"] == 17
    assert indexed[0]["mutable"] is False


def test_get_entity_version(cleanup_after):
    """get_entity_version returns (seq_no, primary_term) and bumps on rewrites."""
    clear_index()

    entity = make_entity(
        {
            "id": "version-test-person",
            "schema": "Person",
            "properties": {"name": ["Jane Versioned"]},
        }
    )
    index_bulk("test_versions", [entity], sync=True)

    v1 = get_entity_version("version-test-person")
    assert isinstance(v1, EntityVersion)
    assert isinstance(v1.seq_no, int)
    assert isinstance(v1.primary_term, int)

    # Re-indexing the same id bumps the seq_no.
    entity2 = make_entity(
        {
            "id": "version-test-person",
            "schema": "Person",
            "properties": {"name": ["Jane Versioned"], "nationality": ["DE"]},
        }
    )
    index_bulk("test_versions", [entity2], sync=True)

    v2 = get_entity_version("version-test-person")
    assert v2 is not None
    assert v2.seq_no > v1.seq_no

    # Unknown id returns None.
    assert get_entity_version("does-not-exist") is None


def test_iter_entity_ids(entities, cleanup_after):
    # clear
    clear_index()

    # Index entities from fixture
    index_bulk("test_dataset", entities)

    # Get all entity IDs
    entity_ids = list(iter_entity_ids())
    assert len(entity_ids) == 21

    # Verify IDs match the indexed entities
    expected_ids = {e.id for e in entities}
    actual_ids = set(entity_ids)
    assert actual_ids == expected_ids

    # Test filtering by dataset
    # Create separate entities for other dataset to avoid overwriting
    other_entities = [
        make_entity(
            {
                "id": f"other-{i}",
                "schema": "Person",
                "properties": {"name": [f"Person {i}"]},
            }
        )
        for i in range(5)
    ]
    index_bulk("other_dataset", other_entities)

    test_dataset_ids = list(iter_entity_ids(dataset="test_dataset"))
    assert len(test_dataset_ids) == 21

    other_dataset_ids = list(iter_entity_ids(dataset="other_dataset"))
    assert len(other_dataset_ids) == 5

    # Verify total count includes both datasets
    all_ids = list(iter_entity_ids())
    assert len(all_ids) == 26

    # Test sorting by _id (ascending)
    sorted_ids = list(iter_entity_ids(dataset="test_dataset", sort="_id"))
    assert len(sorted_ids) == 21
    assert sorted_ids == sorted(sorted_ids), "IDs should be sorted ascending"

    # Test sorting by _id (descending)
    desc_sorted_ids = list(
        iter_entity_ids(dataset="test_dataset", sort={"_id": "desc"})
    )
    assert len(desc_sorted_ids) == 21
    assert desc_sorted_ids == sorted(
        desc_sorted_ids, reverse=True
    ), "IDs should be sorted descending"


def test_translation_plaintext():
    """PlainText: translatedText property is kept in properties; the ES mapping
    copy_to directive copies it into the `translation` field at index time, so
    the transform payload should NOT contain a top-level `translation` key."""
    entity = make_entity(
        {
            "id": "plain-text-translated",
            "schema": "PlainText",
            "properties": {
                "fileName": ["document.txt"],
                "translatedText": ["This is the translated text"],
            },
        }
    )
    action = format_entity("test_dataset", entity)
    assert action is not None
    source = action["_source"]
    # translatedText stays in properties for ES copy_to to handle
    assert "translatedText" in source["properties"]
    assert source["properties"]["translatedText"] == ["This is the translated text"]
    # No explicit translation field — ES copy_to handles it
    assert "translation" not in source


def test_translation_pages():
    """Pages: translations are extracted from indexText values prefixed with
    `__translation__` and placed into the `translation` field explicitly."""
    entity = make_entity(
        {
            "id": "pages-translated",
            "schema": "Pages",
            "properties": {
                "fileName": ["document.pdf"],
                "indexText": [
                    "regular text content",
                    "__translation__ Dies ist der übersetzte Text",
                    "__translation__ Ceci est le texte traduit",
                ],
            },
        }
    )
    action = format_entity("test_dataset", entity)
    assert action is not None
    source = action["_source"]
    assert "translation" in source
    assert set(source["translation"]) == {
        "Dies ist der übersetzte Text",
        "Ceci est le texte traduit",
    }
    # indexText is moved to `content`, and translations are stripped out
    assert "content" in source


def test_cap_text():
    texts = ["abc", "def"]
    assert _cap_text(texts, 100) is texts
    assert _cap_text(texts, 6) is texts
    assert _cap_text(texts, 4) == ["abc", "d"]
    assert _cap_text(texts, 3) == ["abc"]
    # never splits a multi-byte character
    assert _cap_text(["äöü"], 5) == ["äö"]


def test_format_entity_caps_index_text(monkeypatch):
    monkeypatch.setattr(transform_module.settings, "indexer_max_text_bytes", 46)
    entity = make_entity(
        {
            "id": "pages-huge",
            "schema": "Pages",
            "properties": {
                "fileName": ["document.pdf"],
                "indexText": ["x" * 20, "__translation__ hallo", "y" * 20],
            },
        }
    )
    action = format_entity("test_dataset", entity)
    assert action is not None
    source = action["_source"]
    assert source["content"] == ["x" * 20, "y" * 5]
    assert source["translation"] == ["hallo"]


def test_rewrite_mapping_safe_preserves_default_immutables():
    """Regression for the e864564 ``index: false`` bugfix.

    Older indexes were created when ``make_schema_mapping`` dropped the
    ``index: false`` extra from ``TYPE_MAPPINGS``, so ES applied its
    default ``index: true`` to text/html/json properties. ES then froze
    that default — pushing ``index: false`` later raises
    ``illegal_argument_exception``. ``rewrite_mapping_safe`` must
    therefore drop the pending override when the field exists in the
    live mapping but the immutable key is absent (= ES default in
    effect).
    """
    # Field exists; the live mapping omits `index` (ES default `true`
    # was applied at creation). The pending update wants `index: false`
    # — that must be stripped, not pushed.
    pending = {
        "properties": {
            "properties": {
                "type": "object",
                "properties": {
                    "indexText": {
                        "type": "text",
                        "index": False,
                        "copy_to": ["content"],
                    },
                },
            },
        },
    }
    existing = {
        "properties": {
            "properties": {
                "type": "object",
                "properties": {
                    "indexText": {
                        "type": "text",
                        "copy_to": ["content"],
                    },
                },
            },
        },
    }
    result = rewrite_mapping_safe(pending, existing)
    field = result["properties"]["properties"]["properties"]["indexText"]
    assert "index" not in field, field
    assert field["type"] == "text"


def test_rewrite_mapping_safe_preserves_explicit_immutables():
    """Explicit immutable values on the live mapping always win."""
    pending = {
        "properties": {
            "name": {
                "type": "keyword",
                "normalizer": "name-kw-normalizer",
            },
        },
    }
    existing = {
        "properties": {
            "name": {
                "type": "keyword",
                "normalizer": "kw-normalizer",
            },
        },
    }
    result = rewrite_mapping_safe(pending, existing)
    assert result["properties"]["name"]["normalizer"] == "kw-normalizer"


def test_rewrite_mapping_safe_passes_through_new_fields():
    """Fields absent from the live mapping keep all their immutables."""
    pending = {
        "properties": {
            "newProp": {
                "type": "text",
                "index": False,
                "copy_to": ["content"],
            },
        },
    }
    existing = {"properties": {}}
    result = rewrite_mapping_safe(pending, existing)
    new = result["properties"]["newProp"]
    assert new["index"] is False
    assert new["type"] == "text"


def test_indexer_namespace(monkeypatch):
    import importlib

    from openaleph_search.transform import entity as entity_module

    data = {
        "id": "jane",
        "schema": "Person",
        "properties": {"name": ["Jane Doe"], "birthDate": ["1980-01-01"]},
    }
    entity = make_entity(data)
    action = entity_module.format_entity("test", entity)
    assert action is not None
    assert action["_id"] == "jane"

    # Test with namespace enforcement enabled
    monkeypatch.setenv("OPENALEPH_SEARCH_INDEX_NAMESPACE_IDS", "true")
    # Reload the settings module first, then the entity module
    from openaleph_search import settings as settings_module

    importlib.reload(settings_module)
    importlib.reload(entity_module)

    action = entity_module.format_entity("test", entity)
    assert action is not None
    assert action["_id"] == "jane.0ab35dc935d0e27f7bafd9a98610fb635d730ef7"

    # Clean up
    monkeypatch.setenv("OPENALEPH_SEARCH_INDEX_NAMESPACE_IDS", "false")
    importlib.reload(settings_module)
    importlib.reload(entity_module)


def test_indexer_returns_stats(entities, cleanup_after):
    clear_index()
    stats = index_bulk("test_dataset", entities)
    assert stats.indexed == 21
    assert stats.failed == 0
    assert stats.took.total_seconds() >= 0


def test_index_proxy_returns_stats(cleanup_after):
    proxy = make_entity(
        {
            "id": "single-proxy",
            "schema": "Person",
            "properties": {"name": ["John Smith"]},
        }
    )
    stats = index_proxy("test_dataset", proxy, sync=True)
    assert stats.indexed == 1
    assert stats.failed == 0


def _person(ix, value="x"):
    return make_entity(
        {
            "id": f"batch-{ix}",
            "schema": "Person",
            "properties": {"name": [f"Person {ix}"], "notes": [value]},
        }
    )


def test_iter_batches_count_bound():
    # tiny entities: the byte bound is never reached, the count bound cuts
    entities = [_person(i) for i in range(25)]
    batches = list(iter_batches(entities, chunk_size=10, batch_bytes=10_000_000))
    assert [len(b) for b in batches] == [10, 10, 5]


def test_iter_batches_byte_bound():
    # large entities: the byte bound cuts well before the count bound. This is
    # the case a count-only bound gets wrong -- 1000 document entities are
    # ~30MB, far past a sensible bulk request.
    entities = [_person(i, value="x" * 5_000) for i in range(20)]
    batches = list(iter_batches(entities, chunk_size=1000, batch_bytes=10_000))
    assert len(batches) > 1
    assert all(b for b in batches)
    assert sum(len(b) for b in batches) == 20
    for batch in batches:
        assert sum(e._size for e in batch) <= 10_100  # 2 entities or less


def test_iter_batches_empty():
    assert list(iter_batches([], chunk_size=10, batch_bytes=100)) == []


def test_iter_action_batches():
    actions = [{"_id": str(i), "_index": "x", "_source": {}} for i in range(25)]
    batches = list(iter_action_batches(actions, chunk_size=10))
    assert [len(b) for b in batches] == [10, 10, 5]


def test_indexer_concurrency_backpressure(entities, cleanup_after):
    # the indexer must never hold more than `concurrency` bulk requests open,
    # which is what bounds resident memory during a large ingest
    clear_index()
    settings = Settings()
    indexer = Indexer("test_dataset", chunk_size=2, concurrency=2)
    assert indexer.concurrency == 2
    assert indexer.batch_bytes == settings.indexer_batch_bytes
    stats = indexer.index(entities)
    assert stats.indexed == 21
    assert stats.failed == 0


def test_indexer_requires_dataset_for_entities():
    indexer = Indexer()
    with pytest.raises(ValueError):
        indexer.index([])


META = ApiResponseMeta(
    status=200,
    http_version="1.1",
    headers=HttpHeaders(),
    duration=0.0,
    node=NodeConfig("http", "localhost", 9200),
)


def _api_error(status, error_type):
    meta = ApiResponseMeta(
        status=status,
        http_version=META.http_version,
        headers=META.headers,
        duration=META.duration,
        node=META.node,
    )
    body = {"error": {"type": error_type}, "status": status}
    return ApiError(error_type, meta=meta, body=body)


def _actions(n, op_type="index"):
    return [
        {"_op_type": op_type, "_index": "x", "_id": str(i), "_source": {"n": i}}
        for i in range(n)
    ]


def _fake_bulk(monkeypatch, respond):
    """Replace `AsyncElasticsearch.bulk`, answering each request with
    `respond(call, ids)`: an exception or one status per document. The real
    bulk helper still runs. Returns the ids sent per request."""
    requests: list[list[str]] = []

    async def bulk(self, *args, operations, **kwargs):
        ids, ops = [], []
        lines = iter(operations)
        for line in lines:
            ((op_type, header),) = orjson.loads(line).items()
            ids.append(header["_id"])
            ops.append(op_type)
            if op_type != "delete":
                next(lines)  # the document source
        requests.append(ids)
        response = respond(len(requests), ids)
        if isinstance(response, Exception):
            raise response
        items = []
        for op_type, _id, status in zip(ops, ids, response):
            item = {"_index": "x", "_id": _id, "status": status}
            if status >= 300:
                item["error"] = {"type": "es_rejected_execution_exception"}
            items.append({op_type: item})
        body = {"errors": any(s >= 300 for s in response), "items": items}
        return ObjectApiResponse(body=body, meta=META)

    monkeypatch.setattr(AsyncElasticsearch, "bulk", bulk)
    return requests


def _run_bulk(actions, max_retries=3, gate=None):
    async def run():
        es = AsyncElasticsearch("http://localhost:9200")
        try:
            return await _bulk(es, actions, False, gate or _Gate(), max_retries)
        finally:
            await es.close()

    return asyncio.run(run())


@pytest.fixture
def no_backoff(monkeypatch):
    monkeypatch.setattr(indexer_module.settings, "indexer_retry_backoff", 0)


def test_bulk_retries_rejected_documents(monkeypatch, no_backoff):
    def respond(call, ids):
        if call == 1:
            return [200, 429, 200, 503]
        return [200] * len(ids)

    requests = _fake_bulk(monkeypatch, respond)
    assert _run_bulk(_actions(4)) == (4, 0)
    assert requests == [["0", "1", "2", "3"], ["1", "3"]]


def test_bulk_retries_rejected_request(monkeypatch, no_backoff):
    def respond(call, ids):
        if call <= 2:
            return _api_error(429, "circuit_breaking_exception")
        return [200] * len(ids)

    requests = _fake_bulk(monkeypatch, respond)
    assert _run_bulk(_actions(3)) == (3, 0)
    assert len(requests) == 3
    assert all(ids == ["0", "1", "2"] for ids in requests)


def test_bulk_retries_unreachable_cluster(monkeypatch, no_backoff):
    def respond(call, ids):
        if call == 1:
            return ESConnectionError("connection refused")
        return [200] * len(ids)

    requests = _fake_bulk(monkeypatch, respond)
    assert _run_bulk(_actions(2)) == (2, 0)
    assert len(requests) == 2


def test_bulk_resends_only_unsent_chunks(monkeypatch, no_backoff):
    # a 100 byte bound splits the batch into one request per action
    monkeypatch.setattr(indexer_module.settings, "indexer_max_chunk_bytes", 100)

    def respond(call, ids):
        if call == 2:
            return _api_error(429, "es_rejected_execution_exception")
        return [200] * len(ids)

    requests = _fake_bulk(monkeypatch, respond)
    assert _run_bulk(_actions(6)) == (6, 0)
    assert len(requests) > 2
    sent = [_id for ids in requests for _id in ids]
    first, refused = requests[0], requests[1]
    assert sorted(sent) == sorted([str(i) for i in range(6)] + refused)
    assert not set(first) & set(refused)


def test_bulk_does_not_retry_document_errors(monkeypatch, no_backoff):
    # 400: a mapping error, never retried; 404 on delete: already gone
    actions = _actions(2) + _actions(1, op_type="delete")
    actions[-1]["_id"] = "gone"
    requests = _fake_bulk(monkeypatch, lambda call, ids: [200, 400, 404])
    assert _run_bulk(actions) == (1, 1)
    assert len(requests) == 1


def test_bulk_raises_on_other_request_errors(monkeypatch, no_backoff):
    def respond(call, ids):
        return _api_error(401, "security_exception")

    requests = _fake_bulk(monkeypatch, respond)
    with pytest.raises(ApiError):
        _run_bulk(_actions(2))
    assert len(requests) == 1


def test_bulk_skips_document_too_large(monkeypatch, no_backoff):
    def respond(call, ids):
        if "5" in ids:
            return _api_error(413, "request_entity_too_large")
        return [200] * len(ids)

    requests = _fake_bulk(monkeypatch, respond)
    assert _run_bulk(_actions(8)) == (7, 1)
    indexed = [_id for ids in requests if "5" not in ids for _id in ids]
    assert sorted(indexed) == ["0", "1", "2", "3", "4", "6", "7"]
    assert ["5"] in requests


def test_bulk_splits_request_too_large(monkeypatch, no_backoff):
    # the cluster's limit is below `indexer_max_chunk_bytes`
    def respond(call, ids):
        if len(ids) > 2:
            return _api_error(413, "request_entity_too_large")
        return [200] * len(ids)

    requests = _fake_bulk(monkeypatch, respond)
    assert _run_bulk(_actions(8)) == (8, 0)
    indexed = [_id for ids in requests if len(ids) <= 2 for _id in ids]
    assert sorted(indexed) == [str(i) for i in range(8)]


def test_bulk_gives_up_after_max_retries(monkeypatch, no_backoff):
    def respond(call, ids):
        return [429 if _id == "1" else 200 for _id in ids]

    requests = _fake_bulk(monkeypatch, respond)
    with pytest.raises(BulkIndexError) as exc:
        _run_bulk(_actions(2), max_retries=2)
    assert len(requests) == 3
    assert requests[1:] == [["1"], ["1"]]
    assert [e["index"]["_id"] for e in exc.value.errors] == ["1"]


def test_bulk_shuts_gate_on_retry(monkeypatch):
    monkeypatch.setattr(indexer_module.settings, "indexer_retry_backoff", 0.01)

    def respond(call, ids):
        if call == 1:
            return _api_error(429, "circuit_breaking_exception")
        return [200] * len(ids)

    _fake_bulk(monkeypatch, respond)
    gate = _Gate()
    assert _run_bulk(_actions(1), gate=gate) == (1, 0)
    assert gate.until > 0


def test_indexer_survives_rejection(entities, cleanup_after, monkeypatch, no_backoff):
    clear_index()
    original = AsyncElasticsearch.bulk
    calls = 0

    async def bulk(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise _api_error(429, "circuit_breaking_exception")
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(AsyncElasticsearch, "bulk", bulk)
    stats = index_bulk("test_dataset", entities, sync=True)
    assert stats.indexed == 21
    assert stats.failed == 0
    assert calls == 3
    assert len(list(iter_entities())) == 21


def test_index_proxy_keeps_request_retries(cleanup_after, monkeypatch, no_backoff):
    def respond(call, ids):
        return _api_error(429, "circuit_breaking_exception")

    requests = _fake_bulk(monkeypatch, respond)
    proxy = make_entity(
        {"id": "rejected", "schema": "Person", "properties": {"name": ["Jane"]}}
    )
    with pytest.raises(BulkIndexError):
        index_proxy("test_dataset", proxy)
    assert len(requests) == Settings().max_retries + 1
