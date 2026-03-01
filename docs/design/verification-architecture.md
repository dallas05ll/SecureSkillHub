# Verification Architecture

How the multi-agent verification pipeline works, end to end. Read this before implementing or modifying any verification run.

## Overview

5 agents, 8 stages, orchestrated by Claude Code. Three agents use LLM inference (A, B, D/E); one is purely deterministic (C*). The pipeline compares what a skill's documentation claims against what its code actually does, anchored by a static scanner immune to prompt injection.

## Execution Model

The main Claude Code session (you) orchestrates the pipeline. Each LLM-based verification agent runs as a **Claude Code Task agent**. Agent C* runs as direct Python code -- no Task agent needed.

Each agent class provides:
- `prepare()` -- collects input data and returns `system_prompt` + `user_message` for the Task agent. The class does NOT call the LLM itself.
- `validate_output(raw_dict)` (agents A and B) -- parses Task agent JSON response into a validated Pydantic model.
- `validate_and_override(raw_output, ...)` (agents D and E) -- parses Task agent JSON, validates against the Pydantic schema, AND applies deterministic safety overrides before returning.
- `_apply_safety_overrides()` (agents D and E only, called internally by `validate_and_override`) -- deterministic Python code that enforces hard rules after the LLM returns, before output is accepted.

## Data Flow

```
Main Agent (Claude Code session)
  |
  +-- Stage 1: Clone repo (git clone --depth 1)
  |     Output: repo_path, verified_commit (HEAD hash)
  |
  +-- Stage 2a: Task Agent A (sonnet) -- docs only         [PARALLEL]
  |     Class:  AgentAMdReader
  |     Input:  agent_a.prepare(repo_path)
  |               -> system_prompt (extract claims from docs)
  |               -> user_message (concatenated .md/.rst/.txt, max 60K chars)
  |     Output: AgentAOutput
  |               -> skill_name, claimed_description, claimed_features,
  |                  claimed_dependencies, claimed_permissions,
  |                  doc_quality_score (0-10), has_skill_md, has_readme, warnings
  |
  +-- Stage 2b: Task Agent B (sonnet) -- code only          [PARALLEL]
  |     Class:  AgentBCodeParser
  |     Input:  code_text (concatenated source files, max 80K chars)
  |               -> system_prompt (report what code actually does)
  |               -> user_message (file_count, primary_language, source code)
  |     Output: AgentBOutput
  |               -> actual_capabilities, imports, system_calls, network_calls,
  |                  file_operations, env_access, findings[], total_files_analyzed,
  |                  primary_language
  |
  +-- Stage 3: Agent C* (direct Python) -- deterministic scanner
  |     Class:  StaticScanner (src/scanner/scanner.py)
  |     Call:   StaticScanner(repo_path).scan()
  |     Method: semgrep rules + regex patterns, no LLM
  |     Output: ScannerOutput
  |               -> scan_id, scanned_at, total_files_scanned, findings[],
  |                  dangerous_calls_count, network_ops_count, file_ops_count,
  |                  env_access_count, obfuscation_count, obfuscation_high_risk_count, injection_patterns_count
  |
  +-- Stage 4: Sanitize all outputs
  |     Method: Pydantic re-validation (max_length enforcement, type checks)
  |     Falls back to model_validate(model_dump()) if Sanitizer unavailable
  |
  +-- Stage 5: Task Agent D (sonnet) -- scorer
  |     Class:  AgentDScorer
  |     Input:  JSON of {agent_a, agent_b, agent_c} outputs (never raw content)
  |     Output: ScorerOutput (LLM response)
  |               -> overall_score (0-100), status, mismatches[], risk_level,
  |                  undocumented_capabilities[], agent_b_missed_findings[], summary
  |     Post:   _apply_safety_overrides(output, scanner) -- deterministic overrides
  |
  +-- Stage 6: Task Agent E (sonnet) -- supervisor
  |     Class:  AgentESupervisor
  |     Input:  JSON of {agent_a, agent_b, agent_c, agent_d} outputs
  |     Output: SupervisorOutput (LLM response)
  |               -> approved, final_status, confidence (0-100),
  |                  agent_consistency_check, compromised_agent_suspicion,
  |                  override_reason, recommendations[], summary
  |     Post:   _apply_safety_overrides(output, scanner, scorer) -- deterministic
  |
  +-- Stage 7: Write reports to data/scan-reports/{skill-id}/
  |     Files: agent_a_docs.json, agent_b_code.json, agent_c_scanner.json,
  |            agent_d_scorer.json, agent_e_supervisor.json, summary.json
  |
  +-- Stage 8: Build VerifiedSkill -> write to data/skills/{id}.json
        Fields: id, name, repo_url, verified_commit, install_url, source_hub,
                trust_level, verification_status, overall_score, risk_level,
                description, tags, stars, owner, primary_language, scan_date,
                last_repo_update, findings_summary, verification_level
```

