import type { SearchIndexEntry } from "./types.js";

const CACHE_TTL_MS = 10 * 60 * 1000; // 10 minutes

// ── Search index (4.5MB, in-memory singleton) ─────────────────────────

let cachedIndex: SearchIndexEntry[] | null = null;
let cachedAt = 0;
let refreshPromise: Promise<void> | null = null;

async function fetchIndex(staticBase: string): Promise<SearchIndexEntry[]> {
  const url = `${staticBase}/api/search-index.json`;
  const resp = await fetch(url, {
    headers: { "User-Agent": "SecureSkillHub-API/v2" },
    cf: { cacheTtl: 300 },
  });
  if (!resp.ok) throw new Error(`Failed to fetch search index: ${resp.status}`);
  return resp.json() as Promise<SearchIndexEntry[]>;
}

export async function getSearchIndex(staticBase: string): Promise<SearchIndexEntry[]> {
  const now = Date.now();

  // Cold start — must block and fetch
  if (!cachedIndex) {
    cachedIndex = await fetchIndex(staticBase);
    cachedAt = now;
    return cachedIndex;
  }

  // Stale — return old data, refresh in background
  if (now - cachedAt > CACHE_TTL_MS && !refreshPromise) {
    refreshPromise = fetchIndex(staticBase)
      .then((data) => {
        cachedIndex = data;
        cachedAt = Date.now();
      })
      .catch((err) => {
        console.error("[search-cache] Background refresh failed:", err);
      })
      .finally(() => {
        refreshPromise = null;
      });
  }

  return cachedIndex;
}

// ── Small payload caches ──────────────────────────────────────────────

interface CacheEntry<T> {
  data: T;
  at: number;
}

let statsCache: CacheEntry<unknown> | null = null;
let pkgIndexCache: CacheEntry<unknown> | null = null;

async function fetchJson<T>(staticBase: string, path: string): Promise<T> {
  const resp = await fetch(`${staticBase}${path}`, {
    headers: { "User-Agent": "SecureSkillHub-API/v2" },
    cf: { cacheTtl: 300 },
  });
  if (!resp.ok) throw new Error(`Failed to fetch ${path}: ${resp.status}`);
  return resp.json() as Promise<T>;
}

export async function getStats<T>(staticBase: string): Promise<T> {
  const now = Date.now();
  if (statsCache && now - statsCache.at < CACHE_TTL_MS) {
    return statsCache.data as T;
  }
  const data = await fetchJson<T>(staticBase, "/api/v2/meta/stats.json");
  statsCache = { data, at: now };
  return data;
}

export async function getPackagesIndex<T>(staticBase: string): Promise<T> {
  const now = Date.now();
  if (pkgIndexCache && now - pkgIndexCache.at < CACHE_TTL_MS) {
    return pkgIndexCache.data as T;
  }
  const data = await fetchJson<T>(staticBase, "/api/packages/index.json");
  pkgIndexCache = { data, at: now };
  return data;
}
