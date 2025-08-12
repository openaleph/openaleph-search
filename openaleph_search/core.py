from functools import cache

from anystore.decorators import error_handler
from anystore.logging import get_logger
from banal import ensure_list
from elasticsearch import Elasticsearch

from openaleph_search.settings import Settings

log = get_logger(__name__)


def _nodes() -> list[str]:
    nodes: set[str] = set()
    settings = Settings()
    for node in ensure_list(settings.elasticsearch_url):
        nodes.add(str(node))
    return list(nodes)


@error_handler(logger=log)
def _get_client() -> Elasticsearch:
    settings = Settings()
    urls = _nodes()
    es = Elasticsearch(
        hosts=urls,
        request_timeout=settings.elasticsearch_timeout,
        max_retries=settings.elasticsearch_max_retries,
        retry_on_timeout=settings.elasticsearch_retry_on_timeout,
        retry_on_status=[502, 503, 504],
    )
    es.info()
    log.info("Connected to Elasticsearch", nodes=urls)
    return es


@cache
def get_es() -> Elasticsearch:
    return _get_client()
