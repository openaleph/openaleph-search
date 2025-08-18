from typing import Any

from pydantic import BaseModel

from openaleph_search.query.util import auth_datasets_query


class SearchAuth(BaseModel):
    """Control auth for dataset filter"""

    datasets: set[str] = set()
    logged_in: bool = False
    is_admin: bool = False

    def datasets_query(self, field: str = "dataset") -> dict[str, Any]:
        return auth_datasets_query(list(self.datasets), field, self.is_admin)
