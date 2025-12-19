#!/usr/bin/env python3
"""
Cleanup script for cross-bucket duplicate entities.

This script finds and removes duplicate entities that exist in multiple
Elasticsearch index buckets (e.g., same entity ID in both 'documents' and 'pages').

This version works with existing indexes that don't have the 'id' field indexed
as a keyword. It uses scanning + batch ID lookups instead of aggregations.

Usage:
    # Dry run (default) - see what would be deleted
    python contrib/cleanup_cross_bucket_duplicates.py

    # Actually delete duplicates
    python contrib/cleanup_cross_bucket_duplicates.py --execute

    # Filter by dataset
    python contrib/cleanup_cross_bucket_duplicates.py --dataset my_dataset

    # Adjust batch size for memory/performance tradeoff
    python contrib/cleanup_cross_bucket_duplicates.py --batch-size 5000
"""

import argparse
import sys
from typing import Generator, Literal

from anystore.logging import get_logger
from elasticsearch.helpers import scan

from openaleph_search.core import get_es
from openaleph_search.index.indexer import (
    MAX_REQUEST_TIMEOUT,
    MAX_TIMEOUT,
    query_delete,
)
from openaleph_search.index.indexes import bucket_index
from openaleph_search.settings import Settings

log = get_logger(__name__)
settings = Settings()

Bucket = Literal["things", "documents", "pages"]

# Bucket pairs where duplicates can occur, ordered from most to least specific.
# When duplicates exist, keep the entity in the more specific bucket (first in tuple).
BUCKET_CLEANUP_PAIRS: list[tuple[Bucket, Bucket]] = [
    ("pages", "documents"),  # Pages is more specific than Document
    # ("documents", "things"),  # Document is more specific than Thing
    # ("pages", "things"),      # Pages is more specific than Thing
]


def iter_index_ids(
    index: str,
    dataset: str | None = None,
    scroll_size: int = 10000,
) -> Generator[str, None, None]:
    """
    Iterate over all document IDs in an index.

    Args:
        index: Elasticsearch index name
        dataset: Optional dataset filter
        scroll_size: Number of documents per scroll batch

    Yields:
        Document IDs
    """
    es = get_es()

    query: dict = {"match_all": {}}
    if dataset:
        query = {"term": {"dataset": dataset}}

    for hit in scan(
        es,
        index=index,
        query={"query": query, "_source": False},
        timeout=MAX_TIMEOUT,
        request_timeout=MAX_REQUEST_TIMEOUT,
        size=scroll_size,
    ):
        yield hit["_id"]


def find_ids_in_index(
    es,
    index: str,
    ids: list[str],
    dataset: str | None = None,
) -> list[str]:
    """
    Check which IDs from the list exist in the given index.

    Uses an IDs query which is efficient for batch lookups.
    """
    if not ids:
        return []

    query: dict = {"ids": {"values": ids}}
    if dataset:
        query = {
            "bool": {
                "must": [
                    {"ids": {"values": ids}},
                    {"term": {"dataset": dataset}},
                ]
            }
        }

    result = es.search(
        index=index,
        query=query,
        _source=False,
        size=len(ids),
    )

    return [hit["_id"] for hit in result["hits"]["hits"]]


def find_cross_bucket_duplicates(
    keep_bucket: Bucket,
    delete_bucket: Bucket,
    dataset: str | None = None,
    batch_size: int = 10000,
) -> Generator[list[str], None, None]:
    """
    Find entity IDs that exist in both buckets.

    Scans the more specific bucket and checks which IDs also exist in the
    less specific bucket using batch ID queries.

    Args:
        keep_bucket: The more specific bucket (entities here will be kept)
        delete_bucket: The less specific bucket (duplicates here will be deleted)
        dataset: Optional dataset filter
        batch_size: Number of IDs to check per batch

    Yields:
        Batches of duplicate entity IDs
    """
    es = get_es()

    keep_index = bucket_index(keep_bucket, settings.index_write)
    delete_index = bucket_index(delete_bucket, settings.index_write)

    # Check if indexes exist
    if not es.indices.exists(index=keep_index):
        log.warning(f"Index {keep_index} does not exist, skipping")
        return
    if not es.indices.exists(index=delete_index):
        log.warning(f"Index {delete_index} does not exist, skipping")
        return

    # Scan the more specific bucket and collect IDs in batches
    id_batch: list[str] = []
    scanned = 0

    for entity_id in iter_index_ids(
        keep_index, dataset=dataset, scroll_size=batch_size
    ):
        id_batch.append(entity_id)
        scanned += 1

        if scanned % 100000 == 0:
            log.info(f"Scanned {scanned} IDs from {keep_bucket}...")

        if len(id_batch) >= batch_size:
            # Check which IDs from this batch exist in the delete_bucket
            duplicates = find_ids_in_index(es, delete_index, id_batch, dataset)
            if duplicates:
                yield duplicates
            id_batch = []

    # Process remaining IDs
    if id_batch:
        duplicates = find_ids_in_index(es, delete_index, id_batch, dataset)
        if duplicates:
            yield duplicates

    log.info(f"Finished scanning {scanned} IDs from {keep_bucket}")


