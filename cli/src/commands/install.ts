import chalk from "chalk";
import { createInterface } from "node:readline";
import { getConfig } from "../lib/config.js";
import { createClient } from "../lib/api-client.js";
import { table, skillRow, error, info, warn, requireAuth } from "../lib/output.js";
import { installAll } from "../lib/installer.js";
import type { ResolvedManifest } from "../lib/types.js";

/**
 * Ask user for yes/no confirmation.
 */
function confirm(prompt: string): Promise<boolean> {
  const rl = createInterface({
    input: process.stdin,
    output: process.stdout,
  });
  return new Promise((resolve) => {
    rl.question(`${prompt} [y/N] `, (answer) => {
      rl.close();
      resolve(answer.toLowerCase() === "y" || answer.toLowerCase() === "yes");
    });
  });
}

export async function installCommand(options: {
  package?: string;
  yes?: boolean;
  dryRun?: boolean;
}): Promise<void> {
  const config = getConfig();
  requireAuth(config);

  const client = createClient();

  try {
    // Step 1: Resolve the package
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
        "No skills to install. Add tags or pin skills to your package first.",
      );
      return;
    }

    // Step 2: Show what will be installed
    const headers = ["Name", "Score", "Tier", "Language", "Verified", "Install Command"];
    const rows = manifest.skills.map(skillRow);

    console.log("");
    console.log(
      chalk.bold(`Package: ${manifest.package_name}`),
    );
    console.log("");
    console.log(table(headers, rows));
    console.log("");
    console.log(
      `${chalk.bold(String(manifest.total))} skill(s) to install`,
    );

    // Count skills without install commands
    const noCommand = manifest.skills.filter(
      (s) => !s.install_command || s.install_command.trim() === "",
    ).length;
    if (noCommand > 0) {
      warn(`${noCommand} skill(s) have no install command and will be skipped.`);
    }

    // Step 3: Confirm (unless --yes)
    if (!options.yes && !options.dryRun) {
      console.log("");
      const ok = await confirm("Proceed with installation?");
      if (!ok) {
        info("Installation cancelled.");
        return;
      }
    }

    // Step 4: Install
    console.log("");
    await installAll(manifest.skills, { dryRun: options.dryRun });
  } catch (err) {
    error(
      "Failed to install: " +
        (err instanceof Error ? err.message : String(err)),
    );
    process.exit(1);
  }
}
