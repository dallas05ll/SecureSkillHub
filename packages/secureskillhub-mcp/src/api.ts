/** Thin HTTP client for the SecureSkillHub v2 API */

const FETCH_TIMEOUT_MS = 15_000;

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiFetch<T>(base: string, path: string): Promise<T> {
  const url = `${base}${path}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

  try {
    const resp = await fetch(url, {
      headers: {
        "User-Agent": "SecureSkillHub-MCP/0.1.0",
        Accept: "application/json",
      },
      signal: controller.signal,
    });

    if (!resp.ok) {
      const body = await resp.text().catch(() => "");
      // Truncate error body to prevent leaking large HTML error pages
      const brief = (body || resp.statusText).slice(0, 200);
      throw new ApiError(resp.status, `API ${resp.status}: ${brief}`);
    }

    return (await resp.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

/** Format any unknown error into a user-friendly message */
export function formatError(err: unknown): string {
  if (err instanceof Error) {
    if (err.name === "AbortError") return "Request timed out — the API may be unavailable";
    return err.message;
  }
  return "Unknown error";
}
