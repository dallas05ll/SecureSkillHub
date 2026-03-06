/** Thin HTTP client for the SecureSkillHub v2 API */

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
  const resp = await fetch(url, {
    headers: {
      "User-Agent": "SecureSkillHub-MCP/0.1.0",
      Accept: "application/json",
    },
  });

  if (!resp.ok) {
    const body = await resp.text().catch(() => "");
    // Truncate error body to prevent leaking large HTML error pages
    const brief = (body || resp.statusText).slice(0, 200);
    throw new ApiError(resp.status, `API ${resp.status}: ${brief}`);
  }

  return resp.json() as Promise<T>;
}
