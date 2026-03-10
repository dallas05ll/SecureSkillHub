"""
SecureSkillHub Shared Schemas — THE single source of truth for all data contracts.

Every agent reads from this file. No agent modifies it.
All string fields have max_length caps to prevent injection propagation.
All inter-agent communication uses these Pydantic models (structured JSON only).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SkillType(str, Enum):
    MCP_SERVER = "mcp_server"       # MCP protocol servers (tools, resources)
    AGENT_SKILL = "agent_skill"     # SKILL.md-based instruction packages


class SourceHub(str, Enum):
    # MCP sources
    GLAMA = "glama"
    MCP_SO = "mcp_so"
    SMITHERY = "smithery"
    PULSEMCP = "pulsemcp"
    # Agent skill sources
    CLAUDE_SKILLS_HUB = "claude_skills_hub"
    SKILLSMP = "skillsmp"
    SKILLHUB = "skillhub"
    SKILLS_DIRECTORY = "skills_directory"
    SKILLS_SH = "skills_sh"
    # General sources
    AWESOME_LIST = "awesome_list"
    GITHUB_SEARCH = "github_search"


class TrustLevel(str, Enum):
    HIGH = "high"           # Anthropic official
    MEDIUM = "medium"       # Curated directories (claudeskills.info)
    LOW = "low"             # SkillsMP, mcp.so (no vetting)
    DANGEROUS = "dangerous" # Unknown origin


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    PASS = "pass"
    FAIL = "fail"
    MANUAL_REVIEW = "manual_review"
    UPDATED_UNVERIFIED = "updated_unverified"


class VerificationLevel(str, Enum):
    """How the skill was verified — which pipeline path was used."""
    FULL_PIPELINE = "full_pipeline"     # All 5 agents (A+B+C*+D+E)
    SCANNER_ONLY = "scanner_only"       # Agent C* only (deterministic scanner)
    METADATA_ONLY = "metadata_only"     # No clone, heuristic-based


class ScanSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Crawler Output
# ---------------------------------------------------------------------------

class DiscoveredSkill(BaseModel):
    """A skill discovered by a crawler agent from a source hub."""
    name: str = Field(max_length=200)
    repo_url: str = Field(max_length=500)
    source_hub: SourceHub
    skill_type: SkillType = SkillType.MCP_SERVER
    trust_level: TrustLevel = TrustLevel.LOW
    description: str = Field(default="", max_length=500)
    stars: int = Field(default=0, ge=0)
    source_tags: list[str] = Field(default_factory=list)
    last_updated: Optional[str] = Field(default=None, max_length=40)
    owner: str = Field(default="", max_length=200)


class CrawlerBatch(BaseModel):
    """Output of a single crawler run."""
    source_hub: SourceHub
    crawled_at: str = Field(max_length=40)
    skills: list[DiscoveredSkill]
    total_found: int = Field(ge=0)
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent A: Documentation Reader Output
# ---------------------------------------------------------------------------

class AgentAOutput(BaseModel):
    """What the skill CLAIMS to do (from docs only)."""
    skill_name: str = Field(max_length=200)
    claimed_description: str = Field(max_length=1000)
    claimed_features: list[str] = Field(default_factory=list)
    claimed_dependencies: list[str] = Field(default_factory=list)
    claimed_permissions: list[str] = Field(default_factory=list)
    doc_quality_score: int = Field(ge=0, le=10)
    has_skill_md: bool = False
    has_readme: bool = False
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent B: Code Parser Output
# ---------------------------------------------------------------------------

class CodeFinding(BaseModel):
    """A specific finding from code analysis."""
    category: str = Field(max_length=100)
    detail: str = Field(max_length=500)
    file_path: str = Field(max_length=300)
    line_number: Optional[int] = None
    severity: ScanSeverity = ScanSeverity.INFO


class AgentBOutput(BaseModel):
    """What the code ACTUALLY does (from code only)."""
    actual_capabilities: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    system_calls: list[str] = Field(default_factory=list)
    network_calls: list[str] = Field(default_factory=list)
    file_operations: list[str] = Field(default_factory=list)
    env_access: list[str] = Field(default_factory=list)
    findings: list[CodeFinding] = Field(default_factory=list)
    total_files_analyzed: int = Field(ge=0, default=0)
    primary_language: str = Field(default="unknown", max_length=50)


# ---------------------------------------------------------------------------
# Agent C*: Deterministic Scanner Output
# ---------------------------------------------------------------------------

class ScanFinding(BaseModel):
    """A finding from the deterministic static analyzer."""
    rule_id: str = Field(max_length=100)
    category: str = Field(max_length=100)
    severity: ScanSeverity
    message: str = Field(max_length=500)
    file_path: str = Field(max_length=300)
    line_number: Optional[int] = None
    matched_pattern: str = Field(default="", max_length=200)


class ScannerOutput(BaseModel):
    """Output from the deterministic scanner (Agent C*)."""
    scan_id: str = Field(max_length=100)
    scanned_at: str = Field(max_length=30)
    total_files_scanned: int = Field(ge=0)
    findings: list[ScanFinding] = Field(default_factory=list)
    dangerous_calls_count: int = Field(ge=0, default=0)
    network_ops_count: int = Field(ge=0, default=0)
    file_ops_count: int = Field(ge=0, default=0)
    env_access_count: int = Field(ge=0, default=0)
    obfuscation_count: int = Field(ge=0, default=0)
    obfuscation_high_risk_count: int = Field(ge=0, default=0)  # Only high-risk patterns (rot13, marshal, chr concat, etc.)
    injection_patterns_count: int = Field(ge=0, default=0)


# ---------------------------------------------------------------------------
# Agent D: Scorer Output
# ---------------------------------------------------------------------------

class MismatchDetail(BaseModel):
    """A specific mismatch between claimed and actual behavior."""
    category: str = Field(max_length=100)
    claimed: str = Field(max_length=500)
    actual: str = Field(max_length=500)
    severity: ScanSeverity
    explanation: str = Field(max_length=500)


class ScorerOutput(BaseModel):
    """Comparison of docs (A) vs code (B) vs scanner (C*)."""
    overall_score: int = Field(ge=0, le=100)
    status: VerificationStatus
    mismatches: list[MismatchDetail] = Field(default_factory=list)
    risk_level: ScanSeverity
    undocumented_capabilities: list[str] = Field(default_factory=list)
    agent_b_missed_findings: list[str] = Field(default_factory=list)
    summary: str = Field(max_length=1000)


# ---------------------------------------------------------------------------
# Agent E: Supervisor Output
# ---------------------------------------------------------------------------

class SupervisorOutput(BaseModel):
    """Final review and sign-off from the supervisor agent."""
    approved: bool
    final_status: VerificationStatus
    confidence: int = Field(ge=0, le=100)
    agent_consistency_check: bool = True
    compromised_agent_suspicion: Optional[str] = Field(default=None, max_length=500)
    override_reason: Optional[str] = Field(default=None, max_length=500)
    recommendations: list[str] = Field(default_factory=list)
    summary: str = Field(max_length=1000)


# ---------------------------------------------------------------------------
# Agent Audit Trail
# ---------------------------------------------------------------------------

class AgentAuditEntry(BaseModel):
    """Per-agent signature in the audit trail."""
    signed: bool = False
    signed_at: Optional[str] = None
    comment: str = ""


class AgentAudit(BaseModel):
    """Audit trail showing which agents reviewed a skill."""
    agents_completed: int = 0
    agents_required: int = 5
    pipeline_run_at: Optional[str] = None
    agent_a: Optional[dict] = None
    agent_b: Optional[dict] = None
    agent_c_star: Optional[dict] = None
    agent_d: Optional[dict] = None
    agent_e: Optional[dict] = None
    manager_summary: str = ""


# ---------------------------------------------------------------------------
# Verified Skill (final catalog entry)
# ---------------------------------------------------------------------------

class VerifiedSkill(BaseModel):
    """A fully verified skill in the catalog."""
    id: str = Field(max_length=200)
    name: str = Field(max_length=200)
    repo_url: str = Field(max_length=500)
    verified_commit: str = Field(max_length=64)
    install_url: str = Field(default="", max_length=600)
    source_hub: SourceHub
    trust_level: TrustLevel = TrustLevel.LOW
    verification_status: VerificationStatus
    overall_score: int = Field(ge=0, le=100)
    risk_level: ScanSeverity
    description: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list)
    stars: int = Field(default=0, ge=0)
    installs: int = Field(default=0, ge=0)
    skill_type: SkillType = SkillType.MCP_SERVER
    owner: str = Field(default="", max_length=200)
    primary_language: str = Field(default="unknown", max_length=50)
    scan_date: str = Field(max_length=30)
    last_repo_update: Optional[str] = Field(default=None, max_length=30)
    findings_summary: dict = Field(default_factory=dict)
    verification_level: Optional[str] = None  # full_pipeline, scanner_only, metadata_only
    agent_audit: Optional[dict] = None  # Per-agent audit trail (see AgentAudit model)
    has_plugin_json: Optional[bool] = None  # True if repo has .claude-plugin/ or plugin.json


# ---------------------------------------------------------------------------
# Tag Navigation (4-layer hierarchy)
# ---------------------------------------------------------------------------

class TagNode(BaseModel):
    """A node in the 4-layer tag hierarchy."""
    id: str = Field(max_length=100)
    label: str = Field(max_length=100)
    description: str = Field(default="", max_length=300)
    children: list[TagNode] = Field(default_factory=list)
    skill_count: int = Field(ge=0, default=0)


class TagTree(BaseModel):
    """The full tag navigation tree."""
    version: str = Field(default="1.0", max_length=10)
    updated_at: str = Field(max_length=30)
    categories: list[TagNode] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stats & Packages
# ---------------------------------------------------------------------------

class HubStats(BaseModel):
    """Hub-wide statistics."""
    total_skills: int = Field(ge=0, default=0)
    verified_skills: int = Field(ge=0, default=0)
    failed_skills: int = Field(ge=0, default=0)
    pending_review: int = Field(ge=0, default=0)
    total_scans_run: int = Field(ge=0, default=0)
    last_crawl: Optional[str] = Field(default=None, max_length=30)
    last_build: Optional[str] = Field(default=None, max_length=30)
    sources: dict[str, int] = Field(default_factory=dict)
    skill_types: dict[str, int] = Field(default_factory=dict)
    verification_tiers: dict[str, int] = Field(default_factory=dict)


class SkillPackage(BaseModel):
    """An auto-curated package of skills for a tag path."""
    tag_path: str = Field(max_length=300)
    label: str = Field(max_length=200)
    description: str = Field(default="", max_length=500)
    skill_ids: list[str] = Field(default_factory=list)
    total_skills: int = Field(ge=0, default=0)
    avg_score: float = Field(ge=0, le=100, default=0)
    generated_at: str = Field(max_length=30)


class CustomPackageRef(BaseModel):
    """Reference to a user's custom package (for agent discovery)."""
    user_handle: str = Field(max_length=200)
    package_name: str = Field(max_length=100)
    tag_paths: list[str] = Field(default_factory=list)
    pinned_skill_ids: list[str] = Field(default_factory=list)
    is_public: bool = False


# Enable recursive model for TagNode
TagNode.model_rebuild()
