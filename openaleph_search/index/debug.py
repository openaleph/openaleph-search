"""
Debug-instrumented version of indexer for diagnosing concurrency hangs.

This module provides instrumented versions of the async indexer functions
with extensive logging, timeout detection, and task monitoring to help
identify where execution hangs during bulk indexing operations.
"""

import asyncio
import itertools
import os
import signal
import sys
import traceback
from datetime import datetime
from typing import Any, Generator, Iterable, TypeAlias, TypedDict

from anystore.decorators import error_handler
from anystore.io import logged_items
from anystore.logging import get_logger
from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import BulkIndexError, async_bulk

from openaleph_search.core import get_async_ingest_es
from openaleph_search.index.util import refresh_sync
from openaleph_search.settings import Settings

log = get_logger(__name__)
settings = Settings()

MAX_REQUEST_TIMEOUT = 84600


class Action(TypedDict):
    _id: str
    _index: str
    _source: dict[str, Any]


Actions: TypeAlias = Generator[Action, None, None] | Iterable[Action]


# Global flag to enable/disable stack dump signal handler
_signal_handler_installed = False


def install_stack_dump_handler():
    """
    Install SIGUSR1 signal handler to dump stack traces on demand.

    Usage: When process hangs, send signal:
        kill -USR1 <pid>
    """
    global _signal_handler_installed

    if _signal_handler_installed:
        return

    def dump_stack(signum, frame):
        """Dump all thread/task stacks on SIGUSR1"""
        log.info("\n*** STACKTRACE DUMP - START ***")

        # Dump all thread stacks
        for thread_id, stack in sys._current_frames().items():
            log.info(f"\n# ThreadID: {thread_id}")
            for filename, lineno, name, line in traceback.extract_stack(stack):
                log.info(f"  {filename}:{lineno} in {name}")
                if line:
                    log.info(f"    {line.strip()}")

        # Dump asyncio tasks
        try:
            tasks = asyncio.all_tasks()
            log.info(f"\n# Active asyncio tasks: {len(tasks)}")
            for i, task in enumerate(tasks):
                log.info(
                    f"  Task {i}: {task.get_name()}, "
                    f"done={task.done()}, cancelled={task.cancelled()}"
                )
                if hasattr(task, "get_stack"):
                    stack = task.get_stack()
                    for frame in stack:
                        log.info(f"    {frame}")
        except RuntimeError:
            log.info("# No asyncio event loop running")

        log.info("*** STACKTRACE DUMP - END ***\n")

    signal.signal(signal.SIGUSR1, dump_stack)
    _signal_handler_installed = True
    log.info(
        "Stack dump handler installed. Send SIGUSR1 to dump stacks: kill -USR1 %d",
        os.getpid(),
    )


async def monitor_tasks(
    pending_tasks_ref: dict, interval: int = 30, timeout_threshold: int = 300
):
    """
    Background task to monitor pending task states periodically.

    Args:
        pending_tasks_ref: Dict with 'tasks' key containing set of pending tasks
        interval: How often to check (seconds)
        timeout_threshold: Warn if tasks are pending longer than this (seconds)
    """
    start_time = datetime.now()
    last_activity = datetime.now()
    last_task_count = 0

    try:
        while True:
            await asyncio.sleep(interval)

            current_time = datetime.now()
            pending_tasks = pending_tasks_ref.get("tasks", set())
            current_count = len(pending_tasks)

            # Check for activity
            if current_count != last_task_count:
                last_activity = current_time
                last_task_count = current_count

            idle_time = (current_time - last_activity).total_seconds()
            elapsed = (current_time - start_time).total_seconds()

            log.info("=== Task Monitor ===")
            log.info(f"Elapsed time: {elapsed:.1f}s")
            log.info(f"Pending tasks: {current_count}")
            log.info(f"Idle time: {idle_time:.1f}s")

            if current_count > 0:
                # Show detailed task states
                done_count = sum(1 for t in pending_tasks if t.done())
                cancelled_count = sum(1 for t in pending_tasks if t.cancelled())
                active_count = current_count - done_count - cancelled_count

                log.info(
                    f"  Active: {active_count}, Done: {done_count}, "
                    f"Cancelled: {cancelled_count}"
                )

                # Warn if no activity for too long
                if idle_time > timeout_threshold:
                    log.warning(
                        f"⚠️  POSSIBLE HANG: No task activity for {idle_time:.1f}s!"
                    )
                    log.warning(f"  {current_count} tasks still pending")

                    # Log a few task details
                    for i, task in enumerate(list(pending_tasks)[:5]):
                        log.warning(
                            f"  Task {i}: {task.get_name()}, "
                            f"done={task.done()}, cancelled={task.cancelled()}"
                        )
    except asyncio.CancelledError:
        log.info("Task monitor stopped")
        raise


