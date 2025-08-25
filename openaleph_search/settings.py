from anystore.settings import BaseSettings
from pydantic import AliasChoices, Field, HttpUrl
from pydantic_settings import SettingsConfigDict

__version__ = "0.0.0"

MAX_PAGE = 9999


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="openaleph_", extra="ignore"
    )

    testing: bool = Field(
        default=False, validation_alias=AliasChoices("testing", "debug")
    )

    search_auth: bool = False
    """Set to true when using with OpenAleph"""

    search_auth_field: str = "dataset"
    """Default field to filter/apply auth on"""

    elasticsearch_url: HttpUrl | list[HttpUrl] = HttpUrl("http://localhost:9200")
    elasticsearch_timeout: int = 60
    elasticsearch_max_retries: int = 3
    elasticsearch_retry_on_timeout: bool = True

    indexer_concurrency: int = 8
    indexer_chunk_size: int = 1000

    index_shards: int = 25  # 4 indices with dataset routing
    index_replicas: int = 0
    index_prefix: str = "openaleph"
    index_write: str = "v1"
    index_read: list[str] = ["v1"]
    index_expand_clause_limit: int = 10
    index_delete_by_query_batchsize: int = 100
    index_namespace_ids: bool = True
