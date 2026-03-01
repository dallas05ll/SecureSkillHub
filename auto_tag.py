#!/usr/bin/env python3
"""
Auto-tag all skills based on name and description keyword matching.

Assigns tags from our tag hierarchy based on keyword patterns found
in the skill name, description, and repo URL.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SKILLS_DIR = Path("data/skills")

# Keyword -> tag mappings. Each entry: (tag_id, keywords_list)
# Checked against name + description (lowercased)
TAG_RULES: list[tuple[str, list[str]]] = [
    # --- Software Development ---
    ("dev", ["developer", "code", "programming", "sdk", "compiler", "lint", "debug"]),
    ("dev-web", ["web app", "webapp", "html", "css", "website", "browser"]),
    ("dev-web-frontend-react", ["react", "jsx", "next.js", "nextjs"]),
    ("dev-web-frontend-vue", ["vue", "nuxt"]),
    ("dev-web-frontend-svelte", ["svelte"]),
    ("dev-web-backend-node", ["node.js", "nodejs", "express", "npm", "bun"]),
    ("dev-web-backend-python", ["python", "django", "flask", "fastapi"]),
    ("dev-web-backend-go", ["golang", " go "]),
    ("dev-web-backend-rust", ["rust", "cargo"]),
    ("dev-web-fullstack-nextjs", ["next.js", "nextjs"]),
    ("dev-devops-docker", ["docker", "container", "compose"]),
    ("dev-devops-k8s", ["kubernetes", "k8s", "helm"]),
    ("dev-devops-ci", ["ci/cd", "github actions", "jenkins", "pipeline"]),
    ("dev-git", ["git repo", "git commit", "gitlab", "bitbucket", "pull request", "pr review", "git-", "gitops"]),
    ("dev-testing", ["test", "testing", "jest", "pytest", "cypress", "playwright", "qa"]),

    # --- Data & AI ---
    ("data", ["data", "analytics", "dataset", "etl"]),
    ("data-ai", ["ai", "machine learning", "ml", "llm", "model", "neural", "gpt", "claude", "openai", "anthropic", "gemini"]),
    ("data-ai-nlp", ["nlp", "natural language", "text", "summariz", "translat"]),
    ("data-ai-vision", ["image", "vision", "ocr", "photo", "screenshot"]),
    ("data-ai-audio", ["audio", "speech", "voice", "tts", "whisper", "music", "sound"]),
    ("data-db", ["database", "sql", "postgres", "mysql", "mongo", "redis", "sqlite", "supabase", "firebase"]),
    ("data-db-graph", ["neo4j", "graph database", "graphql"]),
    ("data-db-vector", ["vector", "embedding", "pinecone", "qdrant", "weaviate", "milvus", "chroma"]),

    # --- Productivity & Office ---
    ("prod", ["productiv", "workflow", "automat"]),
    ("prod-docs", ["document", "notion", "obsidian", "markdown", "wiki", "confluence", "docs"]),
    ("prod-pm", ["project management", "jira", "linear", "asana", "todoist", "trello", "task"]),
    ("prod-comm", ["slack", "discord", "telegram", "email", "gmail", "chat", "messag", "communi"]),
    ("prod-calendar", ["calendar", "schedule", "agenda", "booking"]),
    ("prod-notes", ["note", "memo", "journal", "diary"]),

    # --- Integrations & APIs ---
    ("integ", ["api", "integration", "connect", "webhook", "oauth"]),
    ("integ-cloud", ["aws", "azure", "gcp", "cloud", "s3", "lambda"]),
    ("integ-cloud-aws", ["aws", "amazon", "s3", "lambda", "dynamodb", "ec2"]),
    ("integ-cloud-azure", ["azure", "microsoft cloud"]),
    ("integ-cloud-gcp", ["gcp", "google cloud", "bigquery"]),
    ("integ-payment", ["payment", "stripe", "paypal", "billing", "invoice"]),
    ("integ-social", ["twitter", "facebook", "instagram", "linkedin", "social media", "youtube"]),
    ("integ-crm", ["salesforce", "hubspot", "crm", "customer"]),

    # --- Security & Compliance ---
    ("sec", ["security", "auth", "encrypt", "firewall", "vulnerab", "pentest", "threat"]),
    ("sec-auth", ["authentication", "oauth", "jwt", "sso", "identity", "login"]),
    ("sec-scan", ["scanner", "scan", "audit", "compliance", "cve"]),
    ("sec-crypto", ["crypto", "blockchain", "web3", "solana", "ethereum", "defi", "wallet", "token"]),

    # --- Utilities ---
    ("util", ["util", "tool", "helper", "convert"]),
    ("util-file", ["file", "filesystem", "storage", "upload", "download", "backup", "s3"]),
    ("util-search", ["search", "find", "index", "browse", "scrape", "crawl", "fetch"]),
    ("util-monitor", ["monitor", "logging", "metrics", "observ", "alert", "sentry", "datadog"]),
    ("util-map", ["map", "geolocation", "gps", "location", "geocod", "mapbox", "amap"]),
    ("util-media", ["media", "video", "stream", "ffmpeg", "youtube"]),
]


def auto_tag(name: str, description: str, repo_url: str) -> list[str]:
    """Determine tags for a skill based on keywords."""
    # Only match against name + description, NOT repo URL (every URL has github.com)
    text = f"{name} {description}".lower()
    tags = set()

    for tag_id, keywords in TAG_RULES:
        for kw in keywords:
            if kw.lower() in text:
                tags.add(tag_id)
                break

    # If no tags matched, assign "util" as fallback for MCP servers
    if not tags:
        if "mcp" in text:
            tags.add("util")
        if "server" in text:
            tags.add("integ")

    return sorted(tags)


def main():
    count = 0
    tagged = 0
    tag_dist: dict[str, int] = {}

    for f in sorted(SKILLS_DIR.glob("*.json")):
        data = json.loads(f.read_text())
        count += 1

        name = data.get("name", "")
        desc = data.get("description", "")
        repo = data.get("repo_url", "")

        new_tags = auto_tag(name, desc, repo)
        if new_tags:
            tagged += 1

        # Preserve system tags (status-*, repo_unavailable) that other scripts manage
        existing_tags = data.get("tags", [])
        system_tags = [t for t in existing_tags if t == "repo_unavailable" or t == "clone_failure" or str(t).startswith("status-")]
        data["tags"] = list(dict.fromkeys(system_tags + new_tags))
        f.write_text(json.dumps(data, indent=2))

        for t in new_tags:
            tag_dist[t] = tag_dist.get(t, 0) + 1

    print(f"Tagged {tagged}/{count} skills")
    print(f"\nTag distribution (top 20):")
    for tag, cnt in sorted(tag_dist.items(), key=lambda x: -x[1])[:20]:
        print(f"  {tag}: {cnt}")


if __name__ == "__main__":
    main()
