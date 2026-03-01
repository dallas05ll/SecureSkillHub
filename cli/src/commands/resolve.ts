import chalk from "chalk";
import { getConfig } from "../lib/config.js";
import { createClient } from "../lib/api-client.js";
import { table, skillRow, error, info, requireAuth } from "../lib/output.js";
import type { ResolvedManifest } from "../lib/types.js";

export async function resolveCommand(options: {
  package?: string;
}): Promise<void> {
  const config = getConfig();
  requireAuth(config);

  const client = createClient();

  try {
    let manifest: ResolvedManifest;

    if (options.package) {
      manifest = await client.get<ResolvedManifest>(
        `/v1/me/packages/${options.package}/resolve`,
      );
    } else {
      manifest = await client.get<ResolvedManifest>(
        "/v1/me/packages/default/resolve",
      );
    }

    if (manifest.skills.length === 0) {
      info(
        "No skills resolved. Add tags or pin skills to your package first.",
      );
      console.log(
        `  ${chalk.dim("secureskillhub add <tag-or-skill-id>")}`,
      );
      return;
    }

    const headers = ["Name", "Score", "Tier", "Language", "Verified", "Install Command"];
    const rows = manifest.skills.map(skillRow);

    console.log("");
    console.log(
      chalk.bold(`Package: ${manifest.package_name}`),
    );
    console.log(
      chalk.dim(`Resolved at: ${manifest.resolved_at}`),
    );
    console.log("");
    console.log(table(headers, rows));
    console.log("");
    console.log(
      `${chalk.bold(String(manifest.total))} skill(s) resolved`,
    );

    if (manifest.filters_applied) {
      const f = manifest.filters_applied;
      console.log(
        chalk.dim(
          `Filters: min_tier=${f.min_tier}, min_score=${f.min_score}, verified_only=${f.verified_only}, types=${f.skill_types}`,
        ),
      );
    }
  } catch (err) {
    error(
      "Failed to resolve package: " +
        (err instanceof Error ? err.message : String(err)),
    );
    process.exit(1);
  }
}
