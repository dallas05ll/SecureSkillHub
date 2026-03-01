/** Shared types used across the CLI, mirroring the API types. */

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

export interface DeviceFlowStart {
  device_code: string;
  user_code: string;
  verification_url: string;
  expires_in: number;
  interval: number;
}

export interface DeviceFlowPollResult {
  status: "pending" | "complete" | "expired";
  token?: string;
  github_handle?: string;
}

export interface TagNode {
  id: string;
  label: string;
  children?: TagNode[];
}

export interface SearchIndexEntry {
  id: string;
  name: string;
  description: string;
  tags: string[];
  stars: number;
  overall_score: number;
  verification_status: string;
  skill_type: string;
}
