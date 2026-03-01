export function getInstallCommand(skill: {
  primary_language: string;
  skill_type: string;
  repo_url: string;
  install_url?: string;
  name: string;
}): string {
  if (skill.skill_type === "mcp_server") {
    if (["TypeScript", "JavaScript"].includes(skill.primary_language)) {
      return `npx -y ${skill.name}`;
    }
    if (skill.primary_language === "Python") {
      return `uvx ${skill.name}`;
    }
  }
  return `git clone ${skill.repo_url}`;
}
