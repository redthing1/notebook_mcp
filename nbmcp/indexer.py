import os
from pathlib import Path
from typing import Dict, List, Set
from minlog import logger


class NotesIndex:
    def __init__(self):
        self.notes: Dict[str, Path] = {}  # note_id -> full_path
        self.sources: Dict[str, Path] = {}  # source_name -> source_dir
        self.extensions: Set[str] = set()

    def add_source(self, source_dir: Path, source_name: str = None):
        """add a source directory to the index"""
        if source_name is None:
            source_name = source_dir.name

        source_dir = source_dir.resolve()
        self.sources[source_name] = source_dir
        logger.info(f"Added source '{source_name}' from {source_dir}")

    def index_sources(self, extensions: List[str]):
        """index all source directories for files with given extensions"""
        self.extensions = {ext.lower().lstrip(".") for ext in extensions}

        total_notes = 0
        for source_name, source_dir in self.sources.items():
            logger.info(f"Indexing {source_name} ({source_dir})...")

            source_notes = 0
            for ext in self.extensions:
                # find all files with this extension recursively
                for file_path in source_dir.rglob(f"*.{ext}"):
                    if file_path.is_file():
                        rel_path = file_path.relative_to(source_dir)
                        note_id = f"{source_name}:{rel_path}"
                        self.notes[note_id] = file_path
                        source_notes += 1

            logger.info(f"Indexed {source_notes} notes from {source_name}")
            total_notes += source_notes

        logger.info(f"Indexing complete. Total notes: {total_notes}")

    def get_note_path(self, note_id: str) -> Path:
        """get the full path for a note ID"""
        if note_id not in self.notes:
            raise ValueError(f"Note ID '{note_id}' not found in index")
        return self.notes[note_id]

    def list_notes(self, query: str = None) -> List[str]:
        """list all note IDs, optionally filtered by query"""
        if not query:
            return list(self.notes.keys())

        # simple filtering - return IDs that contain the query string
        return [note_id for note_id in self.notes if query.lower() in note_id.lower()]
