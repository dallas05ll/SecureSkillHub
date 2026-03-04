#!/usr/bin/env python3
"""
Auto-tag all skills based on name and description keyword matching.

Assigns MULTI-LEVEL tags from our tag hierarchy based on regex patterns found
in skill name and description. Uses word-boundary matching for accuracy.

Key design decisions:
- ALL matching tags are assigned (union, not first-match-wins)
- Parent tags are auto-propagated (dev-web-frontend-react → also gets dev-web-frontend, dev-web, dev)
- System tags preserved: repo_unavailable, clone_failure, status-*, agent-skills, installs:*
- repo_url excluded from matching (every URL has github.com)
- Word-boundary regex prevents substring false positives (e.g. "ai" in "email")
"""

import json
import re
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = PROJECT_ROOT / "data" / "skills"

# --- Tag Rules ---
# Each entry: (tag_id, [regex_patterns])
# Patterns are compiled with IGNORECASE and checked against name + description.
# ALL matching rules are applied (not first-match-wins).
# Use word boundaries (\b) to avoid substring false positives.
TAG_RULES: list[tuple[str, list[str]]] = [
    # ===== Software Development =====
    ("dev", [r"\b(?:developer|programming|sdk|compiler|lint(?:er|ing)?|debug(?:ger|ging)?)\b"]),
    ("dev-web", [r"\b(?:web\s*app|webapp|html|css|website|browser)\b"]),

    # Frontend frameworks
    ("dev-web-frontend-react", [r"\breact(?:\.?js)?\b", r"\bjsx\b", r"\bnext\.?js\b", r"\bnextjs\b"]),
    ("dev-web-frontend-vue", [r"\bvue(?:\.?js)?\b", r"\bnuxt\b"]),
    ("dev-web-frontend-svelte", [r"\bsvelte(?:kit)?\b"]),
    ("dev-web-frontend-angular", [r"\bangular\b"]),
    ("dev-web-frontend", [
        r"\bfrontend\b", r"\bcss\b", r"\btailwind\b",
        r"\bui\s+(?:component|framework|library)\b",
        r"\bremix\b", r"\bastro\b", r"\bvite\b",
    ]),

    # Backend frameworks
    ("dev-web-backend-node", [r"\bnode\.?js\b", r"\bnodejs\b", r"\bexpress(?:\.?js)?\b", r"\bnpm\b", r"\bbun\b", r"\bfastify\b", r"\bhapi\b"]),
    ("dev-web-backend-python", [r"\bpython\b", r"\bdjango\b", r"\bflask\b", r"\bfastapi\b"]),
    ("dev-web-backend-go", [r"\bgolang\b", r"\bgo\s+(?:server|api|backend|service|module)\b"]),
    ("dev-web-backend-rust", [r"\brust\b", r"\bcargo\b", r"\bactix\b", r"\btokio\b"]),
    ("dev-web-backend", [
        r"\bbackend\b", r"\brest\s*api\b", r"\bgraphql\b",
        r"\bendpoint\b", r"\bmiddleware\b", r"\brails\b", r"\blaravel\b", r"\bspring\b",
    ]),

    # Fullstack
    ("dev-web-fullstack-nextjs", [r"\bnext\.?js\b", r"\bnextjs\b"]),
    ("dev-web-fullstack-nuxt", [r"\bnuxt\b"]),
    ("dev-web-fullstack", [r"\bfull[\s-]?stack\b", r"\bmonorepo\b"]),

    # DevOps
    ("dev-devops-docker", [r"\bdocker\b", r"\bcontainer(?:ize|ization)?\b", r"\bcompose\b"]),
    ("dev-devops-k8s", [r"\bkubernetes\b", r"\bk8s\b", r"\bhelm\b"]),
    ("dev-devops-ci", [r"\bci/?cd\b", r"\bgithub\s*actions?\b", r"\bjenkins\b", r"\bgitlab\s*ci\b"]),
    ("dev-devops", [
        r"\bdevops\b", r"\bterraform\b", r"\bansible\b", r"\bpulumi\b",
        r"\binfrastructure\b", r"\bdeployment\b", r"\bpipeline\b",
    ]),

    # Git — match name+desc only (NOT url). Requires git + operation word.
    ("dev-git", [
        r"\bgit\s+(?:push|pull|clone|blame|log|diff|stash|checkout|reset|add|commit|rebase|merge|flow|ops|cherry[.-]pick)\b",
        r"\bgitflow\b", r"\bgitops\b", r"\bversion\s+control\b",
        r"\bpull\s*request\b", r"\bpr\s+review\b", r"\bmerge\s+(?:request|conflict)\b",
    ]),

    # Testing
    ("dev-testing", [
        r"\btesting\b", r"\btest\s+(?:suite|coverage|case|framework|plan|runner)\b",
        r"\bunit\s+test\b", r"\bjest\b", r"\bpytest\b", r"\bvitest\b",
        r"\be2e\b", r"\bplaywright\b", r"\bcypress\b",
    ]),

    # Agents & multi-agent
    ("dev-agents", [
        r"\bagent\s+(?:framework|orchestrat|system|runtime|protocol)\b",
        r"\bmulti[.-]?agent\b", r"\blangchain\b", r"\blanggraph\b",
        r"\bautogen\b", r"\bcrewai\b", r"\bagentic\s+workflow\b",
        r"\ba2a\b", r"\bagent[.-]to[.-]agent\b",
    ]),

    # Mobile
    ("dev-mobile-react-native", [r"\breact\s*native\b"]),
    ("dev-mobile-flutter", [r"\bflutter\b"]),
    ("dev-mobile", [
        r"\bios\s+app\b", r"\bandroid\s+app\b", r"\bmobile\s+(?:app|development|application)\b",
        r"\bswiftui\b", r"\bkotlin\s+(?:multiplatform|android)\b",
    ]),

    # Desktop
    ("dev-desktop-electron", [r"\belectron\b"]),
    ("dev-desktop-tauri", [r"\btauri\b"]),
    ("dev-desktop", [r"\bdesktop\s+(?:application|app)\b"]),

    # Game dev
    ("dev-gamedev", [r"\bunity\b", r"\bunreal\b", r"\bgodot\b", r"\bgame\s+(?:dev|engine|development)\b"]),

    # ===== Data & AI =====
    ("data-ai-nlp", [r"\bnlp\b", r"\bnatural\s+language\b", r"\bsummariz\w*\b", r"\btranslat\w*\b", r"\bsentiment\b", r"\btokeniz\w*\b"]),
    ("data-ai-vision", [r"\bimage\s+(?:process|recogni|generat|classif)\w*\b", r"\bcomputer\s+vision\b", r"\bocr\b", r"\bscreenshot\b"]),
    ("data-ai-audio", [r"\baudio\b", r"\bspeech\b", r"\bvoice\b", r"\btts\b", r"\bwhisper\b", r"\bmusic\b", r"\bsound\b"]),
    ("data-ai-rag", [r"\brag\b", r"\bretrieval[\s-]augmented\b"]),
    ("data-ai", [
        r"\b(?:artificial\s+)?intelligence\b", r"\bmachine\s+learning\b",
        r"\bllm\b", r"\bgpt(?:-[234])?\b", r"\bopenai\b", r"\banthropic\b", r"\bgemini\b",
        r"\bembedding\b", r"\btransformer\b", r"\bneural\b",
        r"\bai\s+(?:agent|assistant|model|tool|chatbot)\b",
        r"\bgenerat(?:ive\s+ai|ion\s+ai)\b", r"\bllama\b", r"\bmistral\b",
        r"\bprompt\s+(?:engineer|template|chain|optim)\w*\b",
        r"\blangchain\b", r"\bllamaindex\b",
    ]),

    # Database
    ("data-db-vector", [r"\bvector\s*(?:store|db|search|index|database)\b", r"\bpinecone\b", r"\bqdrant\b", r"\bweaviate\b", r"\bmilvus\b", r"\bchroma(?:db)?\b"]),
    ("data-db-graph", [r"\bneo4j\b", r"\bgraph\s+database\b"]),
    ("data-db", [
        r"\bdatabase\b", r"\bsql\b", r"\bpostgres(?:ql)?\b", r"\bmysql\b",
        r"\bmongodb?\b", r"\bredis\b", r"\bsqlite\b", r"\belasticsearch\b",
        r"\bsupabase\b", r"\bfirebase\b", r"\bprisma\b", r"\bdrizzle\b", r"\btypeorm\b",
    ]),

    # ML / Data analysis
    ("data-ml", [
        r"\bmachine\s+learning\b", r"\bdeep\s+learning\b", r"\bneural\s+network\b",
        r"\btensorflow\b", r"\bpytorch\b", r"\bhugg(?:ingface|ing\s+face)\b", r"\bmlflow\b",
        r"\bmodel\s+(?:training|inference|fine[.-]?tun)\w*\b",
    ]),
    ("data-analysis", [
        r"\bdata\s+(?:analysis|visualization|processing|analytics)\b",
        r"\bjupyter\b", r"\bpandas\b", r"\bspreadsheet\b", r"\bcsv\s+(?:analysis|pars)\w*\b",
    ]),
    ("data", [r"\bdata(?:set|lake|warehouse)\b", r"\betl\b", r"\bdata\s+(?:ingestion|pipeline)\b"]),
    ("data-finance", [r"\bfinance\b", r"\btrading\b", r"\bstock\b", r"\bcrypto\s+(?:trad|pric|market)\w*\b", r"\bportfolio\b"]),

    # ===== Productivity & Office =====
    ("prod-docs", [r"\bdocument\w*\b", r"\bnotion\b", r"\bobsidian\b", r"\bmarkdown\b", r"\bwiki\b", r"\bconfluence\b"]),
    ("prod-pm", [r"\bproject\s+management\b", r"\bjira\b", r"\blinear\b", r"\basana\b", r"\btodoist\b", r"\btrello\b"]),
    ("prod-comm", [r"\bslack\b", r"\bdiscord\b", r"\btelegram\b", r"\bchat\b", r"\bmessag\w*\b", r"\bcommunicat\w*\b"]),
    ("prod-calendar", [r"\bcalendar\b", r"\bschedul\w*\b", r"\bagenda\b", r"\bbooking\b"]),
    ("prod-notes", [r"\bnote[\s-]?(?:taking|app|book|pad)\b", r"\bmemo\b", r"\bjournal\b"]),
    ("productivity-email", [r"\bgmail\b", r"\bsendgrid\b", r"\bmailgun\b", r"\bsmtp\b", r"\bimap\b", r"\bemail\s+(?:client|manage|send)\w*\b"]),
    ("prod", [r"\bproductiv\w*\b", r"\bworkflow\b", r"\bautomat\w*\b"]),

    # ===== Integrations & APIs =====
    ("integ-cloud-aws", [r"\baws\b", r"\bamazon\b", r"\bs3\b", r"\blambda\b", r"\bdynamodb\b", r"\bec2\b", r"\bsagemaker\b"]),
    ("integ-cloud-azure", [r"\bazure\b", r"\bmicrosoft\s+cloud\b"]),
    ("integ-cloud-gcp", [r"\bgcp\b", r"\bgoogle\s+cloud\b", r"\bbigquery\b"]),
    ("integ-cloud", [r"\bcloud\b"]),
    ("integ-payment", [r"\bpayment\b", r"\bstripe\b", r"\bpaypal\b", r"\bbilling\b", r"\binvoice\b"]),
    ("integ-social", [r"\btwitter\b", r"\bfacebook\b", r"\binstagram\b", r"\blinkedin\b", r"\bsocial\s+media\b", r"\byoutube\b", r"\bbluesky\b"]),
    ("integ-crm", [r"\bsalesforce\b", r"\bhubspot\b", r"\bcrm\b"]),
    ("integrations-github", [r"\bgithub\s+(?:api|issue|pull\s+request|repositor|workflow|copilot|mcp)\b", r"\boctokit\b"]),
    ("integrations-slack", [r"\bslack(?:bot)?\b"]),
    ("integrations-notion", [r"\bnotion\b"]),
    ("integrations-jira", [r"\bjira\b"]),
    ("integrations-google", [r"\bgoogle\s+(?:sheets?|docs?|drive|maps?|calendar|workspace|analytics)\b"]),
    ("integrations-messaging", [r"\btelegram\b", r"\bwhatsapp\b", r"\bsignal\b", r"\bmatrix\b"]),
    ("integ", [r"\bapi\b", r"\bintegration\b", r"\bwebhook\b", r"\boauth\b"]),

    # ===== Security & Compliance =====
    ("sec-auth", [r"\bauthenticat\w*\b", r"\boauth\b", r"\bjwt\b", r"\bsso\b", r"\bidentity\b", r"\blogin\b"]),
    ("sec-scan", [r"\bsecurity\s+scan\w*\b", r"\bvulnerabilit\w*\b", r"\bcve\b", r"\bsast\b", r"\bdast\b"]),
    ("sec-crypto", [r"\bblockchain\b", r"\bweb3\b", r"\bsolana\b", r"\bethereum\b", r"\bdefi\b", r"\bwallet\b", r"\bsmart\s+contract\b"]),
    ("security-secrets", [r"\bhashicorp\s+vault\b", r"\b1password\b", r"\bsecret\s+manag\w*\b", r"\bbitwarden\b", r"\bcredential\s+vault\b"]),
    ("security-compliance", [r"\bcompliance\b", r"\bsoc\s*2\b", r"\bgdpr\b", r"\bhipaa\b", r"\bpci[\s-]dss\b"]),
    ("sec", [r"\bsecurity\b", r"\bencrypt\w*\b", r"\bfirewall\b", r"\bpentest\w*\b", r"\bthreat\b", r"\bcyber\w*\b"]),

    # ===== Utilities =====
    ("util-file", [r"\bfile\s*(?:system|manag|upload|download|backup)\w*\b", r"\bstorage\b"]),
    ("util-search", [r"\bsearch\b", r"\bindex\w*\b", r"\bscrape?\w*\b", r"\bcrawl\w*\b"]),
    ("util-monitor", [r"\bmonitor\w*\b", r"\blogging\b", r"\bmetrics?\b", r"\bobserv\w*\b", r"\balert\w*\b", r"\bsentry\b", r"\bdatadog\b"]),
    ("util-map", [r"\bmap(?:s|box)?\b", r"\bgeolocat\w*\b", r"\bgps\b", r"\blocation\b", r"\bgeocode?\w*\b"]),
    ("util-media", [r"\bmedia\b", r"\bvideo\b", r"\bstream\w*\b", r"\bffmpeg\b"]),
    ("utilities-system", [r"\bshell\s+command\b", r"\bbash\s+script\b", r"\bsystem\s+(?:admin|info|command)\w*\b", r"\bcli\s+tool\b"]),
    ("util", [r"\butili?t\w*\b", r"\btool(?:kit|box|set)?\b", r"\bhelper\b", r"\bconvert\w*\b"]),
]

