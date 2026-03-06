#!/usr/bin/env node

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { searchSkills } from "./tools/search.js";
import { getReport } from "./tools/report.js";
import { getBundle } from "./tools/bundle.js";
import { installSkill } from "./tools/install.js";
import { browseCategories } from "./tools/browse.js";

const API_BASE =
  process.env.SECURESKILLHUB_API_BASE ||
  "https://api.secureskillhub.workers.dev";

// SSRF protection: only allow https:// API base URLs
if (!/^https:\/\//.test(API_BASE)) {
  console.error("SECURESKILLHUB_API_BASE must use https://");
  process.exit(1);
}

const server = new McpServer({
  name: "secureskillhub",
  version: "0.1.0",
});

// ── Tool 1: search_skills ───────────────────────────────────────────────

server.tool(
  "search_skills",
  "Search the SecureSkillHub catalog for verified AI agent skills and MCP servers. " +
    "Returns ranked results with security scores, tier ratings, and install commands. " +
    "Use type='mcp' for MCP servers, type='agent' for agent skills, or type='all'.",
  {
    query: z
      .string()
      .max(200)
      .optional()
      .describe("Text search on name and description"),
    type: z
      .enum(["mcp", "agent", "all"])
      .default("all")
      .describe("Filter by skill type: mcp (MCP servers), agent (agent skills), or all"),
    tags: z
      .string()
      .regex(/^[a-zA-Z0-9_,-]+$/, "Tags must be comma-separated alphanumeric values")
      .optional()
      .describe("Comma-separated tags to filter by (e.g. 'data-db,data-ai')"),
    tier: z
      .string()
      .regex(/^[SABCDE](,[SABCDE])*$/i, "Tier must be comma-separated letters: S,A,B,C,D,E")
      .optional()
      .describe("Comma-separated tier letters: S,A,B,C,D,E (S=10K+, A=1K+, B=100+)"),
    verified: z
      .boolean()
      .default(true)
      .describe("Only return verified skills (default: true)"),
    limit: z
      .number()
      .min(1)
      .max(50)
      .default(10)
      .describe("Max results to return (1-50, default: 10)"),
  },
  async (params) => searchSkills(API_BASE, params)
);

// ── Tool 2: get_report ──────────────────────────────────────────────────

server.tool(
  "get_report",
  "Get the full security audit report for a specific skill. " +
    "Returns verification status, risk level, 5-agent audit trail, findings summary, " +
    "and the verified commit hash. Use the skill ID from search_skills results.",
  {
    skill_id: z
      .string()
      .regex(/^[a-zA-Z0-9_-]+$/, "Invalid skill ID format")
      .describe("The skill ID (e.g. 'mcp-supabase-95603cab')"),
  },
  async (params) => getReport(API_BASE, params.skill_id)
);

// ── Tool 3: get_bundle ──────────────────────────────────────────────────

server.tool(
  "get_bundle",
  "Get a pre-built package of verified skills for a project type. " +
    "Packages are curated bundles grouped by tag (e.g. 'data-db' for databases, " +
    "'dev-web' for web development, 'security' for security tools). " +
    "Each bundle contains top verified skills with install commands.",
  {
    tag: z
      .string()
      .regex(/^[a-zA-Z0-9_-]+$/, "Invalid tag format")
      .describe("Package tag (e.g. 'data-db', 'dev-web', 'security', 'data-ai')"),
  },
  async (params) => getBundle(API_BASE, params.tag)
);

// ── Tool 4: install ─────────────────────────────────────────────────────

server.tool(
  "install",
  "Get the commit-pinned install command for a verified skill. " +
    "Returns the exact install command with the verified commit hash, " +
    "ensuring you install the audited version, not an unverified latest.",
  {
    skill_id: z
      .string()
      .regex(/^[a-zA-Z0-9_-]+$/, "Invalid skill ID format")
      .describe("The skill ID to install (e.g. 'mcp-supabase-95603cab')"),
  },
  async (params) => installSkill(API_BASE, params.skill_id)
);

// ── Tool 5: browse_categories ───────────────────────────────────────────

server.tool(
  "browse_categories",
  "List all available packages and catalog statistics. " +
    "Use this for discovery — see what's available before searching. " +
    "Returns package tags with skill counts, plus overall catalog stats.",
  {},
  async () => browseCategories(API_BASE)
);

// ── Start server ────────────────────────────────────────────────────────

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((err) => {
  console.error("MCP server failed to start:", err);
  process.exit(1);
});
