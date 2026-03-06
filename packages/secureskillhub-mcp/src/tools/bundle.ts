import { apiFetch, ApiError, formatError } from "../api.js";

interface PackageSkill {
  id: string;
  name: string;
  description: string;
  stars: number;
  installs: number;
  overall_score: number;
  verification_status: string;
  risk_level: string;
  skill_type: string;
  install: string;
}

interface PackageResponse {
  tag: string;
  label: string;
  description: string;
  total_skills: number;
  avg_score: number;
  skills: PackageSkill[];
}

export async function getBundle(apiBase: string, tag: string) {
  try {
    const pkg = await apiFetch<PackageResponse>(apiBase, `/v2/packages/${tag}`);

    const skillLines = pkg.skills.map((s, i) => {
      const badge = s.verification_status === "pass" ? "Verified" : s.verification_status;
      const score = Math.max(s.stars || 0, s.installs || 0);
      return `${i + 1}. **${s.name}** (${s.id})\n   Score: ${score} | ${badge} | Risk: ${s.risk_level}\n   ${s.description.slice(0, 120)}\n   Install: \`${s.install}\``;
    });

    const text = [
      `# Package: ${pkg.label}`,
      "",
      `**Tag:** ${pkg.tag}`,
      `**Description:** ${pkg.description}`,
      `**Total Skills:** ${pkg.total_skills}`,
      `**Average Score:** ${pkg.avg_score}`,
      "",
      `## Skills`,
      "",
      skillLines.join("\n\n"),
      "",
      `## Install All`,
      `\`npx secureskillhub install-package ${tag}\``,
    ].join("\n");

    return { content: [{ type: "text" as const, text }] };
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      return {
        content: [
          {
            type: "text" as const,
            text: `Package '${tag}' not found. Use browse_categories to see available packages.`,
          },
        ],
        isError: true,
      };
    }
    return {
      content: [{ type: "text" as const, text: `Bundle failed: ${err instanceof ApiError ? err.message : formatError(err)}` }],
      isError: true,
    };
  }
}
