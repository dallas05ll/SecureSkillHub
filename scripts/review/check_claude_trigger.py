#!/usr/bin/env python3
"""Diagnostic: find skills tagged data-ai solely due to 'claude' keyword."""
import json, re
from pathlib import Path

pat = re.compile(r"\bclaude\b", re.IGNORECASE)

# Find skills that would be tagged data-ai but ONLY because of 'claude'
# i.e., no other data-ai pattern matches
OTHER_AI_PATTERNS = [
    r"\bllm\b", r"\bmachine\s+learning\b", r"\b(?<!\w)ml\b",
    r"\bgpt\b", r"\bopenai\b", r"\bprompt\b", r"\bembedding\b",
    r"\b(?<!\w)rag\b", r"\bvector\s*(store|db|search|index)?\b",
    r"\blangchain\b", r"\bllamaindex\b", r"\btransformer\b", r"\bneural\b",
    r"\bartificial\s+intelligence\b", r"\bai\s+(agent|assistant|model|tool)\b",
    r"\bgenerat(?:ive\s+ai|ion\s+ai)\b", r"\bllama\b", r"\bmistral\b",
]
other_compiled = [re.compile(p, re.IGNORECASE) for p in OTHER_AI_PATTERNS]

SKILLS_DIR = Path(__file__).resolve().parents[2] / "data" / "skills"

claude_only = []
claude_plus = []
for f in sorted(SKILLS_DIR.glob("*.json")):
    try:
        with open(f) as fh:
            data = json.load(fh)
    except:
        continue
    if data.get('source_hub') != 'skillsmp':
        continue
    tags = data.get('tags', [])
    if 'data-ai' not in tags:
        continue

    name = data.get('name', '') or ''
    desc = (data.get('description') or '')
    text = f"{name} {desc}"

    has_claude = bool(pat.search(text))
    has_other = any(p.search(text) for p in other_compiled)

    if has_claude and not has_other:
        claude_only.append((name, desc[:60]))
    elif has_other:
        claude_plus.append((name, desc[:60]))

print(f"data-ai tagged by 'claude' ONLY (no other AI keywords): {len(claude_only)}")
print(f"data-ai tagged with other AI keywords: {len(claude_plus)}")
print("\nSamples of claude-only (questionable):")
for name, desc in claude_only[:15]:
    print(f"  {name}: {desc}")
