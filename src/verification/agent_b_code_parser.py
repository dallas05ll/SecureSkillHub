"""
Agent B -- Code Parser.

Orchestrated via Claude Code Task agents. No API key is needed.

This agent reads ONLY source code files from a skill repository. Agent B NEVER
sees documentation (README.md, SKILL.md, etc.). Its job is to determine what the
code *actually* does -- imports, system calls, network access, file I/O,
env-var access -- so downstream agents can compare against documented claims.

Workflow:
    1. Call ``prepare(repo_path)`` to collect source code and build the prompt
       payload (system prompt + user message + expected output fields).
    2. Hand the returned dict to a Claude Code Task agent, which performs the
       actual LLM inference.
    3. Parse the Task agent's JSON response into an ``AgentBOutput`` instance.

The ``prepare()`` method returns the prompt data; a Task agent does the LLM work.
The output must conform to ``AgentBOutput`` (defined in src.sanitizer.schemas).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from src.sanitizer.schemas import AgentBOutput, CodeFinding, ScanSeverity

logger = logging.getLogger(__name__)

# Extensions that are considered source code.
_CODE_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
    ".go", ".rs", ".rb", ".java", ".kt", ".c", ".cpp", ".h", ".hpp",
    ".sh", ".bash", ".zsh", ".fish",
    ".lua", ".pl", ".pm",
    ".toml", ".yaml", ".yml", ".json", ".cfg", ".ini", ".env",
    ".dockerfile",
})

# Extensions explicitly excluded (docs / non-code assets).
_SKIP_EXTENSIONS: frozenset[str] = frozenset({
    ".md", ".rst", ".txt", ".html", ".css", ".svg", ".png", ".jpg",
    ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".eot",
    ".lock", ".map",
})

# Filenames that are always source-relevant even without a recognised extension.
_SPECIAL_FILENAMES: frozenset[str] = frozenset({
    "Dockerfile", "Makefile", "Procfile", "Gemfile", "Rakefile",
    ".env", ".env.example",
})

# Hard cap on how much code text we send to the model (characters).
_MAX_CODE_CHARS = 80_000

SYSTEM_PROMPT = """\
You are Agent B -- a code-only static analyser for a security verification
pipeline.

RULES -- you MUST follow all of these:
1. You ONLY analyse the source code provided to you.  You have ZERO access
   to documentation, and you must NOT read or reference any .md files.
2. Report what the code ACTUALLY does -- not what anyone claims it does.
3. Extract:
   - actual_capabilities: high-level list of things this code does.
   - imports: all external packages / modules imported.
   - system_calls: any usage of os.system, subprocess, exec, eval, or
     equivalent dangerous calls.
   - network_calls: any HTTP requests, socket usage, DNS lookups, etc.
   - file_operations: any reads/writes to the local filesystem.
   - env_access: any reads of environment variables.
   - findings: a list of notable findings with category, detail, file_path,
     optional line_number, and severity (info/low/medium/high/critical).
   - total_files_analyzed: count of files you were given.
   - primary_language: the dominant programming language.
4. Be exhaustive.  A missed dangerous call is a security failure.
5. If the code is obfuscated, note it as a CRITICAL finding.

