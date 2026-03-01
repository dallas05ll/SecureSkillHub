import type { Client } from "@libsql/client";
import type {
  User,
  CustomPackage,
  PackageTag,
  PinnedSkill,
  PackagePreferences,
  AuthSession,
  CliToken,
  PackageWithDetails,
} from "../lib/types.js";

// ── Users ──────────────────────────────────────────────────────────────

export async function findUserByGithubId(
  db: Client,
  githubId: number
): Promise<User | null> {
  const result = await db.execute({
    sql: "SELECT * FROM users WHERE github_id = ?",
    args: [githubId],
  });
  return (result.rows[0] as unknown as User) ?? null;
}

export async function createUser(
  db: Client,
  params: { id: string; githubId: number; handle: string; avatar: string }
): Promise<User> {
  await db.execute({
    sql: `INSERT INTO users (id, github_id, github_handle, github_avatar, display_name)
          VALUES (?, ?, ?, ?, ?)`,
    args: [params.id, params.githubId, params.handle, params.avatar, params.handle],
  });
  return (await findUserById(db, params.id))!;
}

export async function findUserById(
  db: Client,
  id: string
): Promise<User | null> {
  const result = await db.execute({
    sql: "SELECT * FROM users WHERE id = ?",
    args: [id],
  });
  return (result.rows[0] as unknown as User) ?? null;
}

export async function findUserByHandle(
  db: Client,
  handle: string
): Promise<User | null> {
  const result = await db.execute({
    sql: "SELECT * FROM users WHERE github_handle = ?",
    args: [handle],
  });
  return (result.rows[0] as unknown as User) ?? null;
}

// ── Auth Sessions ──────────────────────────────────────────────────────

export async function createAuthSession(
  db: Client,
  params: { deviceCode: string; userCode: string; expiresAt: string }
): Promise<void> {
  await db.execute({
    sql: `INSERT INTO auth_sessions (device_code, user_code, status, expires_at)
          VALUES (?, ?, 'pending', ?)`,
    args: [params.deviceCode, params.userCode, params.expiresAt],
  });
}

export async function getAuthSession(
  db: Client,
  deviceCode: string
): Promise<AuthSession | null> {
  const result = await db.execute({
    sql: "SELECT * FROM auth_sessions WHERE device_code = ?",
    args: [deviceCode],
  });
  return (result.rows[0] as unknown as AuthSession) ?? null;
}

export async function getAuthSessionByUserCode(
  db: Client,
  userCode: string
): Promise<AuthSession | null> {
  const result = await db.execute({
    sql: "SELECT * FROM auth_sessions WHERE user_code = ?",
    args: [userCode],
  });
  return (result.rows[0] as unknown as AuthSession) ?? null;
}

export async function updateAuthSession(
  db: Client,
  deviceCode: string,
  fields: { userId?: string; status?: string; accessToken?: string }
): Promise<void> {
  const sets: string[] = [];
  const args: (string | null)[] = [];

  if (fields.userId !== undefined) {
    sets.push("user_id = ?");
    args.push(fields.userId);
  }
  if (fields.status !== undefined) {
    sets.push("status = ?");
    args.push(fields.status);
  }
  if (fields.accessToken !== undefined) {
    sets.push("access_token = ?");
    args.push(fields.accessToken);
  }

  if (sets.length === 0) return;

  args.push(deviceCode);
  await db.execute({
    sql: `UPDATE auth_sessions SET ${sets.join(", ")} WHERE device_code = ?`,
    args,
  });
}

// ── CLI Tokens ─────────────────────────────────────────────────────────

export async function createCliToken(
  db: Client,
  params: {
    id: string;
    userId: string;
    tokenHash: string;
    label: string;
    expiresAt: string | null;
  }
): Promise<void> {
  await db.execute({
    sql: `INSERT INTO cli_tokens (id, user_id, token_hash, label, expires_at)
          VALUES (?, ?, ?, ?, ?)`,
    args: [params.id, params.userId, params.tokenHash, params.label, params.expiresAt],
  });
}

export async function findCliToken(
  db: Client,
  tokenHash: string
): Promise<CliToken | null> {
  const result = await db.execute({
    sql: "SELECT * FROM cli_tokens WHERE token_hash = ?",
    args: [tokenHash],
  });
  return (result.rows[0] as unknown as CliToken) ?? null;
}

