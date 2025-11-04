from typing import Any

from pydantic import BaseModel

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
