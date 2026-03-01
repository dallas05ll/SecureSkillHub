import { Hono } from "hono";
import { getDb } from "../db/client.js";
import { getPublicPackagesByHandle } from "../db/queries.js";
import type { Env, Variables, AgentProfile, AgentPackageSummary } from "../lib/types.js";

const agent = new Hono<{ Bindings: Env; Variables: Variables }>();

// GET /v1/agent/profile/:handle — Public agent-readable profile
agent.get("/profile/:handle", async (c) => {
  const handle = c.req.param("handle");
  const db = getDb(c.env);

  const packages = await getPublicPackagesByHandle(db, handle);

  if (packages.length === 0) {
    return c.json(
      { error: "No public packages found for this user" },
      404
    );
  }

  const packageSummaries: AgentPackageSummary[] = packages.map((pkg) => ({
    name: pkg.name,
    tags: pkg.tags.map((t) => t.tag_path),
    pinned_skills: pkg.pinned_skills.map((p) => p.skill_id),
    total_resolved: pkg.tags.length + pkg.pinned_skills.length,
  }));

  const profile: AgentProfile = {
    github_handle: handle,
    packages: packageSummaries,
  };

  return c.json(profile);
});

export default agent;
