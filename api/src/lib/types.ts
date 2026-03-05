export interface Env {
  GITHUB_CLIENT_ID: string;
  GITHUB_CLIENT_SECRET: string;
  STATIC_API_BASE: string;
  API_VERSION: string;
  TURSO_URL: string;
  TURSO_AUTH_TOKEN: string;
}

export interface User {
  id: string;
  github_id: number;
  github_handle: string;
  github_avatar: string;
  display_name: string;
  created_at: string;
  updated_at: string;
}

export interface CustomPackage {
  id: string;
  user_id: string;
  name: string;
  description: string;
  is_default: number;
  is_public: number;
  created_at: string;
  updated_at: string;
}

export interface PackageTag {
  package_id: string;
  tag_path: string;
  added_at: string;
}

export interface PinnedSkill {
  package_id: string;
  skill_id: string;
  added_at: string;
}

export interface PackagePreferences {
  package_id: string;
  min_tier: number;
  min_score: number;
  verified_only: number;
  auto_update: number;
  skill_types: string;
}

export interface AuthSession {
  device_code: string;
  user_code: string;
  user_id: string | null;
  access_token: string | null;
  status: string;
  created_at: string;
  expires_at: string;
}

export interface CliToken {
  id: string;
  user_id: string;
  token_hash: string;
  label: string;
  last_used_at: string | null;
  created_at: string;
  expires_at: string | null;
}

export interface PackageWithDetails extends CustomPackage {
  tags: PackageTag[];
  pinned_skills: PinnedSkill[];
  preferences: PackagePreferences | null;
}

export interface ResolvedSkill {
  id: string;
  name: string;
  description: string;
  repo_url: string;
  install_url: string;
  primary_language: string;
  skill_type: string;
  score: number;
  tier: number;
  verified: boolean;
  install_command: string;
}

export interface ResolvedManifest {
  package_name: string;
  resolved_at: string;
  skills: ResolvedSkill[];
  total: number;
  filters_applied: {
    min_tier: number;
    min_score: number;
    verified_only: boolean;
    skill_types: string;
  };
}

export interface GitHubUser {
  id: number;
  login: string;
  avatar_url: string;
  name: string | null;
}

export interface AgentProfile {
  github_handle: string;
  packages: AgentPackageSummary[];
}

export interface AgentPackageSummary {
  name: string;
  tags: string[];
  pinned_skills: string[];
  total_resolved: number;
}

export type Variables = {
  userId: string;
  user: User;
};

// ── v2 Types ──────────────────────────────────────────────────────────

/** Shape of each entry in search-index.json */
export interface SearchIndexEntry {
  id: string;
  name: string;
  tags: string[];
  description: string;
  stars: number;
  installs: number;
  overall_score: number;
  verification_status: string;
  skill_type: string;
  verified_commit: string;
}

/** Single result item returned by GET /v2/search */
export interface V2SearchResult {
  id: string;
  name: string;
  type: string;
  score: number;
  tier: string;
  verified: boolean;
  safe: boolean;
  tags: string[];
  one_liner: string;
  install: string;
  commit: string;
  report_url: string;
}

/** Response shape for GET /v2/search */
export interface V2SearchResponse {
  total: number;
  offset: number;
  limit: number;
  results: V2SearchResult[];
}

/** Response shape for GET /v2/stats */
export interface V2StatsResponse {
  mcp_servers: { total: number; verified: number; safe: number };
  agent_skills: { total: number; verified: number; safe: number };
  packages: number;
  last_scan: string;
}
