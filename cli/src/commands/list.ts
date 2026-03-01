import chalk from "chalk";
import { getConfig } from "../lib/config.js";
import { createClient } from "../lib/api-client.js";
import { table, error, requireAuth } from "../lib/output.js";
import type { PackageWithDetails } from "../lib/types.js";

export async function listCommand(): Promise<void> {
  const config = getConfig();
  requireAuth(config);

  try {
    const client = createClient();
    const packages = await client.get<PackageWithDetails[]>("/v1/me/packages");

    if (packages.length === 0) {
      console.log("No packages yet. Run `secureskillhub create <name>` to create one.");
      return;
    }

    const headers = ["Name", "Tags", "Pins", "Default", "Public"];
    const rows = packages.map((pkg) => [
      pkg.is_default ? chalk.bold(pkg.name) : pkg.name,
      String(pkg.tags.length),
      String(pkg.pinned_skills.length),
      pkg.is_default ? chalk.green("yes") : "no",
      pkg.is_public ? chalk.cyan("yes") : "no",
    ]);

    console.log("");
    console.log(table(headers, rows));
    console.log("");
    console.log(chalk.dim(`${packages.length} package(s)`));
  } catch (err) {
    error(
      "Failed to list packages: " +
        (err instanceof Error ? err.message : String(err)),
    );
    process.exit(1);
  }
}
