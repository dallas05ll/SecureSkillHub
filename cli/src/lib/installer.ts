import { exec } from "node:child_process";
import { promisify } from "node:util";
import ora from "ora";
import type { ResolvedSkill } from "./types.js";
import { success, error as errorMsg, warn, info } from "./output.js";

const execAsync = promisify(exec);

/**
 * Install a single skill by running its install_command.
 */
export async function installSkill(
  skill: ResolvedSkill,
): Promise<{ success: boolean; output: string }> {
  if (!skill.install_command || skill.install_command.trim() === "") {
    return { success: false, output: "No install command available" };
  }

  try {
    const { stdout, stderr } = await execAsync(skill.install_command, {
      timeout: 120_000, // 2 minute timeout per skill
      env: { ...process.env },
    });
    return { success: true, output: stdout + stderr };
  } catch (err) {
    const message =
      err instanceof Error ? err.message : "Unknown error during install";
    return { success: false, output: message };
  }
}

/**
 * Install all resolved skills with progress reporting.
 */
export async function installAll(
  skills: ResolvedSkill[],
  opts: { dryRun?: boolean } = {},
): Promise<{ installed: number; failed: number; skipped: number }> {
  let installed = 0;
  let failed = 0;
  let skipped = 0;

  for (const skill of skills) {
    if (!skill.install_command || skill.install_command.trim() === "") {
      warn(`Skipping ${skill.name} — no install command`);
      skipped++;
      continue;
    }

    if (opts.dryRun) {
      info(`[dry-run] Would run: ${skill.install_command}`);
      skipped++;
      continue;
    }

    const spinner = ora(`Installing ${skill.name}...`).start();

    const result = await installSkill(skill);

    if (result.success) {
      spinner.succeed(`Installed ${skill.name}`);
      installed++;
    } else {
      spinner.fail(`Failed to install ${skill.name}`);
      errorMsg(`  ${result.output.split("\n")[0]}`);
      failed++;
    }
  }

  console.log("");
  success(
    `Done: ${installed} installed, ${failed} failed, ${skipped} skipped`,
  );

  return { installed, failed, skipped };
}
