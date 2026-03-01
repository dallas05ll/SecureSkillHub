"""
Agent A -- Documentation Reader.

Orchestrated via Claude Code Task agents. No API key is needed.

This agent reads ONLY markdown/documentation files (README.md, SKILL.md) from a
skill repository. Agent A NEVER sees source code. Its job is to extract what the
skill *claims* to do so that downstream agents can compare claims against reality.

Workflow:
    1. Call ``prepare(repo_path)`` to collect documentation files and build the
       prompt payload (system prompt + user message + expected output fields).
    2. Hand the returned dict to a Claude Code Task agent, which performs the
       actual LLM inference.
    3. Parse the Task agent's JSON response into an ``AgentAOutput`` instance.

The ``prepare()`` method returns the prompt data; a Task agent does the LLM work.
The output must conform to ``AgentAOutput`` (defined in src.sanitizer.schemas).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from src.sanitizer.schemas import AgentAOutput

logger = logging.getLogger(__name__)

# Only these file extensions are considered documentation.
_DOC_EXTENSIONS: frozenset[str] = frozenset({".md", ".rst", ".txt"})

# Hard cap on how much documentation text we send to the model to avoid
# runaway token usage (characters, not tokens -- a rough but safe limit).
_MAX_DOC_CHARS = 60_000

SYSTEM_PROMPT = """\
You are Agent A -- a documentation-only reader for a security verification pipeline.

RULES -- you MUST follow all of these:
1. You ONLY analyse the documentation text provided to you.  You have ZERO
   access to source code, and you must NEVER attempt to infer code behaviour.
2. Extract:
   - A concise description of what the skill claims to do.
   - A list of claimed features.
   - A list of claimed dependencies / requirements.
   - A list of claimed permissions or access requirements (env vars, network,
     filesystem, etc.).
   - A documentation-quality score (0-10).
3. If certain information is missing from the docs, leave the corresponding
   field empty rather than guessing.
4. Note any suspicious or vague claims in the "warnings" list (e.g. docs that
   are unusually short, missing purpose statement, or promise functionality
   that sounds dangerous).

Return your analysis as a JSON object matching this schema EXACTLY:
{
  "skill_name": str,
  "claimed_description": str,
  "claimed_features": [str],
  "claimed_dependencies": [str],
  "claimed_permissions": [str],
  "doc_quality_score": int (0-10),
  "has_skill_md": bool,
  "has_readme": bool,
  "warnings": [str]
}
"""

# Expected output field names (mirrors AgentAOutput schema).
OUTPUT_SCHEMA_FIELDS: list[str] = [
    "skill_name",
    "claimed_description",
    "claimed_features",
    "claimed_dependencies",
    "claimed_permissions",
    "doc_quality_score",
    "has_skill_md",
    "has_readme",
    "warnings",
]


class AgentAMdReader:
    """Reads documentation from a skill repo and prepares prompt data for a
    Claude Code Task agent.

    This class is a *data preparation + output validation* layer.  It does NOT
    call any LLM API directly.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def prepare(self, repo_path: str) -> dict:
        """Collect documentation and build the prompt payload for a Task agent.

        Parameters
        ----------
        repo_path : str
            Path to the cloned skill repository on disk.

        Returns
        -------
        dict
            A dictionary with keys:
            - ``system_prompt``   : str -- the system prompt for the Task agent.
            - ``user_message``    : str -- the user message containing docs text.
            - ``output_schema``   : list[str] -- field names expected in the JSON response.
            - ``skill_name``      : str -- extracted skill directory name.
            - ``has_readme``      : bool -- whether a README.md was found.
            - ``has_skill_md``    : bool -- whether a SKILL.md was found.
            - ``empty``           : bool -- True when no docs were found (caller
              should use ``build_empty_output`` instead of invoking a Task agent).

        Raises
        ------
        FileNotFoundError
            If *repo_path* does not exist.
        """
        root = Path(repo_path)
        if not root.is_dir():
            raise FileNotFoundError(f"Repository path does not exist: {repo_path}")

        doc_text, has_readme, has_skill_md = self._collect_docs(root)
        skill_name = root.name

        if not doc_text.strip():
            logger.warning("No documentation found in %s", repo_path)
            return {
                "system_prompt": SYSTEM_PROMPT,
                "user_message": "",
                "output_schema": OUTPUT_SCHEMA_FIELDS,
                "skill_name": skill_name,
                "has_readme": False,
                "has_skill_md": False,
                "empty": True,
            }

        user_message = (
            f"Skill name (from directory): {skill_name}\n\n"
            f"Documentation contents:\n\n{doc_text}"
        )

        return {
            "system_prompt": SYSTEM_PROMPT,
            "user_message": user_message,
            "output_schema": OUTPUT_SCHEMA_FIELDS,
            "skill_name": skill_name,
            "has_readme": has_readme,
            "has_skill_md": has_skill_md,
            "empty": False,
        }

    @staticmethod
    def build_empty_output(skill_name: str) -> AgentAOutput:
        """Return a minimal AgentAOutput when no documentation was found."""
        return AgentAOutput(
            skill_name=skill_name,
            claimed_description="No documentation found.",
            doc_quality_score=0,
            has_readme=False,
            has_skill_md=False,
            warnings=["No documentation files found in repository."],
        )

    @staticmethod
    def validate_output(raw: dict) -> AgentAOutput:
        """Parse and validate raw Task agent JSON into an AgentAOutput.

        Parameters
        ----------
        raw : dict
            The parsed JSON dict returned by the Claude Code Task agent.

        Returns
        -------
        AgentAOutput
            A validated Pydantic model instance.
        """
        return AgentAOutput.model_validate(raw)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_docs(root: Path) -> tuple[str, bool, bool]:
        """Walk *root* and collect documentation text.

        Returns (concatenated_doc_text, has_readme, has_skill_md).
        Only files with extensions in ``_DOC_EXTENSIONS`` are included, and
        source-code directories (node_modules, .git, __pycache__, etc.) are
        always skipped.
        """
        skip_dirs = {
            ".git", "node_modules", "__pycache__", ".venv", "venv", ".tox",
            "dist", "build", ".eggs", ".mypy_cache", ".ruff_cache",
        }

        has_readme = False
        has_skill_md = False
        parts: list[str] = []
        total_chars = 0

        for dirpath, dirnames, filenames in os.walk(root):
            # Prune skipped directories in-place so os.walk won't descend.
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]

            for fname in sorted(filenames):
                ext = Path(fname).suffix.lower()
                if ext not in _DOC_EXTENSIONS:
                    continue

                fpath = Path(dirpath) / fname
                rel = fpath.relative_to(root)

                if fname.lower() == "readme.md":
                    has_readme = True
                if fname.lower() == "skill.md":
                    has_skill_md = True

                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    logger.warning("Could not read %s", fpath)
                    continue

                remaining = _MAX_DOC_CHARS - total_chars
                if remaining <= 0:
                    break

                if len(content) > remaining:
                    content = content[:remaining] + "\n...[truncated]"

                header = f"--- FILE: {rel} ---"
                parts.append(f"{header}\n{content}")
                total_chars += len(content)

        return "\n\n".join(parts), has_readme, has_skill_md
