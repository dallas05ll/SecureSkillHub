import chalk from "chalk";
import type { ResolvedSkill } from "./types.js";

/**
 * Build a formatted ASCII table from headers and rows.
 */
export function table(headers: string[], rows: string[][]): string {
  if (rows.length === 0) {
    return "(no results)";
  }

  // Calculate column widths
  const colWidths = headers.map((h, i) => {
    const dataMax = rows.reduce(
      (max, row) => Math.max(max, (row[i] ?? "").length),
      0,
    );
    return Math.max(h.length, dataMax);
  });

  // Build separator
  const separator = colWidths.map((w) => "-".repeat(w + 2)).join("+");

  // Build header
  const headerLine = headers
    .map((h, i) => ` ${h.padEnd(colWidths[i]!)} `)
    .join("|");

  // Build rows
  const dataLines = rows.map((row) =>
    row.map((cell, i) => ` ${(cell ?? "").padEnd(colWidths[i]!)} `).join("|"),
  );

  return [headerLine, separator, ...dataLines].join("\n");
}

export function success(msg: string): void {
  console.log(chalk.green("✓") + " " + msg);
}

export function error(msg: string): void {
  console.error(chalk.red("✗") + " " + msg);
}

export function warn(msg: string): void {
  console.log(chalk.yellow("!") + " " + msg);
}

export function info(msg: string): void {
  console.log(chalk.blue("i") + " " + msg);
}

/**
 * Format a resolved skill as a table row.
 */
export function skillRow(skill: ResolvedSkill): string[] {
  const riskColor =
    skill.tier <= 2
      ? chalk.green
      : skill.tier <= 3
        ? chalk.yellow
        : chalk.red;

  return [
    skill.name,
    String(skill.score),
    riskColor(`T${skill.tier}`),
    skill.primary_language,
    skill.verified ? chalk.green("yes") : chalk.dim("no"),
    skill.install_command.length > 50
      ? skill.install_command.substring(0, 47) + "..."
      : skill.install_command,
  ];
}

/**
 * Require auth or exit with a message.
 */
export function requireAuth(config: unknown): asserts config is NonNullable<unknown> {
  if (!config) {
    error("Not logged in. Run `secureskillhub login` first.");
    process.exit(1);
  }
}
