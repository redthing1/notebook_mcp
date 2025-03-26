# cli.py
import os
import sys
import asyncio
from pathlib import Path
from typing import List, Optional, Any, Dict

import typer
from minlog import logger, Verbosity

from .server import NotesServer

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])

APP_NAME = "mcp-notes"
app = typer.Typer(
    name=APP_NAME,
    help=f"{APP_NAME}: mcp notes server",
    no_args_is_help=True,
    context_settings=CONTEXT_SETTINGS,
    pretty_exceptions_show_locals=False,
)


def version_callback(value: bool):
    if value:
        from . import __version__

        logger.info(f"{APP_NAME} version {__version__}")
        raise typer.Exit()


@app.callback()
def app_callback(
    verbose: List[bool] = typer.Option([], "--verbose", "-v", help="verbose output"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="quiet output"),
    version: Optional[bool] = typer.Option(
        None, "--version", "-V", callback=version_callback
    ),
):
    if len(verbose) == 1:
        logger.be_verbose()
    elif len(verbose) == 2:
        logger.be_debug()
    elif quiet:
        logger.be_quiet()


@app.command()
def serve(
    dirs: List[Path] = typer.Argument(
        ...,
        help="directories containing notes (will be indexed recursively)",
        exists=True,
        dir_okay=True,
        file_okay=False,
    ),
    exts: str = typer.Option(
        "md,org,txt",
        "--exts",
        "-e",
        help="comma-separated list of file extensions to index",
    ),
    server_name: Optional[str] = typer.Option(
        "Notebook",
        "--name",
        "-n",
        help="name of the mcp server",
    ),
):
    """run the mcp notes server"""
    # parse extensions
    extensions = [ext.strip() for ext in exts.split(",") if ext.strip()]
    if not extensions:
        logger.error("no valid extensions specified")
        raise typer.Exit(code=1)

    logger.info(f"starting notes mcp server")
    logger.debug(f"extensions: {', '.join(extensions)}")

    # create and set up the server
    server = NotesServer(name=server_name)

    # run async setup in event loop
    async def setup_server():
        # add note directories
        for dir_path in dirs:
            try:
                await server.add_notes_dir(dir_path)
                logger.debug(f"added directory: {dir_path}")
            except ValueError as e:
                logger.error(f"error adding directory {dir_path}: {e}")
                raise typer.Exit(code=1)

        # index notes
        try:
            await server.index_notes(extensions)
            logger.info(f"indexed {len(server.index.notes)} notes")
        except Exception as e:
            logger.error(f"error indexing notes: {e}")
            raise typer.Exit(code=1)

    # run async setup
    asyncio.run(setup_server())

    # run the server
    try:
        logger.info(f"starting mcp server: {server_name}")
        server.run()
    except KeyboardInterrupt:
        logger.info("server stopped by user")
    except Exception as e:
        logger.error(f"error running server: {e}")
        raise typer.Exit(code=1)


def main():
    app()


if __name__ == "__main__":
    main()
