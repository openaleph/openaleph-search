from anystore.decorators import error_handler
from anystore.functools import weakref_cache as cache
from anystore.logging import get_logger
from anystore.util import mask_uri
from banal import ensure_list
from elasticsearch import AsyncElasticsearch, Elasticsearch

from openaleph_search.settings import Settings

log = get_logger(__name__)


@cache
def _nodes() -> list[str]:
    nodes: set[str] = set()
    settings = Settings()
    for node in ensure_list(settings.uri):
        nodes.add(str(node))
    return list(nodes)


@error_handler(logger=log)
def _get_client() -> Elasticsearch:
    settings = Settings()
    urls = _nodes()
    es = Elasticsearch(
        hosts=urls,
        request_timeout=settings.timeout,
        max_retries=settings.max_retries,
        retry_on_timeout=settings.retry_on_timeout,
        retry_on_status=[502, 503, 504],
    )
    es.info()
    urls = [mask_uri(u) for u in urls]
    log.info("Connected to Elasticsearch", nodes=urls)
    return es


@error_handler(logger=log)
async def _get_async_client() -> AsyncElasticsearch:
    settings = Settings()
    urls = _nodes()
    es = AsyncElasticsearch(
        hosts=urls,
        request_timeout=settings.timeout,
        max_retries=settings.max_retries,
        retry_on_timeout=settings.retry_on_timeout,
        retry_on_status=[502, 503, 504],
    )
    await es.info()
    log.info("Connected to AsyncElasticsearch", nodes=urls)
    return es


@cache
def get_es() -> Elasticsearch:
    return _get_client()


async def get_async_es() -> AsyncElasticsearch:
    return await _get_async_client()
