import { existsSync, mkdirSync, readFileSync, writeFileSync, unlinkSync } from "node:fs";
import { homedir } from "node:os";
import { join, dirname } from "node:path";

export interface Config {
  token: string;
  github_handle: string;
  api_url: string;
}

const DEFAULT_API_URL = "https://api.secureskillhub.workers.dev";

export function getConfigPath(): string {
  return join(homedir(), ".secureskillhub", "config.json");
}

export function getConfig(): Config | null {
  const configPath = getConfigPath();
  if (!existsSync(configPath)) {
    return null;
  }
  try {
    const raw = readFileSync(configPath, "utf-8");
    const parsed = JSON.parse(raw) as Partial<Config>;
    if (!parsed.token || !parsed.github_handle) {
      return null;
    }
    return {
      token: parsed.token,
      github_handle: parsed.github_handle,
      api_url: parsed.api_url ?? DEFAULT_API_URL,
    };
  } catch {
    return null;
  }
}

export function saveConfig(config: Config): void {
  const configPath = getConfigPath();
  const dir = dirname(configPath);
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true, mode: 0o700 });
  }
  writeFileSync(configPath, JSON.stringify(config, null, 2) + "\n", {
    mode: 0o600,
  });
}

export function clearConfig(): void {
  const configPath = getConfigPath();
  if (existsSync(configPath)) {
    unlinkSync(configPath);
  }
}

export function getApiUrl(): string {
  return (
    process.env.SECURESKILLHUB_API_URL ??
    getConfig()?.api_url ??
    DEFAULT_API_URL
  );
}

export function getSiteUrl(): string {
  return (
    process.env.SECURESKILLHUB_SITE_URL ?? "https://secureskillhub.github.io"
  );
}
