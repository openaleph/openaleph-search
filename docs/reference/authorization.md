# Authorization

The (optional) authorization logic allows dataset-level access control and restricts search requests scope to specific datasets that are allowed for this request.

!!! warning "Know what you're doing?"
    Dataset-level access and authorization is a sensitive matter and the configured default behaviour in **OpenAleph** shipped docker containers ensures correct usage. This documentation section here describes the background and how it can be used in other applications or disabled, but be careful with messing around these settings in production **OpenAleph** deployments.

## Enable authorization

Per default, no access control is enforced when using openaleph-search standalone. (In **OpenAleph** builds, it is, see above).

Enable it via `OPENALEPH_SEARCH_AUTH=1`.

This enforces that each search request (technically, when initializing the query parser class for a search) needs a `SearchAuth` object that contains the allowed datasets the search request has access to.

```python
from openaleph_search.model import SearchAuth

# create an auth obj that can access 2 datasets
auth = SearchAuth(datasets={"dataset1", "dataset2"})

# create an admin auth obj that can see all datasets
auth = SearchAuth(is_admin=True)
```

Internally, the search parser class uses `auth.datasets_query()` to add the allowed datasets as a bool filter to the constructed query.

## Current OpenAleph implementation

Currently, OpenAleph leaks some logic into this approach, as it is using a `collection_id` field instead of `dataset` for access control. (This will change for the upcoming major release 6).

Therefore, the correct configuration must be (as set in the docker builds):

```bash
OPENALEPH_SEARCH_AUTH=1
OPENALEPH_SEARCH_AUTH_FIELD=collection_id
```

And the auth obj is constructed like this:

```python
auth = SearchAuth(collection_ids={1, 2, 3})
```
