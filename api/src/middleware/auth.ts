import type { Context, Next } from "hono";
import { getDb } from "../db/client.js";
import { findCliToken, updateTokenLastUsed, findUserById } from "../db/queries.js";
import { hashToken } from "../lib/github-oauth.js";
import type { Env, Variables } from "../lib/types.js";

export async function authMiddleware(
  c: Context<{ Bindings: Env; Variables: Variables }>,
  next: Next
): Promise<Response | void> {
  const authHeader = c.req.header("Authorization");

  if (!authHeader || !authHeader.startsWith("Bearer ")) {
    return c.json({ error: "Missing or invalid Authorization header" }, 401);
  }

  const token = authHeader.slice(7);
  if (!token) {
    return c.json({ error: "Empty bearer token" }, 401);
  }

  const tokenHash = await hashToken(token);
  const db = getDb(c.env);

  const cliToken = await findCliToken(db, tokenHash);
  if (!cliToken) {
    return c.json({ error: "Invalid token" }, 401);
  }

  if (cliToken.expires_at && new Date(cliToken.expires_at) < new Date()) {
    return c.json({ error: "Token expired" }, 401);
  }

  const user = await findUserById(db, cliToken.user_id);
  if (!user) {
    return c.json({ error: "User not found" }, 401);
  }

  // Update last used timestamp (fire and forget)
  updateTokenLastUsed(db, cliToken.id).catch(() => {});

  c.set("userId", user.id);
  c.set("user", user);

  await next();
}
