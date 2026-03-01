import chalk from "chalk";
import { getConfig } from "../lib/config.js";
import { createClient, createPublicClient } from "../lib/api-client.js";
import { success, error, info, requireAuth } from "../lib/output.js";
import type { TagNode, PackageWithDetails } from "../lib/types.js";

/**
 * Determine if the argument is a tag path by checking against the tag hierarchy.
 * Tags use dash-separated IDs (e.g., "security-scanning") or match a known tag ID.
 */
async function isTagPath(arg: string): Promise<boolean> {
  // Try to fetch tags.json and check if arg matches any tag in the hierarchy
  try {
    const publicClient = createPublicClient();
    const tagsData = await publicClient.get<{ version: string; updated_at: string; categories: TagNode[] }>("/api/tags.json");
    return matchesTag(tagsData.categories, arg);
  } catch {
    // If we can't fetch tags, fall back to heuristic:
    // If it looks like a UUID or contains dots, it's probably a skill ID
    return !arg.includes(".") && !arg.match(/^[0-9a-f-]{36}$/);
  }
}

function matchesTag(tags: TagNode[], query: string): boolean {
  for (const tag of tags) {
    if (tag.id === query || tag.label.toLowerCase() === query.toLowerCase()) {
      return true;
    }
    if (tag.children && matchesTag(tag.children, query)) {
      return true;
    }
  }
  return false;
}

/**
 * Find the user's default package ID.
 */
async function getDefaultPackageId(
  client: ReturnType<typeof createClient>,
): Promise<string> {
  const packages = await client.get<PackageWithDetails[]>("/v1/me/packages");
  const defaultPkg = packages.find((p) => p.is_default);
  if (!defaultPkg) {
    throw new Error(
      "No default package found. Create one with `secureskillhub create <name>`.",
    );
  }
  return defaultPkg.id;
}

export async function addCommand(
  item: string,
  options: { package?: string },
): Promise<void> {
  const config = getConfig();
  requireAuth(config);

  const client = createClient();

  try {
    // Determine package ID
    let packageId: string;
    if (options.package) {
      packageId = options.package;
    } else {
      packageId = await getDefaultPackageId(client);
    }

    // Determine if this is a tag or a skill ID
    const isTag = await isTagPath(item);

    if (isTag) {
      await client.post(`/v1/me/packages/${packageId}/tags`, {
        tag_paths: [item],
      });
      success(`Added tag ${chalk.cyan(item)} to package`);
    } else {
      await client.post(`/v1/me/packages/${packageId}/pins`, {
        skill_ids: [item],
      });
      success(`Pinned skill ${chalk.cyan(item)} to package`);
    }
  } catch (err) {
    error(
      "Failed to add: " +
        (err instanceof Error ? err.message : String(err)),
    );
    process.exit(1);
  }
}
