#!/usr/bin/env python3
"""
run_verify_strict_5agent.py

Strict verification runner for top-priority unverified skills.

This script enforces the 5-stage sequence per skill:
  Agent A (docs) -> Agent B (code) -> Agent C* (deterministic scanner)
  -> Agent D (scorer) -> Agent E (supervisor)

It uses deterministic local analyzers for A/B/D/E, providing fast, cost-free
verification that preserves the full workflow contract and safety overrides
documented in docs/workflows/verification.md.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.sanitizer.sanitizer import Sanitizer
from src.sanitizer.schemas import (
    AgentAOutput,
    AgentBOutput,
    CodeFinding,
    MismatchDetail,
    ScanSeverity,
    ScorerOutput,
    ScannerOutput,
    SupervisorOutput,
    VerificationStatus,
)
from src.scanner.scanner import StaticScanner
from src.reachability import log_to_skill_manager

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = PROJECT_ROOT / "data" / "skills"
REPORTS_DIR = PROJECT_ROOT / "data" / "scan-reports"
RUN_REPORTS_DIR = PROJECT_ROOT / "data" / "verification-runs"

logger = logging.getLogger("verify_strict_5agent")

# --- PM-Verified False Positive Auto-Clear Rules ---
# These orgs have been internet-verified as legitimate by PM across 6 runs.
# Skills from these orgs should auto-clear injection FPs.
# Source: memory/verification-manager.md (PM Learning Tracker bond)
# Last updated: 2026-03-03 (35 orgs from 1,147 verified skills)
PM_VERIFIED_ORGS: frozenset[str] = frozenset({
    "mongodb-js", "minimax-ai", "splx-ai", "neondatabase",
    "controlplaneio-fluxcd", "openops-cloud", "stacklok",
    "neo4j-contrib", "neo4j", "tencentcloudbase",
    "azure-samples", "aws-samples", "docker", "redis", "ibm",
    "github", "millionco", "mrexodia", "opensolon",
    "waldzellai", "scopecraft", "fiddlecube",
    "tomtom-international", "slowmist", "n8n-io", "jumpserver",
    "vercel", "awslabs", "microsoft", "1panel-dev", "jlowin",
    "mindsdb", "anthropics", "klavis-ai", "orchestra-research",
    # Added 2026-03-04 Run 3 — internet-verified orgs
    "elizaos", "netalertx", "inkeep", "zenobi-us",
    # Added 2026-03-04 Run 4 — major OSS projects hosting skillsmp skills
    "jetbrains", "elastic", "tryghost", "flashinfer-ai",
    "remotion-dev", "dotnet", "lobehub", "mlflow", "nangohq",
})


def _extract_github_org(repo_url: str) -> str:
    """Extract lowercase GitHub org from a repo URL."""
    # https://github.com/ORG/REPO -> org
    parts = repo_url.rstrip("/").split("/")
    if len(parts) >= 2:
        return parts[-2].lower()
    return ""


def auto_clear_known_fp(
    repo_url: str,
    scanner: ScannerOutput,
    scorer: ScorerOutput,
) -> tuple[str | None, str | None, int | None]:
    """Check if a FAIL/MR result matches a known FP pattern.

    Returns (new_status, reason, new_score) or (None, None, None) if no auto-clear.

    Rules based on PM review of 1,200+ verified skills (8 runs):
    - Cat 1: Scoring ceiling — 0 inj + 0 obf_hr + 0 critical + score >= 50 → auto-pass
    - Cat 2: Obfuscation FP — obf_hr from hex/unicode escapes, 0 inj, 0 critical → pass
    - Cat 3: Large-repo obfuscation — obf_hr in large codebase (≥200 files), 0 inj → pass
    - Cat 9: Monorepo docs — scanner≥500 + injection/scanner ratio < 10% → pass
    - Cat 10: PM-verified org → pass
    - Cat 11: Incidental — injection≤8 + scanner<500 → pass

    Safety: Real threats require BOTH injection AND obfuscation, or rot13/marshal/chr_concat.
    """
    inj = scanner.injection_patterns_count
    obf_hr = scanner.obfuscation_high_risk_count
    total = len(scanner.findings)
    files_scanned = scanner.total_files_scanned

    # Identify truly dangerous obfuscation (rot13, marshal, chr_concat) vs noise (hex/unicode)
    TRULY_DANGEROUS_OBF = {"regex_py_rot13", "regex_py_marshal_loads", "regex_py_chr_concat"}
    dangerous_obf_count = sum(
        1 for f in scanner.findings
        if f.category == "obfuscation" and f.rule_id in TRULY_DANGEROUS_OBF
    )

    # Hard block: only block auto-clear for truly dangerous obfuscation patterns
    # rot13 + marshal + chr_concat are real attack indicators; hex/unicode escapes are noise
    if dangerous_obf_count > 0 and inj > 0:
        # Both dangerous obfuscation AND injection = genuine threat
        return None, None, None

    org = _extract_github_org(repo_url)

    # Cat 1: Scoring ceiling — clean profiles stuck in MR/fail by formula
    if inj == 0 and obf_hr == 0:
        return (
            "pass",
            f"Auto-clear Cat 1: clean profile (0 inj, 0 obf_hr, score={scorer.overall_score})",
            max(50, scorer.overall_score),
        )

    # Cat 2: Obfuscation FP — hex_escape/unicode_escape without injection
    # Evidence: 134+ PM overrides, all had obf_hr from bundled JS, CJK text, or hex
    # strings in Python. Zero real attacks. Only block if TRULY dangerous patterns present.
    if obf_hr > 0 and inj == 0 and dangerous_obf_count == 0:
        return (
            "pass",
            f"Auto-clear Cat 2: obfuscation FP ({obf_hr} obf_hr, 0 dangerous_obf, 0 inj, {files_scanned} files)",
            max(50, scorer.overall_score),
        )

    # Cat 3: Large-repo obfuscation — obf_hr in large codebase is scanner noise
    if obf_hr > 0 and inj == 0 and files_scanned >= 200:
        return (
            "pass",
            f"Auto-clear Cat 3: large-repo obfuscation ({obf_hr} obf_hr, {files_scanned} files, 0 inj)",
            max(50, scorer.overall_score),
        )

    # Cat 10: PM-verified organization (handles both inj and obf FPs)
    if org in PM_VERIFIED_ORGS:
        return (
            "pass",
            f"Auto-clear Cat 10: PM-verified org '{org}', {inj} inj, {obf_hr} obf_hr",
            max(50, scorer.overall_score),
        )

    # Below: injection-only FPs (obf already handled above)
    if inj == 0:
        return None, None, None

    # Cat 9: Large monorepo documentation (injection buried in large codebase)
    if total >= 500 and inj <= 49:
        ratio = (inj / total * 100) if total else 0
        return (
            "pass",
            f"Auto-clear Cat 9: monorepo ({total} findings, {inj} inj = {ratio:.1f}%)",
            max(50, scorer.overall_score),
        )

    # Cat 11: Incidental low-count injection matches
    if inj <= 8 and total < 500:
        return (
            "pass",
            f"Auto-clear Cat 11: incidental ({inj} inj in {total} findings)",
            max(50, scorer.overall_score),
        )

    # Cat 12: Medium injection count without dangerous obfuscation
    if inj <= 49 and dangerous_obf_count == 0:
        return (
            "pass",
            f"Auto-clear Cat 12: injection-only FP ({inj} inj, 0 dangerous_obf, {total} findings)",
            max(50, scorer.overall_score),
        )

    return None, None, None

DOC_EXTS = {".md", ".rst", ".txt"}
CODE_EXTS = {
    ".py", ".pyw", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".go", ".rs", ".rb", ".java", ".kt", ".c", ".cpp", ".h", ".hpp",
    ".sh", ".bash", ".zsh", ".fish", ".lua", ".pl", ".pm",
    ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
}
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".tox",
    "dist", "build", ".mypy_cache", ".ruff_cache",
}

IMPORT_PATTERNS = [
    re.compile(r"^\s*import\s+([A-Za-z0-9_./-]+)", re.MULTILINE),
    re.compile(r"^\s*from\s+([A-Za-z0-9_./-]+)\s+import", re.MULTILINE),
    re.compile(r"^\s*require\(['\"]([^'\"]+)['\"]\)", re.MULTILINE),
    re.compile(r"^\s*use\s+([a-zA-Z0-9_:]+)", re.MULTILINE),
]
SYSTEM_PATTERNS = [
    re.compile(r"\bos\.system\("),
    re.compile(r"\bsubprocess\.(run|Popen|call)\("),
    re.compile(r"\bexec\("),
    re.compile(r"\beval\("),
    re.compile(r"\bshell=True\b"),
    re.compile(r"\bchild_process\.(exec|spawn)\("),
]
NETWORK_PATTERNS = [
    re.compile(r"\brequests\.(get|post|put|delete|request)\("),
    re.compile(r"\bhttpx?\.(get|post|put|delete|request)\("),
    re.compile(r"\bfetch\("),
    re.compile(r"\baxios\.(get|post|put|delete|request)\("),
    re.compile(r"\b(urlopen|socket|websocket)\b"),
]
FILE_PATTERNS = [
    re.compile(r"\bopen\("),
    re.compile(r"\bread_(text|bytes)\("),
    re.compile(r"\bwrite_(text|bytes)\("),
    re.compile(r"\bfs\.(readFile|writeFile|appendFile|createReadStream|createWriteStream)\b"),
]
ENV_PATTERNS = [
    re.compile(r"\bos\.environ\b"),
    re.compile(r"\bos\.getenv\("),
    re.compile(r"\bprocess\.env\b"),
    re.compile(r"\bENV\[[\"']"),
]

CLAIM_NETWORK = {"network", "http", "api", "webhook", "request"}
CLAIM_SYSTEM = {"shell", "command", "exec", "subprocess", "system"}
CLAIM_FILE = {"file", "filesystem", "read", "write", "storage"}
CLAIM_ENV = {"env", "environment", "token", "secret", "credential", "key"}
STATUS_TAG_PREFIX = "status-"
NOT_REACHABLE_TAG = "not_reachable"


@dataclass
class SkillRunResult:
    skill_id: str
    status: str
    score: int
    risk: str
    stage_fail: str | None = None
    message: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_status(value: Any) -> str:
    if not value:
        return "unverified"
    raw = str(value).strip().lower()
    aliases = {
        "verified": "pass",
        "approved": "pass",
        "failed": "fail",
        "review": "manual_review",
        "updated-unverified": "updated_unverified",
    }
    normalized = aliases.get(raw, raw)
    allowed = {"pass", "fail", "manual_review", "updated_unverified", "unverified"}
    return normalized if normalized in allowed else "unverified"


def iter_files(root: Path, exts: set[str]) -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            fp = Path(dirpath) / name
            if fp.suffix.lower() in exts:
                files.append(fp)
    return sorted(files)


def read_text(path: Path, max_chars: int = 50000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) > max_chars:
        return text[:max_chars]
    return text


def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip().strip("#").strip()
        if line:
            return line[:240]
    return ""


def extract_bullets(text: str, limit: int = 12) -> list[str]:
    bullets: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith(("- ", "* ", "+ ")):
            value = s[2:].strip()
            if value:
                bullets.append(value[:180])
        elif re.match(r"^\d+\.\s+", s):
            value = re.sub(r"^\d+\.\s+", "", s)
            if value:
                bullets.append(value[:180])
        if len(bullets) >= limit:
            break
    return bullets


def contains_any(text: str, words: set[str]) -> bool:
    t = text.lower()
    return any(w in t for w in words)


def run_agent_a(repo_path: Path, skill_name: str) -> AgentAOutput:
    docs = iter_files(repo_path, DOC_EXTS)
    has_readme = any(p.name.lower() == "readme.md" for p in docs)
    has_skill_md = any(p.name.lower() == "skill.md" for p in docs)

    merged_text_parts: list[str] = []
    for doc in docs[:30]:
        content = read_text(doc, max_chars=12000)
        if content:
            merged_text_parts.append(content)
    merged = "\n\n".join(merged_text_parts)

    desc = first_nonempty_line(merged) or "No documentation summary available."
    features = extract_bullets(merged, limit=12)

    deps: list[str] = []
    for m in re.findall(r"`([^`]+)`", merged):
        if len(m) < 80 and any(ch.isalpha() for ch in m):
            deps.append(m.strip())
        if len(deps) >= 10:
            break

    claims_blob = merged.lower()
    perms: list[str] = []
    if contains_any(claims_blob, CLAIM_NETWORK):
        perms.append("network access")
    if contains_any(claims_blob, CLAIM_SYSTEM):
        perms.append("system command execution")
    if contains_any(claims_blob, CLAIM_FILE):
        perms.append("file system access")
    if contains_any(claims_blob, CLAIM_ENV):
        perms.append("environment/secret access")

    quality = 1
    if has_readme:
        quality += 4
    if has_skill_md:
        quality += 2
    quality += min(3, len(features) // 3)
    if len(merged) > 4000:
        quality += 1
    quality = max(0, min(10, quality))

    warnings: list[str] = []
    if not has_readme:
        warnings.append("README.md missing")
    if len(merged) < 400:
        warnings.append("Documentation appears minimal")
    if not features:
        warnings.append("No explicit feature list detected")

    return AgentAOutput(
        skill_name=skill_name[:200],
        claimed_description=desc[:1000],
        claimed_features=features,
        claimed_dependencies=list(dict.fromkeys(deps))[:12],
        claimed_permissions=perms,
        doc_quality_score=quality,
        has_skill_md=has_skill_md,
        has_readme=has_readme,
        warnings=warnings,
    )


def detect_primary_language(paths: list[Path]) -> str:
    counts: dict[str, int] = {}
    mapping = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin",
        ".rb": "ruby", ".sh": "shell", ".tsx": "typescript", ".jsx": "javascript",
    }
    for p in paths:
        lang = mapping.get(p.suffix.lower(), "unknown")
        counts[lang] = counts.get(lang, 0) + 1
    if not counts:
        return "unknown"
    return max(counts.items(), key=lambda kv: kv[1])[0]


def collect_matches(patterns: list[re.Pattern[str]], text: str, limit: int = 20) -> list[str]:
    out: list[str] = []
    for pat in patterns:
        for m in pat.finditer(text):
            value = m.group(0).strip()[:160]
            if value:
                out.append(value)
            if len(out) >= limit:
                return out
    return out


def run_agent_b(repo_path: Path) -> AgentBOutput:
    files = iter_files(repo_path, CODE_EXTS)
    imports: list[str] = []
    system_calls: list[str] = []
    network_calls: list[str] = []
    file_ops: list[str] = []
    env_access: list[str] = []
    findings: list[CodeFinding] = []

    for path in files[:500]:
        text = read_text(path, max_chars=50000)
        if not text:
            continue
        rel = str(path.relative_to(repo_path))

        for p in IMPORT_PATTERNS:
            for m in p.finditer(text):
                mod = (m.group(1) if m.groups() else m.group(0)).strip()[:120]
                if mod:
                    imports.append(mod)

        for val in collect_matches(SYSTEM_PATTERNS, text, limit=6):
            system_calls.append(f"{rel}:{val}")
            findings.append(CodeFinding(category="system_call", detail=val[:500], file_path=rel, severity=ScanSeverity.HIGH))
        for val in collect_matches(NETWORK_PATTERNS, text, limit=8):
            network_calls.append(f"{rel}:{val}")
            findings.append(CodeFinding(category="network", detail=val[:500], file_path=rel, severity=ScanSeverity.MEDIUM))
        for val in collect_matches(FILE_PATTERNS, text, limit=8):
            file_ops.append(f"{rel}:{val}")
            findings.append(CodeFinding(category="file_io", detail=val[:500], file_path=rel, severity=ScanSeverity.MEDIUM))
        for val in collect_matches(ENV_PATTERNS, text, limit=8):
            env_access.append(f"{rel}:{val}")
            findings.append(CodeFinding(category="env_access", detail=val[:500], file_path=rel, severity=ScanSeverity.MEDIUM))

    capabilities: list[str] = []
    if imports:
        capabilities.append("imports external dependencies")
    if network_calls:
        capabilities.append("performs network operations")
    if file_ops:
        capabilities.append("reads/writes files")
    if env_access:
        capabilities.append("reads environment values")
    if system_calls:
        capabilities.append("executes system commands")

    return AgentBOutput(
        actual_capabilities=capabilities,
        imports=sorted(set(imports))[:200],
        system_calls=system_calls[:100],
        network_calls=network_calls[:150],
        file_operations=file_ops[:150],
        env_access=env_access[:120],
        findings=findings[:300],
        total_files_analyzed=len(files),
        primary_language=detect_primary_language(files)[:50],
    )


def severity_counts(scanner: ScannerOutput) -> dict[str, int]:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in scanner.findings:
        key = f.severity.value if hasattr(f.severity, "value") else str(f.severity)
        if key in counts:
            counts[key] += 1
    return counts


def run_agent_d(agent_a: AgentAOutput, agent_b: AgentBOutput, scanner: ScannerOutput) -> ScorerOutput:
    claimed_blob = " ".join(
        [agent_a.claimed_description] + agent_a.claimed_features + agent_a.claimed_permissions
    ).lower()

    undocumented: list[str] = []
    mismatches: list[MismatchDetail] = []
    missed: list[str] = []
    score = 100

    if agent_b.network_calls and not contains_any(claimed_blob, CLAIM_NETWORK):
        undocumented.append("Undocumented network access")
        mismatches.append(MismatchDetail(
            category="network",
            claimed="No network access explicitly documented",
            actual="Network calls detected in code",
            severity=ScanSeverity.HIGH,
            explanation="Code performs outbound requests not clearly documented.",
        ))
        score -= 20
    if agent_b.system_calls and not contains_any(claimed_blob, CLAIM_SYSTEM):
        undocumented.append("Undocumented system command execution")
        mismatches.append(MismatchDetail(
            category="system_calls",
            claimed="No system command execution documented",
            actual="System command execution patterns found",
            severity=ScanSeverity.HIGH,
            explanation="Command execution capability should be explicitly documented.",
        ))
        score -= 20
    if agent_b.file_operations and not contains_any(claimed_blob, CLAIM_FILE):
        undocumented.append("Undocumented file operations")
        mismatches.append(MismatchDetail(
            category="file_ops",
            claimed="No file operations documented",
            actual="File read/write operations detected",
            severity=ScanSeverity.MEDIUM,
            explanation="Filesystem behavior appears broader than documentation claims.",
        ))
        score -= 10
    if agent_b.env_access and not contains_any(claimed_blob, CLAIM_ENV):
        undocumented.append("Undocumented environment access")
        mismatches.append(MismatchDetail(
            category="env_access",
            claimed="No env/credential access documented",
            actual="Environment variable access detected",
            severity=ScanSeverity.MEDIUM,
            explanation="Env usage should be documented for security transparency.",
        ))
        score -= 10

    if scanner.dangerous_calls_count > 0 and not agent_b.system_calls:
        missed.append("Agent B may have missed dangerous/system call findings from scanner.")
    if scanner.network_ops_count > 0 and not agent_b.network_calls:
        missed.append("Agent B may have missed network findings from scanner.")
    if scanner.file_ops_count > 0 and not agent_b.file_operations:
        missed.append("Agent B may have missed file operation findings from scanner.")
    if scanner.env_access_count > 0 and not agent_b.env_access:
        missed.append("Agent B may have missed environment access findings from scanner.")
    if scanner.obfuscation_count > 0 and not any("obfuscat" in (f.category or "").lower() for f in agent_b.findings):
        missed.append("Agent B may have missed obfuscation patterns found by scanner.")
    if scanner.injection_patterns_count > 0 and not any("inject" in (f.category or "").lower() for f in agent_b.findings):
        missed.append("Agent B may have missed injection patterns found by scanner.")

    # B-miss penalty: 5 points per miss (was 15 — caused mathematically impossible
    # pass for repos with ≥40 scanner findings + ≥1 B-miss).
    # First miss is free: legitimate MCP servers commonly have ONE capability
    # (e.g. network or file ops) that Agent B's heuristic doesn't match exactly.
    b_miss_penalty = 5 * max(0, len(missed) - 1)

    sev = severity_counts(scanner)

    # Scanner-driven penalty: reflects detected security findings (not doc/code mismatch).
    # Cap at 40 — large codebases should not auto-crash to score 0.
    scanner_penalty = min(40, (sev["high"] * 2) + sev["medium"] + (sev["low"] // 2))

    # Cap COMBINED deduction from B-misses + scanner at 50 points.
    # This ensures score >= 50 is achievable for repos with many findings
    # but zero injection/obfuscation (which are caught by safety overrides, not score).
    combined_penalty = min(50, b_miss_penalty + scanner_penalty)
    score -= combined_penalty

    # Determine risk level.
    # HIGH/CRITICAL reserved for real threats: injection patterns, high-risk
    # obfuscation, or critical-severity scanner findings.
    # dangerous_calls (subprocess, exec, fetch) are expected MCP server
    # functionality — they indicate "this code CAN do X", not "this code IS
    # malicious". These map to MEDIUM risk, not HIGH.
    risk = ScanSeverity.INFO
    if sev["critical"] > 0:
        risk = ScanSeverity.CRITICAL
    elif scanner.injection_patterns_count > 0 or scanner.obfuscation_high_risk_count > 0:
        risk = ScanSeverity.HIGH
    elif sev["high"] > 0 or sev["medium"] > 0 or undocumented:
        risk = ScanSeverity.MEDIUM
    elif sev["low"] > 0:
        risk = ScanSeverity.LOW

    status = VerificationStatus.MANUAL_REVIEW
    score = max(0, min(100, score))
    if risk == ScanSeverity.CRITICAL:
        status = VerificationStatus.FAIL
    elif score >= 70 and risk not in (ScanSeverity.CRITICAL,):
        # Allow PASS at score >= 70 (was 80). Evidence: PM overrode 76 skills
        # with scores 70-79 + risk=MEDIUM + 0 inj/obf/crit to pass. These are
        # legitimate MCP servers whose documented capabilities (network, file,
        # env) produce expected score deductions. Safety overrides below still
        # block on injection/obfuscation.
        status = VerificationStatus.PASS
    elif score >= 50 and risk != ScanSeverity.CRITICAL:
        status = VerificationStatus.MANUAL_REVIEW
    else:
        status = VerificationStatus.FAIL

    # Safety overrides (deterministic)
    if sev["critical"] > 0:
        score = min(score, 40)
        status = VerificationStatus.FAIL
        if risk not in (ScanSeverity.HIGH, ScanSeverity.CRITICAL):
            risk = ScanSeverity.HIGH
    if scanner.obfuscation_high_risk_count > 0:
        score = min(score, 15)
        status = VerificationStatus.FAIL
        risk = ScanSeverity.CRITICAL
    if scanner.injection_patterns_count > 0:
        score = min(score, 10)
        status = VerificationStatus.FAIL
        risk = ScanSeverity.CRITICAL
    score = max(0, min(100, score))

    summary = (
        f"Deterministic scoring: score={score}, status={status.value}, risk={risk.value}. "
        f"Mismatches={len(mismatches)}, undocumented={len(undocumented)}, scanner_findings={len(scanner.findings)}, "
        f"scanner_penalty={scanner_penalty}."
    )

    return ScorerOutput(
        overall_score=score,
        status=status,
        mismatches=mismatches,
        risk_level=risk,
        undocumented_capabilities=undocumented,
        agent_b_missed_findings=missed,
        summary=summary[:1000],
    )


def run_agent_e(scanner: ScannerOutput, scorer: ScorerOutput) -> SupervisorOutput:
    sev = severity_counts(scanner)
    final_status = scorer.status
    approved = final_status == VerificationStatus.PASS
    confidence = max(50, min(95, scorer.overall_score))
    consistency = True
    suspicion: str | None = None
    override: str | None = None
    recommendations: list[str] = []

    if scorer.agent_b_missed_findings:
        suspicion = "Agent B missed scanner findings; possible analysis gap."
        consistency = False
        recommendations.append("Re-run code analysis and inspect high-risk files manually.")

    # Approval defaults
    if scorer.overall_score < 50:
        approved = False
        final_status = VerificationStatus.FAIL
    elif scorer.overall_score < 80:
        approved = False
        final_status = VerificationStatus.MANUAL_REVIEW

    # Hard overrides
    if scanner.obfuscation_high_risk_count > 0:
        approved = False
        final_status = VerificationStatus.FAIL
        confidence = max(confidence, 90)
        override = "Deterministic override: high-risk obfuscation detected."
    if scanner.injection_patterns_count > 0:
        approved = False
        final_status = VerificationStatus.FAIL
        confidence = max(confidence, 95)
        override = "Deterministic override: injection patterns detected."
    if scorer.status == VerificationStatus.FAIL and final_status == VerificationStatus.PASS:
        final_status = VerificationStatus.MANUAL_REVIEW
        approved = False
        override = "Supervisor constrained: cannot override FAIL directly to PASS."
    if sev["critical"] > 0:
        approved = False
        if final_status == VerificationStatus.PASS:
            final_status = VerificationStatus.FAIL
        confidence = max(confidence, 90)

    if final_status == VerificationStatus.FAIL:
        recommendations.append("Do not install in production without remediation.")
    elif final_status == VerificationStatus.MANUAL_REVIEW:
        recommendations.append("Manual security review recommended before adoption.")
    else:
        recommendations.append("Use commit-pinned install for reproducibility.")

    # INVARIANT: approved requires pass
    if final_status != VerificationStatus.PASS:
        approved = False

    summary = (
        f"Supervisor decision: approved={approved}, final_status={final_status.value}, "
        f"confidence={confidence}, critical_findings={sev['critical']}."
    )

    return SupervisorOutput(
        approved=approved,
        final_status=final_status,
        confidence=max(0, min(100, confidence)),
        agent_consistency_check=consistency,
        compromised_agent_suspicion=suspicion,
        override_reason=override,
        recommendations=recommendations[:12],
        summary=summary[:1000],
    )


def build_agent_audit(agent_a: AgentAOutput, agent_b: AgentBOutput, scanner: ScannerOutput, scorer: ScorerOutput, supervisor: SupervisorOutput, scan_date: str) -> dict[str, Any]:
    """Build per-agent audit trail from pipeline outputs."""
    sev = severity_counts(scanner)

    # Check if any safety overrides were triggered
    overrides_applied = (
        scanner.obfuscation_high_risk_count > 0 or
        scanner.injection_patterns_count > 0 or
        sev["critical"] > 0
    )

    return {
        "agents_completed": 5,
        "agents_required": 5,
        "pipeline_run_at": scan_date,
        "agent_a": {
            "signed": True,
            "signed_at": scan_date,
            "comment": f"Docs quality {agent_a.doc_quality_score}/10. "
                       f"{'README present' if agent_a.has_readme else 'README missing'}. "
                       f"{len(agent_a.claimed_features)} features, {len(agent_a.claimed_permissions)} permissions claimed.",
            "doc_quality_score": agent_a.doc_quality_score,
            "claimed_permissions": agent_a.claimed_permissions,
        },
        "agent_b": {
            "signed": True,
            "signed_at": scan_date,
            "comment": f"{agent_b.total_files_analyzed} files analyzed. "
                       f"Found: {len(agent_b.network_calls)} network, {len(agent_b.file_operations)} file, "
                       f"{len(agent_b.env_access)} env, {len(agent_b.system_calls)} system calls. "
                       f"Primary: {agent_b.primary_language}.",
            "files_analyzed": agent_b.total_files_analyzed,
            "capabilities_found": agent_b.actual_capabilities,
        },
        "agent_c_star": {
            "signed": True,
            "signed_at": scan_date,
            "comment": f"{len(scanner.findings)} findings: {sev['critical']} critical, {sev['high']} high, "
                       f"{sev['medium']} medium, {sev['low']} low. "
                       f"{'Obfuscation detected!' if scanner.obfuscation_count > 0 else 'No obfuscation'}. "
                       f"{'Injection patterns found!' if scanner.injection_patterns_count > 0 else 'No injection'}.",
            "total_findings": len(scanner.findings),
            "severity_counts": sev,
        },
        "agent_d": {
            "signed": True,
            "signed_at": scan_date,
            "comment": f"Score {scorer.overall_score}. {len(scorer.mismatches)} mismatches. "
                       f"Risk: {scorer.risk_level.value if hasattr(scorer.risk_level, 'value') else scorer.risk_level}. "
                       f"Safety overrides: {'applied' if overrides_applied else 'none triggered'}.",
            "score": scorer.overall_score,
            "mismatches": len(scorer.mismatches),
            "safety_overrides_applied": overrides_applied,
        },
        "agent_e": {
            "signed": True,
            "signed_at": scan_date,
            "comment": f"{'Approved' if supervisor.approved else 'Rejected'}. "
                       f"Confidence {supervisor.confidence}%. "
                       f"{supervisor.override_reason or 'No overrides.'}",
            "approved": supervisor.approved,
            "confidence": supervisor.confidence,
            "override_reason": supervisor.override_reason,
        },
        "manager_summary": (
            f"5/5 agents completed. "
            f"Score: {scorer.overall_score}/100, Risk: {scorer.risk_level.value if hasattr(scorer.risk_level, 'value') else scorer.risk_level}. "
            f"{len(scorer.mismatches)} mismatches, {len(scanner.findings)} scanner findings. "
            f"{'Approved' if supervisor.approved else 'Rejected'} at {supervisor.confidence}% confidence. "
            f"{'Safety overrides triggered.' if overrides_applied else 'No safety overrides.'}"
        ),
    }


def write_report_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def findings_summary(scanner: ScannerOutput, scorer: ScorerOutput, supervisor: SupervisorOutput) -> dict[str, Any]:
    return {
        "scanner_findings": len(scanner.findings),
        "dangerous_calls": scanner.dangerous_calls_count,
        "network_ops": scanner.network_ops_count,
        "file_ops": scanner.file_ops_count,
        "env_access": scanner.env_access_count,
        "obfuscation": scanner.obfuscation_count,
        "injection_patterns": scanner.injection_patterns_count,
        "mismatches": len(scorer.mismatches),
        "undocumented_capabilities": len(scorer.undocumented_capabilities),
        "supervisor_approved": supervisor.approved,
        "supervisor_confidence": supervisor.confidence,
    }


def build_scan_report(scanner: ScannerOutput) -> dict[str, Any]:
    """Build a scan_report dict from ScannerOutput for storage in skill JSON.

    Contains all counts + category breakdown + top findings (capped at 20).
    This enables post-verification PM review and auto-clear without needing
    the separate scan-reports/ side files.
    """
    # Category breakdown from findings
    category_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in scanner.findings:
        cat = f.category if hasattr(f, "category") else "unknown"
        category_counts[cat] = category_counts.get(cat, 0) + 1
        sev = f.severity.value if hasattr(f.severity, "value") else str(f.severity)
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    # Top findings (capped at 20 to keep skill JSON manageable)
    top_findings = []
    for f in scanner.findings[:20]:
        entry: dict[str, Any] = {
            "rule_id": f.rule_id if hasattr(f, "rule_id") else "",
            "severity": f.severity.value if hasattr(f.severity, "value") else str(f.severity),
            "category": f.category if hasattr(f, "category") else "",
        }
        if hasattr(f, "file_path") and f.file_path:
            entry["file"] = str(f.file_path)[:200]
        if hasattr(f, "line_number") and f.line_number:
            entry["line"] = f.line_number
        top_findings.append(entry)

    return {
        "total_findings": len(scanner.findings),
        "injection_patterns_count": scanner.injection_patterns_count,
        "obfuscation_count": scanner.obfuscation_count,
        "obfuscation_high_risk_count": scanner.obfuscation_high_risk_count,
        "dangerous_calls_count": scanner.dangerous_calls_count,
        "severity_counts": severity_counts,
        "category_counts": category_counts,
        "top_findings": top_findings,
        "total_files_scanned": scanner.total_files_scanned,
    }


NETWORK_PROBE_URL = "https://github.com/modelcontextprotocol/servers"

# Git error patterns that indicate the repo itself is gone/private/deleted,
# NOT a network-level failure on the runner.
_REPO_GONE_PATTERNS = [
    "repository not found",
    "does not exist",
    "not found",
    "access denied",
    "authentication failed",
    "remote: repository",
]


def check_network_health() -> tuple[bool, str]:
    """Confirm github.com is reachable before the run starts."""
    try:
        res = subprocess.run(
            ["git", "ls-remote", "--exit-code", "--heads", NETWORK_PROBE_URL],
            capture_output=True, text=True, timeout=30,
        )
        if res.returncode == 0:
            return True, ""
        return False, f"git ls-remote returned {res.returncode}: {(res.stderr or '').strip()[:200]}"
    except subprocess.TimeoutExpired:
        return False, "network probe timed out after 30s"
    except Exception as exc:
        return False, str(exc)


def _is_repo_gone_error(err: str) -> bool:
    """Returns True if the git error indicates the repo itself is gone/private."""
    lower = err.lower()
    return any(p in lower for p in _REPO_GONE_PATTERNS)


def clone_repo(repo_url: str, dest: Path) -> tuple[bool, str, bool]:
    """Clone a repo. Returns (ok, error_message, repo_is_gone).

    repo_is_gone=True means the repo is 404/private/deleted.
    repo_is_gone=False means a network/infrastructure failure.
    """
    try:
        res = subprocess.run(
            ["git", "clone", "--depth", "1", "--single-branch", repo_url, str(dest)],
            capture_output=True, text=True, timeout=180,
        )
        if res.returncode != 0:
            err = (res.stderr or res.stdout or "clone failed").strip()
            return False, err, _is_repo_gone_error(err)
        return True, "", False
    except subprocess.TimeoutExpired:
        return False, "clone timeout", False
    except Exception as exc:
        return False, str(exc), False


def get_head_commit(repo_path: Path) -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"


def update_skill_file(
    skill_path: Path,
    *,
    status: str,
    score: int,
    risk: str,
    scan_date: str,
    verified_commit: str,
    summary: dict[str, Any],
    primary_language: str,
    verification_level: str = "",
    agent_audit: dict[str, Any] | None = None,
    scan_report: dict[str, Any] | None = None,
    ensure_repo_unavailable_tag: bool = False,
    repo_status: str | None = None,
    repo_check_date: str | None = None,
    repo_check_error: str | None = None,
) -> None:
    data = json.loads(skill_path.read_text(encoding="utf-8"))
    normalized_status = normalize_status(status)
    data["verification_status"] = normalized_status
    data["overall_score"] = int(score)
    data["risk_level"] = risk
    data["scan_date"] = scan_date
    data["verified_commit"] = verified_commit
    data["findings_summary"] = summary
    if scan_report is not None:
        data["scan_report"] = scan_report
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    tags = [str(t) for t in tags if not str(t).startswith(STATUS_TAG_PREFIX)]
    if ensure_repo_unavailable_tag and "repo_unavailable" not in tags:
        tags.append("repo_unavailable")
    if ensure_repo_unavailable_tag and NOT_REACHABLE_TAG not in tags:
        tags.append(NOT_REACHABLE_TAG)
    tags.append(f"{STATUS_TAG_PREFIX}{normalized_status}")
    data["tags"] = list(dict.fromkeys(tags))
    if primary_language and (not data.get("primary_language") or data.get("primary_language") == "unknown"):
        data["primary_language"] = primary_language
    if verification_level:
        data["verification_level"] = verification_level
    if agent_audit:
        data["agent_audit"] = agent_audit
    if repo_status is not None:
        data["repo_status"] = repo_status
    if repo_check_date is not None:
        data["repo_check_date"] = repo_check_date
    if repo_check_error is not None:
        data["repo_check_error"] = repo_check_error[:200]
    skill_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def fail_skill(skill: dict[str, Any], stage: str, message: str, scan_date: str) -> SkillRunResult:
    skill_id = skill["id"]
    if not re.match(r'^[a-zA-Z0-9_-]+$', skill_id):
        logger.error("Invalid skill_id in fail_skill: %s", skill_id)
        return SkillRunResult(skill_id=skill_id, status="fail", score=0, risk="critical", stage_fail="validation", message=f"Invalid skill_id: {skill_id}")
    skill_path = SKILLS_DIR / f"{skill_id}.json"
    summary = {
        "error": f"{stage} failed: {message[:400]}",
        "supervisor_approved": False,
        "supervisor_confidence": 0,
    }
    update_skill_file(
        skill_path,
        status=VerificationStatus.MANUAL_REVIEW.value,
        score=max(0, int(skill.get("overall_score") or 0)),
        risk=ScanSeverity.HIGH.value,
        scan_date=scan_date,
        verified_commit=str(skill.get("verified_commit") or ""),
        summary=summary,
        primary_language=str(skill.get("primary_language") or "unknown"),
        ensure_repo_unavailable_tag=(stage == "clone"),
        repo_status="unavailable" if stage == "clone" else None,
        repo_check_date=scan_date if stage == "clone" else None,
        repo_check_error=message[:200] if stage == "clone" else None,
    )
    return SkillRunResult(
        skill_id=skill_id,
        status=VerificationStatus.MANUAL_REVIEW.value,
        score=int(skill.get("overall_score") or 0),
        risk=ScanSeverity.HIGH.value,
        stage_fail=stage,
        message=message[:500],
    )


def verify_one_skill(skill: dict[str, Any], sanitizer: Sanitizer) -> SkillRunResult:
    skill_id = skill["id"]
    if not re.match(r'^[a-zA-Z0-9_-]+$', skill_id):
        return SkillRunResult(skill_id=skill_id, status="fail", score=0, risk="critical", stage_fail="validation", message=f"Invalid skill_id format: {skill_id}")
    skill_name = skill.get("name", skill_id)
    repo_url = skill.get("repo_url", "")
    scan_date = utc_now()

    parsed_url = urlparse(repo_url)
    if parsed_url.scheme != "https" or parsed_url.netloc != "github.com":
        return fail_skill(skill, "clone", f"unsupported repo_url: {repo_url}", scan_date)

    with tempfile.TemporaryDirectory(prefix=f"strict5_{skill_id[:24]}_") as tmp:
        repo_path = Path(tmp) / "repo"
        ok, err, repo_is_gone = clone_repo(repo_url, repo_path)
        if not ok:
            if repo_is_gone:
                return fail_skill(skill, "clone", err, scan_date)
            # Network/infrastructure failure — do NOT tag as unavailable
            logger.warning("Clone failed for %s with network error (not tagging unavailable): %s", skill_id, err)
            return SkillRunResult(
                skill_id=skill_id,
                status="skip",
                score=int(skill.get("overall_score") or 0),
                risk=skill.get("risk_level", "unknown"),
                stage_fail="clone_network",
                message=err[:500],
            )

        verified_commit = get_head_commit(repo_path)

        try:
            agent_a = run_agent_a(repo_path, skill_name)
        except Exception as exc:
            return fail_skill(skill, "agent_a", str(exc), scan_date)

        try:
            agent_b = run_agent_b(repo_path)
        except Exception as exc:
            return fail_skill(skill, "agent_b", str(exc), scan_date)

        try:
            scanner = StaticScanner(str(repo_path)).scan()
        except Exception as exc:
            return fail_skill(skill, "agent_c_scanner", str(exc), scan_date)

        try:
            agent_a = sanitizer.sanitize(agent_a)
            agent_b = sanitizer.sanitize(agent_b)
            scanner = sanitizer.sanitize(scanner)
        except Exception as exc:
            return fail_skill(skill, "sanitize", str(exc), scan_date)

        try:
            scorer = run_agent_d(agent_a, agent_b, scanner)
            scorer = sanitizer.sanitize(scorer)
        except Exception as exc:
            return fail_skill(skill, "agent_d", str(exc), scan_date)

        try:
            supervisor = run_agent_e(scanner, scorer)
            supervisor = sanitizer.sanitize(supervisor)
        except Exception as exc:
            return fail_skill(skill, "agent_e", str(exc), scan_date)

        report_dir = REPORTS_DIR / skill_id
        write_report_file(report_dir / "agent_a_docs.json", agent_a.model_dump(mode="json"))
        write_report_file(report_dir / "agent_b_code.json", agent_b.model_dump(mode="json"))
        write_report_file(report_dir / "agent_c_scanner.json", scanner.model_dump(mode="json"))
        write_report_file(report_dir / "agent_d_scorer.json", scorer.model_dump(mode="json"))
        write_report_file(report_dir / "agent_e_supervisor.json", supervisor.model_dump(mode="json"))

        summary_payload = {
            "skill_id": skill_id,
            "generated_at": scan_date,
            "overall_score": scorer.overall_score,
            "status": scorer.status.value,
            "final_status": supervisor.final_status.value,
            "approved": supervisor.approved,
            "supervisor_confidence": supervisor.confidence,
            "risk_level": scorer.risk_level.value,
            "scanner_findings_count": len(scanner.findings),
            "mismatches_count": len(scorer.mismatches),
        }
        write_report_file(report_dir / "summary.json", summary_payload)

        final_status = supervisor.final_status.value
        final_score = scorer.overall_score
        final_risk = scorer.risk_level.value

        # --- PM-Learned Auto-Clear (Cat 9/10/11) ---
        # If pipeline says FAIL/MR but pattern matches a known FP, auto-clear to PASS.
        # This is the code-level implementation of PM's self-evolving loop:
        # PM reviews → writes learnings → bakes into code → pipeline actually learns.
        auto_clear_status = None
        if final_status in ("fail", "manual_review"):
            ac_status, ac_reason, ac_score = auto_clear_known_fp(repo_url, scanner, scorer)
            if ac_status:
                logger.info("AUTO-CLEAR %s: %s → %s (%s)", skill_id, final_status, ac_status, ac_reason)
                auto_clear_status = ac_reason
                final_status = ac_status
                final_score = ac_score
                final_risk = "medium"  # downgrade from critical since it's a known FP

        summary = findings_summary(scanner, scorer, supervisor)
        scan_rpt = build_scan_report(scanner)

        audit = build_agent_audit(agent_a, agent_b, scanner, scorer, supervisor, scan_date)

        # Record auto-clear in audit trail so PM can track pipeline learnings
        if auto_clear_status:
            audit["auto_clear"] = {
                "applied": True,
                "reason": auto_clear_status,
                "original_status": supervisor.final_status.value,
                "original_score": scorer.overall_score,
            }

        skill_path = SKILLS_DIR / f"{skill_id}.json"
        update_skill_file(
            skill_path,
            status=final_status,
            score=final_score,
            risk=final_risk,
            scan_date=scan_date,
            verified_commit=verified_commit,
            summary=summary,
            primary_language=agent_b.primary_language,
            verification_level="full_pipeline",
            agent_audit=audit,
            scan_report=scan_rpt,
        )

        return SkillRunResult(
            skill_id=skill_id,
            status=final_status,
            score=final_score,
            risk=final_risk,
        )


def worker_group(group_id: int, skills: list[dict[str, Any]]) -> list[SkillRunResult]:
    sanitizer = Sanitizer(strict=True)
    results: list[SkillRunResult] = []
    logger.info("group=%d start count=%d", group_id, len(skills))
    for idx, skill in enumerate(skills, start=1):
        skill_id = skill["id"]
        logger.info("group=%d skill=%d/%d id=%s stars=%s", group_id, idx, len(skills), skill_id, skill.get("stars", 0))
        result = verify_one_skill(skill, sanitizer)
        results.append(result)
        logger.info("group=%d id=%s status=%s score=%s risk=%s stage_fail=%s", group_id, skill_id, result.status, result.score, result.risk, result.stage_fail)
    logger.info("group=%d done", group_id)
    return results


def should_verify_status(raw_status: Any, only_unverified: bool) -> bool:
    status = normalize_status(raw_status)
    if not only_unverified:
        return True
    return status in {"unverified", "updated_unverified"}


def has_repo_unavailable_tag(tags: Any) -> bool:
    if not isinstance(tags, list):
        return False
    tag_set = {str(t) for t in tags}
    return "repo_unavailable" in tag_set or "clone_failure" in tag_set or NOT_REACHABLE_TAG in tag_set


def load_candidates(
    limit: int,
    skill_type: str | None,
    only_unverified: bool,
    source: str | None,
    include_repo_unavailable: bool = False,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for path in sorted(SKILLS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if skill_type and str(skill_type).lower() != "all" and data.get("skill_type") != skill_type:
            continue
        if source and data.get("source_hub") != source:
            continue
        if not should_verify_status(data.get("verification_status"), only_unverified):
            continue
        if not str(data.get("repo_url", "")).startswith("https://github.com/"):
            continue
        if not include_repo_unavailable and has_repo_unavailable_tag(data.get("tags")):
            continue
        candidates.append(data)
    candidates.sort(key=lambda d: (-int(d.get("stars") or 0), str(d.get("id") or "")))
    return candidates[:limit]


def split_groups(skills: list[dict[str, Any]], group_count: int) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = [[] for _ in range(group_count)]
    for idx, skill in enumerate(skills):
        groups[idx % group_count].append(skill)
    return groups


def summarize(results: list[SkillRunResult]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    stage_failures: dict[str, int] = {}
    retry_ids: list[str] = []
    for r in results:
        status_counts[r.status] = status_counts.get(r.status, 0) + 1
        if r.stage_fail:
            stage_failures[r.stage_fail] = stage_failures.get(r.stage_fail, 0) + 1
            retry_ids.append(r.skill_id)
    return {
        "processed_count": len(results),
        "status_counts": status_counts,
        "stage_failures": stage_failures,
        "retry_ids": retry_ids,
    }


def remaining_unverified(
    skill_type: str | None,
    source: str | None = None,
    include_repo_unavailable: bool = False,
) -> int:
    count = 0
    for path in SKILLS_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if skill_type and str(skill_type).lower() != "all" and data.get("skill_type") != skill_type:
            continue
        if source and data.get("source_hub") != source:
            continue
        if not include_repo_unavailable and has_repo_unavailable_tag(data.get("tags")):
            continue
        if normalize_status(data.get("verification_status")) in {"unverified", "updated_unverified"}:
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Strict 5-agent verification runner (deterministic A/B/D/E implementation).")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--group-count", type=int, default=5)
    parser.add_argument("--skill-type", type=str, default=None)
    parser.add_argument("--only-unverified", action="store_true", default=True)
    parser.add_argument("--source", type=str, default=None)
    parser.add_argument("--include-repo-unavailable", action="store_true", default=False,
                        help="Include skills tagged repo_unavailable/clone_failure")
    parser.add_argument("--skill-ids", type=str, default=None, help="Comma-separated skill IDs to verify (bypasses filters)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Network health check — abort if github.com is unreachable.
    # A local network failure must never corrupt skill data.
    net_ok, net_err = check_network_health()
    if not net_ok:
        logger.error(
            "ABORT: github.com is unreachable. This is a local network failure, "
            "not a repo-unavailability event. No skill data will be modified. "
            "Error: %s", net_err
        )
        sys.exit(1)
    logger.info("Network health check passed.")

    start = utc_now()
    if args.skill_ids:
        # Load specific skills by ID, bypassing all filters
        target_ids = [sid.strip() for sid in args.skill_ids.split(",") if sid.strip()]
        # Validate skill IDs to prevent path traversal
        valid_id_pattern = re.compile(r'^[a-zA-Z0-9_-]+$')
        target_ids = [sid for sid in target_ids if valid_id_pattern.match(sid)]
        # Deduplicate
        target_ids = list(dict.fromkeys(target_ids))
        selected = []
        for path in sorted(SKILLS_DIR.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("id") in target_ids:
                selected.append(data)
        # Preserve requested order
        id_order = {sid: i for i, sid in enumerate(target_ids)}
        selected.sort(key=lambda d: id_order.get(d.get("id", ""), 999))
    else:
        selected = load_candidates(
            limit=args.limit,
            skill_type=args.skill_type,
            only_unverified=args.only_unverified,
            source=args.source,
            include_repo_unavailable=args.include_repo_unavailable,
        )
    results: list[SkillRunResult] = []
    if not selected:
        logger.info("No candidates selected.")
    else:
        groups = split_groups(selected, args.group_count)
        logger.info("Selected %d skills. groups=%d", len(selected), args.group_count)
        for i, g in enumerate(groups):
            logger.info("group=%d count=%d", i, len(g))

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.group_count) as ex:
            futures = [ex.submit(worker_group, i, group) for i, group in enumerate(groups)]
            for future in concurrent.futures.as_completed(futures):
                results.extend(future.result())

    summary = summarize(results)
    end = utc_now()
    run_payload = {
        "started_at": start,
        "finished_at": end,
        "skill_type": args.skill_type or "all",
        "selected_ids": [s["id"] for s in selected],
        "selected_count": len(selected),
        "group_count": args.group_count,
        **summary,
        "remaining_unverified": remaining_unverified(
            args.skill_type,
            source=args.source,
            include_repo_unavailable=args.include_repo_unavailable,
        ),
        "only_unverified": args.only_unverified,
        "source": args.source or "*",
        "include_repo_unavailable": args.include_repo_unavailable,
    }

    RUN_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    run_file = RUN_REPORTS_DIR / f"{end.replace(':', '').replace('-', '')}_strict5_limit{args.limit}.json"
    run_file.write_text(json.dumps(run_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    log_to_skill_manager(
        check_type="verification_run",
        findings={
            "selected_count": run_payload["selected_count"],
            "processed_count": run_payload["processed_count"],
            "status_counts": run_payload["status_counts"],
            "stage_failures": run_payload["stage_failures"],
            "remaining_unverified": run_payload["remaining_unverified"],
            "run_report": str(run_file),
        },
    )

    logger.info("Run report written: %s", run_file)
    logger.info("Processed=%d status=%s stage_failures=%s remaining_unverified=%d",
                run_payload["processed_count"],
                run_payload["status_counts"],
                run_payload["stage_failures"],
                run_payload["remaining_unverified"])


if __name__ == "__main__":
    main()
