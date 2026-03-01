"""
Verification Pipeline -- Reference Architecture.

This file defines the REFERENCE ARCHITECTURE for the multi-agent skill
verification pipeline.  Actual LLM execution happens via Claude Code Task
agent orchestration, NOT via direct API calls.

Pipeline stages:
    1. Clone   -- Clone the skill repository to a temporary directory.
    2. Prepare -- Use AgentAMdReader.prepare() and AgentBCodeParser.prepare()
                  to collect files and build prompt payloads.
    3. Scan    -- Run Agent C* (deterministic scanner) -- no LLM involved.
    4. Task A+B -- Hand prompt payloads to Claude Code Task agents for
                   Agents A and B (can run in parallel).
    5. Sanitize -- Sanitize all outputs through the Sanitizer.
    6. Task D  -- Use AgentDScorer.prepare() to build prompt, run Task agent,
                  then AgentDScorer.validate_and_override() for safety.
    7. Task E  -- Use AgentESupervisor.prepare() to build prompt, run Task
                  agent, then AgentESupervisor.validate_and_override() for safety.
    8. Write   -- Write reports to data/scan-reports/{skill-id}/.
    9. Build   -- Assemble the final VerifiedSkill catalog entry.

Each Task agent stage uses the corresponding agent class's ``prepare()``
method (to build prompts) and ``validate_output()`` or
``validate_and_override()`` method (to parse and safety-check results).

The helper methods below (clone, scan, sanitize, write reports, build skill)
are kept as utilities that the orchestrating Task agent can invoke.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.sanitizer.schemas import (
    AgentAOutput,
    AgentBOutput,
    ScannerOutput,
    ScanSeverity,
    ScorerOutput,
    SourceHub,
    SupervisorOutput,
    TrustLevel,
    VerificationStatus,
    VerifiedSkill,
)

logger = logging.getLogger(__name__)

# Project root -- used to resolve data/ directory.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_REPORTS_DIR = _PROJECT_ROOT / "data" / "scan-reports"

# Git clone timeout in seconds.
_CLONE_TIMEOUT = 120


class VerificationPipeline:
    """Reference architecture and utility methods for the verification pipeline.

    This class provides the infrastructure methods (clone, scan, sanitize,
    write reports, build results) that Claude Code Task agents use during
    orchestration.  It does NOT call any LLM API directly.
    """

    # ------------------------------------------------------------------
    # Repository operations
    # ------------------------------------------------------------------

    @staticmethod
    def clone_repo(repo_url: str) -> str:
        """Clone a git repository into a temporary directory.

        Returns the path to the cloned directory.
        """
        tmp_dir = tempfile.mkdtemp(prefix="secureskillhub_")
        clone_target = str(Path(tmp_dir) / "repo")

        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", "--single-branch", repo_url, clone_target],
                capture_output=True,
                text=True,
                timeout=_CLONE_TIMEOUT,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise RuntimeError(
                f"Git clone failed for {repo_url}: {exc.stderr.strip()}"
            ) from exc
        except subprocess.TimeoutExpired:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise RuntimeError(
                f"Git clone timed out after {_CLONE_TIMEOUT}s for {repo_url}"
            )

        return clone_target

    @staticmethod
    def get_head_commit(repo_path: str) -> str:
        """Get the HEAD commit hash of a cloned repository."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=repo_path,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return "unknown"

    # ------------------------------------------------------------------
    # Scanner (Agent C* -- deterministic, no LLM)
    # ------------------------------------------------------------------

    @staticmethod
    def run_scanner(repo_path: str, skill_id: str, scan_time: str) -> ScannerOutput:
        """Run the deterministic scanner (Agent C*).

        Attempts to import the scanner module. If it is not yet available,
        returns a minimal ScannerOutput so the pipeline can still proceed
        (with degraded confidence).
        """
        try:
            from src.scanner.scanner import StaticScanner

            scanner = StaticScanner(repo_path)
            return scanner.scan()
        except ImportError:
            logger.warning(
                "StaticScanner not available -- returning empty scanner output. "
                "The scanner module may not have been built yet."
            )
            # SECURITY: Scanner failure must trigger safety overrides (fail-safe).
            # Set injection_patterns_count=1 so Agent D caps score to 10 and fails.
            return ScannerOutput(
                scan_id=f"scan-{skill_id}-error",
                scanned_at=scan_time,
                total_files_scanned=0,
                injection_patterns_count=1,
            )
        except Exception:
            logger.exception("Scanner failed for %s", repo_path)
            # SECURITY: Scanner failure must trigger safety overrides (fail-safe).
            # Set injection_patterns_count=1 so Agent D caps score to 10 and fails.
            return ScannerOutput(
                scan_id=f"scan-{skill_id}-error",
                scanned_at=scan_time,
                total_files_scanned=0,
                injection_patterns_count=1,
            )

    # ------------------------------------------------------------------
    # Sanitization
    # ------------------------------------------------------------------

    @staticmethod
    def sanitize_outputs(
        agent_a: AgentAOutput,
        agent_b: AgentBOutput,
        scanner: ScannerOutput,
    ) -> tuple[AgentAOutput, AgentBOutput, ScannerOutput]:
        """Sanitize all agent outputs through the Sanitizer.

        If the sanitizer module is not yet available, re-validates through
        Pydantic as a fallback (which enforces max_length constraints).
        """
        try:
            from src.sanitizer.sanitizer import Sanitizer

            sanitizer = Sanitizer()
            agent_a = sanitizer.sanitize(agent_a)
            agent_b = sanitizer.sanitize(agent_b)
            scanner = sanitizer.sanitize(scanner)
        except ImportError:
            logger.warning(
                "Sanitizer not available -- falling back to Pydantic re-validation."
            )
            agent_a = AgentAOutput.model_validate(agent_a.model_dump())
            agent_b = AgentBOutput.model_validate(agent_b.model_dump())
            scanner = ScannerOutput.model_validate(scanner.model_dump())
        except Exception:
            logger.exception("Sanitizer failed -- using raw outputs with re-validation")
            agent_a = AgentAOutput.model_validate(agent_a.model_dump())
            agent_b = AgentBOutput.model_validate(agent_b.model_dump())
            scanner = ScannerOutput.model_validate(scanner.model_dump())

        return agent_a, agent_b, scanner

    # ------------------------------------------------------------------
    # Report writing
    # ------------------------------------------------------------------

    @staticmethod
    def write_reports(
        *,
        skill_id: str,
        agent_a: AgentAOutput,
        agent_b: AgentBOutput,
        scanner: ScannerOutput,
        scorer: ScorerOutput,
        supervisor: SupervisorOutput,
    ) -> None:
        """Write all agent reports to data/scan-reports/{skill_id}/."""
        report_dir = _REPORTS_DIR / skill_id
        report_dir.mkdir(parents=True, exist_ok=True)

        reports = {
            "agent_a_docs.json": agent_a,
            "agent_b_code.json": agent_b,
            "agent_c_scanner.json": scanner,
            "agent_d_scorer.json": scorer,
            "agent_e_supervisor.json": supervisor,
        }

        for filename, model in reports.items():
            filepath = report_dir / filename
            try:
                filepath.write_text(
                    json.dumps(model.model_dump(mode="json"), indent=2) + "\n",
                    encoding="utf-8",
                )
                logger.debug("Wrote report: %s", filepath)
            except OSError:
                logger.exception("Failed to write report: %s", filepath)

        # Write a combined summary.
        summary = {
            "skill_id": skill_id,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "overall_score": scorer.overall_score,
            "status": scorer.status if isinstance(scorer.status, str) else scorer.status.value,
            "final_status": (
                supervisor.final_status
                if isinstance(supervisor.final_status, str)
                else supervisor.final_status.value
            ),
            "approved": supervisor.approved,
            "supervisor_confidence": supervisor.confidence,
            "risk_level": (
                scorer.risk_level
                if isinstance(scorer.risk_level, str)
                else scorer.risk_level.value
            ),
            "scanner_findings_count": len(scanner.findings),
            "mismatches_count": len(scorer.mismatches),
        }

        summary_path = report_dir / "summary.json"
        try:
            summary_path.write_text(
                json.dumps(summary, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError:
            logger.exception("Failed to write summary: %s", summary_path)

    # ------------------------------------------------------------------
    # Result builders
    # ------------------------------------------------------------------

    @staticmethod
    def build_verified_skill(
        *,
        skill_id: str,
        skill_name: str,
        repo_url: str,
        verified_commit: str,
        source_hub: SourceHub,
        trust_level: TrustLevel,
        scan_time: str,
        agent_b: AgentBOutput,
        scorer: ScorerOutput,
        supervisor: SupervisorOutput,
        scanner: ScannerOutput,
    ) -> VerifiedSkill:
        """Build the final VerifiedSkill from all pipeline outputs."""
        # Determine final verification status from supervisor.
        final_status = supervisor.final_status
        if isinstance(final_status, str):
            final_status = VerificationStatus(final_status)

        # Build findings summary for the catalog entry.
        findings_summary = {
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

        # Determine risk level.
        risk_level = scorer.risk_level
        if isinstance(risk_level, str):
            risk_level = ScanSeverity(risk_level)

        return VerifiedSkill(
            id=skill_id,
            name=skill_name,
            repo_url=repo_url,
            verified_commit=verified_commit,
            install_url=repo_url,
            source_hub=source_hub,
            trust_level=trust_level,
            verification_status=final_status,
            overall_score=scorer.overall_score,
            risk_level=risk_level,
            description=scorer.summary[:500] if scorer.summary else "",
            tags=[],
            primary_language=agent_b.primary_language,
            scan_date=scan_time,
            findings_summary=findings_summary,
            verification_level="full_pipeline",
        )

    @staticmethod
    def build_error_skill(
        *,
        skill_id: str,
        skill_name: str,
        repo_url: str,
        source_hub: SourceHub,
        trust_level: TrustLevel,
        scan_time: str,
    ) -> VerifiedSkill:
        """Build a VerifiedSkill representing a pipeline failure."""
        return VerifiedSkill(
            id=skill_id,
            name=skill_name,
            repo_url=repo_url,
            verified_commit="error",
            install_url=repo_url,
            source_hub=source_hub,
            trust_level=trust_level,
            verification_status=VerificationStatus.FAIL,
            overall_score=0,
            risk_level=ScanSeverity.CRITICAL,
            description="Verification pipeline encountered an error.",
            scan_date=scan_time,
            findings_summary={"error": "Pipeline failed -- see logs."},
        )

    @staticmethod
    def make_skill_id(skill_name: str, repo_url: str) -> str:
        """Generate a deterministic skill ID from name and URL.

        Uses a sanitized name with a short UUID suffix for uniqueness.
        """
        # Sanitize name: lowercase, replace non-alnum with hyphens, collapse.
        safe_name = ""
        for ch in skill_name.lower():
            if ch.isalnum():
                safe_name += ch
            elif safe_name and safe_name[-1] != "-":
                safe_name += "-"
        safe_name = safe_name.strip("-")[:60]

        # Short deterministic suffix from URL.
        url_hash = uuid.uuid5(uuid.NAMESPACE_URL, repo_url).hex[:8]

        return f"{safe_name}-{url_hash}" if safe_name else f"skill-{url_hash}"
