import chalk from "chalk";
import { getConfig } from "../lib/config.js";
import { createClient } from "../lib/api-client.js";
import { success, error, requireAuth } from "../lib/output.js";
import type { CustomPackage } from "../lib/types.js";

export async function createCommand(name: string): Promise<void> {
  const config = getConfig();
  requireAuth(config);

  try {
    const client = createClient();
    const pkg = await client.post<CustomPackage>("/v1/me/packages", { name });

    success(
      `Created package ${chalk.bold(pkg.name)} (${chalk.dim(pkg.id)})`,
    );
  } catch (err) {
    error(
      "Failed to create package: " +
        (err instanceof Error ? err.message : String(err)),
    );
    process.exit(1);
  }
}
