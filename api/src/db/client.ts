import { createClient, type Client } from "@libsql/client";
import type { Env } from "../lib/types.js";

export function getDb(env: Env): Client {
  return createClient({
    url: env.TURSO_URL,
    authToken: env.TURSO_AUTH_TOKEN,
  });
}