def cleanup_cross_bucket_duplicates(
    dataset: str | None = None,
    dry_run: bool = True,
    batch_size: int = 10000,
) -> dict:
    """
    Remove duplicate entities that exist in multiple schema buckets.

    Keeps the entity in the most specific bucket (pages > documents > things)
    and deletes copies from less specific buckets.

    Args:
        dataset: Optional dataset filter
        dry_run: If True, only report what would be deleted
        batch_size: Number of IDs to process per batch

    Returns:
        Dict with statistics: {found, deleted, errors}
    """
    stats = {"found": 0, "deleted": 0, "errors": 0}

    for keep_bucket, delete_bucket in BUCKET_CLEANUP_PAIRS:
        delete_index = bucket_index(delete_bucket, settings.index_write)

        log.info(
            f"Checking for duplicates: {keep_bucket} (keep) vs {delete_bucket} (delete)",
            dataset=dataset,
        )

        for duplicate_ids in find_cross_bucket_duplicates(
            keep_bucket=keep_bucket,
            delete_bucket=delete_bucket,
            dataset=dataset,
            batch_size=batch_size,
        ):
            stats["found"] += len(duplicate_ids)

            if dry_run:
                log.info(
                    f"Would delete {len(duplicate_ids)} duplicates from {delete_bucket}",
                    sample_ids=duplicate_ids[:5],
                )
                stats["deleted"] += len(duplicate_ids)
            else:
                try:
                    # Bulk delete using delete_by_query with IDs
                    query: dict = {"ids": {"values": duplicate_ids}}
                    if dataset:
                        query = {
                            "bool": {
                                "must": [
                                    {"ids": {"values": duplicate_ids}},
                                    {"term": {"dataset": dataset}},
                                ]
                            }
                        }

                    result = query_delete(delete_index, query, sync=True)
                    deleted_count = result.get("deleted", 0)
                    stats["deleted"] += deleted_count

                    log.info(
                        f"Deleted {deleted_count} duplicates from {delete_bucket}",
                        sample_ids=duplicate_ids[:5],
                    )
                except Exception as e:
                    log.error(
                        f"Failed to delete batch from {delete_bucket}",
                        error=str(e),
                        batch_size=len(duplicate_ids),
                    )
                    stats["errors"] += len(duplicate_ids)

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Clean up cross-bucket duplicate entities in Elasticsearch indexes."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete duplicates (default is dry-run mode)",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=None,
        help="Filter cleanup to a specific dataset",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10000,
        help="Number of IDs to process per batch (default: 10000)",
    )

    args = parser.parse_args()

    dry_run = not args.execute

    if dry_run:
        log.info("=" * 60)
        log.info("DRY RUN MODE - No changes will be made")
        log.info("Use --execute to actually delete duplicates")
        log.info("=" * 60)
    else:
        log.warning("=" * 60)
        log.warning("EXECUTE MODE - Duplicates will be deleted!")
        log.warning("=" * 60)

    stats = cleanup_cross_bucket_duplicates(
        dataset=args.dataset,
        dry_run=dry_run,
        batch_size=args.batch_size,
    )

    action = "Would delete" if dry_run else "Deleted"
    log.info("=" * 60)
    log.info("Cleanup complete:")
    log.info(f"  Found: {stats['found']} duplicates")
    log.info(f"  {action}: {stats['deleted']} documents")
    log.info(f"  Errors: {stats['errors']}")
    log.info("=" * 60)

    if stats["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
