const WINDOW_MS = 60_000; // 1 minute window
const MAX_REQUESTS = 100; // 100 requests per window

export async function checkRateLimit(ip: string): Promise<{
  allowed: boolean;
  remaining: number;
  reset: number;
}> {
  const cache = caches.default;
  const key = `https://rate-limit.internal/${ip}`;
  const now = Date.now();

  const existing = await cache.match(key);
  let count = 0;
  let windowStart = now;

  if (existing) {
    const body = (await existing.json()) as {
      count: number;
      windowStart: number;
    };
    if (now - body.windowStart < WINDOW_MS) {
      count = body.count;
      windowStart = body.windowStart;
    }
  }

  count++;
  const resetAt = windowStart + WINDOW_MS;
  const ttlSeconds = Math.max(1, Math.ceil((resetAt - now) / 1000));

  const response = new Response(JSON.stringify({ count, windowStart }), {
    headers: {
      "Cache-Control": `max-age=${ttlSeconds}`,
      "Content-Type": "application/json",
    },
  });
  await cache.put(key, response);

  return {
    allowed: count <= MAX_REQUESTS,
    remaining: Math.max(0, MAX_REQUESTS - count),
    reset: resetAt,
  };
}
