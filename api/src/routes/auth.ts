import { Hono } from "hono";
import { nanoid } from "nanoid";
import { getDb } from "../db/client.js";
import {
  createAuthSession,
  getAuthSession,
  getAuthSessionByUserCode,
  updateAuthSession,
  findUserByGithubId,
  createUser,
  createCliToken,
  createPackage,
  upsertPackagePreferences,
  deleteCliToken,
} from "../db/queries.js";
import {
  generateUserCode,
  generateDeviceCode,
  generateCliToken,
  hashToken,
  exchangeCodeForToken,
  getGithubUser,
} from "../lib/github-oauth.js";
import type { Env, Variables } from "../lib/types.js";
import { authMiddleware } from "../middleware/auth.js";

const auth = new Hono<{ Bindings: Env; Variables: Variables }>();

// POST /v1/auth/device — Start device flow
auth.post("/device", async (c) => {
  const deviceCode = generateDeviceCode();
  const userCode = generateUserCode();
  const expiresAt = new Date(Date.now() + 15 * 60 * 1000).toISOString();

  const db = getDb(c.env);
  await createAuthSession(db, { deviceCode, userCode, expiresAt });

  const apiBase = new URL(c.req.url).origin;

  return c.json({
    device_code: deviceCode,
    user_code: userCode,
    verification_url: `${apiBase}/v1/auth/verify?code=${userCode}`,
    expires_in: 900,
    interval: 5,
  });
});

// POST /v1/auth/device/poll — Poll for authorization
auth.post("/device/poll", async (c) => {
  const body = await c.req.json<{ device_code: string }>();

  if (!body.device_code) {
    return c.json({ error: "device_code is required" }, 400);
  }

  const db = getDb(c.env);
  const session = await getAuthSession(db, body.device_code);

  if (!session) {
    return c.json({ error: "Invalid device code" }, 404);
  }

  if (new Date(session.expires_at) < new Date()) {
    return c.json({ error: "expired_token", error_description: "The device code has expired" }, 400);
  }

  if (session.status === "pending") {
    return c.json({ error: "authorization_pending", error_description: "User has not yet authorized" }, 400);
  }

  if (session.status === "authorized" && session.user_id) {
    // Generate a CLI token for the user
    const rawToken = generateCliToken();
    const tokenHash = await hashToken(rawToken);
    const tokenId = nanoid();

    await createCliToken(db, {
      id: tokenId,
      userId: session.user_id,
      tokenHash,
      label: "CLI (device flow)",
      expiresAt: null,
    });

    // Mark session as complete so it cannot be polled again
    await updateAuthSession(db, body.device_code, { status: "complete" });

    return c.json({
      access_token: rawToken,
      token_type: "bearer",
      user_id: session.user_id,
    });
  }

  if (session.status === "denied") {
    return c.json({ error: "access_denied", error_description: "User denied access" }, 400);
  }

  // status === "complete" or anything else
  return c.json({ error: "expired_token", error_description: "This device code has already been used" }, 400);
});

