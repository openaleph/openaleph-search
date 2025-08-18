# ported from aleph/tests/test_xref.py
# this tests the xref index but not the actual xref execution

import time
from datetime import datetime
from random import randint
from typing import Any
from uuid import uuid4

from followthemoney import EntityProxy
from ftmq.util import make_entity

from openaleph_search.index.admin import clear_index
from openaleph_search.index.entities import index_bulk
from openaleph_search.index.util import bulk_actions
from openaleph_search.index.xref import delete_xref, iter_matches, xref_index
from openaleph_search.model import SearchAuth


def _make_entity(schema: str, name: str, **data) -> EntityProxy:
    return make_entity(
        {
            "id": str(uuid4()),
            "schema": schema,
            "properties": {"name": [name], **{k: [v] for k, v in data.items()}},
        }
    )


ent1 = _make_entity("Person", "Carlos Danger", nationality="us")
ent2 = _make_entity("Person", "Carlos Danger", nationality="us")
ent3 = _make_entity("LegalEntity", "Carlos Danger", country="gb")
ent4 = _make_entity("Person", "Pure Risk", nationality="us")
ent5 = _make_entity("LegalEntity", "Carlos Danger", country="gb")


def _index_entities():
    index_bulk("dataset1", [ent1])
    index_bulk("dataset2", [ent2, ent3, ent4])
    index_bulk("dataset3", [ent5])


def _make_match(
    e1: EntityProxy, e2: EntityProxy, d1: str, d2: str, score: float
) -> dict[str, Any]:
    return {
        "_id": str(uuid4()),
        "_index": xref_index(),
        "_source": {
            "score": score,
            "doubt": 1 - score,
            "method": "test",
            "random": randint(1, 2**31),
            "entity_id": e1.id,
            "schema": e1.schema.name,
            "dataset": d1,
            "entityset_ids": [],
            "match_id": e2.id,
            "match_dataset": d2,
            "countries": [],
            "text": [],
            "created_at": datetime.now().isoformat(),
        },
    }


def test_xref(monkeypatch):
    monkeypatch.setenv("OPENALEPH_SEARCH_AUTH", "true")
    _index_entities()
    auth1 = SearchAuth(logged_in=True, datasets={"dataset1", "dataset2"})
    auth2 = SearchAuth(logged_in=True, datasets={"dataset1", "dataset2", "dataset3"})

    # nothing yet
    results = list(iter_matches("dataset1", auth1))
    assert len(results) == 0

    # add matches to index
    bulk_actions(
        [
            _make_match(ent1, ent2, "dataset1", "dataset2", 0.9),
            _make_match(ent1, ent5, "dataset1", "dataset3", 0.8),
        ]
    )
    # auth1 can see 1 match
    results = list(iter_matches("dataset1", auth1))
    assert len(results) == 1
    # auth2 can see 2 matches
    results = list(iter_matches("dataset1", auth2))
    assert len(results) == 2
    # no auth can't see anything
    results = list(iter_matches("dataset1", SearchAuth()))
    assert len(results) == 0

    # purge
    delete_xref("dataset1")
    # FIXME async refresh?
    time.sleep(2)
    results = list(iter_matches("dataset1", auth1))
    assert len(results) == 0
    results = list(iter_matches("dataset1", auth2))
    assert len(results) == 0

    clear_index()
