import { Hono } from "hono";
import { nanoid } from "nanoid";
import { getDb } from "../db/client.js";
import {
  getUserPackages,
  createPackage,
  getPackageById,
  getPackageWithDetails,
  updatePackage,
  deletePackage,
  addPackageTags,
  removePackageTag,
  addPinnedSkills,
  removePinnedSkill,
  getPackagePreferences,
  upsertPackagePreferences,
} from "../db/queries.js";
import { authMiddleware } from "../middleware/auth.js";
import type { Env, Variables } from "../lib/types.js";

const packages = new Hono<{ Bindings: Env; Variables: Variables }>();

// All routes require auth
packages.use("*", authMiddleware);

// GET /v1/me/packages — List user packages
packages.get("/", async (c) => {
  const userId = c.get("userId");
  const db = getDb(c.env);
  const pkgs = await getUserPackages(db, userId);
  return c.json({ packages: pkgs });
});

// POST /v1/me/packages — Create a new package
packages.post("/", async (c) => {
  const userId = c.get("userId");
  const body = await c.req.json<{ name?: string; description?: string }>();
  const db = getDb(c.env);

  const name = body.name?.trim() || "My Stack";
  const description = body.description?.trim() || "";

  // Check if user already has a package with this name
  const existing = await getUserPackages(db, userId);
  const duplicate = existing.find((p) => p.name === name);
  if (duplicate) {
    return c.json({ error: "A package with this name already exists" }, 409);
  }

  // If this is the user's first package, make it default
  const isDefault = existing.length === 0 ? 1 : 0;

  const pkgId = nanoid();
  const pkg = await createPackage(db, {
    id: pkgId,
    userId,
    name,
    description,
    isDefault,
  });

  // Create default preferences for the new package
  await upsertPackagePreferences(db, pkgId, {});

  return c.json({ package: pkg }, 201);
});

// GET /v1/me/packages/:id — Get package with details
packages.get("/:id", async (c) => {
  const userId = c.get("userId");
  const packageId = c.req.param("id");
  const db = getDb(c.env);

  const pkg = await getPackageWithDetails(db, packageId);
  if (!pkg) {
    return c.json({ error: "Package not found" }, 404);
  }
  if (pkg.user_id !== userId) {
    return c.json({ error: "Package not found" }, 404);
  }

  return c.json({ package: pkg });
});

// PATCH /v1/me/packages/:id — Update package
packages.patch("/:id", async (c) => {
  const userId = c.get("userId");
  const packageId = c.req.param("id");
  const body = await c.req.json<{ name?: string; description?: string; is_public?: boolean }>();
  const db = getDb(c.env);

  const pkg = await getPackageById(db, packageId);
  if (!pkg) {
    return c.json({ error: "Package not found" }, 404);
  }
  if (pkg.user_id !== userId) {
    return c.json({ error: "Package not found" }, 404);
  }

  const updates: { name?: string; description?: string; is_public?: number } = {};
  if (body.name !== undefined) updates.name = body.name.trim();
  if (body.description !== undefined) updates.description = body.description.trim();
  if (body.is_public !== undefined) updates.is_public = body.is_public ? 1 : 0;

  await updatePackage(db, packageId, updates);

  const updated = await getPackageWithDetails(db, packageId);
  return c.json({ package: updated });
});

// DELETE /v1/me/packages/:id — Delete package
packages.delete("/:id", async (c) => {
  const userId = c.get("userId");
  const packageId = c.req.param("id");
  const db = getDb(c.env);

  const pkg = await getPackageById(db, packageId);
  if (!pkg) {
    return c.json({ error: "Package not found" }, 404);
  }
  if (pkg.user_id !== userId) {
    return c.json({ error: "Package not found" }, 404);
  }
  if (pkg.is_default === 1) {
    return c.json({ error: "Cannot delete the default package" }, 400);
  }

  await deletePackage(db, packageId);
  return c.json({ message: "Package deleted" });
});

// POST /v1/me/packages/:id/tags — Add tags
packages.post("/:id/tags", async (c) => {
  const userId = c.get("userId");
  const packageId = c.req.param("id");
  const body = await c.req.json<{ tag_paths: string[] }>();
  const db = getDb(c.env);

  if (!body.tag_paths || !Array.isArray(body.tag_paths) || body.tag_paths.length === 0) {
    return c.json({ error: "tag_paths must be a non-empty array of strings" }, 400);
  }

  const pkg = await getPackageById(db, packageId);
  if (!pkg) {
    return c.json({ error: "Package not found" }, 404);
  }
  if (pkg.user_id !== userId) {
    return c.json({ error: "Package not found" }, 404);
  }

  await addPackageTags(db, packageId, body.tag_paths);

  const updated = await getPackageWithDetails(db, packageId);
  return c.json({ package: updated });
});

