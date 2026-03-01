"""
Agent D -- Scorer.

Orchestrated via Claude Code Task agents. No API key is needed.

Compares the *claimed* behaviour from Agent A (docs) against the *actual*
behaviour from Agent B (code) and Agent C* (deterministic scanner).

Key responsibilities:
- Detect mismatches between docs and code.
- Flag undocumented capabilities.
- Detect whether Agent B may have been compromised (i.e. missed dangerous
  calls that C* found deterministically).
- Produce an overall risk score.

Workflow:
    1. Call ``prepare(agent_a, agent_b, scanner)`` to build the prompt payload
       (system prompt + user message + expected output fields) from the three
       upstream agent outputs.
    2. Hand the returned dict to a Claude Code Task agent, which performs the
       actual LLM inference.
    3. Call ``validate_and_override(raw_output, scanner)`` to parse the Task
       agent's JSON response, validate it against the Pydantic schema, and
       apply deterministic safety overrides.

The ``prepare()`` method returns the prompt data; a Task agent does the LLM work.
The output must conform to ``ScorerOutput`` (defined in src.sanitizer.schemas).
"""

from __future__ import annotations

import json
import logging

from src.sanitizer.schemas import (
    AgentAOutput,
    AgentBOutput,
    ScannerOutput,
    ScanSeverity,
    ScorerOutput,
    VerificationStatus,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are Agent D -- the Scorer in a multi-agent security verification pipeline.

You receive three structured JSON reports:
1. Agent A output -- what the skill's documentation CLAIMS (features,
   dependencies, permissions).
2. Agent B output -- what the code ACTUALLY does (capabilities, imports,
   system calls, network calls, file ops, env access).
3. Agent C* output -- deterministic static scanner findings (ground truth
   for dangerous patterns).

YOUR JOB:
- Compare claimed vs actual behaviour.
- Identify mismatches: things the code does that docs don't mention, or
  things docs promise that code doesn't deliver.
- Cross-check Agent B against C*.  If C* found dangerous patterns that B
  did NOT report, this is a red flag -- B may have been compromised or
  its analysis was incomplete.
- Compute an overall score (0-100) and risk level.

SCORING GUIDELINES:
- Start at 100 and deduct points:
  * -5  per minor undocumented capability (e.g. extra file reads).
  * -10 per medium mismatch (e.g. undocumented network call).
  * -20 per high-severity mismatch (e.g. docs say "read-only" but code
        writes files or makes system calls).
  * -30 per critical mismatch (e.g. docs say "safe helper" but code has
        os.system, eval, exec, or obfuscation).
  * -15 per C* finding that B missed (agent compromise indicator).
- Minimum score is 0.

STATUS RULES:
- score >= 80 AND no critical/high findings => "pass"
- score >= 50 AND no critical findings       => "manual_review"
- otherwise                                  => "fail"

RISK LEVEL:
- critical: any obfuscation, eval/exec with user input, or undocumented
  reverse shells / data exfiltration.
- high: undocumented system calls, undocumented network access.
- medium: undocumented file operations, undocumented dependencies.
- low: minor doc-code discrepancies.
- info: docs and code match well.

Return a JSON object matching this schema EXACTLY:
{
  "overall_score": int (0-100),
  "status": "pass" | "fail" | "manual_review",
  "mismatches": [
    {
      "category": str,
      "claimed": str,
      "actual": str,
      "severity": "info" | "low" | "medium" | "high" | "critical",
      "explanation": str
    }
  ],
  "risk_level": "info" | "low" | "medium" | "high" | "critical",
  "undocumented_capabilities": [str],
  "agent_b_missed_findings": [str],
  "summary": str
}
"""

# Expected output field names (mirrors ScorerOutput schema).
OUTPUT_SCHEMA_FIELDS: list[str] = [
    "overall_score",
    "status",
    "mismatches",
    "risk_level",
    "undocumented_capabilities",
    "agent_b_missed_findings",
    "summary",
]


class AgentDScorer:
    """Compares Agent A, B, and C* outputs and prepares prompt data for a
    Claude Code Task agent.

    This class is a *data preparation + output validation + safety override*
    layer.  It does NOT call any LLM API directly.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def prepare(
        self,
        agent_a: AgentAOutput,
        agent_b: AgentBOutput,
        scanner: ScannerOutput,
    ) -> dict:
        """Build the prompt payload for a Task agent from upstream outputs.

        Parameters
        ----------
        agent_a : AgentAOutput
            What the docs claim.
        agent_b : AgentBOutput
            What the code actually does (LLM analysis).
        scanner : ScannerOutput
            What the deterministic scanner found (ground truth).

        Returns
        -------
        dict
            A dictionary with keys:
            - ``system_prompt``  : str -- the system prompt for the Task agent.
            - ``user_message``   : str -- JSON payload of all three agent outputs.
            - ``output_schema``  : list[str] -- field names expected in the JSON response.
        """
        input_payload = {
            "agent_a_docs_analysis": agent_a.model_dump(mode="json"),
            "agent_b_code_analysis": agent_b.model_dump(mode="json"),
            "agent_c_scanner_findings": scanner.model_dump(mode="json"),
        }

        return {
            "system_prompt": SYSTEM_PROMPT,
            "user_message": json.dumps(input_payload, indent=2),
            "output_schema": OUTPUT_SCHEMA_FIELDS,
        }

    def validate_and_override(
        self,
        raw_output: dict,
        scanner: ScannerOutput,
    ) -> ScorerOutput:
        """Validate raw LLM output and apply deterministic safety overrides.

        Parameters
        ----------
        raw_output : dict
            The parsed JSON dict returned by the Claude Code Task agent.
        scanner : ScannerOutput
            The deterministic scanner output (used for safety overrides).

        Returns
        -------
        ScorerOutput
            A validated and safety-overridden Pydantic model instance.
        """
        overridden = self._apply_safety_overrides(dict(raw_output), scanner)
        return ScorerOutput.model_validate(overridden)

    # ------------------------------------------------------------------
    # Safety overrides -- deterministic guardrails the LLM cannot bypass
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_safety_overrides(
        parsed: dict,
        scanner: ScannerOutput,
    ) -> dict:
        """Enforce hard rules regardless of what the LLM returned.

        These overrides exist because the LLM's judgement can be manipulated
        by adversarial skill content.  The deterministic scanner is the
        source of truth for dangerous patterns.
        """
        # If the scanner found critical patterns, score can never be above 40
        # and status must be "fail" unless it's already lower.
        critical_scanner_findings = [
            f for f in scanner.findings if f.severity == ScanSeverity.CRITICAL
        ]

        if critical_scanner_findings:
            parsed["overall_score"] = min(parsed.get("overall_score", 0), 40)
            parsed["status"] = VerificationStatus.FAIL.value
            if parsed.get("risk_level") not in ("critical",):
                parsed["risk_level"] = ScanSeverity.HIGH.value

        # If high-risk obfuscation was detected, instant fail.
        if scanner.obfuscation_high_risk_count > 0:
            parsed["overall_score"] = min(parsed.get("overall_score", 0), 15)
            parsed["status"] = VerificationStatus.FAIL.value
            parsed["risk_level"] = ScanSeverity.CRITICAL.value

        # If injection patterns found, instant fail.
        if scanner.injection_patterns_count > 0:
            parsed["overall_score"] = min(parsed.get("overall_score", 0), 10)
            parsed["status"] = VerificationStatus.FAIL.value
            parsed["risk_level"] = ScanSeverity.CRITICAL.value

        # Ensure score bounds.
        score = parsed.get("overall_score", 0)
        parsed["overall_score"] = max(0, min(100, score))

        return parsed