// GET /v1/auth/verify — Landing page for device flow
auth.get("/verify", async (c) => {
  const userCode = c.req.query("code") || "";
  const clientId = c.env.GITHUB_CLIENT_ID;
  const apiBase = new URL(c.req.url).origin;
  const callbackUrl = `${apiBase}/v1/auth/callback`;

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SecureSkillHub - Authorize CLI</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0d1117; color: #c9d1d9; display: flex; justify-content: center; align-items: center; min-height: 100vh; }
    .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 2rem; max-width: 420px; width: 90%; text-align: center; }
    h1 { font-size: 1.5rem; margin-bottom: 0.5rem; color: #f0f6fc; }
    p { margin-bottom: 1rem; color: #8b949e; font-size: 0.9rem; }
    .code-display { font-family: 'SF Mono', monospace; font-size: 2rem; letter-spacing: 0.15em; color: #58a6ff; background: #0d1117; padding: 0.75rem 1.5rem; border-radius: 8px; margin: 1rem 0; border: 1px solid #30363d; }
    .btn { display: inline-block; background: #238636; color: #fff; padding: 0.75rem 2rem; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 1rem; border: none; cursor: pointer; transition: background 0.2s; }
    .btn:hover { background: #2ea043; }
  </style>
</head>
<body>
  <div class="card">
    <h1>SecureSkillHub CLI</h1>
    <p>Confirm this is the code shown in your terminal:</p>
    <div class="code-display">${userCode || "--------"}</div>
    <p>Click below to sign in with GitHub and authorize the CLI.</p>
    <a class="btn" href="https://github.com/login/oauth/authorize?client_id=${clientId}&redirect_uri=${encodeURIComponent(callbackUrl)}&state=${encodeURIComponent(userCode)}&scope=read:user">
      Authorize with GitHub
    </a>
  </div>
</body>
</html>`;

  return c.html(html);
});

// GET /v1/auth/callback — GitHub OAuth redirect handler
auth.get("/callback", async (c) => {
  const code = c.req.query("code");
  const state = c.req.query("state"); // this is the user_code
  const error = c.req.query("error");

  if (error) {
    return c.html(renderResultPage(false, "Authorization was denied."));
  }

  if (!code || !state) {
    return c.html(renderResultPage(false, "Missing code or state parameter."), 400);
  }

  const db = getDb(c.env);

  // Look up the auth session by user_code
  const session = await getAuthSessionByUserCode(db, state);
  if (!session) {
    return c.html(renderResultPage(false, "Invalid or expired session. Please try again from the CLI."), 400);
  }

  if (new Date(session.expires_at) < new Date()) {
    return c.html(renderResultPage(false, "This authorization session has expired. Please try again from the CLI."), 400);
  }

  try {
    // Exchange code for GitHub access token
    const ghToken = await exchangeCodeForToken(
      code,
      c.env.GITHUB_CLIENT_ID,
      c.env.GITHUB_CLIENT_SECRET
    );

    // Get GitHub user info
    const ghUser = await getGithubUser(ghToken);

    // Find or create user
    let user = await findUserByGithubId(db, ghUser.id);
    if (!user) {
      const userId = nanoid();
      user = await createUser(db, {
        id: userId,
        githubId: ghUser.id,
        handle: ghUser.login,
        avatar: ghUser.avatar_url,
      });

      // Create a default package for the new user
      const pkgId = nanoid();
      await createPackage(db, {
        id: pkgId,
        userId: user.id,
        name: "My Stack",
        description: "My default skill collection",
        isDefault: 1,
      });
      await upsertPackagePreferences(db, pkgId, {});
    }

    // Update the auth session
    await updateAuthSession(db, session.device_code, {
      userId: user.id,
      status: "authorized",
      accessToken: ghToken,
    });

    return c.html(renderResultPage(true, `Welcome, ${user.github_handle}! You can close this tab and return to the CLI.`));
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return c.html(renderResultPage(false, `Authentication failed: ${message}`), 500);
  }
});

// DELETE /v1/auth/token — Revoke current token
auth.delete("/token", authMiddleware, async (c) => {
  const authHeader = c.req.header("Authorization");
  if (!authHeader) {
    return c.json({ error: "Missing Authorization header" }, 401);
  }

  const rawToken = authHeader.slice(7);
  const tokenHash = await hashToken(rawToken);

  const db = getDb(c.env);
  await deleteCliToken(db, tokenHash);

  return c.json({ message: "Token revoked" });
});

function renderResultPage(success: boolean, message: string): string {
  const color = success ? "#238636" : "#da3633";
  const icon = success ? "&#10003;" : "&#10007;";
  const title = success ? "Authorized!" : "Authorization Failed";

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SecureSkillHub - ${title}</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0d1117; color: #c9d1d9; display: flex; justify-content: center; align-items: center; min-height: 100vh; }
    .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 2rem; max-width: 420px; width: 90%; text-align: center; }
    h1 { font-size: 1.5rem; margin-bottom: 0.5rem; color: #f0f6fc; }
    .icon { font-size: 3rem; color: ${color}; margin-bottom: 1rem; }
    p { color: #8b949e; font-size: 0.95rem; line-height: 1.5; }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">${icon}</div>
    <h1>${title}</h1>
    <p>${message}</p>
  </div>
</body>
</html>`;
}

export default auth;