# --- Parent Tag Propagation ---
# When a leaf tag is assigned, also assign all ancestor tags.
# Built from the tag hierarchy structure.
PARENT_MAP: dict[str, list[str]] = {
    # dev hierarchy
    "dev-web-frontend-react": ["dev-web-frontend", "dev-web", "dev"],
    "dev-web-frontend-vue": ["dev-web-frontend", "dev-web", "dev"],
    "dev-web-frontend-svelte": ["dev-web-frontend", "dev-web", "dev"],
    "dev-web-frontend-angular": ["dev-web-frontend", "dev-web", "dev"],
    "dev-web-frontend": ["dev-web", "dev"],
    "dev-web-backend-node": ["dev-web-backend", "dev-web", "dev"],
    "dev-web-backend-python": ["dev-web-backend", "dev-web", "dev"],
    "dev-web-backend-go": ["dev-web-backend", "dev-web", "dev"],
    "dev-web-backend-rust": ["dev-web-backend", "dev-web", "dev"],
    "dev-web-backend": ["dev-web", "dev"],
    "dev-web-fullstack-nextjs": ["dev-web-fullstack", "dev-web", "dev"],
    "dev-web-fullstack-nuxt": ["dev-web-fullstack", "dev-web", "dev"],
    "dev-web-fullstack": ["dev-web", "dev"],
    "dev-web": ["dev"],
    "dev-devops-docker": ["dev-devops", "dev"],
    "dev-devops-k8s": ["dev-devops", "dev"],
    "dev-devops-ci": ["dev-devops", "dev"],
    "dev-devops": ["dev"],
    "dev-git": ["dev"],
    "dev-testing": ["dev"],
    "dev-agents": ["dev"],
    "dev-mobile-react-native": ["dev-mobile", "dev"],
    "dev-mobile-flutter": ["dev-mobile", "dev"],
    "dev-mobile": ["dev"],
    "dev-desktop-electron": ["dev-desktop", "dev"],
    "dev-desktop-tauri": ["dev-desktop", "dev"],
    "dev-desktop": ["dev"],
    "dev-gamedev": ["dev"],
    # data hierarchy
    "data-ai-nlp": ["data-ai", "data"],
    "data-ai-vision": ["data-ai", "data"],
    "data-ai-audio": ["data-ai", "data"],
    "data-ai-rag": ["data-ai", "data"],
    "data-ai": ["data"],
    "data-db-vector": ["data-db", "data"],
    "data-db-graph": ["data-db", "data"],
    "data-db": ["data"],
    "data-ml": ["data"],
    "data-analysis": ["data"],
    "data-finance": ["data"],
    # productivity hierarchy
    "prod-docs": ["prod"],
    "prod-pm": ["prod"],
    "prod-comm": ["prod"],
    "prod-calendar": ["prod"],
    "prod-notes": ["prod"],
    "productivity-email": ["prod"],
    # integrations hierarchy
    "integ-cloud-aws": ["integ-cloud", "integ"],
    "integ-cloud-azure": ["integ-cloud", "integ"],
    "integ-cloud-gcp": ["integ-cloud", "integ"],
    "integ-cloud": ["integ"],
    "integ-payment": ["integ"],
    "integ-social": ["integ"],
    "integ-crm": ["integ"],
    "integrations-github": ["integ"],
    "integrations-slack": ["integ"],
    "integrations-notion": ["integ"],
    "integrations-jira": ["integ"],
    "integrations-google": ["integ"],
    "integrations-messaging": ["integ"],
    # security hierarchy
    "sec-auth": ["sec"],
    "sec-scan": ["sec"],
    "sec-crypto": ["sec"],
    "security-secrets": ["sec"],
    "security-compliance": ["sec"],
    # utilities hierarchy
    "util-file": ["util"],
    "util-search": ["util"],
    "util-monitor": ["util"],
    "util-map": ["util"],
    "util-media": ["util"],
    "utilities-system": ["util"],
}