## Model Routing

| Agent | Model | Rationale |
|-------|-------|-----------|
| Agent A (docs reader) | sonnet | Structured extraction from text; token-efficient |
| Agent B (code parser) | sonnet | Reads lots of source files; cost-effective for bulk analysis |
| Agent C* (scanner) | None (deterministic) | No LLM. Semgrep + regex only. |
| Agent D (scorer) | sonnet | Comparison and scoring; structured JSON in/out |
| Agent E (supervisor) | sonnet | Final review; structured JSON in/out |

The model is specified at Task agent launch time by the orchestrating Claude Code session, not by the agent classes themselves. Agent classes are data preparation layers only.

## Safety Overrides

Deterministic Python code that executes after the LLM returns. No prompt can bypass these.

### Agent D Overrides (`AgentDScorer._apply_safety_overrides`)

| Condition | Action |
|-----------|--------|
| C* found critical-severity findings | Score capped at 40, status -> `fail`, risk -> `high` minimum |
| C* detected high-risk obfuscation (`obfuscation_high_risk_count > 0`) | Score capped at 15, status -> `fail`, risk -> `critical` |
| C* detected injection patterns (`injection_patterns_count > 0`) | Score capped at 10, status -> `fail`, risk -> `critical` |
| Score out of [0, 100] | Clamped to bounds |

### Agent E Overrides (`AgentESupervisor._apply_safety_overrides`)

| Condition | Action |
|-----------|--------|
| C* detected high-risk obfuscation (`obfuscation_high_risk_count > 0`) | approved -> `false`, status -> `fail`, confidence >= 90 |
| C* detected injection patterns | approved -> `false`, status -> `fail`, confidence >= 95 |
| D set status to `fail` but E tries `pass` | Constrained to `manual_review` (fail -> pass forbidden) |
| C* found critical findings | approved -> `false`, status cannot be `pass` |
| Confidence out of [0, 100] | Clamped to bounds |

## Information Barriers

