import shutil
import json
from pathlib import Path
from typing import Dict, List, Optional
from minlog import logger
import sh


class NotesSearcher:
    def __init__(self, notes_index):
        self.index = notes_index
        self._check_tools()

    def _check_tools(self):
        """check if ripgrep is available, otherwise fallback to grep"""
        self.use_ripgrep = shutil.which("rg") is not None
        self.use_grep = shutil.which("grep") is not None

        if self.use_ripgrep:
            logger.info("Using ripgrep for searching")
        elif self.use_grep:
            logger.info("Using grep for searching (ripgrep not found)")
        else:
            logger.warning(
                "Neither ripgrep nor grep found, search functionality will be limited"
            )

    def search(
        self, query: str, max_results: int = 10, context_lines: int = 2
    ) -> List[Dict]:
        """
        search notes for the given query
        returns: list of dicts with note_id, line_number, context
        """
        results = []

        if not (self.use_ripgrep or self.use_grep):
            # fallback to basic string search if no tools available
            return self._basic_search(query, max_results)

        try:
            if self.use_ripgrep:
                results = self._ripgrep_search(query, max_results, context_lines)
            else:
                results = self._grep_search(query, max_results, context_lines)
        except Exception as e:
            logger.error(f"Search error: {e}")
            # fallback to basic search on error
            return self._basic_search(query, max_results)

        return results

    def _ripgrep_search(
        self, query: str, max_results: int, context_lines: int
    ) -> List[Dict]:
        """search using ripgrep"""
        results = []
        count = 0

        # build include pattern for extensions
        include_pattern = f"*.{{{','.join(self.index.extensions)}}}"

        # run ripgrep for each source directory
        for source_name, source_dir in self.index.sources.items():
            if count >= max_results:
                break

            try:
                # use ripgrep with JSON output for easier parsing
                rg = sh.rg.bake(
                    "--json",  # JSON output
                    "-C",
                    context_lines,  # context lines
                    "--max-count",
                    1,  # max 1 match per file
                    "-g",
                    include_pattern,  # only include specified extensions
                    "--no-heading",  # no file headers
                    "--color",
                    "never",  # no color
                )

                # run the search command
                output = rg(
                    query, source_dir, _ok_code=[0, 1]
                )  # 1 is normal "no matches" exit code

                # parse results
                for line in output.splitlines():
                    if count >= max_results:
                        break

                    try:
                        match = json.loads(line)

                        if match.get("type") == "match":
                            file_path = Path(match["data"]["path"]["text"])
                            rel_path = file_path.relative_to(source_dir)
                            note_id = f"{source_name}:{rel_path}"

                            line_number = match["data"]["line_number"]
                            context = match["data"]["lines"]["text"]

                            results.append(
                                {
                                    "note_id": note_id,
                                    "line_number": line_number,
                                    "context": context,
                                }
                            )
                            count += 1
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.debug(f"Failed to parse ripgrep output: {e}")
                        continue

            except sh.ErrorReturnCode as e:
                logger.debug(f"ripgrep error in {source_name}: {e}")
                continue

        return results

    def _grep_search(
        self, query: str, max_results: int, context_lines: int
    ) -> List[Dict]:
        """search using grep"""
        results = []
        count = 0

        # run grep for each source directory
        for source_name, source_dir in self.index.sources.items():
            if count >= max_results:
                break

            for ext in self.index.extensions:
                try:
                    # use grep with context
                    grep = sh.grep.bake(
                        "-n",  # line numbers
                        "-A",
                        context_lines,  # after context
                        "-B",
                        context_lines,  # before context
                        "--color=never",  # no color
                        "-r",  # recursive
                        "--include",
                        f"*.{ext}",  # only include specified extension
                    )

                    # run the search command
                    output = grep(
                        query, source_dir, _ok_code=[0, 1]
                    )  # 1 is normal "no matches" exit code

                    # parse results - grep output is more complex to parse
                    current_file = None
                    current_result = None

                    for line in output.splitlines():
                        if count >= max_results:
                            break

                        # check if this is a file:line indicator or a context line
                        if line.startswith("--"):  # separator between results
                            if current_result:
                                results.append(current_result)
                                current_result = None
                                count += 1
                            continue

                        if ":" in line and current_file is None:
                            # this is likely a file:line:content format
                            parts = line.split(":", 2)
                            if len(parts) >= 3:
                                file_path = Path(parts[0])
                                try:
                                    rel_path = file_path.relative_to(source_dir)
                                    note_id = f"{source_name}:{rel_path}"
                                    line_number = int(parts[1])

                                    current_result = {
                                        "note_id": note_id,
                                        "line_number": line_number,
                                        "context": parts[2] + "\n",
                                    }
                                except ValueError:
                                    continue
                        elif current_result:
                            # add to current context
                            current_result["context"] += line + "\n"

                    # add the last result if present
                    if current_result:
                        results.append(current_result)
                        count += 1

                except sh.ErrorReturnCode as e:
                    logger.debug(f"grep error in {source_name}: {e}")
                    continue

        return results

    def _basic_search(self, query: str, max_results: int) -> List[Dict]:
        """basic string search as fallback"""
        results = []
        count = 0

        query = query.lower()

        for note_id, file_path in self.index.notes.items():
            if count >= max_results:
                break

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                if query in content.lower():
                    # find the line number of the first match
                    lines = content.splitlines()
                    line_number = 0

                    for i, line in enumerate(lines):
                        if query in line.lower():
                            line_number = i + 1
                            break

                    # get some context (simplified)
                    start = max(0, line_number - 3)
                    end = min(len(lines), line_number + 2)
                    context = "\n".join(lines[start:end])

                    results.append(
                        {
                            "note_id": note_id,
                            "line_number": line_number,
                            "context": context,
                        }
                    )
                    count += 1
            except Exception as e:
                logger.debug(f"Error reading {note_id}: {e}")
                continue

        return results

    def read_note(self, note_id: str) -> str:
        """read the full contents of a note by its ID"""
        file_path = self.index.get_note_path(note_id)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error reading note {note_id}: {e}")
            raise ValueError(f"Failed to read note {note_id}: {e}")
