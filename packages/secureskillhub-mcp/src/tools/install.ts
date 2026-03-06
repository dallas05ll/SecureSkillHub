import { apiFetch, ApiError } from "../api.js";

interface SkillDetail {
  id: string;
  name: string;
  repo_url: string;
  install_url: string;
  verified_commit: string;
  verification_status: string;
  risk_level: string;
  overall_score: number;
  skill_type: string;
}

export async function installSkill(apiBase: string, skillId: string) {
  try {
    const skill = await apiFetch<SkillDetail>(apiBase, `/v2/skill/${skillId}`);

    const verified = skill.verification_status === "pass";
    const installCmd = `npx secureskillhub install ${skill.id}`;

    const lines = [
      `# Install: ${skill.name}`,
      "",
      `**ID:** ${skill.id}`,
      `**Type:** ${skill.skill_type}`,
      `**Verification:** ${skill.verification_status}`,
      `**Score:** ${skill.overall_score}/100`,
      `**Risk:** ${skill.risk_level}`,
      "",
    ];

    if (verified && skill.verified_commit) {
      lines.push(
        `## Verified Install (Recommended)`,
        "",
        `\`\`\``,
        installCmd,
        `\`\`\``,
        "",
        `Pinned to verified commit: \`${skill.verified_commit}\``,
        `Repo: ${skill.repo_url}`
      );
    } else if (verified) {
      lines.push(
        `## Install`,
        "",
        `\`\`\``,
        installCmd,
        `\`\`\``,
        "",
        `Note: Skill is verified but no specific commit is pinned.`,
        `Repo: ${skill.repo_url}`
      );
    } else {
      lines.push(
        `## Install (Unverified)`,
        "",
        `\`\`\``,
        installCmd,
        `\`\`\``,
        "",
        `WARNING: This skill has not passed full verification.`,
        `Status: ${skill.verification_status}`,
        `Repo: ${skill.repo_url}`,
        "",
        `Consider using get_report to review the security details before installing.`
      );
    }

    if (skill.install_url && skill.install_url !== skill.repo_url) {
      lines.push("", `**Direct install URL:** ${skill.install_url}`);
    }

    return { content: [{ type: "text" as const, text: lines.join("\n") }] };
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      return {
        content: [
          {
            type: "text" as const,
            text: `Skill '${skillId}' not found. Use search_skills to find valid IDs.`,
          },
        ],
        isError: true,
      };
    }
    if (err instanceof ApiError) {
      return {
        content: [{ type: "text" as const, text: `Install failed: ${err.message}` }],
        isError: true,
      };
    }
    throw err;
  }
}