// DELETE /v1/me/packages/:id/tags/:tagPath — Remove a tag
packages.delete("/:id/tags/:tagPath", async (c) => {
  const userId = c.get("userId");
  const packageId = c.req.param("id");
  const tagPath = decodeURIComponent(c.req.param("tagPath"));
  const db = getDb(c.env);

  const pkg = await getPackageById(db, packageId);
  if (!pkg) {
    return c.json({ error: "Package not found" }, 404);
  }
  if (pkg.user_id !== userId) {
    return c.json({ error: "Package not found" }, 404);
  }

  await removePackageTag(db, packageId, tagPath);

  const updated = await getPackageWithDetails(db, packageId);
  return c.json({ package: updated });
});

// POST /v1/me/packages/:id/pins — Add pinned skills
packages.post("/:id/pins", async (c) => {
  const userId = c.get("userId");
  const packageId = c.req.param("id");
  const body = await c.req.json<{ skill_ids: string[] }>();
  const db = getDb(c.env);

  if (!body.skill_ids || !Array.isArray(body.skill_ids) || body.skill_ids.length === 0) {
    return c.json({ error: "skill_ids must be a non-empty array of strings" }, 400);
  }

  const pkg = await getPackageById(db, packageId);
  if (!pkg) {
    return c.json({ error: "Package not found" }, 404);
  }
  if (pkg.user_id !== userId) {
    return c.json({ error: "Package not found" }, 404);
  }

  await addPinnedSkills(db, packageId, body.skill_ids);

  const updated = await getPackageWithDetails(db, packageId);
  return c.json({ package: updated });
});

// DELETE /v1/me/packages/:id/pins/:skillId — Remove a pinned skill
packages.delete("/:id/pins/:skillId", async (c) => {
  const userId = c.get("userId");
  const packageId = c.req.param("id");
  const skillId = c.req.param("skillId");
  const db = getDb(c.env);

  const pkg = await getPackageById(db, packageId);
  if (!pkg) {
    return c.json({ error: "Package not found" }, 404);
  }
  if (pkg.user_id !== userId) {
    return c.json({ error: "Package not found" }, 404);
  }

  await removePinnedSkill(db, packageId, skillId);

  const updated = await getPackageWithDetails(db, packageId);
  return c.json({ package: updated });
});

// GET /v1/me/packages/:id/preferences — Get package preferences
packages.get("/:id/preferences", async (c) => {
  const userId = c.get("userId");
  const packageId = c.req.param("id");
  const db = getDb(c.env);

  const pkg = await getPackageById(db, packageId);
  if (!pkg) {
    return c.json({ error: "Package not found" }, 404);
  }
  if (pkg.user_id !== userId) {
    return c.json({ error: "Package not found" }, 404);
  }

  const prefs = await getPackagePreferences(db, packageId);
  return c.json({ preferences: prefs });
});

// PUT /v1/me/packages/:id/preferences — Update package preferences
packages.put("/:id/preferences", async (c) => {
  const userId = c.get("userId");
  const packageId = c.req.param("id");
  const body = await c.req.json<{
    min_tier?: number;
    min_score?: number;
    verified_only?: boolean;
    auto_update?: boolean;
    skill_types?: string;
  }>();
  const db = getDb(c.env);

  const pkg = await getPackageById(db, packageId);
  if (!pkg) {
    return c.json({ error: "Package not found" }, 404);
  }
  if (pkg.user_id !== userId) {
    return c.json({ error: "Package not found" }, 404);
  }

  const prefs: Record<string, number | string> = {};
  if (body.min_tier !== undefined) prefs.min_tier = body.min_tier;
  if (body.min_score !== undefined) prefs.min_score = body.min_score;
  if (body.verified_only !== undefined) prefs.verified_only = body.verified_only ? 1 : 0;
  if (body.auto_update !== undefined) prefs.auto_update = body.auto_update ? 1 : 0;
  if (body.skill_types !== undefined) prefs.skill_types = body.skill_types;

  await upsertPackagePreferences(db, packageId, prefs);

  const updated = await getPackagePreferences(db, packageId);
  return c.json({ preferences: updated });
});

export default packages;
