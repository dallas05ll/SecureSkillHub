import type { GitHubUser } from "./types.js";

export async function exchangeCodeForToken(
  code: string,
  clientId: string,
  clientSecret: string
): Promise<string> {
  const response = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({
      client_id: clientId,
      client_secret: clientSecret,
      code,
    }),
  });

  if (!response.ok) {
    throw new Error(`GitHub OAuth token exchange failed: ${response.status}`);
  }

  const data = (await response.json()) as { access_token?: string; error?: string; error_description?: string };

  if (data.error) {
    throw new Error(`GitHub OAuth error: ${data.error} - ${data.error_description}`);
  }

  if (!data.access_token) {
    throw new Error("No access token in GitHub response");
  }

  return data.access_token;
}

export async function getGithubUser(accessToken: string): Promise<GitHubUser> {
  const response = await fetch("https://api.github.com/user", {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "SecureSkillHub-API",
    },
  });

  if (!response.ok) {
    throw new Error(`GitHub API user fetch failed: ${response.status}`);
  }

  return (await response.json()) as GitHubUser;
}

export function generateUserCode(): string {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  let part1 = "";
  let part2 = "";
  const randomValues = new Uint8Array(8);
  crypto.getRandomValues(randomValues);

  for (let i = 0; i < 4; i++) {
    part1 += chars[randomValues[i]! % chars.length];
    part2 += chars[randomValues[i + 4]! % chars.length];
  }

  return `${part1}-${part2}`;
}

export function generateDeviceCode(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export function generateCliToken(): string {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  const bytes = new Uint8Array(48);
  crypto.getRandomValues(bytes);
  return Array.from(bytes)
    .map((b) => chars[b % chars.length])
    .join("");
}

export async function hashToken(token: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(token);
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);
  const hashArray = new Uint8Array(hashBuffer);
  return Array.from(hashArray)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
