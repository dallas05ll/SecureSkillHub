"""
StaticScanner — deterministic static analysis engine (Agent C*).

Runs semgrep rules and regex patterns against a target directory,
producing a ScannerOutput schema. This is NOT an LLM — it cannot be
prompt-injected. It is purely deterministic.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.sanitizer.schemas import ScanFinding, ScannerOutput, ScanSeverity

from . import regex_patterns
from .regex_patterns import ALL_PATTERN_GROUPS, OBFUSCATION_HIGH_RISK_NAMES, PatternEntry

logger = logging.getLogger(__name__)

# File extensions we scan with regex (keep it focused)
_SCANNABLE_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".pyw",
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".json",
    ".yaml", ".yml",
    ".toml",
    ".cfg", ".ini",
    ".sh", ".bash", ".zsh",
    ".md", ".txt", ".rst",
})

# Maximum file size we will read (2 MB) to avoid memory issues
_MAX_FILE_BYTES: int = 2 * 1024 * 1024

# Mapping from pattern group names to ScannerOutput count field names
_CATEGORY_TO_COUNT_FIELD: dict[str, str] = {
    "dangerous_calls": "dangerous_calls_count",
    "network_ops": "network_ops_count",
    "file_ops": "file_ops_count",
    "env_access": "env_access_count",
    "obfuscation": "obfuscation_count",
    "injection_patterns": "injection_patterns_count",
    # suspicious_urls are reported as findings but have no dedicated count field
}

# Mapping from semgrep rule-id prefixes to our internal categories
_SEMGREP_RULE_CATEGORY_MAP: dict[str, str] = {
    "dangerous": "dangerous_calls",
    "network": "network_ops",
    "file": "file_ops",
    "env": "env_access",
    "obfuscation": "obfuscation",
}

# Semgrep severity string to ScanSeverity enum
_SEMGREP_SEVERITY_MAP: dict[str, ScanSeverity] = {
    "INFO": ScanSeverity.INFO,
    "WARNING": ScanSeverity.MEDIUM,
    "ERROR": ScanSeverity.HIGH,
}


class StaticScanner:
    """
    Deterministic static analyzer that combines semgrep rules and regex
    pattern matching to produce structured findings.

    Usage:
        scanner = StaticScanner("/path/to/skill/repo")
        output: ScannerOutput = scanner.scan()
    """

    def __init__(self, target_dir: str) -> None:
        self._target_dir = Path(target_dir).resolve()
        if not self._target_dir.is_dir():
            raise ValueError(f"Target directory does not exist: {self._target_dir}")

        self._rules_dir = Path(__file__).parent / "semgrep_rules"
        self._semgrep_available: Optional[bool] = None
        self._semgrep_cmd = self._resolve_semgrep_cmd()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(self) -> ScannerOutput:
        """Run all analyses and return a ScannerOutput."""
        scan_id = f"scan_{uuid.uuid4().hex[:12]}"
        scanned_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        findings: list[ScanFinding] = []
        files_scanned: int = 0

        # 1. Semgrep analysis (graceful fallback if unavailable)
        semgrep_findings = self._run_semgrep()
        findings.extend(semgrep_findings)

        # 2. Regex analysis (always runs)
        regex_findings, files_scanned = self._run_regex_scan()
        findings.extend(regex_findings)

        # 3. Deduplicate findings that overlap between semgrep and regex
        findings = self._deduplicate(findings)

        # 4. Count by category
        counts = self._count_by_category(findings)

        # 5. Count high-risk obfuscation (only patterns that signal real obfuscation)
        obfuscation_high_risk = sum(
            1 for f in findings
            if f.category == "obfuscation"
            and f.rule_id.startswith("regex_")
            and f.rule_id[len("regex_"):] in OBFUSCATION_HIGH_RISK_NAMES
        )

        return ScannerOutput(
            scan_id=scan_id,
            scanned_at=scanned_at,
            total_files_scanned=files_scanned,
            findings=findings,
            dangerous_calls_count=counts.get("dangerous_calls", 0),
            network_ops_count=counts.get("network_ops", 0),
            file_ops_count=counts.get("file_ops", 0),
            env_access_count=counts.get("env_access", 0),
            obfuscation_count=counts.get("obfuscation", 0),
            obfuscation_high_risk_count=obfuscation_high_risk,
            injection_patterns_count=counts.get("injection_patterns", 0),
        )

    # ------------------------------------------------------------------
    # Semgrep runner
    # ------------------------------------------------------------------

    def _check_semgrep(self) -> bool:
        """Check if semgrep is installed and accessible."""
        if self._semgrep_available is not None:
            return self._semgrep_available

        try:
            result = subprocess.run(
                self._semgrep_cmd + ["--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self._semgrep_available = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            self._semgrep_available = False

        if not self._semgrep_available:
            logger.warning(
                "semgrep is not available — falling back to regex-only scanning"
            )
        return self._semgrep_available

    @staticmethod
    def _resolve_semgrep_cmd() -> list[str]:
        """Prefer semgrep on PATH; fall back to the current Python env."""
        semgrep_bin = shutil.which("semgrep")
        if semgrep_bin:
            return [semgrep_bin]

        venv_semgrep = Path(sys.executable).resolve().with_name("semgrep")
        if venv_semgrep.is_file():
            return [str(venv_semgrep)]

        return [sys.executable, "-m", "semgrep.cli"]

    def _run_semgrep(self) -> list[ScanFinding]:
        """Run semgrep with all rule files against the target directory."""
        if not self._check_semgrep():
            return []

        if not self._rules_dir.is_dir():
            logger.warning("Semgrep rules directory not found: %s", self._rules_dir)
            return []

        rule_files = list(self._rules_dir.glob("*.yaml"))
        if not rule_files:
            logger.warning("No semgrep rule files found in %s", self._rules_dir)
            return []

        findings: list[ScanFinding] = []

        for rule_file in rule_files:
            try:
                result = subprocess.run(
                    self._semgrep_cmd + [
                        "--config", str(rule_file),
                        "--json",
                        "--no-git-ignore",
                        "--quiet",
                        str(self._target_dir),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )

                if result.stdout.strip():
                    parsed = json.loads(result.stdout)
                    for item in parsed.get("results", []):
                        finding = self._semgrep_result_to_finding(item)
                        if finding is not None:
                            findings.append(finding)

            except subprocess.TimeoutExpired:
                logger.error("Semgrep timed out on rule file: %s", rule_file.name)
            except json.JSONDecodeError:
                logger.error(
                    "Failed to parse semgrep JSON output for: %s", rule_file.name
                )
            except OSError as exc:
                logger.error("Semgrep execution error for %s: %s", rule_file.name, exc)

        return findings

    def _semgrep_result_to_finding(self, result: dict) -> Optional[ScanFinding]:
        """Convert a single semgrep JSON result to a ScanFinding."""
        try:
            check_id: str = result.get("check_id", "unknown")
            message: str = result.get("extra", {}).get("message", "").strip()
            severity_raw: str = result.get("extra", {}).get("severity", "WARNING")
            file_path: str = result.get("path", "")
            line_number: int = result.get("start", {}).get("line", 0)
            matched: str = result.get("extra", {}).get("lines", "").strip()

            # Derive category from rule-id prefix
            category = "unknown"
            rule_lower = check_id.lower()
            for prefix, cat in _SEMGREP_RULE_CATEGORY_MAP.items():
                if rule_lower.startswith(prefix):
                    category = cat
                    break

            severity = _SEMGREP_SEVERITY_MAP.get(
                severity_raw.upper(), ScanSeverity.MEDIUM
            )

            # Make file_path relative to target_dir for readability
            try:
                file_path = str(
                    Path(file_path).relative_to(self._target_dir)
                )
            except ValueError:
                pass

            return ScanFinding(
                rule_id=check_id[:100],
                category=category[:100],
                severity=severity,
                message=message[:500],
                file_path=file_path[:300],
                line_number=line_number if line_number > 0 else None,
                matched_pattern=matched[:200],
            )
        except Exception:
            logger.debug("Failed to parse semgrep result: %s", result, exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Regex scanner
    # ------------------------------------------------------------------

    def _run_regex_scan(self) -> tuple[list[ScanFinding], int]:
        """Scan all eligible files with compiled regex patterns."""
        findings: list[ScanFinding] = []
        files_scanned: int = 0

        for file_path in self._iter_files():
            files_scanned += 1
            content = self._read_file_safe(file_path)
            if content is None:
                continue

            rel_path = self._relative_path(file_path)

            for category, patterns in ALL_PATTERN_GROUPS.items():
                # Skip obfuscation checks on JSON/data files — they inherently
                # contain base64, unicode escapes, etc. that aren't obfuscation.
                if category == "obfuscation" and file_path.suffix.lower() in (".json",):
                    continue
                for entry in patterns:
                    for match in entry.pattern.finditer(content):
                        line_number = content[:match.start()].count("\n") + 1
                        matched_text = match.group(0)

                        severity = self._severity_for_category(category)

                        findings.append(
                            ScanFinding(
                                rule_id=f"regex_{entry.name}"[:100],
                                category=category[:100],
                                severity=severity,
                                message=f"Regex match: {entry.name}"[:500],
                                file_path=str(rel_path)[:300],
                                line_number=line_number,
                                matched_pattern=matched_text[:200],
                            )
                        )

        return findings, files_scanned

    def _iter_files(self):
        """Yield all scannable file paths under the target directory."""
        for root, dirs, files in os.walk(self._target_dir):
            # Skip hidden directories and common non-code directories
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".")
                and d not in {"node_modules", "__pycache__", "venv", ".venv", "dist", "build"}
            ]
            for filename in files:
                fp = Path(root) / filename
                if fp.suffix.lower() in _SCANNABLE_EXTENSIONS:
                    yield fp

    def _read_file_safe(self, file_path: Path) -> Optional[str]:
        """Read a file's contents, returning None on failure or if too large."""
        try:
            size = file_path.stat().st_size
            if size > _MAX_FILE_BYTES:
                logger.debug("Skipping large file (%d bytes): %s", size, file_path)
                return None
            return file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.debug("Failed to read %s: %s", file_path, exc)
            return None

    def _relative_path(self, file_path: Path) -> Path:
        """Return file_path relative to the target directory."""
        try:
            return file_path.relative_to(self._target_dir)
        except ValueError:
            return file_path

    @staticmethod
    def _severity_for_category(category: str) -> ScanSeverity:
        """Map pattern category to a default severity level."""
        severity_map: dict[str, ScanSeverity] = {
            "dangerous_calls": ScanSeverity.HIGH,
            "network_ops": ScanSeverity.MEDIUM,
            "file_ops": ScanSeverity.LOW,
            "env_access": ScanSeverity.MEDIUM,
            "obfuscation": ScanSeverity.HIGH,
            "injection_patterns": ScanSeverity.CRITICAL,
            "suspicious_urls": ScanSeverity.HIGH,
        }
        return severity_map.get(category, ScanSeverity.INFO)

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    @staticmethod
    def _deduplicate(findings: list[ScanFinding]) -> list[ScanFinding]:
        """
        Remove duplicate findings that match on the same file, line, and
        category. Prefer the finding with higher severity.
        """
        seen: dict[tuple[str, Optional[int], str], ScanFinding] = {}
        severity_order = {
            ScanSeverity.INFO: 0,
            ScanSeverity.LOW: 1,
            ScanSeverity.MEDIUM: 2,
            ScanSeverity.HIGH: 3,
            ScanSeverity.CRITICAL: 4,
        }

        for f in findings:
            key = (f.file_path, f.line_number, f.category)
            existing = seen.get(key)
            if existing is None or severity_order.get(
                f.severity, 0
            ) > severity_order.get(existing.severity, 0):
                seen[key] = f

        return list(seen.values())

    @staticmethod
    def _count_by_category(findings: list[ScanFinding]) -> dict[str, int]:
        """Count findings per category."""
        counts: dict[str, int] = {}
        for f in findings:
            counts[f.category] = counts.get(f.category, 0) + 1
        return counts
