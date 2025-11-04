# openaleph-search

[Elasticsearch](https://www.elastic.co/)-based search module for [FollowTheMoney](https://followthemoney.tech) entity search and matching.

!!! info Usage
    This documentation explains the technical background and configuration parameters for the openaleph-search package. If you are not a technical user / administrator and instead want to learn how to search for documents and structured data in **OpenAleph**, head over to the [end-user search documentation](https://openaleph.org/docs/user-guide/101/basic-search/) over there.

This is the core search module used to search across documents and structured data in [OpenAleph](https://openaleph.org). But it can be used standalone as well.

Originally this codebase was part of the OpenAleph application, but outsourcing it makes it easier to develop and debug. As well data can be indexed without the application roundtrip, and the command line interface provides a short hand for debugging search queries and their behaviour.

!!! info "[AWS] OpenSearch"
    This library is developed and tested against Elasticsearch, but is not using super-specific _Elasticsearch_ features, so OpenSearch could probably work, too, but is not tested.

## What is this

This package provides search functionality for entity data stored in Elasticsearch. It handles full-text search, entity matching/deduplication, and terms facets aggregation. The data model follows the [Follow the Money (FtM)](https://followthemoney.tech) specification for entities and relationships.

## Installation

```bash
pip install openaleph-search
```

## Basic usage

Configure Elasticsearch connection via environment variables:

```bash
export OPENALEPH_SEARCH_URI=http://localhost:9200
export OPENALEPH_SEARCH_INDEX_PREFIX=openaleph
```

Search entities via CLI:

```bash
# Simple text search
openaleph-search search query-string "john smith"

# Search with filters
openaleph-search search query-string "company" --args "filter:schema=Company&filter:countries=us"

# Enable highlighting
openaleph-search search query-string "investigation" --args "highlight=true"
```

## Key features

- Full-text search across entity names, properties, and content
- [Entity matching and deduplication using names, identifiers, and properties](./matching.md)
- [Facets and aggregations](./aggregations.md)
- [Search result highlighting](./highlighting.md)
- Multi-language support via Unicode normalization and [rigour symbols](https://rigour.followthemoney.tech/names/)
- [Command-line interface](./reference/cli.md) for testing and debugging queries

## Get started

- [Configuration](reference/settings.md) - Environment variables and settings
- [Command Line](reference/cli.md) - CLI usage for testing queries
