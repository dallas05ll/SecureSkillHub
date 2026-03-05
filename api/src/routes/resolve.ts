import { Hono } from "hono";
import { getDb } from "../db/client.js";
import {
  getPackageWithDetails,
  getDefaultPackage,
} from "../db/queries.js";
import { authMiddleware } from "../middleware/auth.js";
import { getInstallCommand } from "../lib/install-command.js";
import type { Env, Variables, ResolvedSkill, ResolvedManifest, PackageWithDetails } from "../lib/types.js";

const resolve = new Hono<{ Bindings: Env; Variables: Variables }>();

// GET /v1/me/packages/default/resolve — Resolve the default package (auth required)
resolve.get("/me/packages/default/resolve", authMiddleware, async (c) => {
  const userId = c.get("userId");
  const db = getDb(c.env);

  const defaultPkg = await getDefaultPackage(db, userId);
  if (!defaultPkg) {
    return c.json({ error: "No default package found" }, 404);
  }

  const detailed = await getPackageWithDetails(db, defaultPkg.id);
  if (!detailed) {
    return c.json({ error: "Package not found" }, 404);
  }

  const manifest = await resolvePackage(detailed, c.env.STATIC_API_BASE);
  return c.json(manifest);
});

// GET /v1/me/packages/:id/resolve — Resolve a specific package (auth required)
resolve.get("/me/packages/:id/resolve", authMiddleware, async (c) => {
  const userId = c.get("userId");
  const packageId = c.req.param("id")!;
  const db = getDb(c.env);

  const detailed = await getPackageWithDetails(db, packageId);
  if (!detailed) {
    return c.json({ error: "Package not found" }, 404);
  }
  if (detailed.user_id !== userId) {
    return c.json({ error: "Package not found" }, 404);
  }

  const manifest = await resolvePackage(detailed, c.env.STATIC_API_BASE);
  return c.json(manifest);
});

// GET /v1/packages/:id/resolve — Resolve a public package (no auth)
resolve.get("/packages/:id/resolve", async (c) => {
  const packageId = c.req.param("id")!;
  const db = getDb(c.env);

  const detailed = await getPackageWithDetails(db, packageId);
  if (!detailed) {
    return c.json({ error: "Package not found" }, 404);
  }
  if (detailed.is_public !== 1) {
    return c.json({ error: "Package not found" }, 404);
  }

  const manifest = await resolvePackage(detailed, c.env.STATIC_API_BASE);
  return c.json(manifest);
});

// ── Resolution Engine ──────────────────────────────────────────────────

interface StaticPackageData {
  tag_path: string;
  skill_ids: string[];
  [key: string]: unknown;
}

interface StaticSkillData {
  id: string;
  name: string;
  description: string;
  repo_url: string;
  install_url?: string;
  primary_language: string;
  skill_type: string;
  score: number;
  tier: number;
  verified: boolean;
  [key: string]: unknown;
}

async function resolvePackage(
  pkg: PackageWithDetails,
  staticApiBase: string
): Promise<ResolvedManifest> {
  const prefs = pkg.preferences ?? {
    package_id: pkg.id,
    min_tier: 5,
    min_score: 0,
    verified_only: 0,
    auto_update: 1,
    skill_types: "both",
  };

  // Step 1: Fetch all tag packages from static API and collect skill IDs
  const allSkillIds = new Set<string>();

  const tagFetches = pkg.tags.map(async (tag) => {
    try {
      const url = `${staticApiBase}/api/packages/${tag.tag_path}.json`;
      const response = await fetch(url, {
        headers: { "User-Agent": "SecureSkillHub-API" },
      });
      if (!response.ok) return;
      const data = (await response.json()) as StaticPackageData;
      if (data.skill_ids && Array.isArray(data.skill_ids)) {
        for (const id of data.skill_ids) {
          allSkillIds.add(id);
        }
      }
    } catch {
      // Skip tags that fail to resolve
    }
  });

  await Promise.all(tagFetches);

  // Step 2: Add pinned skills
  for (const pin of pkg.pinned_skills) {
    allSkillIds.add(pin.skill_id);
  }

  // Step 3: Fetch skill details from static API
  const skillFetches = Array.from(allSkillIds).map(async (skillId): Promise<StaticSkillData | null> => {
    try {
      const url = `${staticApiBase}/api/skills/${skillId}.json`;
      const response = await fetch(url, {
        headers: { "User-Agent": "SecureSkillHub-API" },
      });
      if (!response.ok) return null;
      return (await response.json()) as StaticSkillData;
    } catch {
      return null;
    }
  });

  const rawSkills = (await Promise.all(skillFetches)).filter(
    (s): s is StaticSkillData => s !== null
  );

  // Step 4: Apply filters
  const filtered = rawSkills.filter((skill) => {
    // min_tier: lower tier number = better, so include skills at or below the threshold
    if (skill.tier > prefs.min_tier) return false;

    // min_score: include skills at or above the minimum score
    if (skill.score < prefs.min_score) return false;

    // verified_only
    if (prefs.verified_only === 1 && !skill.verified) return false;

    // skill_types filter
    if (prefs.skill_types !== "both") {
      if (prefs.skill_types === "mcp_server" && skill.skill_type !== "mcp_server") return false;
      if (prefs.skill_types === "slash_command" && skill.skill_type !== "slash_command") return false;
    }

    return true;
  });

  // Step 5: Build resolved skills with install commands
  const resolvedSkills: ResolvedSkill[] = filtered.map((skill) => ({
    id: skill.id,
    name: skill.name,
    description: skill.description,
    repo_url: skill.repo_url,
    install_url: skill.install_url || "",
    primary_language: skill.primary_language,
    skill_type: skill.skill_type,
    score: skill.score,
    tier: skill.tier,
    verified: skill.verified,
    install_command: getInstallCommand({
      primary_language: skill.primary_language,
      skill_type: skill.skill_type,
      repo_url: skill.repo_url,
      install_url: skill.install_url,
      name: skill.name,
    }),
  }));

  // Sort by score descending, then tier ascending
  resolvedSkills.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    return a.tier - b.tier;
  });

  return {
    package_name: pkg.name,
    resolved_at: new Date().toISOString(),
    skills: resolvedSkills,
    total: resolvedSkills.length,
    filters_applied: {
      min_tier: prefs.min_tier,
      min_score: prefs.min_score,
      verified_only: prefs.verified_only === 1,
      skill_types: prefs.skill_types,
    },
  };
}

export default resolve;
