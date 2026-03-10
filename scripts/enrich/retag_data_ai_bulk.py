#!/usr/bin/env python3
"""
Bulk add data-ai-rag and data-ai-agents sub-tags to data-ai skills.

Finds all skills tagged `data-ai` that lack the specific sub-tags,
then applies keyword-based sub-tags.

Modes:
  --dry-run   (default) Print counts and samples without writing
  --execute   Apply changes and log to skill-manager-log.json

Usage:
    python3 scripts/enrich/retag_data_ai_bulk.py --dry-run
    python3 scripts/enrich/retag_data_ai_bulk.py --execute
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = PROJECT_ROOT / "data" / "skills"
SM_LOG = PROJECT_ROOT / "data" / "skill-manager-log.json"

# ---------------------------------------------------------------------------
# Keyword rules for data-ai sub-tags
# ---------------------------------------------------------------------------
DATA_AI_RULES: list[tuple[str, list[str]]] = [
    ("data-ai-rag", [
        " rag ", "retrieval-augmented", "retrieval augmented",
        "vector search", "vector store", "vector db", "vectordb",
        "embedding search", "embeddings search",
        "langchain retrieval", "llamaindex", "llama_index", "llama-index",
        "knowledge retrieval", "document retrieval",
        "semantic search", "hybrid search",
        "pinecone", "weaviate", "qdrant", "chroma", "milvus",
    ]),
    ("data-ai-agents", [
        "agent framework", "agent orchestrat", "multi-agent", "multiagent",
        "crewai", "crew ai", "autogen", "langgraph", "langchain agent",
        "autonomous agent", "ai agent framework",
        "swarm agent", "agentic workflow", "agentic framework",
        "task decomposition", "agent loop", "tool-use agent",
        "smolagents", "pydantic-ai", "pydantic ai",
    ]),
]

# Tags indicating skill already has the specific sub-tag
ALREADY_RAG: set[str] = {"data-ai-rag", "ai-rag", "vector-search", "data-rag", "rag"}
ALREADY_AGENTS: set[str] = {"data-ai-agents", "ai-agents", "agent-framework", "dev-agents", "dev-multi-agent"}


def load_skill(path: Path) -> dict[str, Any] | None:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def save_skill(path: Path, data: dict[str, Any]) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def log_to_sm(entry: dict[str, Any]) -> None:
    """Append to skill-manager-log.json."""
    try:
        if SM_LOG.exists():
            with open(SM_LOG) as f:
                log = json.load(f)
        else:
            log = {"log_version": "1.0", "entries": []}

        if isinstance(log, list):
            log.append(entry)
        elif isinstance(log, dict):
            log.setdefault("entries", []).append(entry)
        else:
            log = [entry]

        with open(SM_LOG, "w") as f:
            json.dump(log, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except Exception as exc:
        print(f"  [warn] Could not write SM log: {exc}", file=sys.stderr)


def match_rules(text: str, rules: list[tuple[str, list[str]]]) -> list[str]:
    """Return all sub-tag IDs whose keywords appear in text."""
    matches = []
    for tag_id, keywords in rules:
        for kw in keywords:
            if kw in text:
                matches.append(tag_id)
                break
    return matches


def run(execute: bool) -> None:
    mode = "EXECUTE" if execute else "DRY-RUN"
    print(f"\n=== retag_data_ai_bulk.py  [{mode}] ===\n")

    all_skills = sorted(SKILLS_DIR.glob("*.json"))
    print(f"Total skill files: {len(all_skills)}")

    # Find data-ai candidates
    rag_candidates: list[tuple[Path, dict[str, Any]]] = []
    agents_candidates: list[tuple[Path, dict[str, Any]]] = []

    for path in all_skills:
        data = load_skill(path)
        if data is None:
            continue
        tags = set(data.get("tags", []))
        if "data-ai" not in tags:
            continue

        needs_rag = not bool(ALREADY_RAG & tags)
        needs_agents = not bool(ALREADY_AGENTS & tags)

        if needs_rag or needs_agents:
            if needs_rag:
                rag_candidates.append((path, data))
            if needs_agents:
                agents_candidates.append((path, data))

    print(f"Candidates needing RAG check:    {len(rag_candidates)}")
    print(f"Candidates needing Agents check: {len(agents_candidates)}\n")

    # Match and collect changes
    changes: dict[Path, list[str]] = {}  # path -> list of tags to add
    tag_counts: dict[str, int] = {"data-ai-rag": 0, "data-ai-agents": 0}

    # RAG pass
    for path, data in rag_candidates:
        name = (data.get("name") or "").lower()
        desc = (data.get("description") or "").lower()
        text = f" {name} {desc} "
        matched = match_rules(text, DATA_AI_RULES)
        if "data-ai-rag" in matched:
            changes.setdefault(path, []).append("data-ai-rag")
            tag_counts["data-ai-rag"] += 1

    # Agents pass
    for path, data in agents_candidates:
        name = (data.get("name") or "").lower()
        desc = (data.get("description") or "").lower()
        text = f" {name} {desc} "
        matched = match_rules(text, DATA_AI_RULES)
        if "data-ai-agents" in matched:
            changes.setdefault(path, []).append("data-ai-agents")
            tag_counts["data-ai-agents"] += 1

    print(f"Skills that will be updated: {len(changes)}")
    print(f"\nSub-tags that will be added (counts):")
    for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1]):
        print(f"  {tag:40s}  {count:>4}")

    print("\nSample changes (first 30):")
    for i, (path, new_tags) in enumerate(list(changes.items())[:30]):
        data = load_skill(path)
        name = (data.get("name") or path.stem)[:60]
        print(f"  [{path.stem[:40]}]  {name}")
        print(f"    + {new_tags}")

    if execute:
        written = 0
        for path, new_tags in changes.items():
            data = load_skill(path)
            if data is None:
                continue
            existing = data.get("tags", [])
            to_add = [t for t in new_tags if t not in existing]
            if to_add:
                data["tags"] = sorted(set(existing + to_add))
                save_skill(path, data)
                written += 1

        log_entry = {
            "type": "retag_data_ai_bulk",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "updated": written,
            "tag_counts": tag_counts,
        }
        log_to_sm(log_entry)
        print(f"\nWrote {written} skill files. Logged to skill-manager-log.json.")
    else:
        print(f"\n[dry-run] No files written. Run with --execute to apply.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk sub-tag data-ai skills.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", default=True)
    group.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    run(execute=args.execute)


if __name__ == "__main__":
    main()
