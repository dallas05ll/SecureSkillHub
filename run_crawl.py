#!/usr/bin/env python3
"""
Run all SecureSkillHub crawlers in parallel and collect skills.

Usage:
    python3 run_crawl.py [--max-pages N]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.crawler.glama import GlamaCrawler
from src.crawler.mcp_so import MCPSoCrawler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_crawl")


async def run_single_crawler(crawler_cls, max_pages: int) -> dict:
    """Run a single crawler and return a summary."""
    name = crawler_cls.__name__
    logger.info("=" * 60)
    logger.info("Starting %s (max_pages=%d)", name, max_pages)
    logger.info("=" * 60)

    try:
        async with crawler_cls(max_pages=max_pages) as crawler:
            batch = await crawler.scrape()
            filepath = crawler.save_batch(batch)

            summary = {
                "crawler": name,
                "status": "success",
                "skills_found": len(batch.skills),
                "errors": len(batch.errors),
                "output_file": str(filepath),
            }
            logger.info(
                "%s finished: %d skills, %d errors -> %s",
                name, len(batch.skills), len(batch.errors), filepath,
            )
            if batch.errors:
                for err in batch.errors[:5]:
                    logger.warning("  error: %s", err)
                if len(batch.errors) > 5:
                    logger.warning("  ... and %d more errors", len(batch.errors) - 5)
            return summary

    except Exception as exc:
        logger.exception("CRAWLER FAILED: %s", name)
        return {
            "crawler": name,
            "status": "failed",
            "error": str(exc),
        }


async def main(max_pages: int = 10) -> None:
    crawlers = [GlamaCrawler, MCPSoCrawler]

    logger.info("=" * 60)
    logger.info("SecureSkillHub Crawl — launching %d crawlers", len(crawlers))
    logger.info("Max pages per crawler: %d", max_pages)
    logger.info("=" * 60)

    results = await asyncio.gather(
        *[run_single_crawler(cls, max_pages) for cls in crawlers],
        return_exceptions=False,
    )

    logger.info("")
    logger.info("=" * 60)
    logger.info("CRAWL SUMMARY")
    logger.info("=" * 60)
    total_skills = 0
    for r in results:
        if r["status"] == "success":
            total_skills += r["skills_found"]
            logger.info(
                "  %s: %d skills (%d errors) -> %s",
                r["crawler"], r["skills_found"], r["errors"], r["output_file"],
            )
        else:
            logger.error("  %s: FAILED - %s", r["crawler"], r.get("error", "unknown"))

    logger.info("")
    logger.info("Total skills discovered: %d", total_skills)
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run SecureSkillHub crawlers")
    parser.add_argument(
        "--max-pages", type=int, default=10,
        help="Max pages to crawl per hub (default: 10)",
    )
    args = parser.parse_args()
    asyncio.run(main(max_pages=args.max_pages))
