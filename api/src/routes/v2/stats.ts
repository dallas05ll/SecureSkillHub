import { Hono } from "hono";
import type { Env, Variables, V2StatsResponse } from "../../lib/types.js";
import { getStats, getSearchIndex, getPackagesIndex } from "../../lib/search-cache.js";

const stats = new Hono<{ Bindings: Env; Variables: Variables }>();

interface RawStats {
  mcp_servers: { total: number; verified: number };
  agent_skills: { total: number; verified: number };
  last_build: string;
}

interface RawPkgIndex {
  total_packages: number;
}

stats.get("/", async (c) => {
  const [rawStats, index, pkgIndex] = await Promise.all([
    getStats<RawStats>(c.env.STATIC_API_BASE),
    getSearchIndex(c.env.STATIC_API_BASE),
    getPackagesIndex<RawPkgIndex>(c.env.STATIC_API_BASE),
  ]);

  // Compute "safe" counts from search index (pass = safe)
  let mcpSafe = 0;
  let agentSafe = 0;
  for (const entry of index) {
    if (entry.verification_status === "pass") {
      if (entry.skill_type === "mcp_server") mcpSafe++;
      else agentSafe++;
    }
  }

  const response: V2StatsResponse = {
    mcp_servers: {
      total: rawStats.mcp_servers.total,
      verified: rawStats.mcp_servers.verified,
      safe: mcpSafe,
    },
    agent_skills: {
      total: rawStats.agent_skills.total,
      verified: rawStats.agent_skills.verified,
      safe: agentSafe,
    },
    packages: pkgIndex.total_packages,
    last_scan: rawStats.last_build,
  };

  return c.json(response);
});

export default stats;
