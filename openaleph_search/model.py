from typing import Any

from pydantic import BaseModel, field_validator

from openaleph_search.query.util import auth_datasets_query
from openaleph_search.settings import Settings

settings = Settings()


class SearchAuth(BaseModel):
    """Control auth for dataset filter"""

    datasets: set[str] = set()
    logged_in: bool = False
    is_admin: bool = False
    role: str | None = None

    # leaked OpenAleph logic
    collection_ids: set[int] = set()

    def datasets_query(self, field: str | None = settings.auth_field) -> dict[str, Any]:
        field = field or settings.auth_field
        if "collection" in field:
            return auth_datasets_query(
                list(map(str, self.collection_ids)), field, self.is_admin
            )
        return auth_datasets_query(list(self.datasets), field, self.is_admin)


class PercolatorDoc(BaseModel):
    """A stored percolator document mapping entity names to a key.

    Indexed into the percolator index by `bulk_index_queries`. The `query`
    field on the actual ES doc is built from `names`; this dataclass holds
    the metadata that travels with it.
    """

    key: str
    names: list[str]
    countries: list[str] = []
    schemata: list[str] = []

    @field_validator("names", mode="after")
    @classmethod
    def _clean_names(cls, names: list[str]) -> list[str]:
        """Drop names that are too noisy to percolate.

        - Multi-token names are kept (specific enough for phrase matching).
        - Single-token names are kept only if at least 7 characters long;
          shorter single tokens (e.g. "Doe", "Acme") produce too many false
          positives when percolated against arbitrary text.
        - Empty / whitespace-only entries are dropped.
        """
        cleaned: list[str] = []
        for name in names:
            stripped = (name or "").strip()
            if not stripped:
                continue
            tokens = stripped.split()
            if len(tokens) > 1:
                cleaned.append(stripped)
            elif len(tokens[0]) >= 7:
                cleaned.append(stripped)
        return cleaned
