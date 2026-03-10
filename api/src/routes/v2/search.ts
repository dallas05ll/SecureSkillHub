import { Hono } from "hono";
import type { Env, Variables, V2SearchResult, V2SearchResponse } from "../../lib/types.js";
import { getSearchIndex } from "../../lib/search-cache.js";
import { computeTier, computeScore } from "../../lib/tier.js";
import type { TierLetter } from "../../lib/tier.js";

const search = new Hono<{ Bindings: Env; Variables: Variables }>();

const VALID_TYPES = new Set(["mcp", "agent", "all"]);
const VALID_SORTS = new Set(["score", "name"]);

search.get("/", async (c) => {
  // ── Parse parameters ────────────────────────────────────────────────
  const type = c.req.query("type") || "all";
  const tagsParam = c.req.query("tags");
  const tierParam = c.req.query("tier");
  const verifiedParam = c.req.query("verified") ?? "true";
  const rawQ = c.req.query("q");
  if (tagsParam && tagsParam.length > 200) {
    return c.json({ error: "tags parameter too long (max 200 chars)" }, 400);
  }
  if (tierParam && !/^[SABCDE](,[SABCDE])*$/i.test(tierParam)) {
    return c.json({ error: "tier must be a comma-separated list of letters A-E or S (e.g. 'S,A,B')" }, 400);
  }
  if (rawQ && rawQ.length > 200) {
    return c.json({ error: "Search query too long (max 200 chars)" }, 400);
  }
  const q = rawQ?.toLowerCase();
  const sort = c.req.query("sort") || "score";
  const limit = Math.min(Math.max(1, parseInt(c.req.query("limit") || "20", 10)), 50);
  const offset = Math.max(0, parseInt(c.req.query("offset") || "0", 10));

  // ── Validate ────────────────────────────────────────────────────────
  if (!VALID_TYPES.has(type)) {
    return c.json({ error: "type must be 'mcp', 'agent', or 'all'" }, 400);
  }
  if (!VALID_SORTS.has(sort)) {
    return c.json({ error: "sort must be 'score' or 'name'" }, 400);
  }

  const requestedTags = tagsParam
    ? tagsParam.split(",").map((t) => t.trim().toLowerCase())
    : null;
  const requestedTiers: Set<TierLetter> | null = tierParam
    ? new Set(
        tierParam
          .split(",")
          .map((t) => t.trim().toUpperCase()) as TierLetter[]
      )
    : null;

  // ── Load search index ───────────────────────────────────────────────
  const index = await getSearchIndex(c.env.STATIC_API_BASE);

  // ── Filter ──────────────────────────────────────────────────────────
  const filtered = index.filter((entry) => {
    // Type
    if (type === "mcp" && entry.skill_type !== "mcp_server") return false;
    if (type === "agent" && entry.skill_type !== "agent_skill") return false;

    // Tags (any-match)
    if (requestedTags) {
      const entryTagsLower = entry.tags.map((t) => t.toLowerCase());
      if (!requestedTags.some((rt) => entryTagsLower.includes(rt))) return false;
    }

    // Tier
    if (requestedTiers) {
      const score = computeScore(entry.stars, entry.installs);
      if (!requestedTiers.has(computeTier(score))) return false;
    }

    // Verified
    if (verifiedParam === "true" && entry.verification_status !== "pass")
      return false;
    if (verifiedParam === "false" && entry.verification_status === "pass")
      return false;

    // Text search
    if (q) {
      const nameMatch = entry.name.toLowerCase().includes(q);
      const descMatch = (entry.description || "").toLowerCase().includes(q);
      if (!nameMatch && !descMatch) return false;
    }

    return true;
  });

  // ── Sort ────────────────────────────────────────────────────────────
  if (sort === "name") {
    filtered.sort((a, b) => a.name.localeCompare(b.name));
  } else {
    filtered.sort(
      (a, b) =>
        computeScore(b.stars, b.installs) - computeScore(a.stars, a.installs)
    );
  }

  // ── Paginate ────────────────────────────────────────────────────────
  const total = filtered.length;
  const page = filtered.slice(offset, offset + limit);

  // ── Map to response shape ───────────────────────────────────────────
  const results: V2SearchResult[] = page.map((entry) => {
    const score = computeScore(entry.stars, entry.installs);
    return {
      id: entry.id,
      name: entry.name,
      type: entry.skill_type,
      score,
      tier: computeTier(score),
      verified: entry.verification_status === "pass",
      safe: entry.verification_status === "pass",
      tags: entry.tags.filter((t) => t !== "repo_unavailable"),
      one_liner: (entry.description || "").slice(0, 150),
      install: `npx secureskillhub install ${entry.id}`,
      commit: entry.verified_commit || "",
      report_url: `${c.env.STATIC_API_BASE}/api/skills/${entry.id}.json`,
    };
  });

  const response: V2SearchResponse = { total, offset, limit, results };
  return c.json(response);
});

export default search;