@error_handler(logger=log, max_retries=settings.max_retries)
async def process_chunk_debug(
    es: AsyncElasticsearch,
    chunk_actions,
    sync: bool,
    chunk_id: int,
    timeout: int = 600,  # 10 minute timeout per chunk
):
    """
    Instrumented version of process_chunk with detailed logging and timeout.

    Args:
        es: Elasticsearch client
        chunk_actions: Actions to process
        sync: Whether to sync/refresh
        chunk_id: Identifier for this chunk (for logging)
        timeout: Maximum time to wait for chunk processing (seconds)
    """
    start = datetime.now()
    log.debug(f"[Chunk {chunk_id}] Starting processing")

    try:
        # Wrap async_bulk with timeout
        result = await asyncio.wait_for(
            async_bulk(
                es,
                chunk_actions,
                max_retries=settings.max_retries,
                refresh=refresh_sync(sync),
                timeout=f"{MAX_REQUEST_TIMEOUT}s",
                chunk_size=settings.indexer_chunk_size,
                max_chunk_bytes=settings.indexer_max_chunk_bytes,
            ),
            timeout=timeout,
        )

        success, failed = result

        # Log failures
        for failure in failed:
            if failure.get("delete", {}).get("status") == 404:
                continue
            log.warning(f"[Chunk {chunk_id}] Bulk index error: %r" % failure)

        elapsed = (datetime.now() - start).total_seconds()
        log.debug(
            f"[Chunk {chunk_id}] Completed in {elapsed:.2f}s: "
            f"{success} success, {len(failed)} failed"
        )

        return success, failed

    except asyncio.TimeoutError:
        elapsed = (datetime.now() - start).total_seconds()
        log.error(
            f"[Chunk {chunk_id}] ⚠️  TIMEOUT after {elapsed:.1f}s (limit: {timeout}s)"
        )
        raise
    except BulkIndexError as e:
        elapsed = (datetime.now() - start).total_seconds()
        log.error(
            f"[Chunk {chunk_id}] BulkIndexError after {elapsed:.2f}s: "
            f"{len(e.errors)} document(s) failed"
        )
        log.error(f"[Chunk {chunk_id}] Error details: {e}")

        # Log detailed information about each failed document
        for i, error in enumerate(e.errors[:10]):
            log.error(f"[Chunk {chunk_id}] Document {i + 1} error: {error}")

        if len(e.errors) > 10:
            log.error(
                f"[Chunk {chunk_id}] ... and {len(e.errors) - 10} more errors (truncated)"
            )

        raise
    except Exception as e:
        elapsed = (datetime.now() - start).total_seconds()
        log.error(f"[Chunk {chunk_id}] Unexpected error after {elapsed:.2f}s: {e}")
        raise