| Agent | Sees Docs | Sees Code | Sees Scanner Output | Sees Other Agent Output |
|-------|-----------|-----------|---------------------|------------------------|
| A | Yes | No | No | No |
| B | No | Yes | No | No |
| C* | N/A (deterministic) | Yes (regex/semgrep) | N/A | No |
| D | No (only A's JSON) | No (only B's JSON) | Yes (C*'s JSON) | A + B + C* JSON only |
| E | No (only A's JSON) | No (only B's JSON) | Yes (C*'s JSON) | A + B + C* + D JSON only |

Agents D and E never see raw skill content. They receive only sanitized, structured JSON from upstream agents.

## Three Verification Levels

### Metadata-Only

- **What runs:** No agents, no clone. Heuristic scoring from metadata fields.
- **Script:** `batch_verify_agent_skills.py`
- **Cost:** Zero (no LLM calls, no git clone).
- **Speed:** Milliseconds per skill.
- **What it catches:** Missing fields, low-quality metadata, unreachable repos.
- **What it misses:** Everything code-level -- no security analysis at all.
- **Scoring:** Heuristic based on field completeness (description, tags, stars, repo_url).
- **Use for:** Quick triage of agent skills that don't have GitHub repos or need fast categorization.

### C*-Scanned (Scanner-Only)

- **What runs:** Agent C* only (deterministic scanner).
- **Script:** `run_verify_sample.py`
- **Cost:** Zero (no LLM calls).
- **Speed:** Seconds per skill.
- **What it catches:** Known-bad patterns -- dangerous calls, obfuscation, injection patterns, suspicious URLs, env access, network ops, file ops.
- **What it misses:** Doc-vs-code mismatches, undocumented capabilities, semantic analysis of behavior.
- **Scoring:** Heuristic based on finding counts and severity (see `docs/workflows/verification.md`).
- **Use for:** Bulk triage of the catalog. Getting from >90% unverified to a baseline.

### Fully Verified (5-Agent Pipeline)

- **What runs:** All 5 agents (A + B + C* + D + E).
- **Script:** `run_verify_strict_5agent.py` (deterministic local implementation) or Claude Code Task agent orchestration using `src/verification/pipeline.py` utilities
- **Cost:** 4 LLM Task agent calls per skill (Task agent path) or zero (deterministic `run_verify_strict_5agent.py` path).
- **Speed:** Minutes per skill (Task agent path) or seconds (deterministic path).
- **What it catches:** Everything C* catches, plus doc-vs-code mismatches, undocumented capabilities, agent compromise signals.
- **Scoring:** LLM-driven comparison (Agent D) with deterministic safety overrides.
- **Use for:** High-star skills, skills flagged by C*, anything going into a curated package.

## How to Run a Full Verification

As the orchestrating Claude Code agent:

1. Clone the target repository to a temp directory.
2. Get the HEAD commit hash (`git rev-parse HEAD`).
3. Call `AgentAMdReader().prepare(repo_path)` to get the prompt payload.
4. Launch a Task agent with the system prompt and user message from step 3. Parse the JSON response via `AgentAMdReader.validate_output(raw)`.
5. In parallel with step 3-4, call `AgentBCodeParser().prepare(repo_path)` to get the prompt payload. Launch a Task agent with the system prompt and user message. Parse via `AgentBCodeParser.validate_output(raw)`.
6. Call `StaticScanner(repo_path).scan()` directly (no Task agent).
7. Re-validate all outputs through Pydantic (`model_validate(model_dump())`).
8. Call `AgentDScorer().prepare(agent_a, agent_b, scanner)` to build the prompt payload. Launch a Task agent with the system prompt and user message. Call `AgentDScorer().validate_and_override(raw_output, scanner)` to parse and apply safety overrides.
9. Call `AgentESupervisor().prepare(agent_a, agent_b, scanner, scorer)` to build the prompt payload. Launch a Task agent. Call `AgentESupervisor().validate_and_override(raw_output, scanner, scorer)` to parse and apply safety overrides.
10. Write reports to `data/scan-reports/{skill-id}/`.
11. Build the `VerifiedSkill` object and write to `data/skills/{id}.json`.

## Key Source Files

| File | Purpose |
|------|---------|
| `src/verification/pipeline.py` | Pipeline utilities (clone, scan, sanitize, write reports, build result) |
| `src/verification/agent_a_md_reader.py` | Agent A: doc extraction + prompt preparation |
| `src/verification/agent_b_code_parser.py` | Agent B: code extraction + prompt preparation |
| `src/scanner/scanner.py` | Agent C*: deterministic static analysis |
| `src/verification/agent_d_scorer.py` | Agent D: scoring + safety overrides |
| `src/verification/agent_e_supervisor.py` | Agent E: supervision + safety overrides |
| `src/sanitizer/schemas.py` | All Pydantic data contracts |
| `src/sanitizer/sanitizer.py` | Inter-agent output sanitization |
| `run_verify_strict_5agent.py` | Full 5-agent deterministic verification runner |
| `run_verify_sample.py` | Scanner-only (C*) batch verification |
| `batch_verify_agent_skills.py` | Metadata-only quick triage |