# Pre-compile patterns
COMPILED_RULES: list[tuple[str, list[re.Pattern]]] = []
for tag_id, patterns in TAG_RULES:
    COMPILED_RULES.append((tag_id, [re.compile(p, re.IGNORECASE) for p in patterns]))


def auto_tag(name: str, description: str) -> list[str]:
    """Determine tags for a skill based on keywords. Returns sorted list of matched tags."""
    text = f"{name} {description}"
    tags: set[str] = set()

    for tag_id, patterns in COMPILED_RULES:
        for pat in patterns:
            if pat.search(text):
                tags.add(tag_id)
                break

    # Propagate parent tags (leaf → ancestors)
    propagated: set[str] = set()
    for tag in tags:
        if tag in PARENT_MAP:
            propagated.update(PARENT_MAP[tag])
    tags.update(propagated)

    # CJK keyword matching for non-Latin descriptions
    text_lower = text.lower()
    if not tags:
        # Chinese/Japanese/Korean keyword patterns
        cjk_kw = {
            "data-ai": ["大语言模型", "人工智能", "机器学习", "深度学习", "自然语言", "智能", "ai", "llm"],
            "integ": ["api", "服务", "接口", "集成"],
            "dev-web": ["前端", "后端", "网页", "网站"],
            "dev-devops": ["部署", "运维", "容器", "云原生"],
            "data-db": ["数据库", "存储"],
            "sec": ["安全", "加密", "认证"],
            "util": ["工具", "辅助", "转换"],
            "util-search": ["搜索", "检索", "爬虫"],
            "util-media": ["视频", "音频", "直播", "媒体"],
            "prod": ["办公", "效率", "自动化"],
            "prod-docs": ["文档", "笔记"],
        }
        for tag_id, keywords in cjk_kw.items():
            for kw in keywords:
                if kw in text:
                    tags.add(tag_id)
        # Propagate parents for CJK matches too
        propagated2: set[str] = set()
        for tag in tags:
            if tag in PARENT_MAP:
                propagated2.update(PARENT_MAP[tag])
        tags.update(propagated2)

    # Fallback: if still no tags matched, assign based on common MCP patterns
    if not tags:
        if "mcp" in text_lower:
            tags.add("util")
        if "server" in text_lower:
            tags.add("integ")

    return sorted(tags)


