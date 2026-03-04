export function getInstallCommand(skill: {
  primary_language: string;
  skill_type: string;
  repo_url: string;
  install_url?: string;
  name: string;
}): string {
  const lang = (skill.primary_language || "").toLowerCase();
  if (skill.skill_type === "mcp_server") {
    if (["typescript", "javascript"].includes(lang)) {
      return `npx -y "${skill.name}"`;
    }
    if (lang === "python") {
      return `uvx "${skill.name}"`;
    }
  }
  return `git clone ${skill.repo_url}`;
}
