import type { Context, Next } from "hono";
import { checkRateLimit } from "../lib/rate-limit.js";
import type { Env, Variables } from "../lib/types.js";

export async function rateLimitMiddleware(
  c: Context<{ Bindings: Env; Variables: Variables }>,
  next: Next
): Promise<Response | void> {
  const ip =
    c.req.header("cf-connecting-ip") ||
    c.req.header("x-forwarded-for")?.split(",")[0].trim() ||
    "unknown";

  const { allowed, remaining, reset } = await checkRateLimit(ip);

  c.header("X-RateLimit-Limit", "100");
  c.header("X-RateLimit-Remaining", String(remaining));
  c.header("X-RateLimit-Reset", String(Math.ceil(reset / 1000)));

  if (!allowed) {
    return c.json(
      { error: "Rate limit exceeded. Max 100 requests per minute." },
      429
    );
  }

  await next();
}
