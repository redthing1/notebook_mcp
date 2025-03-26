# server.py
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional, Any
from minlog import logger

from mcp.server.fastmcp import FastMCP, Context
from mcp.server.fastmcp.prompts import base

from .indexer import NotesIndex
from .searcher import NotesSearcher


@dataclass
class NotesContext:
    """type-safe context for the notes server"""

    index: NotesIndex
    searcher: NotesSearcher


@asynccontextmanager
async def notes_lifespan(server: FastMCP) -> AsyncIterator[NotesContext]:
    """manage server lifecycle with type-safe context"""
    # initialize resources
    logger.info("initializing notes index and searcher")
    index = NotesIndex()
    searcher = NotesSearcher(index)

    try:
        yield NotesContext(index=index, searcher=searcher)
    finally:
        # cleanup resources if needed
        logger.info("shutting down notes server")


class NotesServer:
    def __init__(self, name: str = "Notes MCP"):
        """initialize the notes mcp server"""
        # create server with lifespan support
        self.mcp = FastMCP(
            name,
            lifespan=notes_lifespan,
        )

        # local index and searcher for direct access outside of mcp context
        self.index = NotesIndex()
        self.searcher = NotesSearcher(self.index)

        # register mcp handlers
        self._register_tools()
        self._register_resources()
        self._register_prompts()

    def _register_tools(self):
        """register mcp tools"""

        @self.mcp.tool()
        async def note_search(
            query: str,
            max_results: int = 10,
            context_lines: int = 2,
            ctx: Context = None,
        ) -> List[Dict]:
            """
            search notes using text search

            args:
                query: the search query
                max_results: maximum number of results to return
                context_lines: number of context lines to include

            returns:
                list of results with note_id, line_number, and context
            """
            # use progress reporting for long searches
            if ctx:
                ctx.info(f"searching notes for: {query}")

            return self.searcher.search(query, max_results, context_lines)

        @self.mcp.tool()
        def note_list(query: Optional[str] = None) -> List[str]:
            """
            list note ids, optionally filtered by a query

            args:
                query: optional filter to apply to note ids

            returns:
                list of matching note ids
            """
            return self.index.list_notes(query)

        @self.mcp.tool()
        def note_read(note_id: str) -> str:
            """
            read the contents of a note by its id

            args:
                note_id: the note identifier

            returns:
                the full contents of the note
            """
            return self.searcher.read_note(note_id)

    def _register_resources(self):
        """register mcp resources"""

        # register a resource to list all notes
        @self.mcp.resource("notes://list")
        def list_all_notes() -> str:
            """get a list of all notes"""
            notes = self.index.list_notes()
            return "\n".join(notes)

        # register a resource to get information about the notes collection
        @self.mcp.resource("notes://info")
        def get_notes_info() -> str:
            """get information about the indexed notes"""
            info = [
                f"total notes: {len(self.index.notes)}",
                f"extensions: {', '.join(self.index.extensions)}",
                "sources:",
            ]

            for source_name, source_dir in self.index.sources.items():
                source_notes = [
                    id for id in self.index.notes if id.startswith(f"{source_name}:")
                ]
                info.append(
                    f"  - {source_name}: {len(source_notes)} notes ({source_dir})"
                )

            return "\n".join(info)

        # register a dynamic resource for each note
        @self.mcp.resource("note://{note_id}")
        def get_note_content(note_id: str) -> str:
            """
            get the contents of a note by its id

            args:
                note_id: the note identifier

            returns:
                the full contents of the note
            """
            return self.searcher.read_note(note_id)

    def _register_prompts(self):
        """register mcp prompts for common note interactions"""

        @self.mcp.prompt()
        def search_notes(query: str) -> str:
            """
            create a prompt to search notes for a specific query

            args:
                query: the search query

            returns:
                a prompt to search for notes
            """
            return f"""
            please search my notes for information about "{query}".
            use the note_search tool with this query, then read the most relevant notes using the note_read tool.
            summarize what you find and cite specific notes by their id.
            """

        @self.mcp.prompt()
        def browse_notes(topic: Optional[str] = None) -> list[base.Message]:
            """
            create a prompt to browse notes, optionally filtered by topic

            args:
                topic: optional topic to filter notes by

            returns:
                a sequence of messages to browse notes
            """
            if topic:
                instruction = f"please help me browse my notes about {topic}."
            else:
                instruction = "please help me browse through my notes collection."

            return [
                base.UserMessage(instruction),
                base.AssistantMessage(
                    "i'll help you browse your notes. first, let me get information about your notes collection."
                ),
                base.AssistantMessage(
                    "to browse your notes, i can:\n"
                    "1. list all notes or filter by a keyword\n"
                    "2. search for specific content\n"
                    "3. read specific notes in full\n"
                    "what would you like to do?"
                ),
            ]

        @self.mcp.prompt()
        def analyze_notes(query: str) -> str:
            """
            create a prompt to analyze notes on a specific topic

            args:
                query: the topic to analyze

            returns:
                a prompt to analyze notes
            """
            return f"""
            please analyze my notes about "{query}".
            
            1. first, search for relevant notes using the note_search tool
            2. read the full content of the most relevant notes using note_read
            3. analyze key themes, concepts, and connections
            4. identify any gaps in my notes or potential areas to explore further
            5. summarize your findings in a structured way
            """

        @self.mcp.prompt()
        def daily_notes_review() -> str:
            """
            create a prompt for a daily review of recently modified notes

            returns:
                a prompt for daily notes review
            """
            return """
            please help me review my recent notes:
            
            1. list notes that might contain today's date or "daily log" in their ids
            2. for the most recent notes, read their content
            3. summarize key points, tasks, and insights
            4. identify any follow-up actions or connected ideas
            """

    async def add_notes_dir(
        self, dir_path: str, name: Optional[str] = None, ctx: Optional[Context] = None
    ):
        """add a notes directory to the index"""
        path = Path(dir_path).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"not a directory: {path}")

        if name is None:
            name = path.name

        if ctx:
            ctx.info(f"adding notes source: {name} ({path})")

        self.index.add_source(path, name)

    async def index_notes(self, extensions: List[str], ctx: Optional[Context] = None):
        """index notes with the specified extensions"""
        total_files = 0

        # count total files first for progress reporting
        if ctx:
            ctx.info(f"counting files with extensions: {', '.join(extensions)}")
            for source_name, source_dir in self.index.sources.items():
                for ext in extensions:
                    files = list(source_dir.rglob(f"*.{ext}"))
                    total_files += len(files)

            ctx.info(f"found {total_files} files to index")

        # now index with progress reporting
        indexed = 0
        for source_name, source_dir in self.index.sources.items():
            if ctx:
                ctx.info(f"indexing source: {source_name}")

            for ext in extensions:
                files = list(source_dir.rglob(f"*.{ext}"))
                for file_path in files:
                    if file_path.is_file():
                        rel_path = file_path.relative_to(source_dir)
                        note_id = f"{source_name}:{rel_path}"
                        self.index.notes[note_id] = file_path
                        indexed += 1

                        if ctx and total_files > 0:
                            await ctx.report_progress(indexed, total_files)

        # set extensions after indexing
        self.index.extensions = {ext.lower().lstrip(".") for ext in extensions}

        # log indexing summary
        logger.info(
            f"indexed {len(self.index.notes)} notes with extensions: {', '.join(self.index.extensions)}"
        )

        if ctx:
            ctx.info(f"indexing complete: {len(self.index.notes)} notes indexed")

    def run(self):
        """run the mcp server"""
        self.mcp.run()
