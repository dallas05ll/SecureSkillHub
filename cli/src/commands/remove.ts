import chalk from "chalk";
import { getConfig } from "../lib/config.js";
import { createClient, createPublicClient } from "../lib/api-client.js";
import { success, error, requireAuth } from "../lib/output.js";
import type { TagNode, PackageWithDetails } from "../lib/types.js";

/**
 * Determine if the argument is a tag path.
 * Tags use dash-separated IDs (e.g., "security-scanning").
 */
async function isTagPath(arg: string): Promise<boolean> {
  // Try to fetch tags.json and check if arg matches any tag in the hierarchy
  try {
    const publicClient = createPublicClient();
    const tagsData = await publicClient.get<{ version: string; updated_at: string; categories: TagNode[] }>("/api/tags.json");
    return matchesTag(tagsData.categories, arg);
  } catch {
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

export async function removeCommand(
  item: string,
  options: { package?: string },
): Promise<void> {
  const config = getConfig();
  requireAuth(config);

  const client = createClient();

  try {
    let packageId: string;
    if (options.package) {
      packageId = options.package;
    } else {
      packageId = await getDefaultPackageId(client);
    }

    const isTag = await isTagPath(item);

    if (isTag) {
      await client.delete(
        `/v1/me/packages/${packageId}/tags/${encodeURIComponent(item)}`,
      );
      success(`Removed tag ${chalk.cyan(item)} from package`);
    } else {
      await client.delete(
        `/v1/me/packages/${packageId}/pins/${encodeURIComponent(item)}`,
      );
      success(`Unpinned skill ${chalk.cyan(item)} from package`);
    }
  } catch (err) {
    error(
      "Failed to remove: " +
        (err instanceof Error ? err.message : String(err)),
    );
    process.exit(1);
  }
}
