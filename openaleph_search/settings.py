from anystore.settings import BaseSettings
from pydantic import AliasChoices, Field, HttpUrl
from pydantic_settings import SettingsConfigDict

__version__ = "5.0.5"

MAX_PAGE = 9999
BULK_PAGE = 1000


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="openaleph_search_", extra="ignore"
    )

    testing: bool = Field(
        default=False, validation_alias=AliasChoices("testing", "debug")
    )

    auth: bool = False
    """Set to true when using with OpenAleph"""

    auth_field: str = "dataset"
    """Default field to filter/apply auth on"""

    uri: HttpUrl | list[HttpUrl] = Field(
        default=HttpUrl("http://localhost:9200"), alias="openaleph_elasticsearch_uri"
    )

    timeout: int = 60
    max_retries: int = 3
    retry_on_timeout: bool = True

    indexer_concurrency: int = 8
    indexer_chunk_size: int = 1000
    indexer_max_chunk_bytes: int = 50 * 1024 * 1024

    index_shards: int = 10
    index_replicas: int = 0
    index_prefix: str = "openaleph"
    index_write: str = "v1"
    index_read: list[str] = ["v1"]
    index_expand_clause_limit: int = 10
    index_delete_by_query_batchsize: int = 100
    index_namespace_ids: bool = True

    # configure different weights for indices
    index_boost_intervals: int = 1
    index_boost_things: int = 1
    index_boost_documents: int = 1
    index_boost_pages: int = 1

    # enable/disable function_score wrapper for performance tuning
    query_function_score: bool = False

    # enable/disable term vectors and offsets for content field (used for highlighting)
    content_term_vectors: bool = True
