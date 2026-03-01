import chalk from "chalk";
import { createPublicClient } from "../lib/api-client.js";
import { table, error, info } from "../lib/output.js";
import type { SearchIndexEntry } from "../lib/types.js";

/**
 * Simple fuzzy match: check if all query words appear somewhere in the text.
 */
function fuzzyMatch(query: string, text: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const haystack = text.toLowerCase();
  return words.every((word) => haystack.includes(word));
}

/**
 * Score a search result for ranking. Higher is better.
 */
function scoreMatch(query: string, entry: SearchIndexEntry): number {
  const q = query.toLowerCase();
  let score = 0;

  // Exact name match
  if (entry.name.toLowerCase() === q) {
    score += 100;
  }
  // Name starts with query
  else if (entry.name.toLowerCase().startsWith(q)) {
    score += 50;
  }
  // Name contains query
  else if (entry.name.toLowerCase().includes(q)) {
    score += 25;
  }

  // Boost by stars (normalized)
  score += Math.min(entry.stars / 100, 20);

  // Boost by overall_score
  score += entry.overall_score / 10;

  // Boost verified (pass status)
  if (entry.verification_status === "pass") {
    score += 5;
  }

  // Tag match
  const qWords = q.split(/\s+/);
  for (const word of qWords) {
    if (entry.tags.some((t) => t.toLowerCase().includes(word))) {
      score += 10;
    }
  }

  return score;
}

export async function searchCommand(
  query: string,
  options: { limit?: string },
): Promise<void> {
  const limit = parseInt(options.limit ?? "20", 10);

  try {
    const client = createPublicClient();
    const index = await client.get<SearchIndexEntry[]>("/api/search-index.json");

    // Build search text for each entry
    const results = index
      .filter((entry) => {
        const searchText = [
          entry.name,
          entry.description,
          ...entry.tags,
          entry.skill_type,
        ].join(" ");
        return fuzzyMatch(query, searchText);
      })
      .map((entry) => ({
        entry,
        relevance: scoreMatch(query, entry),
      }))
      .sort((a, b) => b.relevance - a.relevance)
      .slice(0, limit);

    if (results.length === 0) {
      info(`No skills found matching "${query}".`);
      return;
    }

    const statusColor = (status: string) =>
      status === "pass" ? chalk.green : status === "fail" ? chalk.red : chalk.yellow;

    const headers = ["Name", "Tags", "Stars", "Score", "Status", "Type"];
    const rows = results.map(({ entry }) => [
      entry.name,
      entry.tags.slice(0, 3).join(", ") +
        (entry.tags.length > 3 ? ` +${entry.tags.length - 3}` : ""),
      String(entry.stars),
      String(entry.overall_score),
      statusColor(entry.verification_status)(entry.verification_status),
      entry.skill_type || chalk.dim("n/a"),
    ]);

    console.log("");
    console.log(table(headers, rows));
    console.log("");
    console.log(
      chalk.dim(`${results.length} result(s) for "${query}"`),
    );
  } catch (err) {
    error(
      "Failed to search: " +
        (err instanceof Error ? err.message : String(err)),
    );
    process.exit(1);
  }
}
