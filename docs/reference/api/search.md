# Search API

A query class builds an Elasticsearch request from a [`SearchQueryParser`][openaleph_search.parse.parser.SearchQueryParser] and runs it against the read indexes. The parameters are described in [Query parameters](../parser.md).

```python
from openaleph_search import EntitiesQuery, SearchQueryParser, unpack_result

parser = SearchQueryParser([("q", "jane doe"), ("filter:schema", "Person")])
result = EntitiesQuery(parser).search()
entities = [unpack_result(hit) for hit in result["hits"]["hits"]]
```

## Parameters

::: openaleph_search.parse.parser.SearchQueryParser
    options:
      members: false

::: openaleph_search.model.SearchAuth
    options:
      members: false

## Queries

::: openaleph_search.query.base.Query
    options:
      members:
        - search

::: openaleph_search.query.queries.EntitiesQuery
    options:
      members: false

::: openaleph_search.query.queries.MatchQuery
    options:
      members: false

::: openaleph_search.query.queries.MoreLikeThisQuery
    options:
      members: false

::: openaleph_search.query.queries.GeoDistanceQuery
    options:
      members: false

::: openaleph_search.query.queries.PercolatorQuery
    options:
      members: false

::: openaleph_search.query.mentions.MentionsQuery
    options:
      members: false

::: openaleph_search.query.mentions.MultiMentionsQuery
    options:
      members: false

## Results

::: openaleph_search.index.util.unpack_result
