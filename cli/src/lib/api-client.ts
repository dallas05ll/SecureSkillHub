import { getConfig, getApiUrl, getSiteUrl } from "./config.js";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly statusText: string,
    public readonly body: string,
  ) {
    super(`API error ${status} ${statusText}: ${body}`);
    this.name = "ApiError";
  }
}

export class ApiClient {
  constructor(
    private baseUrl: string,
    private token?: string,
  ) {}

  private headers(): Record<string, string> {
    const h: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "application/json",
    };
    if (this.token) {
      h["Authorization"] = `Bearer ${this.token}`;
    }
    return h;
  }

  async get<T>(path: string): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const res = await fetch(url, {
      method: "GET",
      headers: this.headers(),
    });
    if (!res.ok) {
      const body = await res.text();
      throw new ApiError(res.status, res.statusText, body);
    }
    return (await res.json()) as T;
  }

  async post<T>(path: string, body?: unknown): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const res = await fetch(url, {
      method: "POST",
      headers: this.headers(),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      const respBody = await res.text();
      throw new ApiError(res.status, res.statusText, respBody);
    }
    return (await res.json()) as T;
  }

  async patch<T>(path: string, body: unknown): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const res = await fetch(url, {
      method: "PATCH",
      headers: this.headers(),
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const respBody = await res.text();
      throw new ApiError(res.status, res.statusText, respBody);
    }
    return (await res.json()) as T;
  }

  async delete(path: string): Promise<void> {
    const url = `${this.baseUrl}${path}`;
    const res = await fetch(url, {
      method: "DELETE",
      headers: this.headers(),
    });
    if (!res.ok) {
      const body = await res.text();
      throw new ApiError(res.status, res.statusText, body);
    }
  }
}

/**
 * Create an authenticated API client.
 * Reads token from config; throws if not logged in.
 */
export function createClient(): ApiClient {
  const config = getConfig();
  if (!config) {
    throw new Error(
      "Not logged in. Run `secureskillhub login` first.",
    );
  }
  const apiUrl = getApiUrl();
  return new ApiClient(apiUrl, config.token);
}

/**
 * Create a public (unauthenticated) client pointed at the static site API.
 */
export function createPublicClient(): ApiClient {
  const siteUrl = getSiteUrl();
  return new ApiClient(siteUrl);
}

/**
 * Create an unauthenticated client pointed at the Worker API.
 * Used for auth flows that don't yet have a token.
 */
export function createAnonClient(): ApiClient {
  const apiUrl = getApiUrl();
  return new ApiClient(apiUrl);
}
