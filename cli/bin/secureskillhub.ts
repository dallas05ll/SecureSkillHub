#!/usr/bin/env node

import { Command } from "commander";
import { loginCommand } from "../src/commands/login.js";
import { logoutCommand } from "../src/commands/logout.js";
import { whoamiCommand } from "../src/commands/whoami.js";
import { listCommand } from "../src/commands/list.js";
import { createCommand } from "../src/commands/create.js";
import { addCommand } from "../src/commands/add.js";
import { removeCommand } from "../src/commands/remove.js";
import { resolveCommand } from "../src/commands/resolve.js";
import { installCommand } from "../src/commands/install.js";
import { searchCommand } from "../src/commands/search.js";

const program = new Command();

program
  .name("secureskillhub")
  .description(
    "Install your personalized, security-verified AI skill stack",
  )
  .version("0.1.0");

// ─── Auth ────────────────────────────────────────────────────────────────────

program
  .command("login")
  .description("Log in via GitHub OAuth device flow")
  .action(async () => {
    await loginCommand();
  });

program
  .command("logout")
  .description("Log out and revoke your token")
  .action(async () => {
    await logoutCommand();
  });

program
  .command("whoami")
  .description("Show current authenticated user")
  .action(async () => {
    await whoamiCommand();
  });

// ─── Package Management ─────────────────────────────────────────────────────

program
  .command("list")
  .description("List your custom skill packages")
  .action(async () => {
    await listCommand();
  });

program
  .command("create")
  .description("Create a new skill package")
  .argument("<name>", "Package name")
  .action(async (name: string) => {
    await createCommand(name);
  });

// ─── Package Contents ───────────────────────────────────────────────────────

program
  .command("add")
  .description("Add a tag or pin a skill to your default package")
  .argument("<item>", "Tag ID (e.g., security-scanning) or skill ID")
  .option(
    "-p, --package <id>",
    "Target package ID (defaults to your default package)",
  )
  .action(async (item: string, opts: { package?: string }) => {
    await addCommand(item, opts);
  });

program
  .command("remove")
  .description("Remove a tag or unpin a skill from your default package")
  .argument("<item>", "Tag ID (e.g., security-scanning) or skill ID to remove")
  .option(
    "-p, --package <id>",
    "Target package ID (defaults to your default package)",
  )
  .action(async (item: string, opts: { package?: string }) => {
    await removeCommand(item, opts);
  });

// ─── Resolve & Install ─────────────────────────────────────────────────────

program
  .command("resolve")
  .description("Resolve a package to a concrete list of skills")
  .option(
    "-p, --package <id>",
    "Package ID to resolve (defaults to your default package)",
  )
  .action(async (opts: { package?: string }) => {
    await resolveCommand(opts);
  });

program
  .command("install")
  .description("Resolve and install all skills in a package")
  .option(
    "-p, --package <id>",
    "Package ID to install (defaults to your default package)",
  )
  .option("-y, --yes", "Skip confirmation prompt")
  .option("--dry-run", "Show what would be installed without installing")
  .action(
    async (opts: { package?: string; yes?: boolean; dryRun?: boolean }) => {
      await installCommand(opts);
    },
  );

// ─── Search ─────────────────────────────────────────────────────────────────

program
  .command("search")
  .description("Search the skill catalog (no auth required)")
  .argument("<query>", "Search query")
  .option("-l, --limit <n>", "Maximum results to show", "20")
  .action(async (query: string, opts: { limit?: string }) => {
    await searchCommand(query, opts);
  });

// ─── Run ────────────────────────────────────────────────────────────────────

program.parseAsync(process.argv).catch((err) => {
  console.error(err);
  process.exit(1);
});
