import { Hono } from "hono";
import type { Env, Variables } from "../../lib/types.js";
import { getPackagesIndex } from "../../lib/search-cache.js";

const packages = new Hono<{ Bindings: Env; Variables: Variables }>();

const TAG_RE = /^[a-zA-Z0-9_-]+$/;

interface PkgIndexData {
  total_packages: number;
  packages: Record<
    string,
    { label: string; total_skills: number; avg_score: number }
  >;
}

interface StaticPackageData {
  tag_path: string;
  label: string;
  description: string;
  total_skills: number;
  avg_score: number;
  skills: Array<{
    id: string;
    name: string;
    description: string;
    repo_url: string;
    stars: number;
    installs: number;
    overall_score: number;
    verification_status: string;
    risk_level: string;
    skill_type: string;
    verified_commit: string;
  }>;
}

// GET /v2/packages — List all packages
packages.get("/", async (c) => {
  const indexData = await getPackagesIndex<PkgIndexData>(
    c.env.STATIC_API_BASE
  );

  const list = Object.entries(indexData.packages).map(([tag, info]) => ({
    tag,
    label: info.label,
    total_skills: info.total_skills,
    avg_score: info.avg_score,
  }));

  return c.json({ total: list.length, packages: list });
});

// GET /v2/packages/:tag — Full package with skills
packages.get("/:tag", async (c) => {
  const tag = c.req.param("tag");

  if (!TAG_RE.test(tag)) {
    return c.json({ error: "Invalid package tag format" }, 400);
  }

  const url = `${c.env.STATIC_API_BASE}/api/packages/${tag}.json`;
  const resp = await fetch(url, {
    headers: { "User-Agent": "SecureSkillHub-API/v2" },
    cf: { cacheTtl: 300 },
  });

  if (!resp.ok) {
    return c.json({ error: "Package not found" }, 404);
  }

  const data = (await resp.json()) as StaticPackageData;

  const skills = data.skills.map((s) => ({
    ...s,
    install: `npx secureskillhub install ${s.id}`,
  }));

  return c.json({
    tag: data.tag_path,
    label: data.label,
    description: data.description,
    total_skills: data.total_skills,
    avg_score: data.avg_score,
    skills,
  });
});

// GET /v2/packages/:tag/install — Install instructions only
packages.get("/:tag/install", async (c) => {
  const tag = c.req.param("tag");

  if (!TAG_RE.test(tag)) {
    return c.json({ error: "Invalid package tag format" }, 400);
  }

  const url = `${c.env.STATIC_API_BASE}/api/packages/${tag}.json`;
  const resp = await fetch(url, {
    headers: { "User-Agent": "SecureSkillHub-API/v2" },
    cf: { cacheTtl: 300 },
  });

  if (!resp.ok) {
    return c.json({ error: "Package not found" }, 404);
  }

  const data = (await resp.json()) as StaticPackageData;

  return c.json({
    tag: data.tag_path,
    install_all: `npx secureskillhub install-package ${tag}`,
    skills: data.skills.map((s) => ({
      id: s.id,
      name: s.name,
      install: `npx secureskillhub install ${s.id}`,
    })),
  });
});

export default packages;
