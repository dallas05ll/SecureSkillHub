#!/usr/bin/env python3
"""Tag skillsmp skills that only have 'agent-skills' tag with domain-specific tags.

Rules:
- Only modifies files where source_hub == 'skillsmp'
- Only modifies files where the only non-installs tag is 'agent-skills'
- Adds exactly one domain tag (the first matching category)
- Falls back to 'utilities' for unclassifiable skills
- Uses word-boundary regex to avoid substring false positives

Pattern matching uses name + description only (NOT repo_url), except for
categories where the repo_url provides meaningful signal (e.g. org names).
dev-git in particular must NOT match on 'github.com' in repo URLs.
"""

import json
import re
import glob
from pathlib import Path
from collections import defaultdict

# Category rules: (category_name, [(pattern, match_in_url_too)])
# Second element: True = match against name+desc+url, False = name+desc only
CATEGORY_RULES = [
    ("dev-web-frontend", True, [
        r"\breact(?:\.?js)?\b", r"\bvue(?:\.?js)?\b", r"\bsvelte\b", r"\bangular\b",
        r"\bfrontend\b", r"\bcss\b", r"\bhtml\b", r"\btailwind\b", r"\bcomponent\b",
        r"\bnext\.?js\b", r"\bnuxt\b", r"\bremix\b", r"\bastro\b",
        r"\bui\s+(component|framework|library)\b",
    ]),
    ("dev-web-backend", True, [
        r"\bnode\.?js\b", r"\bexpress(?:\.?js)?\b", r"\bfastapi\b", r"\bdjango\b",
        r"\bflask\b", r"\bbackend\b", r"\brest\s*api\b", r"\bgraphql\b",
        r"\bendpoint\b", r"\bmiddleware\b", r"\brails\b", r"\blaravel\b", r"\bspring\b",
        r"\bfastify\b", r"\bhapi\b",
    ]),
    ("dev-web-fullstack", True, [
        r"\bfullstack\b", r"\bfull[\s-]stack\b", r"\bmonorepo\b", r"\bwebapp\b",
    ]),
    ("dev-devops", True, [
        r"\bdocker\b", r"\bkubernetes\b", r"\bk8s\b", r"\bdevops\b",
        r"\bterraform\b", r"\bansible\b", r"\bhelm\b",
        r"\bci/cd\b", r"\bgithub.?actions\b", r"\bjenkins\b",
        r"\baws\b", r"\bgcp\b", r"\bazure\b",
        r"\binfrastructure\b", r"\bdeployment\b", r"\bpipeline\b",
        r"\bdeploy\b",
    ]),
    ("data-db", True, [
        r"\bsql\b", r"\bpostgres(?:ql)?\b", r"\bmysql\b",
        r"\bdatabase\b", r"\bmongodb?\b", r"\bredis\b",
        r"\bsupabase\b", r"\bfirebase\b", r"\bprisma\b", r"\bdrizzle\b", r"\btypeorm\b",
        r"\bsqlite\b", r"\belasticsearch\b",
    ]),
    ("data-ai", True, [
        r"\bllm\b", r"\bmachine\s+learning\b", r"\b(?<!\w)ml\b",
        r"\bgpt\b", r"\bopenai\b",
        # Removed 'claude' — too many skillsmp skills mention claude as their host platform
        r"\bembedding\b", r"\b(?<!\w)rag\b", r"\bvector\s*(store|db|search|index)\b",
        r"\blangchain\b", r"\bllamaindex\b", r"\btransformer\b", r"\bneural\b",
        r"\bartificial\s+intelligence\b", r"\bai\s+(agent|assistant|model|tool)\b",
        r"\bgenerat(?:ive\s+ai|ion\s+ai)\b", r"\bllama\b", r"\bmistral\b",
        r"\bprompt\s+(engineer|inject|template|chain|optim)\b",
        # 'prompt' alone is too broad (many skills mention "prompt" for UI)
        # Only match when it's clearly AI context
    ]),
    ("security", True, [
        r"\bsecurity\b", r"\boauth\b", r"\bjwt\b", r"\bencrypt\b",
        r"\bvulnerabilit\b", r"\bpentest\b", r"\bsecurity\s+audit\b",
        # Removed plain 'audit' — too many false positives (accessibility audit, code audit, etc.)
        r"\bfirewall\b", r"\bssl\b", r"\btls\b",
        r"\bauthentication\b", r"\bauthorization\b",
        r"\b(?:cyber)?security\b", r"\bmalware\b", r"\bexploit\b",
    ]),
    ("dev-testing", True, [
        r"\btesting\b", r"\btest\s+(?:suite|coverage|case|framework|plan)\b",
        r"\bunit\s+test\b", r"\bjest\b", r"\bpytest\b",
        r"\be2e\b", r"\bplaywright\b", r"\bcypress\b",
        r"\bvitest\b", r"\bcoverage\b", r"\bspec\s+file\b",
    ]),
    ("dev-mobile", True, [
        r"\bios\b", r"\bandroid\b", r"\breact.native\b", r"\bflutter\b",
        r"\bswift(?:ui)?\b", r"\bkotlin\b", r"\bmobile\b",
    ]),
    # dev-git: match name+desc only (NOT repo_url) to avoid matching 'github.com'
    # Pattern requires git to be followed by a specific operation word OR to be standalone
    # but NOT 'github' or 'gitlab' (those are platforms, not git-specific)
    ("dev-git", False, [
        r"\bgit\s+(?:push|pull|clone|blame|log|diff|stash|checkout|reset|add|commit|rebase|merge|flow|ops|cherry.pick)\b",
        r"\bgitflow\b", r"\bgit-ops\b", r"\bcommits?\b", r"\bbranch(?:ing)?\b",
        r"\bmerge\s+(?:request|conflict)\b", r"\brebase\b",
        r"\bpull\s*request\b", r"\bpr\s+review\b",
        r"\bversion\s+control\b",
        r"\b(?:git|version)\s+history\b",
        # standalone 'git' only when it's clearly about git the tool:
        r"(?:using|with|via|learn|master|understand)\s+git\b",
    ]),
    ("utilities", True, [
        r"\butilities\b", r"\butil(?:ity|ities)?\b", r"\btool(?:kit|box|set)?\b",
        r"\bhelper\b", r"\b(?:command.line|cli)\b", r"\bscript\b",
        r"\bautomation\b", r"\bworkflow\b", r"\bproductivity\b",
    ]),
]

