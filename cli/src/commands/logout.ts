import { getConfig, clearConfig } from "../lib/config.js";
import { createClient, ApiError } from "../lib/api-client.js";
import { success, error, warn, info } from "../lib/output.js";

export async function logoutCommand(): Promise<void> {
  const config = getConfig();
  if (!config) {
    info("Not logged in.");
    return;
  }

  // Try to revoke the token server-side
  try {
    const client = createClient();
    await client.delete("/v1/auth/token");
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      // Token was already invalid — that's fine
      warn("Token was already expired or revoked.");
    } else {
      warn(
        "Could not revoke token on server: " +
          (err instanceof Error ? err.message : String(err)),
      );
      warn("Clearing local credentials anyway.");
    }
  }

  clearConfig();
  success("Logged out.");
}
