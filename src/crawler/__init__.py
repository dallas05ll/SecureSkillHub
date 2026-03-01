"""
SecureSkillHub Crawler Module — discovers skills from external hub directories.

Each crawler scrapes a specific source hub and produces a CrawlerBatch
that is written as JSON to ``data/discovered/``.
"""

from src.crawler.base import BaseCrawler
from src.crawler.glama import GlamaCrawler
from src.crawler.mcp_so import MCPSoCrawler

__all__ = [
    "BaseCrawler",
    "GlamaCrawler",
    "MCPSoCrawler",
]
