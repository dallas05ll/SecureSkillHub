import { apiFetch, ApiError } from "../api.js";

interface SearchResult {
  id: string;
  name: string;
  type: string;
  score: number;
  tier: string;
  verified: boolean;
  safe: boolean;
  tags: string[];
  one_liner: string;
  install: string;
  commit: string;
  report_url: string;
}

interface SearchResponse {
  total: number;
  offset: number;
  limit: number;
  results: SearchResult[];
}

interface SearchParams {
  query?: string;
  type?: string;
  tags?: string;
  tier?: string;
  verified?: boolean;
  limit?: number;
}

export async function searchSkills(apiBase: string, params: SearchParams) {
  const qs = new URLSearchParams();
  if (params.type) qs.set("type", params.type);
  if (params.query) qs.set("q", params.query);
  if (params.tags) qs.set("tags", params.tags);
  if (params.tier) qs.set("tier", params.tier);
  if (params.verified !== undefined) qs.set("verified", String(params.verified));
  if (params.limit) qs.set("limit", String(params.limit));

  try {
    const data = await apiFetch<SearchResponse>(
      apiBase,
      `/v2/search?${qs.toString()}`
    );

    if (data.results.length === 0) {
      return {
        content: [
          {
            type: "text" as const,
            text: `No results found for your search. Try broadening your query or changing filters.\n\nFilters used: type=${params.type || "all"}, verified=${params.verified ?? true}${params.query ? `, query="${params.query}"` : ""}${params.tags ? `, tags=${params.tags}` : ""}${params.tier ? `, tier=${params.tier}` : ""}`,
          },
        ],
      };
    }

    const lines = data.results.map((r, i) => {
      const badge = r.verified ? "Verified" : "Unverified";
      return `${i + 1}. **${r.name}** (${r.id})\n   Score: ${r.score} | Tier: ${r.tier} | ${badge} | Type: ${r.type}\n   ${r.one_liner}\n   Tags: ${r.tags.join(", ")}\n   Install: \`${r.install}\``;
    });

    const text = `Found ${data.total} results (showing ${data.results.length}):\n\n${lines.join("\n\n")}`;

    return { content: [{ type: "text" as const, text }] };
  } catch (err) {
    if (err instanceof ApiError) {
      return {
        content: [{ type: "text" as const, text: `Search failed: ${err.message}` }],
        isError: true,
      };
    }
    throw err;
  }
}