Return your analysis as a JSON object matching this schema EXACTLY:
{
  "actual_capabilities": [str],
  "imports": [str],
  "system_calls": [str],
  "network_calls": [str],
  "file_operations": [str],
  "env_access": [str],
  "findings": [
    {
      "category": str,
      "detail": str,
      "file_path": str,
      "line_number": int | null,
      "severity": "info" | "low" | "medium" | "high" | "critical"
    }
  ],
  "total_files_analyzed": int,
  "primary_language": str
}
"""

# Expected output field names (mirrors AgentBOutput schema).
OUTPUT_SCHEMA_FIELDS: list[str] = [
    "actual_capabilities",
    "imports",
    "system_calls",
    "network_calls",
    "file_operations",
    "env_access",
    "findings",
    "total_files_analyzed",
    "primary_language",
]


class AgentBCodeParser:
    """Reads source code from a skill repo and prepares prompt data for a
    Claude Code Task agent.

    This class is a *data preparation + output validation* layer.  It does NOT
    call any LLM API directly.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def prepare(self, repo_path: str) -> dict:
        """Collect source code and build the prompt payload for a Task agent.

        Parameters
        ----------
        repo_path : str
            Path to the cloned skill repository on disk.

        Returns
        -------
        dict
            A dictionary with keys:
            - ``system_prompt``    : str -- the system prompt for the Task agent.
            - ``user_message``     : str -- the user message containing code text.
            - ``output_schema``    : list[str] -- field names expected in the JSON response.
            - ``file_count``       : int -- number of source files collected.
            - ``primary_language`` : str -- detected primary language.
            - ``empty``            : bool -- True when no source files were found
              (caller should use ``build_empty_output`` instead of invoking a
              Task agent).

        Raises
        ------
        FileNotFoundError
            If *repo_path* does not exist.
        """
        root = Path(repo_path)
        if not root.is_dir():
            raise FileNotFoundError(f"Repository path does not exist: {repo_path}")

        code_text, file_count, primary_lang = self._collect_code(root)

        if not code_text.strip():
            logger.warning("No source files found in %s", repo_path)
            return {
                "system_prompt": SYSTEM_PROMPT,
                "user_message": "",
                "output_schema": OUTPUT_SCHEMA_FIELDS,
                "file_count": 0,
                "primary_language": "unknown",
                "empty": True,
            }

        user_message = (
            f"Total source files provided: {file_count}\n"
            f"Detected primary language: {primary_lang}\n\n"
            f"Source code:\n\n{code_text}"
        )

        return {
            "system_prompt": SYSTEM_PROMPT,
            "user_message": user_message,
            "output_schema": OUTPUT_SCHEMA_FIELDS,
            "file_count": file_count,
            "primary_language": primary_lang,
            "empty": False,
        }

    @staticmethod
    def build_empty_output() -> AgentBOutput:
        """Return a minimal AgentBOutput when no source files were found."""
        return AgentBOutput(
            actual_capabilities=[],
            total_files_analyzed=0,
            primary_language="unknown",
            findings=[
                CodeFinding(
                    category="no_code",
                    detail="No source code files found in repository.",
                    file_path=".",
                    severity=ScanSeverity.HIGH,
                )
            ],
        )

    @staticmethod
    def validate_output(raw: dict) -> AgentBOutput:
        """Parse and validate raw Task agent JSON into an AgentBOutput.

        Parameters
        ----------
        raw : dict
            The parsed JSON dict returned by the Claude Code Task agent.

        Returns
        -------
        AgentBOutput
            A validated Pydantic model instance.
        """
        return AgentBOutput.model_validate(raw)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_code(root: Path) -> tuple[str, int, str]:
        """Walk *root* and collect source-code text.

        Returns (concatenated_code_text, file_count, primary_language).
        Documentation files are explicitly excluded.
        """
        skip_dirs = {
            ".git", "node_modules", "__pycache__", ".venv", "venv", ".tox",
            "dist", "build", ".eggs", ".mypy_cache", ".ruff_cache",
        }

        parts: list[str] = []
        total_chars = 0
        file_count = 0
        ext_counts: dict[str, int] = {}

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]

            for fname in sorted(filenames):
                fpath = Path(dirpath) / fname
                ext = fpath.suffix.lower()

                # Decide whether this file is code.
                is_code = (
                    ext in _CODE_EXTENSIONS
                    or fname in _SPECIAL_FILENAMES
                )
                if not is_code or ext in _SKIP_EXTENSIONS:
                    continue

                rel = fpath.relative_to(root)

                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    logger.warning("Could not read %s", fpath)
                    continue

                remaining = _MAX_CODE_CHARS - total_chars
                if remaining <= 0:
                    break

                if len(content) > remaining:
                    content = content[:remaining] + "\n# ...[truncated]"

                header = f"--- FILE: {rel} ---"
                parts.append(f"{header}\n{content}")
                total_chars += len(content)
                file_count += 1

                lang_ext = ext or fname.lower()
                ext_counts[lang_ext] = ext_counts.get(lang_ext, 0) + 1

        primary_lang = _ext_to_language(
            max(ext_counts, key=ext_counts.get) if ext_counts else ""
        )
        return "\n\n".join(parts), file_count, primary_lang


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

_EXT_LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".java": "java",
    ".kt": "kotlin",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".fish": "shell",
    ".lua": "lua",
    ".pl": "perl",
    ".pm": "perl",
    "dockerfile": "docker",
    "makefile": "make",
}


def _ext_to_language(ext: str) -> str:
    """Map a file extension (or special filename) to a language name."""
    return _EXT_LANGUAGE_MAP.get(ext.lower(), "unknown")
