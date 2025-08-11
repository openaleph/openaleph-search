from pydantic import AliasChoices, Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="openaleph_", extra="ignore"
    )

    testing: bool = Field(
        default=False, validation_alias=AliasChoices("testing", "debug")
    )

    elasticsearch_url: HttpUrl | list[HttpUrl] = HttpUrl("http://localhost:9200")
    elasticsearch_timeout: int = 60
    elasticsearch_max_retries: int = 3
    elasticsearch_retry_on_timeout: bool = True

    index_shards: int = 5
    index_replicas: int = 0
    index_prefix: str = "openaleph"
    index_write: str = "v1"
    index_read: list[str] = ["v1"]
    index_expand_clause_limit: int = 10
    index_delete_by_query_batchsize: int = 100
    index_namespace_ids: bool = True

    xref_scroll: str = "5m"
    xref_scroll_size: int = 1000
