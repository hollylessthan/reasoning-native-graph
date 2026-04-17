"""
Slack / Linen scraper — future extension.

Apache Iceberg's public Slack archive is available at:
    https://linen.dev/s/iceberg-dev  (or similar Linen URL)

When implemented this module should produce the same normalised dict shape
as github.py so that extractor.py and graph_builder.py need no changes:

    {
        "id":     "slack-msg-<channel>-<ts>",
        "title":  "",                          # Slack has no titles; use first 80 chars of text
        "body":   "...",
        "source": "slack",
        "type":   "message",
        "date":   "2024-01-15T10:00:00Z",
        "url":    "https://linen.dev/...",
        "author": "display_name",
        "refs":   [],
        "reviews": [],
        "labels": [],
        "milestone": None,
        "raw":    { ... }
    }

TODOs when implementing:
1. Check if linen.dev exposes a public JSON API (some instances do)
2. Otherwise scrape the HTML thread list — each page is statically rendered
3. Group messages by thread (parent_ts) to capture full decision discussions
4. Filter for threads with high reply counts — those capture debates, not just announcements
"""

from pathlib import Path


def scrape(channel: str = "dev", max_threads: int = 100) -> list[dict]:
    raise NotImplementedError(
        "Slack scraper not yet implemented. "
        "See docstring above for implementation guidance."
    )


def save(items: list[dict], path: Path = Path("data/slack_raw.json")) -> None:
    raise NotImplementedError("Slack scraper not yet implemented.")