export async function updateTokenLastUsed(
  db: Client,
  tokenId: string
): Promise<void> {
  await db.execute({
    sql: "UPDATE cli_tokens SET last_used_at = datetime('now') WHERE id = ?",
    args: [tokenId],
  });
}

export async function deleteCliToken(
  db: Client,
  tokenHash: string
): Promise<void> {
  await db.execute({
    sql: "DELETE FROM cli_tokens WHERE token_hash = ?",
    args: [tokenHash],
  });
}

// ── Custom Packages ────────────────────────────────────────────────────

export async function getUserPackages(
  db: Client,
  userId: string
): Promise<CustomPackage[]> {
  const result = await db.execute({
    sql: "SELECT * FROM custom_packages WHERE user_id = ? ORDER BY is_default DESC, created_at ASC",
    args: [userId],
  });
  return result.rows as unknown as CustomPackage[];
}

export async function createPackage(
  db: Client,
  params: { id: string; userId: string; name: string; description: string; isDefault: number }
): Promise<CustomPackage> {
  await db.execute({
    sql: `INSERT INTO custom_packages (id, user_id, name, description, is_default)
          VALUES (?, ?, ?, ?, ?)`,
    args: [params.id, params.userId, params.name, params.description, params.isDefault],
  });
  return (await getPackageById(db, params.id))!;
}

export async function getPackageById(
  db: Client,
  packageId: string
): Promise<CustomPackage | null> {
  const result = await db.execute({
    sql: "SELECT * FROM custom_packages WHERE id = ?",
    args: [packageId],
  });
  return (result.rows[0] as unknown as CustomPackage) ?? null;
}

export async function updatePackage(
  db: Client,
  packageId: string,
  fields: { name?: string; description?: string; is_public?: number }
): Promise<void> {
  const sets: string[] = ["updated_at = datetime('now')"];
  const args: (string | number)[] = [];

  if (fields.name !== undefined) {
    sets.push("name = ?");
    args.push(fields.name);
  }
  if (fields.description !== undefined) {
    sets.push("description = ?");
    args.push(fields.description);
  }
  if (fields.is_public !== undefined) {
    sets.push("is_public = ?");
    args.push(fields.is_public);
  }

  args.push(packageId);
  await db.execute({
    sql: `UPDATE custom_packages SET ${sets.join(", ")} WHERE id = ?`,
    args,
  });
}

export async function deletePackage(
  db: Client,
  packageId: string
): Promise<void> {
  await db.execute({
    sql: "DELETE FROM custom_packages WHERE id = ?",
    args: [packageId],
  });
}

// ── Package Tags ───────────────────────────────────────────────────────

export async function getPackageTags(
  db: Client,
  packageId: string
): Promise<PackageTag[]> {
  const result = await db.execute({
    sql: "SELECT * FROM package_tags WHERE package_id = ? ORDER BY added_at ASC",
    args: [packageId],
  });
  return result.rows as unknown as PackageTag[];
}

export async function addPackageTags(
  db: Client,
  packageId: string,
  tagPaths: string[]
): Promise<void> {
  for (const tagPath of tagPaths) {
    await db.execute({
      sql: `INSERT OR IGNORE INTO package_tags (package_id, tag_path) VALUES (?, ?)`,
      args: [packageId, tagPath],
    });
  }
}

export async function removePackageTag(
  db: Client,
  packageId: string,
  tagPath: string
): Promise<void> {
  await db.execute({
    sql: "DELETE FROM package_tags WHERE package_id = ? AND tag_path = ?",
    args: [packageId, tagPath],
  });
}

// ── Pinned Skills ──────────────────────────────────────────────────────

export async function getPinnedSkills(
  db: Client,
  packageId: string
): Promise<PinnedSkill[]> {
  const result = await db.execute({
    sql: "SELECT * FROM pinned_skills WHERE package_id = ? ORDER BY added_at ASC",
    args: [packageId],
  });
  return result.rows as unknown as PinnedSkill[];
}

