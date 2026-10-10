import copy

import orjson
import pytest
from conftest import FIXTURES_PATH, TEST_PRIVATE, TEST_PUBLIC
from followthemoney.namespace import Namespace
from ftmq.aggregate import EntityPayload, aggregate_fragments_unsafe
from ftmq.io import smart_read_proxies
from ftmq.util import make_entity
from typer.testing import CliRunner

from openaleph_search.cli import cli
from openaleph_search.index.admin import clear_index
from openaleph_search.index.entities import index_bulk, iter_entities
from openaleph_search.transform import entity as transform_module
from openaleph_search.transform.entity import entity_size, format_entity, iter_batches

OWNERSHIP = {
    "id": "own-1",
    "schema": "Ownership",
    "properties": {"owner": ["jane"], "asset": ["acme"], "percentage": ["50"]},
}
PERSON_FRAGMENT = {
    "id": "merged",
    "schema": "Person",
    "properties": {"name": ["Jane Doe"], "birthDate": ["1980-01-01"]},
}
COMPANY_FRAGMENT = {
    "id": "merged",
    "schema": "Company",
    "properties": {"name": ["Jane Doe Ltd"], "jurisdiction": ["de"]},
}


def _normalize(action):
    action = copy.deepcopy(action)
    action["_source"].pop("indexed_at")

    def norm(value):
        if isinstance(value, dict):
            return {k: norm(v) for k, v in value.items()}
        if isinstance(value, list):
            return sorted((norm(v) for v in value), key=orjson.dumps)
        return value

    return norm(action)


def _fixture_proxies():
    yield from smart_read_proxies(FIXTURES_PATH / "samples.ijson")
    yield from smart_read_proxies(FIXTURES_PATH / "pages.jsonl")
    yield from map(make_entity, TEST_PRIVATE + TEST_PUBLIC + [OWNERSHIP])


@pytest.mark.parametrize("namespace", [False, True])
def test_format_entity_data_equals_proxy(monkeypatch, namespace):
    monkeypatch.setattr(transform_module.settings, "index_namespace_ids", namespace)
    for proxy in _fixture_proxies():
        expected = _normalize(format_entity("test", proxy))
        data = proxy.to_dict()
        assert _normalize(format_entity("test", data)) == expected
        payload = EntityPayload.from_dict(data)
        assert _normalize(format_entity("test", payload)) == expected


def test_format_entity_data_is_not_modified(monkeypatch):
    monkeypatch.setattr(transform_module.settings, "index_namespace_ids", True)
    data = {
        "id": "pages",
        "schema": "Pages",
        "properties": {
            "fileName": ["document.pdf"],
            "indexText": ["text", "__translation__ hallo"],
            "parent": ["folder"],
        },
        "role_id": [36],
    }
    for entity in (data, OWNERSHIP):
        before = copy.deepcopy(entity)
        assert format_entity("test", entity) is not None
        assert entity == before


def test_format_entity_data_namespace(monkeypatch):
    monkeypatch.setattr(transform_module.settings, "index_namespace_ids", True)
    signed = Namespace("test").apply(make_entity(OWNERSHIP))
    action = format_entity("test", OWNERSHIP)
    assert action is not None
    assert action["_id"] == signed.id
    assert action["_source"]["properties"]["owner"] == signed.get("owner")
    assert action["_source"]["properties"]["asset"] == signed.get("asset")


def test_format_entity_unsafe_aggregate():
    # Person + Company merge to LegalEntity, keeping the Person's `birthDate`
    (data,) = aggregate_fragments_unsafe([PERSON_FRAGMENT, COMPANY_FRAGMENT])
    assert data["schema"] == "LegalEntity"
    assert "birthDate" in data["properties"]
    action = format_entity("test", data)
    assert action is not None
    source = action["_source"]
    assert source["schema"] == "LegalEntity"
    assert "birthDate" not in source["properties"]
    assert source["properties"]["jurisdiction"] == ["de"]
    assert source["caption"] in ("Jane Doe", "Jane Doe Ltd")
    assert "birthDate" not in source.get("numeric", {})


def test_format_entity_data_caption():
    data = {**TEST_PRIVATE[0], "caption": "Given caption"}
    action = format_entity("test", data)
    assert action is not None
    assert action["_source"]["caption"] == "Given caption"
    action = format_entity("test", TEST_PRIVATE[0])
    assert action is not None
    assert action["_source"]["caption"] == "Banana"


def test_format_entity_data_folds_collection_id():
    # the unsafe fragment merge list-ifies context, even for a single fragment
    (data,) = aggregate_fragments_unsafe([{**PERSON_FRAGMENT, "collection_id": 7}])
    assert data["collection_id"] == [7]
    action = format_entity("test", data)
    assert action is not None
    assert action["_source"]["collection_id"] == 7
    action = format_entity("test", data, collection_id=17)
    assert action is not None
    assert action["_source"]["collection_id"] == 17


def test_format_entity_data_invalid():
    with pytest.raises(ValueError):
        format_entity("test", {"schema": "Person", "properties": {}})
    with pytest.raises(ValueError):
        format_entity("test", {"id": "x", "schema": "Banana", "properties": {}})


def test_entity_size():
    for proxy in _fixture_proxies():
        data = proxy.to_dict()
        assert entity_size(data) == proxy._size
        assert entity_size(EntityPayload.from_dict(data)) == proxy._size


def test_iter_batches_byte_bound_data():
    entities = [
        {"id": f"batch-{i}", "schema": "Person", "properties": {"notes": ["x" * 5_000]}}
        for i in range(20)
    ]
    batches = list(iter_batches(entities, chunk_size=1000, batch_bytes=10_000))
    assert [len(b) for b in batches] == [2] * 10


def test_index_bulk_unsafe(cleanup_after):
    clear_index()
    fragments = [
        PERSON_FRAGMENT,
        {**PERSON_FRAGMENT, "properties": {"nationality": ["de"]}},
        OWNERSHIP,
    ]
    stats = index_bulk("test_unsafe", aggregate_fragments_unsafe(fragments), sync=True)
    assert stats.indexed == 2
    assert stats.failed == 0
    entities = {e["id"]: e for e in iter_entities()}
    assert entities["merged"]["properties"]["nationality"] == ["de"]
    assert entities["own-1"]["schema"] == "Ownership"


def test_cli_format_entities_unsafe(tmp_path):
    source = tmp_path / "entities.json"
    source.write_bytes(b"\n".join(orjson.dumps(e) for e in TEST_PRIVATE))
    target = tmp_path / "actions.json"
    args = ["format-entities", "-d", "test", "-i", str(source), "-o", str(target)]
    result = CliRunner().invoke(cli, [*args, "--unsafe"])
    assert result.exit_code == 0, result.output
    actions = [orjson.loads(line) for line in target.read_bytes().splitlines()]
    assert [a["_source"]["caption"] for a in actions] == ["Banana"] * 2 + [
        "Banana ba Nana"
    ]
