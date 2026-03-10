#!/usr/bin/env python3
"""Diagnostic: find skills tagged dev-git and break down which pattern triggered."""
import json, re
from pathlib import Path

# The current dev-git patterns
PATTERNS = [
    r"\bgit\s+(?:push|pull|clone|blame|log|diff|stash|checkout|reset|add|commit|rebase|merge|flow|ops|cherry.pick)\b",
    r"\bgitflow\b", r"\bgit-ops\b", r"\bcommits?\b", r"\bbranch(?:ing)?\b",
    r"\bmerge\s+(?:request|conflict)\b", r"\brebase\b",
    r"\bpull\s*request\b", r"\bpr\s+review\b",
    r"\bversion\s+control\b",
    r"\b(?:git|version)\s+history\b",
    r"(?:using|with|via|learn|master|understand)\s+git\b",
]
LABELS = [
    "git <op>", "gitflow", "git-ops", "commit", "branch", "merge request",
    "rebase", "pull request", "pr review", "version control", "git history", "using git",
]
compiled = [(re.compile(p, re.IGNORECASE), l) for p, l in zip(PATTERNS, LABELS)]

SKILLS_DIR = Path(__file__).resolve().parents[2] / "data" / "skills"

samples = {}
counts = {}
for label in LABELS:
    counts[label] = 0
    samples[label] = []

for f in sorted(SKILLS_DIR.glob("*.json")):
    try:
        with open(f) as fh:
            data = json.load(fh)
    except:
        continue
    if data.get('source_hub') != 'skillsmp':
        continue
    tags = data.get('tags', [])
    if 'dev-git' not in tags:
        continue

    name = data.get('name', '') or ''
    desc = (data.get('description') or '')
    text = f"{name} {desc}"

    for pat, label in compiled:
        m = pat.search(text)
        if m:
            counts[label] += 1
            if len(samples[label]) < 3:
                samples[label].append(f"{name}: '{m.group()}'")
            break

print("dev-git trigger breakdown:")
for label, count in sorted(counts.items(), key=lambda x: -x[1]):
    if count > 0:
        print(f"  {label}: {count}")
        for s in samples[label]:
            print(f"    e.g. {s}")
