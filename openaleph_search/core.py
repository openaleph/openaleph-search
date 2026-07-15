import asyncio
import atexit
import time
from functools import cache
from weakref import WeakKeyDictionary

from anystore.logging import get_logger
from anystore.util import mask_uri
from banal import ensure_list
from elasticsearch import AsyncElasticsearch, Elasticsearch
from elasticsearch.exceptions import ConnectionError as ESConnectionError

from openaleph_search.settings import Settings

log = get_logger(__name__)

RETRY_DELAY = 5  # seconds between connection retries
MAX_RETRIES = 60  # maximum number of retries (~5 minutes with 5s delay)


@cache
def _nodes() -> list[str]:
    settings = Settings()
    return list({str(node) for node in ensure_list(settings.uri)})


@cache
def _ingest_nodes() -> list[str]:
    settings = Settings()
    uri = settings.ingest_uri if settings.ingest_uri is not None else settings.uri
    return list({str(node) for node in ensure_list(uri)})


def _connect_sync(urls: list[str], name: str) -> Elasticsearch:
    settings = Settings()
    masked_urls = [mask_uri(u) for u in urls]

    for attempt in range(MAX_RETRIES):
        try:
            es = Elasticsearch(
                hosts=urls,
                request_timeout=settings.timeout,
                max_retries=settings.max_retries,
                retry_on_timeout=settings.retry_on_timeout,
                retry_on_status=[502, 503, 504],
            )
            es.info()
            log.info(f"Connected to Elasticsearch {name}", nodes=masked_urls)
            return es
        except ESConnectionError as e:
            log.warning(
                f"Elasticsearch {name} not ready, retrying...",
                nodes=masked_urls,
                attempt=attempt + 1,
                max_retries=MAX_RETRIES,
                error=str(e),
            )
            time.sleep(RETRY_DELAY)

    raise ESConnectionError(
        f"Could not connect to Elasticsearch {name} after {MAX_RETRIES} attempts"
    )


async def _connect_async(urls: list[str], name: str) -> AsyncElasticsearch:
    settings = Settings()
    masked_urls = [mask_uri(u) for u in urls]

    for attempt in range(MAX_RETRIES):
        es = None
        try:
            es = AsyncElasticsearch(
                hosts=urls,
                request_timeout=settings.timeout,
                max_retries=settings.max_retries,
                retry_on_timeout=settings.retry_on_timeout,
                retry_on_status=[502, 503, 504],
                connections_per_node=settings.connection_pool_limit_per_host,
            )
            await es.info()
            log.info(
                f"Connected to AsyncElasticsearch {name}",
                nodes=masked_urls,
                connections_per_node=settings.connection_pool_limit_per_host,
            )
            return es
        except ESConnectionError as e:
            if es is not None:
                await es.close()
            log.warning(
                f"Elasticsearch {name} not ready, retrying...",
                nodes=masked_urls,
                attempt=attempt + 1,
                max_retries=MAX_RETRIES,
                error=str(e),
            )
            await asyncio.sleep(RETRY_DELAY)

    raise ESConnectionError(
        f"Could not connect to Elasticsearch {name} after {MAX_RETRIES} attempts"
    )


# Async clients cached per event loop: an AsyncElasticsearch is bound to the
# loop it was created on, so `@cache` can't be used, but repeated calls on the
# same loop should not pay a fresh client + `es.info()` handshake each time.
_async_clients: WeakKeyDictionary = WeakKeyDictionary()


async def _connect_async_cached(urls: list[str], name: str) -> AsyncElasticsearch:
    loop = asyncio.get_running_loop()
    cache_ = _async_clients.setdefault(loop, {"lock": asyncio.Lock(), "clients": {}})
    if name not in cache_["clients"]:
        async with cache_["lock"]:
            if name not in cache_["clients"]:
                cache_["clients"][name] = await _connect_async(urls, name)
    return cache_["clients"][name]


@atexit.register
def _close_async_clients() -> None:
    # Best effort: close cached clients on their (idle) loops to avoid
    # "Unclosed client session" noise at interpreter shutdown.
    for loop, cache_ in list(_async_clients.items()):
        if loop.is_closed() or loop.is_running():
            continue
        for es in cache_["clients"].values():
            try:
                loop.run_until_complete(es.close())
            except Exception:
                pass


@cache
def get_es() -> Elasticsearch:
    return _connect_sync(_nodes(), "")


async def get_async_es() -> AsyncElasticsearch:
    """Get the async client for the running event loop. Cached per loop —
    callers must not close it."""
    return await _connect_async_cached(_nodes(), "")


@cache
def get_ingest_es() -> Elasticsearch:
    return _connect_sync(_ingest_nodes(), "ingest")


async def get_async_ingest_es() -> AsyncElasticsearch:
    """Get the async ingest client for the running event loop. Cached per
    loop — callers must not close it."""
    return await _connect_async_cached(_ingest_nodes(), "ingest")