async def bulk_actions_async_debug(
    actions: Actions,
    chunk_size: int | None = settings.indexer_chunk_size,
    max_concurrency: int | None = settings.indexer_concurrency,
    sync: bool | None = False,
    monitor_interval: int = 30,
    chunk_timeout: int = 600,
    enable_signal_handler: bool = True,
):
    """
    Instrumented version of bulk_actions_async with extensive debugging.

    Args:
        actions: Iterator/iterable of actions to index
        chunk_size: Number of actions per chunk
        max_concurrency: Maximum number of concurrent chunks
        sync: Whether to refresh index after operations
        monitor_interval: How often to log task status (seconds)
        chunk_timeout: Maximum time to wait for a single chunk (seconds)
        enable_signal_handler: Install SIGUSR1 handler for stack dumps
    """
    start = datetime.now()
    log.info("=" * 60)
    log.info("Starting INSTRUMENTED bulk_actions_async")
    log.info(f"  concurrency={max_concurrency}")
    log.info(f"  chunk_size={chunk_size}")
    log.info(f"  sync={sync}")
    log.info(f"  monitor_interval={monitor_interval}s")
    log.info(f"  chunk_timeout={chunk_timeout}s")
    log.info(f"  PID={os.getpid()}")
    log.info("=" * 60)

    # Install signal handler if requested
    if enable_signal_handler:
        install_stack_dump_handler()

    # Initialize Elasticsearch client
    log.info("[1/5] Creating Elasticsearch client...")
    es = await get_async_ingest_es()
    log.info("[1/5] ✓ Elasticsearch client created")

    # Prepare actions iterator
    log.info("[2/5] Preparing actions iterator...")
    actions = logged_items(actions, "Loading", 10_000, item_name="doc", logger=log)
    chunks = itertools.batched(actions, n=chunk_size or settings.indexer_chunk_size)
    max_concurrency = max_concurrency or settings.indexer_concurrency
    semaphore = asyncio.Semaphore(max_concurrency)
    log.info(f"[2/5] ✓ Actions iterator ready (semaphore: {max_concurrency})")

    async def process_chunk_with_semaphore(chunk, chunk_id):
        available_before = semaphore._value
        log.debug(
            f"[Chunk {chunk_id}] Waiting for semaphore "
            f"(available: {available_before}/{max_concurrency})"
        )

        async with semaphore:
            available_after = semaphore._value
            log.debug(
                f"[Chunk {chunk_id}] Acquired semaphore "
                f"(available: {available_after}/{max_concurrency})"
            )

            result = await process_chunk_debug(
                es, chunk, sync, chunk_id, timeout=chunk_timeout
            )

            log.debug(f"[Chunk {chunk_id}] Releasing semaphore")
            return result

    success = 0
    errors = 0
    pending_tasks = set()
    chunk_count = 0

    # Shared reference for monitor
    pending_tasks_ref = {"tasks": pending_tasks}

    # Start task monitor
    log.info("[3/5] Starting task monitor...")
    monitor = asyncio.create_task(
        monitor_tasks(
            pending_tasks_ref,
            interval=monitor_interval,
            timeout_threshold=chunk_timeout,
        )
    )
    monitor.set_name("TaskMonitor")
    log.info("[3/5] ✓ Task monitor started")

    try:
        log.info("[4/5] Processing chunks...")
        iteration_count = 0

        for chunk in chunks:
            chunk_count += 1
            iteration_count += 1

            log.debug(
                f"[Main Loop] Iteration {iteration_count}: "
                f"Creating task for chunk {chunk_count}"
            )

            # Create task
            task = asyncio.create_task(
                process_chunk_with_semaphore(list(chunk), chunk_count)
            )
            task.set_name(f"Chunk-{chunk_count}")
            pending_tasks.add(task)

            log.debug(f"[Main Loop] Pending tasks: {len(pending_tasks)}")

            # Process completed tasks when we hit concurrency limit
            if len(pending_tasks) >= max_concurrency:
                log.debug(
                    f"[Main Loop] Hit concurrency limit "
                    f"({len(pending_tasks)}/{max_concurrency}), "
                    f"waiting for completion..."
                )

                try:
                    # Add timeout to detect hangs
                    done, pending_tasks = await asyncio.wait_for(
                        asyncio.wait(
                            pending_tasks, return_when=asyncio.FIRST_COMPLETED
                        ),
                        timeout=chunk_timeout * 2,  # Allow 2x chunk timeout
                    )

                    log.debug(
                        f"[Main Loop] {len(done)} tasks completed, "
                        f"{len(pending_tasks)} still pending"
                    )

                except asyncio.TimeoutError:
                    elapsed = (datetime.now() - start).total_seconds()
                    log.error("=" * 60)
                    log.error(f"⚠️  HANG DETECTED at iteration {iteration_count}!")
                    log.error(f"  Elapsed time: {elapsed:.1f}s")
                    log.error(f"  No task completed in {chunk_timeout * 2}s")
                    log.error(f"  Pending tasks: {len(pending_tasks)}")
                    log.error(f"  Last chunk ID: {chunk_count}")
                    log.error("=" * 60)

                    # Log detailed task states
                    for i, task in enumerate(pending_tasks):
                        log.error(
                            f"  Hung Task {i}: {task.get_name()}, "
                            f"done={task.done()}, cancelled={task.cancelled()}"
                        )

                    raise

                # Collect results from completed tasks
                for task in done:
                    try:
                        result = await task
                        success += result[0]
                        errors += len(result[1])
                    except Exception as e:
                        log.error(
                            f"[Main Loop] Chunk processing failed: {e}", exc_info=True
                        )
                        errors += 1

        # Process remaining tasks
        log.info(f"[5/5] Processing {len(pending_tasks)} remaining tasks...")
        if pending_tasks:
            results = await asyncio.gather(*pending_tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    log.error(f"[Cleanup] Task {i} failed: {result}", exc_info=True)
                    errors += 1
                else:
                    success += result[0]
                    errors += len(result[1])

        log.info("[5/5] ✓ All tasks processed")

    finally:
        # Stop monitor
        log.info("Stopping task monitor...")
        monitor.cancel()
        try:
            await monitor
        except asyncio.CancelledError:
            pass

        # Close Elasticsearch client
        log.info("Closing Elasticsearch client...")
        await es.close()
        log.info("✓ Elasticsearch client closed")

    end = datetime.now()
    elapsed = end - start

    log.info("=" * 60)
    log.info("INSTRUMENTED bulk_actions_async COMPLETED")
    log.info(f"  Total chunks: {chunk_count}")
    log.info(f"  Successful: {success}")
    log.info(f"  Failed: {errors}")
    log.info(f"  Duration: {elapsed}")
    log.info(
        f"  Throughput: {success / elapsed.total_seconds():.1f} docs/sec"
        if elapsed.total_seconds() > 0
        else "  Throughput: N/A"
    )
    log.info("=" * 60)
