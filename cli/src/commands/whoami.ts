import chalk from "chalk";
import { getConfig } from "../lib/config.js";
import { createClient, ApiError } from "../lib/api-client.js";
import { info, error } from "../lib/output.js";
import type { User } from "../lib/types.js";

export async function whoamiCommand(): Promise<void> {
  const config = getConfig();
  if (!config) {
    info("Not logged in. Run `secureskillhub login` to authenticate.");
    return;
  }

  try {
    const client = createClient();
    const user = await client.get<User>("/v1/me");

    console.log("");
    console.log(`  Handle:  ${chalk.bold("@" + user.github_handle)}`);
    if (user.display_name) {
      console.log(`  Name:    ${user.display_name}`);
    }
    console.log(`  ID:      ${user.id}`);
    console.log(`  Joined:  ${user.created_at}`);
    console.log("");
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      error(
        "Session expired or token invalid. Run `secureskillhub login` to re-authenticate.",
      );
    } else {
      error(
        "Failed to fetch user info: " +
          (err instanceof Error ? err.message : String(err)),
      );
    }
    process.exit(1);
  }
}
