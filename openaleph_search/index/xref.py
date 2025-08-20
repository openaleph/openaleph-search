import logging
from datetime import datetime
from random import randint

from banal import hash_data
from elasticsearch.helpers import scan
from followthemoney.types import registry

from openaleph_search.core import get_es
from openaleph_search.index.indexer import bulk_actions, configure_index, query_delete
from openaleph_search.index.mapping import FieldType
from openaleph_search.index.util import (
    index_name,
    index_settings,
    unpack_result,
)
from openaleph_search.model import SearchAuth

log = logging.getLogger(__name__)
XREF_SOURCE = {"excludes": ["text", "countries", "entityset_ids"]}
MAX_NAMES = 30


def xref_index():
    return index_name("xref", "v1")


def configure_xref():
    mapping = {
        "date_detection": False,
        "dynamic": False,
        "properties": {
            "score": {"type": "float"},
            "doubt": {"type": "float"},
            "method": FieldType.KEYWORD,
            # TODO: remove "random" field once "doubt" field has fermented
            # in production
            "random": {"type": "integer"},
            "entity_id": FieldType.KEYWORD,
            "dataset": FieldType.KEYWORD,
            "entityset_ids": FieldType.KEYWORD,
            "match_id": FieldType.KEYWORD,
            "match_dataset": FieldType.KEYWORD,
            registry.country.group: FieldType.KEYWORD,
            "schema": FieldType.KEYWORD,
            "text": FieldType.TEXT,
            "created_at": {"type": "date"},
        },
    }
    settings = index_settings()
    return configure_index(xref_index(), mapping, settings)


def _index_form(dataset: str, matches):
    now = datetime.utcnow().isoformat()
    for match in matches:
        xref_id = hash_data((match.entity.id, dataset, match.match.id))
        text = set([match.entity.caption, match.match.caption])
        text.update(match.entity.get_type_values(registry.name)[:MAX_NAMES])
        text.update(match.match.get_type_values(registry.name)[:MAX_NAMES])
        countries = set(match.entity.get_type_values(registry.country))
        countries.update(match.match.get_type_values(registry.country))
        yield {
            "_id": xref_id,
            "_index": xref_index(),
            "_source": {
                "score": match.score,
                "doubt": match.doubt,
                "method": match.method,
                "random": randint(1, 2**31),
                "entity_id": match.entity.id,
                "schema": match.match.schema.name,
                "dataset": dataset,
                "entityset_ids": list(match.entityset_ids),
                "match_id": match.match.id,
                "match_dataset": match.dataset,
                "countries": list(countries),
                "text": list(text),
                "created_at": now,
            },
        }


def index_matches(dataset: str, matches, sync=False):
    """Index cross-referencing matches."""
    bulk_actions(_index_form(dataset, matches), sync=sync)


def iter_matches(dataset: str, auth: SearchAuth):
    """Scan all matching xref results, does not support sorting."""
    filters = [{"term": {"dataset": dataset}}, auth.datasets_query("match_dataset")]
    query = {"query": {"bool": {"filter": filters}}, "_source": XREF_SOURCE}
    es = get_es()
    for res in scan(es, index=xref_index(), query=query):
        yield unpack_result(res)


def delete_xref(dataset: str, entity_id=None, sync=False):
    """Delete xref matches of an entity or a dataset."""
    shoulds = [
        {"term": {"dataset": dataset}},
        {"term": {"match_dataset": dataset}},
    ]
    if entity_id is not None:
        shoulds = [
            {"term": {"entity_id": entity_id}},
            {"term": {"match_id": entity_id}},
        ]
    query = {"bool": {"should": shoulds, "minimum_should_match": 1}}
    query_delete(xref_index(), query, sync=sync)
