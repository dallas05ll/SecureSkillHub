import { Hono } from "hono";
import type { Env, Variables } from "../../lib/types.js";

const skill = new Hono<{ Bindings: Env; Variables: Variables }>();

const SKILL_ID_RE = /^[a-zA-Z0-9._-]+$/;

skill.get("/:id", async (c) => {
  const id = c.req.param("id");

  if (!SKILL_ID_RE.test(id)) {
    return c.json({ error: "Invalid skill ID format" }, 400);
  }

  const url = `${c.env.STATIC_API_BASE}/api/skills/${id}.json`;
  const resp = await fetch(url, {
    headers: { "User-Agent": "SecureSkillHub-API/v2" },
    cf: { cacheTtl: 300 },
  });

  if (!resp.ok) {
    if (resp.status === 404) {
      return c.json({ error: "Skill not found" }, 404);
    }
    return c.json({ error: "Failed to fetch skill data" }, 502);
  }

  const data = await resp.json();
  return c.json(data);
});

export default skill;