# Pre-compile
COMPILED_RULES = []
for entry in CATEGORY_RULES:
    cat, use_url, patterns = entry
    compiled_patterns = [re.compile(p, re.IGNORECASE) for p in patterns]
    COMPILED_RULES.append((cat, use_url, compiled_patterns))


def classify_skill(name: str, description: str, repo_url: str) -> str:
    """Return the first matching category tag, or 'utilities' as fallback."""
    name = name or ""
    description = description or ""
    repo_url = repo_url or ""
    name_desc = f"{name} {description}"
    full_text = f"{name} {description} {repo_url}"

    for category, use_url, patterns in COMPILED_RULES:
        text = full_text if use_url else name_desc
        for pat in patterns:
            if pat.search(text):
                return category
    return "utilities"


def main():
    skills_dir = Path("data/skills")
    files = sorted(skills_dir.glob("*.json"))

    target_files = []
    for f in files:
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        if data.get("source_hub") != "skillsmp":
            continue
        tags = data.get("tags", [])
        domain_tags = [
            t for t in tags
            if not t.startswith("installs:")
            and t not in ("agent-skills", "repo_unavailable")
        ]
        if len(domain_tags) == 0:
            target_files.append((f, data))

    print(f"Target files (skillsmp, only agent-skills): {len(target_files)}")

    stats = defaultdict(int)
    fallback_count = 0
    modified = 0

    for f, data in target_files:
        name = data.get("name", "") or ""
        description = data.get("description", "") or ""
        repo_url = data.get("repo_url", "") or ""

        category = classify_skill(name, description, repo_url)

        # Track true fallbacks (no keyword at all matched before reaching utilities default)
        name_desc = f"{name} {description}"
        full_text = f"{name} {description} {repo_url}"
        matched_any_non_util = False
        for cat, use_url, patterns in COMPILED_RULES[:-1]:
            text = full_text if use_url else name_desc
            for pat in patterns:
                if pat.search(text):
                    matched_any_non_util = True
                    break
            if matched_any_non_util:
                break
        if not matched_any_non_util:
            # Also check utilities keywords explicitly
            util_match = False
            for pat in COMPILED_RULES[-1][2]:
                if pat.search(full_text):
                    util_match = True
                    break
            if not util_match:
                fallback_count += 1

        tags = data.get("tags", [])
        if category not in tags:
            if "agent-skills" in tags:
                idx = tags.index("agent-skills")
                tags.insert(idx + 1, category)
            else:
                tags.append(category)
            data["tags"] = tags
            f.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            modified += 1
        stats[category] += 1

    print(f"Modified: {modified} files")
    print(f"\nCategory breakdown:")
    for cat, count in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")
    print(f"\nTotal tagged: {sum(stats.values())}")
    print(f"True fallbacks (default utilities, no keyword match): {fallback_count}")


if __name__ == "__main__":
    main()
