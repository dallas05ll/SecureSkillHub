import { apiFetch, ApiError } from "../api.js";

interface AgentAuditEntry {
  signed: boolean;
  signed_at: string;
  comment: string;
}

interface SkillDetail {
  id: string;
  name: string;
  description: string;
  repo_url: string;
  install_url: string;
  skill_type: string;
  stars: number;
  installs: number;
  verified_commit: string;
  verification_status: string;
  verification_level: string;
  overall_score: number;
  risk_level: string;
  tags: string[];
  owner: string;
  primary_language: string;
  findings_summary: Record<string, unknown>;
  agent_audit: Record<string, AgentAuditEntry>;
}

export async function getReport(apiBase: string, skillId: string) {
  try {
    const skill = await apiFetch<SkillDetail>(apiBase, `/v2/skill/${skillId}`);

    const auditLines = Object.entries(skill.agent_audit || {}).map(
      ([agent, entry]) => {
        const status = entry.signed ? "SIGNED" : "NOT SIGNED";
        return `  ${agent}: ${status} (${entry.signed_at || "n/a"}) — ${entry.comment || "no comment"}`;
      }
    );

    const findings = skill.findings_summary || {};
    const findingsLines = Object.entries(findings).map(
      ([key, val]) => `  ${key}: ${JSON.stringify(val)}`
    );

    const text = [
      `# Security Report: ${skill.name}`,
      "",
      `**ID:** ${skill.id}`,
      `**Type:** ${skill.skill_type}`,
      `**Owner:** ${skill.owner || "unknown"}`,
      `**Language:** ${skill.primary_language || "unknown"}`,
      `**Repo:** ${skill.repo_url}`,
      "",
      `## Verification`,
      `- **Status:** ${skill.verification_status}`,
      `- **Level:** ${skill.verification_level || "unverified"}`,
      `- **Overall Score:** ${skill.overall_score}/100`,
      `- **Risk Level:** ${skill.risk_level}`,
      `- **Verified Commit:** ${skill.verified_commit || "none"}`,
      "",
      `## Popularity`,
      `- **Stars:** ${skill.stars.toLocaleString()}`,
      `- **Installs:** ${skill.installs.toLocaleString()}`,
      `- **Tags:** ${skill.tags.join(", ")}`,
      "",
      `## 5-Agent Audit Trail`,
      auditLines.length > 0 ? auditLines.join("\n") : "  No audit trail available",
      "",
      `## Findings Summary`,
      findingsLines.length > 0 ? findingsLines.join("\n") : "  No findings recorded",
      "",
      `## Install`,
      `\`npx secureskillhub install ${skill.id}\``,
      skill.verified_commit
        ? `(pinned to verified commit ${skill.verified_commit})`
        : "(WARNING: no verified commit — install at your own risk)",
    ].join("\n");

    return { content: [{ type: "text" as const, text }] };
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      return {
        content: [
          {
            type: "text" as const,
            text: `Skill '${skillId}' not found. Check the ID and try again — use search_skills to find valid IDs.`,
          },
        ],
        isError: true,
      };
    }
    if (err instanceof ApiError) {
      return {
        content: [{ type: "text" as const, text: `Report failed: ${err.message}` }],
        isError: true,
      };
    }
    throw err;
  }
}
