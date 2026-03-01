"""
Agent E -- Supervisor.

Orchestrated via Claude Code Task agents. No API key is needed.

The final review agent in the verification pipeline. Agent E receives
structured JSON summaries from ALL prior agents and has the FINAL say on
whether a skill is approved or rejected.

Key responsibilities:
- Check for consistency across all agent outputs.
- Look for signs of agent compromise (e.g. Agent B gave a suspiciously
  clean report while C* found many issues).
- Can OVERRIDE the scorer's decision (in either direction).
- Produce final recommendations for human reviewers.

Workflow:
    1. Call ``prepare(agent_a, agent_b, scanner, scorer)`` to build the prompt
       payload (system prompt + user message + expected output fields) from all
       upstream agent outputs.
    2. Hand the returned dict to a Claude Code Task agent, which performs the
       actual LLM inference.
    3. Call ``validate_and_override(raw_output, scanner, scorer)`` to parse the
       Task agent's JSON response, validate it against the Pydantic schema, and
       apply deterministic safety overrides.

The ``prepare()`` method returns the prompt data; a Task agent does the LLM work.
The output must conform to ``SupervisorOutput`` (defined in src.sanitizer.schemas).
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
    SupervisorOutput,
    VerificationStatus,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are Agent E -- the Supervisor in a multi-agent security verification
pipeline.  You have the FINAL say.

You receive structured JSON summaries from four sources:
1. Agent A -- documentation analysis (what the skill claims).
2. Agent B -- code analysis (what the code actually does).
3. Agent C* -- deterministic scanner (ground truth for patterns).
4. Agent D -- scorer output (comparison and score).

YOUR JOB:
1. CONSISTENCY CHECK: Do the agent outputs tell a coherent story?
   - Does Agent D's score reflect the severity of findings from A, B, C*?
   - Are there contradictions between agents?

2. AGENT COMPROMISE DETECTION: Could any agent have been manipulated?
   Red flags include:
   - Agent B reports "no issues" while C* found critical patterns.
   - Agent A reports rich documentation but B found minimal code.
   - Agent D gave a high score despite many C* findings.
   - Any agent output that seems suspiciously bland or incomplete.

3. FINAL DECISION:
   - approved=true: skill is safe to list in the catalog.
   - approved=false: skill must be rejected or sent for manual review.
   - You CAN override Agent D's score if you have good reason.

4. RECOMMENDATIONS:
   - If rejected, explain what would need to change.
   - If approved with caveats, note the caveats.
   - If you suspect compromise, flag it clearly.

APPROVAL RULES:
- NEVER approve if C* found obfuscation or injection patterns.
- NEVER approve if Agent B missed critical C* findings (compromise signal).
- If score < 50, default to reject unless you have strong reason to override.
- If score 50-79, default to manual_review.
- If score >= 80, default to approve.

Return a JSON object matching this schema EXACTLY:
{
  "approved": bool,
  "final_status": "pass" | "fail" | "manual_review",
  "confidence": int (0-100),
  "agent_consistency_check": bool,
  "compromised_agent_suspicion": str | null,
  "override_reason": str | null,
  "recommendations": [str],
  "summary": str
}
"""

# Expected output field names (mirrors SupervisorOutput schema).
OUTPUT_SCHEMA_FIELDS: list[str] = [
    "approved",
    "final_status",
    "confidence",
    "agent_consistency_check",
    "compromised_agent_suspicion",
    "override_reason",
    "recommendations",
    "summary",
]


class AgentESupervisor:
    """Reviews all agent outputs and prepares prompt data for a Claude Code
    Task agent.

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
        scorer: ScorerOutput,
    ) -> dict:
        """Build the prompt payload for a Task agent from all upstream outputs.

        Parameters
        ----------
        agent_a : AgentAOutput
        agent_b : AgentBOutput
        scanner : ScannerOutput
        scorer  : ScorerOutput

        Returns
        -------
        dict
            A dictionary with keys:
            - ``system_prompt``  : str -- the system prompt for the Task agent.
            - ``user_message``   : str -- JSON payload of all four agent outputs.
            - ``output_schema``  : list[str] -- field names expected in the JSON response.
        """
        input_payload = {
            "agent_a_docs_analysis": agent_a.model_dump(mode="json"),
            "agent_b_code_analysis": agent_b.model_dump(mode="json"),
            "agent_c_scanner_findings": scanner.model_dump(mode="json"),
            "agent_d_scorer_output": scorer.model_dump(mode="json"),
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
        scorer: ScorerOutput,
    ) -> SupervisorOutput:
        """Validate raw LLM output and apply deterministic safety overrides.

        Parameters
        ----------
        raw_output : dict
            The parsed JSON dict returned by the Claude Code Task agent.
        scanner : ScannerOutput
            The deterministic scanner output (used for safety overrides).
        scorer : ScorerOutput
            The scorer output (used for safety overrides).

        Returns
        -------
        SupervisorOutput
            A validated and safety-overridden Pydantic model instance.
        """
        overridden = self._apply_safety_overrides(dict(raw_output), scanner, scorer)
        return SupervisorOutput.model_validate(overridden)

    # ------------------------------------------------------------------
    # Safety overrides -- the LLM cannot override these
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_safety_overrides(
        parsed: dict,
        scanner: ScannerOutput,
        scorer: ScorerOutput,
    ) -> dict:
        """Enforce hard safety rules that no LLM output can circumvent."""

        # HARD RULE: Never approve if high-risk obfuscation is detected.
        if scanner.obfuscation_high_risk_count > 0:
            parsed["approved"] = False
            parsed["final_status"] = VerificationStatus.FAIL.value
            parsed["confidence"] = max(parsed.get("confidence", 0), 90)
            if not parsed.get("override_reason"):
                parsed["override_reason"] = (
                    "Deterministic override: obfuscation detected by scanner."
                )

        # HARD RULE: Never approve if injection patterns are detected.
        if scanner.injection_patterns_count > 0:
            parsed["approved"] = False
            parsed["final_status"] = VerificationStatus.FAIL.value
            parsed["confidence"] = max(parsed.get("confidence", 0), 95)
            if not parsed.get("override_reason"):
                parsed["override_reason"] = (
                    "Deterministic override: injection patterns detected by scanner."
                )

        # HARD RULE: If scorer already set status to "fail", supervisor
        # cannot upgrade to "pass" (only to "manual_review" at best).
        if scorer.status == VerificationStatus.FAIL:
            if parsed.get("final_status") == VerificationStatus.PASS.value:
                parsed["final_status"] = VerificationStatus.MANUAL_REVIEW.value
                parsed["override_reason"] = (
                    "Supervisor attempted to override FAIL to PASS; "
                    "constrained to manual_review."
                )

        # HARD RULE: If scanner found critical findings, never approve.
        critical_count = sum(
            1 for f in scanner.findings if f.severity == ScanSeverity.CRITICAL
        )
        if critical_count > 0:
            parsed["approved"] = False
            if parsed.get("final_status") == VerificationStatus.PASS.value:
                parsed["final_status"] = VerificationStatus.FAIL.value

        # Ensure confidence bounds.
        conf = parsed.get("confidence", 50)
        parsed["confidence"] = max(0, min(100, conf))

        # INVARIANT: approved=True requires final_status="pass"
        if parsed.get("final_status") != VerificationStatus.PASS.value:
            parsed["approved"] = False

        return parsed
