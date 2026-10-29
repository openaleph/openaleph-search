# Indexing API

[`index_bulk`][openaleph_search.index.entities.index_bulk] transforms entities with [`format_entity`][openaleph_search.transform.entity.format_entity] and bulk-indexes them with an [`Indexer`][openaleph_search.index.indexer.Indexer]. The indexer is tuned by the [indexing settings](../settings.md#indexing).

```python
from followthemoney import model
from openaleph_search.index.entities import index_bulk

entity = model.make_entity("Person")
entity.id = "jane-doe"
entity.add("name", "Jane Doe")
stats = index_bulk("my_dataset", [entity], sync=True)
```

With `index_namespace_ids` (the default) the indexed ID is signed with the dataset, so look entities up by the IDs a search returns.

## Write

::: openaleph_search.index.entities.index_bulk

::: openaleph_search.index.entities.index_proxy

::: openaleph_search.index.entities.delete_entity

::: openaleph_search.index.indexer.Indexer
    options:
      members:
        - index
        - index_actions

::: openaleph_search.index.indexer.IndexStats
    options:
      members: false

## Read

::: openaleph_search.index.entities.get_entity

::: openaleph_search.index.entities.entities_by_ids

::: openaleph_search.index.entities.iter_entities

::: openaleph_search.index.entities.get_entity_content

## Transform

::: openaleph_search.transform.entity.format_entity

::: openaleph_search.transform.entity.format_entities

::: openaleph_search.transform.entity.iter_batches
