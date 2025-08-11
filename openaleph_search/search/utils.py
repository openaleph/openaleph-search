import logging

from openaleph_search.index.indexes import TYPE_MAPPINGS
from openaleph_search.index.util import KEYWORD, NUMERIC, NUMERIC_TYPES

log = logging.getLogger(__name__)


def get_index_field_type(type_):
    """Given a FtM property type, return the corresponding ElasticSearch field type"""
    es_type = TYPE_MAPPINGS.get(type_, KEYWORD)
    if type_ in NUMERIC_TYPES:
        es_type = NUMERIC
    if es_type:
        return es_type.get("type")