# Tags that must be preserved from existing data (not domain tags)
PRESERVED_PREFIXES = ("installs:", "status-")
PRESERVED_EXACT = frozenset({"agent-skills", "repo_unavailable", "clone_failure"})


def is_preserved_tag(tag: str) -> bool:
    """Return True if this tag should be preserved (not a domain tag we manage)."""
    return tag in PRESERVED_EXACT or any(tag.startswith(p) for p in PRESERVED_PREFIXES)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Auto-tag all skills")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    parser.add_argument("--source", help="Only tag skills from this source_hub")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of skills to process")
    args = parser.parse_args()

    count = 0
    tagged = 0
    modified = 0
    tag_dist: dict[str, int] = defaultdict(int)
    changes: list[tuple[str, list[str], list[str]]] = []

    files = sorted(SKILLS_DIR.glob("*.json"))
    for f in files:
        data = json.loads(f.read_text())
        count += 1

        if args.source and data.get("source_hub") != args.source:
            continue

        name = data.get("name", "")
        desc = data.get("description", "")

        new_domain_tags = auto_tag(name, desc)
        if new_domain_tags:
            tagged += 1

        # Preserve system/identity tags from existing data
        existing_tags = data.get("tags", [])
        preserved = [t for t in existing_tags if is_preserved_tag(t)]

        # If auto_tag found nothing, keep existing domain tags as fallback
        if not new_domain_tags:
            new_domain_tags = [t for t in existing_tags if not is_preserved_tag(t)]

        # Merge: preserved first, then domain tags (deduped, order preserved)
        merged = list(dict.fromkeys(preserved + new_domain_tags))

        if merged != existing_tags:
            old_domain = [t for t in existing_tags if not is_preserved_tag(t)]
            new_domain = [t for t in merged if not is_preserved_tag(t)]
            if old_domain != new_domain:
                changes.append((f.name, old_domain, new_domain))
                modified += 1

            if not args.dry_run:
                data["tags"] = merged
                f.write_text(json.dumps(data, indent=2, ensure_ascii=False))

        for t in new_domain_tags:
            tag_dist[t] += 1

        if args.limit and count >= args.limit:
            break

    print(f"Processed: {count} skills")
    print(f"Tagged: {tagged} skills with domain tags")
    print(f"Modified: {modified} skills {'(dry run)' if args.dry_run else ''}")
    print(f"\nTag distribution (top 30):")
    for tag, cnt in sorted(tag_dist.items(), key=lambda x: -x[1])[:30]:
        print(f"  {tag}: {cnt}")

    if args.dry_run and changes:
        print(f"\nSample changes (first 10):")
        for name, old, new in changes[:10]:
            print(f"  {name}: {old} → {new}")


if __name__ == "__main__":
    main()
