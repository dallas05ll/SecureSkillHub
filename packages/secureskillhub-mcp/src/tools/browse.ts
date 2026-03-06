import { apiFetch, ApiError, formatError } from "../api.js";

interface PackageListItem {
  tag: string;
  label: string;
  total_skills: number;
  avg_score: number;
}

interface PackagesResponse {
  total: number;
  packages: PackageListItem[];
}

interface StatsResponse {
  mcp_servers: { total: number; verified: number; safe: number };
  agent_skills: { total: number; verified: number; safe: number };
  packages: number;
  last_scan: string;
}

export async function browseCategories(apiBase: string) {
  try {
    const [pkgs, stats] = await Promise.all([
      apiFetch<PackagesResponse>(apiBase, "/v2/packages"),
      apiFetch<StatsResponse>(apiBase, "/v2/stats"),
    ]);

    const pkgLines = pkgs.packages.map(
      (p) =>
        `- **${p.label}** (\`${p.tag}\`) — ${p.total_skills} skills, avg score ${p.avg_score}`
    );

    const text = [
      `# SecureSkillHub Catalog`,
      "",
      `## Stats`,
      `- **MCP Servers:** ${stats.mcp_servers.total.toLocaleString()} total, ${stats.mcp_servers.verified.toLocaleString()} verified, ${stats.mcp_servers.safe.toLocaleString()} safe`,
      `- **Agent Skills:** ${stats.agent_skills.total.toLocaleString()} total, ${stats.agent_skills.verified.toLocaleString()} verified, ${stats.agent_skills.safe.toLocaleString()} safe`,
      `- **Packages:** ${stats.packages}`,
      `- **Last Scan:** ${stats.last_scan}`,
      "",
      `## Available Packages (${pkgs.total})`,
      "",
      `Use \`get_bundle\` with any tag below to get the full package:`,
      "",
      pkgLines.join("\n"),
      "",
      `## Quick Actions`,
      `- Search: use \`search_skills\` with type='mcp' or type='agent'`,
      `- Get details: use \`get_report\` with a skill ID`,
      `- Install: use \`install\` with a skill ID`,
    ].join("\n");

    return { content: [{ type: "text" as const, text }] };
  } catch (err) {
    return {
      content: [{ type: "text" as const, text: `Browse failed: ${err instanceof ApiError ? err.message : formatError(err)}` }],
      isError: true,
    };
  }
}
