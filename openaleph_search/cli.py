from typing import Annotated, Optional

import typer
from anystore.cli import ErrorHandler
from anystore.logging import configure_logging, get_logger
from ftmq.io import smart_read_proxies
from rich import print

from openaleph_search import __version__
from openaleph_search.index import admin, entities
from openaleph_search.settings import Settings

settings = Settings()

cli = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=settings.debug)
log = get_logger(__name__)

OPT_INPUT_URI = typer.Option("-", "-i", help="Input uri, default stdin")
OPT_DATASET = typer.Option(..., "-d", help="Dataset")


@cli.callback(invoke_without_command=True)
def cli_openaleph_search(
    version: Annotated[Optional[bool], typer.Option(..., help="Show version")] = False,
    settings: Annotated[
        Optional[bool], typer.Option(..., help="Show current settings")
    ] = False,
):
    if version:
        print(__version__)
        raise typer.Exit()
    if settings:
        settings_ = Settings()
        print(settings_)
        raise typer.Exit()
    configure_logging()


@cli.command("upgrade")
def cli_upgrade():
    """Upgrade the index mappings or create if they don't exist"""
    with ErrorHandler(log):
        admin.upgrade_search()


@cli.command("reset")
def cli_reset():
    """Drop all data and indexes and re-upgrade"""
    with ErrorHandler(log):
        admin.delete_index()
        admin.upgrade_search()


@cli.command("index-entities")
def cli_index_entities(
    input_uri: str = OPT_INPUT_URI,
    dataset: str = OPT_DATASET,
):
    """Index entities into given dataset"""
    with ErrorHandler(log):
        entities.index_bulk(dataset, smart_read_proxies(input_uri))
