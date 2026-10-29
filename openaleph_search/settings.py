from typing import Any

from anystore.settings import BaseSettings
from pydantic import AliasChoices, Field, HttpUrl, field_validator
from pydantic_settings import SettingsConfigDict

__version__ = "5.3.3"

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

    ingest_uri: HttpUrl | list[HttpUrl] | None = Field(
        default=None, alias="openaleph_elasticsearch_ingest_uri"
    )
    """URI(s) for indexing, falls back to `uri`."""

    timeout: int = 60
    max_retries: int = 3
    retry_on_timeout: bool = True

    connection_pool_limit_per_host: int = 25
    """Connection pool limit of the async client."""

    indexer_concurrency: int = 8
    """Upper bound on bulk requests the indexer keeps outstanding at once."""

    indexer_adaptive_concurrency: bool = True
    """Adapt the outstanding bulk requests between 1 and `indexer_concurrency`."""

    indexer_target_latency: float = 5
    """Seconds a bulk request may take before adaptive concurrency eases off."""

    indexer_chunk_size: int = 1000
    """Upper bound on entities per batch (one batch = one bulk request)."""

    indexer_batch_bytes: int = 5 * 1024 * 1024  # 5mb
    """Upper bound on payload bytes per batch."""

    indexer_max_chunk_bytes: int = 5 * 1024 * 1024  # 5mb

    indexer_max_retries: int = 60
    """Retries for a rejected bulk batch (429, 502-504, connection errors)."""

    indexer_retry_backoff: float = 2
    """Seconds before the first retry, doubling on each further one."""

    indexer_retry_max_backoff: float = 300
    """Upper bound in seconds for a single retry wait."""

    indexer_max_text_bytes: int = 100 * 1024 * 1024  # 100mb
    """Upper bound in UTF-8 bytes for an entity's `indexText`."""

    indexer_max_names: int = 65536
    """Upper bound on the names of an entity: all own names, and a random sample
    of the mentioned ones."""

    index_shards: int = 10
    index_replicas: int = 0
    index_prefix: str = "openaleph"
    index_write: str = "v1"
    index_read: str | list[str] = ["v1"]
    index_expand_clause_limit: int = 10
    index_delete_by_query_batchsize: int = 100
    index_namespace_ids: bool = True
    index_refresh_interval: str = "1s"

    index_boost_intervals: int = 1
    """Search boost of the intervals bucket."""

    index_boost_things: int = 1
    """Search boost of the things bucket."""

    index_boost_documents: int = 1
    """Search boost of the documents bucket."""

    index_boost_pages: int = 1
    """Search boost of the pages buckets."""

    significant_terms_sampler_size: int = 2000
    """Sampler `shard_size` for significant terms, without `random_sampler`."""

    significant_text_sampler_size: int = 200
    """Sampler `shard_size` for significant text."""

    significant_terms_min_doc_count: int = 5
    """Minimum foreground frequency of a significant term across shards."""

    significant_terms_shard_min_doc_count: int = 2
    """Minimum foreground frequency of a significant term on a shard."""

    significant_terms_random_sampler: bool = True
    """Sample significant terms with `random_sampler` instead of `sampler`."""

    significant_terms_sampler_probability: float = 0.1
    """Sampling probability of `random_sampler`."""

    query_function_score: bool = False
    """Wrap queries in a `function_score` that de-penalizes entities with many
    names."""

    highlighter_fragment_size: int = 200
    """Characters per highlight snippet."""

    highlighter_number_of_fragments: int = 3
    """Snippets per document."""

    highlighter_no_match_size: int = 300
    """Snippet size when nothing matched."""

    highlighter_text_field: bool = True
    """Highlight the `text` field."""

    highlighter_translation_field: bool = True
    """Highlight the `translation` field."""

    highlighter_max_analyzed_offset: int = 100000
    """Characters analyzed for highlighting."""

    mlt_min_doc_freq: int = 1
    """Minimum document frequency of More Like This terms."""

    mlt_min_term_freq: int = 1
    """Minimum frequency of a More Like This term in the source document."""

    mlt_max_query_terms: int = 200
    """Maximum More Like This query terms."""

    mlt_minimum_should_match: str = "10%"
    """Share of More Like This terms that must match."""

    mlt_min_word_length: int = 5
    """Minimum length of More Like This terms."""

    mlt_max_doc_freq: int = 500
    """Maximum document frequency of More Like This terms."""

    match_name_parts: bool = True
    """Match entities on name parts (`names` and `name_keys` always match)."""

    match_phonetic: bool = False
    """Match entities on phonetic names."""

    match_symbols: bool = False
    """Match entities on name symbols."""

    percolation: bool = False
    """Store percolator queries on things-bucket entities."""

    matching_single_token_min_length: int = 10
    """Minimum length of a single-token name in `clean_matching_names`."""

    matching_multi_token_min_length: int = 3
    """Minimum length of one token of a multi-token name in
    `clean_matching_names`."""

    eager_global_ordinals: bool = True
    """Build global ordinals of aggregated keyword fields at refresh."""

    allow_leading_wildcard: bool = False
    """Allow a leading wildcard in search text."""

    @field_validator("index_read", mode="before")
    @classmethod
    def split_index_read(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            return [v.strip() for v in value.split(",") if v.strip()]
        return value
