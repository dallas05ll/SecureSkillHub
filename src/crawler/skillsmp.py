"""
SkillsMP crawler — discovers Claude Code skills sourced from skillsmp.com.

## Why a GitHub-backed approach

skillsmp.com is protected by Cloudflare (hard block — "Attention Required" 403,
requires CAPTCHA). The API at /api/v1/skills/ai-search requires a paid/registered
Bearer API key (SKILL_MAP_API_KEY). HTML scraping and programmatic CF bypass are
both infeasible without credentials.

However, AmazingAng/skilldb (https://github.com/AmazingAng/skilldb) is a public
GitHub repository that archives 180K+ entries from SkillsMP, skills.sh, and
ClawHub as a unified, deduplicated JSON file (skilldb.json). This file is the
cleanest available mirror of SkillsMP data without requiring authentication.

## Data note: Claude Code skills vs MCP servers

SkillsMP hosts *Claude Code skills* — markdown instruction files stored inside
GitHub repos (e.g. `facebook/react/.claude/skills/extract-errors`). These are
*not* MCP server repos. Each skilldb entry has:
  - githubUrl: URL to the skill file within its host repo (e.g.
    https://github.com/facebook/react/tree/main/.claude/skills/extract-errors)
  - owner/repo: the GitHub repo that contains the skill file

We extract the canonical repo URL (https://github.com/{owner}/{repo}) as the
repo_url for dedup purposes. Many skills share the same host repo, so we dedup
at the repo level to avoid creating hundreds of entries for e.g. facebook/react.

## Dedup awareness

Before adding any skill, callers MUST check whether the repo_url already exists
in data/skills/. The CrawlerBatch returned here is deduplicated at the repo level
internally; downstream process_discovered.py handles cross-batch dedup.

## Rate limiting

We fetch a single ~167MB JSON file from GitHub LFS / raw content. There is no
pagination — we stream the file and parse incrementally. We do NOT make per-skill
HTTP requests. Rate: effectively 1 request for the entire crawl.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from src.crawler.base import BaseCrawler
from src.sanitizer.schemas import (
    CrawlerBatch,
    DiscoveredSkill,
    SkillType,
    SourceHub,
    TrustLevel,
)

logger = logging.getLogger(__name__)

# AmazingAng/skilldb — public archive of SkillsMP + skills.sh + ClawHub
# Sorted by installs descending. Updated automatically via GH Actions.
_SKILLDB_DOWNLOAD_URL = (
    "https://media.githubusercontent.com/media/AmazingAng/skilldb/main/skilldb.json"
)

# Alternatively use the raw GitHub API (may have size limits):
_SKILLDB_RAW_URL = (
    "https://raw.githubusercontent.com/AmazingAng/skilldb/main/skilldb.json"
)

# GitHub repo URL pattern
_GITHUB_REPO_RE = re.compile(
    r"https?://github\.com/([^/]+)/([^/\s?#]+).*",
    re.IGNORECASE,
)

# We only want entries that originated from SkillsMP
_SKILLSMP_SOURCE = "skillsmp"

# Max skills to include per crawl run (to avoid processing 161K at once)
# Default: 5000 highest-install entries from SkillsMP
_DEFAULT_LIMIT = 5_000


class SkillsMPCrawler(BaseCrawler):
    """Discovers Claude Code skills sourced from skillsmp.com via the
    AmazingAng/skilldb public GitHub archive.

    Since skillsmp.com is protected by Cloudflare and requires an authenticated
    API key, this crawler reads from the public skilldb.json mirror instead.
    This gives us access to 161K+ SkillsMP entries without authentication.

    Each unique GitHub *repo* that hosts a SkillsMP skill becomes one
    DiscoveredSkill entry. Skills within the same repo are merged (we take the
    highest-install skill's metadata as the representative entry).

    Dedup note: repo_url deduplication happens at two levels:
      1. Within this crawler: we keep only the first (highest-install) skill
         per repo_url before emitting the batch.
      2. In downstream process_discovered.py: cross-batch dedup against the
         existing data/skills/ collection.
    """

    source_hub = SourceHub.SKILLSMP

    def __init__(
        self,
        *,
        limit: int = _DEFAULT_LIMIT,
        skillsmp_only: bool = True,
        **kwargs,
    ) -> None:
        # No per-request rate limiting needed — single bulk file download
        super().__init__(requests_per_second=0.5, **kwargs)
        self._limit = limit
        self._skillsmp_only = skillsmp_only

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scrape(self) -> CrawlerBatch:
        """Download skilldb.json and extract SkillsMP-sourced skill repos."""
        errors: list[str] = []

        self._logger.info(
            "Downloading skilldb.json from AmazingAng/skilldb (may be large)..."
        )

        raw_json = self._download_skilldb(errors)
        if raw_json is None:
            return CrawlerBatch(
                source_hub=SourceHub.SKILLSMP,
                crawled_at=datetime.now(timezone.utc).isoformat(),
                skills=[],
                total_found=0,
                errors=errors[:50],
            )

        self._logger.info("Parsing skilldb entries...")
        skills = list(self._extract_skills(raw_json, errors))

        self._logger.info(
            "SkillsMP crawl complete: %d unique repos discovered (limit=%d)",
            len(skills),
            self._limit,
        )

        return CrawlerBatch(
            source_hub=SourceHub.SKILLSMP,
            crawled_at=datetime.now(timezone.utc).isoformat(),
            skills=skills,
            total_found=len(skills),
            errors=errors[:50],
        )

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def _download_skilldb(self, errors: list[str]) -> list | None:
        """Download skilldb.json using subprocess curl (handles large files
        and GitHub LFS redirects without loading all into memory at parse time).

        Returns the parsed JSON list, or None on failure.
        """
        with tempfile.TemporaryDirectory(prefix="skillsmp_crawl_") as tmpdir:
            dest = Path(tmpdir) / "skilldb.json"

            # Use curl to download — handles LFS redirect, progress, resume
            cmd = [
                "curl",
                "--silent",
                "--location",  # follow redirects (LFS)
                "--fail",
                "--max-time", "300",  # 5 min timeout for 167MB
                "--output", str(dest),
                _SKILLDB_DOWNLOAD_URL,
            ]

            self._logger.info("Running: %s", " ".join(cmd[:4]) + " ...")
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=360,
                )
                if result.returncode != 0:
                    err = result.stderr.decode("utf-8", errors="replace")[:500]
                    errors.append(f"curl failed (rc={result.returncode}): {err}")
                    self._logger.error("curl failed: %s", err)
                    return None
            except subprocess.TimeoutExpired:
                errors.append("curl timed out after 360s")
                self._logger.error("curl timed out")
                return None
            except Exception as exc:
                errors.append(f"curl exception: {exc}")
                self._logger.error("curl exception: %s", exc)
                return None

            file_size = dest.stat().st_size
            self._logger.info(
                "Downloaded skilldb.json: %.1f MB", file_size / 1_048_576
            )

            try:
                with dest.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, list):
                    errors.append("skilldb.json is not a JSON array")
                    return None
                self._logger.info("Parsed %d total entries", len(data))
                return data
            except json.JSONDecodeError as exc:
                errors.append(f"JSON parse error: {exc}")
                self._logger.error("JSON parse failed: %s", exc)
                return None

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    def _extract_skills(
        self,
        entries: list,
        errors: list[str],
    ) -> Iterator[DiscoveredSkill]:
        """Walk skilldb entries (sorted by installs desc) and yield one
        DiscoveredSkill per unique GitHub repo, up to self._limit.

        Dedup: first entry wins (highest installs). Subsequent entries for
        the same repo are silently skipped.
        """
        seen_repos: set[str] = set()
        yielded = 0
        skipped_no_repo = 0
        skipped_non_skillsmp = 0

        for entry in entries:
            if yielded >= self._limit:
                break

            try:
                skill = self._parse_entry(entry)
            except Exception as exc:
                errors.append(f"Entry parse error: {exc}")
                continue

            if skill is None:
                skipped_no_repo += 1
                continue

            # Filter to SkillsMP-only entries if requested
            if self._skillsmp_only:
                sources = entry.get("sources", [])
                if _SKILLSMP_SOURCE not in sources:
                    skipped_non_skillsmp += 1
                    continue

            repo_url = skill.repo_url
            if repo_url in seen_repos:
                continue  # dedup within this batch
            seen_repos.add(repo_url)

            yield skill
            yielded += 1

        self._logger.info(
            "Extraction done: %d yielded, %d skipped (no repo), %d skipped (non-skillsmp)",
            yielded,
            skipped_no_repo,
            skipped_non_skillsmp,
        )

    def _parse_entry(self, entry: dict) -> DiscoveredSkill | None:
        """Parse a single skilldb entry into a DiscoveredSkill.

        Returns None if we can't extract a valid GitHub repo URL.
        """
        owner = (entry.get("owner") or "").strip()
        repo = (entry.get("repo") or "").strip()

        if not owner or not repo:
            return None

        # Canonical repo URL (repo-level, not file-level)
        repo_url = f"https://github.com/{owner}/{repo}"

        name = (entry.get("name") or repo).strip()
        description = (entry.get("description") or "").strip()

        # installs are NOT GitHub stars — store as 0 to avoid inflation.
        # Real stars will be enriched later via enrich_stars.py.
        # Install count is preserved in source_tags for reference.
        installs = entry.get("installs") or 0
        install_count = int(installs) if isinstance(installs, (int, float)) else 0

        # Tags: derive from skillPath patterns and description keywords
        tags = self._derive_tags(entry)
        if install_count > 0:
            tags.append(f"installs:{install_count}")

        return DiscoveredSkill(
            name=self._truncate(name, 200),
            repo_url=repo_url,
            source_hub=SourceHub.SKILLSMP,
            skill_type=SkillType.AGENT_SKILL,
            trust_level=TrustLevel.LOW,
            description=self._truncate(description, 500),
            stars=0,  # will be enriched with real GitHub stars later
            source_tags=tags,
            owner=owner,
        )

    def _derive_tags(self, entry: dict) -> list[str]:
        """Derive SecureSkillHub-style tags from a skilldb entry."""
        tags: list[str] = []

        # skill_path hints (e.g. ".claude/skills/react-component" → frontend)
        skill_path = (entry.get("skillPath") or "").lower()
        description = (entry.get("description") or "").lower()
        name = (entry.get("name") or "").lower()
        combined = f"{skill_path} {description} {name}"

        # Claude Code skills → tag as agent/LLM tooling
        tags.append("agent-skills")

        # Rough category heuristics
        if any(w in combined for w in ("react", "vue", "svelte", "angular", "frontend", "ui", "css")):
            tags.append("dev-web-frontend")
        elif any(w in combined for w in ("node", "express", "fastapi", "django", "backend", "api", "server")):
            tags.append("dev-web-backend")
        elif any(w in combined for w in ("docker", "kubernetes", "k8s", "ci", "deploy", "devops")):
            tags.append("dev-devops")
        elif any(w in combined for w in ("sql", "postgres", "mysql", "database", "db")):
            tags.append("data-db")
        elif any(w in combined for w in ("llm", "ai", "gpt", "claude", "openai", "machine learning")):
            tags.append("data-ai")
        elif any(w in combined for w in ("security", "auth", "oauth", "jwt", "encrypt")):
            tags.append("security")
        elif any(w in combined for w in ("test", "spec", "jest", "pytest", "unittest")):
            tags.append("dev-testing")

        return tags[:5]  # cap tag count