export async function addPinnedSkills(
  db: Client,
  packageId: string,
  skillIds: string[]
): Promise<void> {
  for (const skillId of skillIds) {
    await db.execute({
      sql: `INSERT OR IGNORE INTO pinned_skills (package_id, skill_id) VALUES (?, ?)`,
      args: [packageId, skillId],
    });
  }
}

export async function removePinnedSkill(
  db: Client,
  packageId: string,
  skillId: string
): Promise<void> {
  await db.execute({
    sql: "DELETE FROM pinned_skills WHERE package_id = ? AND skill_id = ?",
    args: [packageId, skillId],
  });
}

// ── Package Preferences ────────────────────────────────────────────────

export async function getPackagePreferences(
  db: Client,
  packageId: string
): Promise<PackagePreferences | null> {
  const result = await db.execute({
    sql: "SELECT * FROM package_preferences WHERE package_id = ?",
    args: [packageId],
  });
  return (result.rows[0] as unknown as PackagePreferences) ?? null;
}

export async function upsertPackagePreferences(
  db: Client,
  packageId: string,
  prefs: Partial<Omit<PackagePreferences, "package_id">>
): Promise<void> {
  const existing = await getPackagePreferences(db, packageId);

  if (!existing) {
    await db.execute({
      sql: `INSERT INTO package_preferences (package_id, min_tier, min_score, verified_only, auto_update, skill_types)
            VALUES (?, ?, ?, ?, ?, ?)`,
      args: [
        packageId,
        prefs.min_tier ?? 5,
        prefs.min_score ?? 0,
        prefs.verified_only ?? 0,
        prefs.auto_update ?? 1,
        prefs.skill_types ?? "both",
      ],
    });
    return;
  }

  const sets: string[] = [];
  const args: (string | number)[] = [];

  if (prefs.min_tier !== undefined) {
    sets.push("min_tier = ?");
    args.push(prefs.min_tier);
  }
  if (prefs.min_score !== undefined) {
    sets.push("min_score = ?");
    args.push(prefs.min_score);
  }
  if (prefs.verified_only !== undefined) {
    sets.push("verified_only = ?");
    args.push(prefs.verified_only);
  }
  if (prefs.auto_update !== undefined) {
    sets.push("auto_update = ?");
    args.push(prefs.auto_update);
  }
  if (prefs.skill_types !== undefined) {
    sets.push("skill_types = ?");
    args.push(prefs.skill_types);
  }

  if (sets.length === 0) return;

  args.push(packageId);
  await db.execute({
    sql: `UPDATE package_preferences SET ${sets.join(", ")} WHERE package_id = ?`,
    args,
  });
}

// ── Composite Queries ──────────────────────────────────────────────────

export async function getPackageWithDetails(
  db: Client,
  packageId: string
): Promise<PackageWithDetails | null> {
  const pkg = await getPackageById(db, packageId);
  if (!pkg) return null;

  const [tags, pinnedSkills, preferences] = await Promise.all([
    getPackageTags(db, packageId),
    getPinnedSkills(db, packageId),
    getPackagePreferences(db, packageId),
  ]);

  return {
    ...pkg,
    tags,
    pinned_skills: pinnedSkills,
    preferences,
  };
}

export async function getDefaultPackage(
  db: Client,
  userId: string
): Promise<CustomPackage | null> {
  const result = await db.execute({
    sql: "SELECT * FROM custom_packages WHERE user_id = ? AND is_default = 1 LIMIT 1",
    args: [userId],
  });
  return (result.rows[0] as unknown as CustomPackage) ?? null;
}

export async function getPublicPackagesByHandle(
  db: Client,
  githubHandle: string
): Promise<PackageWithDetails[]> {
  const user = await findUserByHandle(db, githubHandle);
  if (!user) return [];

  const result = await db.execute({
    sql: "SELECT * FROM custom_packages WHERE user_id = ? AND is_public = 1 ORDER BY is_default DESC, created_at ASC",
    args: [user.id],
  });

  const packages = result.rows as unknown as CustomPackage[];
  const detailed: PackageWithDetails[] = [];

  for (const pkg of packages) {
    const details = await getPackageWithDetails(db, pkg.id);
    if (details) detailed.push(details);
  }

  return detailed;
}
