"""
GitHub scraper — fetches merged PRs and closed issues from a public repo.

Produces a list of normalized dicts with the shared schema expected by
extractor.py and graph_builder.py:

    {
        "id":     "github-pr-9876",
        "title":  "...",
        "body":   "...",
        "source": "github",
        "type":   "PR" | "Issue",
        "date":   "2024-01-15T10:00:00Z",   # merged_at for PRs, closed_at for issues
        "url":    "https://github.com/...",
        "author": "login",
        "refs":   ["github-pr-100", "github-issue-200"],  # #-references parsed from body
        "reviews": [{"reviewer": "login", "state": "APPROVED"}],  # PRs only
        "labels": ["bug", "improvement"],
        "raw":    { ... }   # original API response for debugging
    }

Run directly:
    python -m src.scrapers.github
"""

import json
import re
import time
from pathlib import Path

import requests
from tqdm import tqdm

from src.config import GITHUB_TOKEN, GITHUB_REPO, GITHUB_MAX_ITEMS

GITHUB_API = "https://api.github.com"
DATA_DIR = Path(__file__).parent.parent.parent / "data"

_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
if GITHUB_TOKEN:
    _HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _get(url: str, params: dict = None) -> dict | list:
    """GET with basic rate-limit retry."""
    for attempt in range(3):
        resp = requests.get(url, headers=_HEADERS, params=params, timeout=30)
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            wait = int(resp.headers.get("Retry-After", 60))
            print(f"  Rate limited — sleeping {wait}s")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"Failed after retries: {url}")


def _paginate(url: str, params: dict, max_items: int) -> list:
    """Walk pages until max_items collected or exhausted."""
    results = []
    params = {**params, "per_page": 100, "page": 1}
    while len(results) < max_items:
        page = _get(url, params)
        if not page:
            break
        results.extend(page)
        if len(page) < 100:
            break
        params["page"] += 1
    return results[:max_items]


# ── Reference parser ──────────────────────────────────────────────────────────

_REF_RE = re.compile(r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)?\s*#(\d+)", re.IGNORECASE)
_PR_REF_RE = re.compile(r"#(\d+)")


def _parse_refs(body: str, known_pr_numbers: set[int]) -> list[str]:
    """
    Extract #N references from body text.
    Returns normalized IDs like "github-pr-1234" or "github-issue-5678".
    We can't always tell if a ref is a PR or issue without extra API calls,
    so we check against the known PR set and default to 'issue' otherwise.
    """
    if not body:
        return []
    nums = set(int(m) for m in _PR_REF_RE.findall(body))
    refs = []
    for n in sorted(nums):
        kind = "pr" if n in known_pr_numbers else "issue"
        refs.append(f"github-{kind}-{n}")
    return refs


# ── Reviews ───────────────────────────────────────────────────────────────────

def _fetch_reviews(pr_number: int) -> list[dict]:
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/pulls/{pr_number}/reviews"
    try:
        data = _get(url)
    except Exception:
        return []
    seen = {}
    for r in data:
        login = r.get("user", {}).get("login", "unknown")
        state = r.get("state", "COMMENTED")
        # Keep the most significant state per reviewer
        priority = {"APPROVED": 3, "CHANGES_REQUESTED": 2, "DISMISSED": 1, "COMMENTED": 0}
        if priority.get(state, 0) > priority.get(seen.get(login, {}).get("state", ""), 0):
            seen[login] = {"reviewer": login, "state": state}
    return list(seen.values())


# ── Normaliser ────────────────────────────────────────────────────────────────

def _normalise_pr(pr: dict, known_pr_numbers: set[int]) -> dict:
    number = pr["number"]
    body = pr.get("body") or ""
    reviews = _fetch_reviews(number)
    return {
        "id": f"github-pr-{number}",
        "title": pr.get("title", ""),
        "body": body,
        "source": "github",
        "type": "PR",
        "date": pr.get("merged_at") or pr.get("closed_at") or pr.get("created_at"),
        "url": pr.get("html_url", ""),
        "author": (pr.get("user") or {}).get("login", "unknown"),
        "author_association": pr.get("author_association", ""),
        "refs": _parse_refs(body, known_pr_numbers),
        "reviews": reviews,
        "labels": [lb["name"] for lb in pr.get("labels", [])],
        "milestone": (pr.get("milestone") or {}).get("title"),
        "raw": pr,
    }


def _normalise_issue(issue: dict, known_pr_numbers: set[int]) -> dict:
    number = issue["number"]
    body = issue.get("body") or ""
    return {
        "id": f"github-issue-{number}",
        "title": issue.get("title", ""),
        "body": body,
        "source": "github",
        "type": "Issue",
        "date": issue.get("closed_at") or issue.get("created_at"),
        "url": issue.get("html_url", ""),
        "author": (issue.get("user") or {}).get("login", "unknown"),
        "author_association": issue.get("author_association", ""),
        "refs": _parse_refs(body, known_pr_numbers),
        "reviews": [],
        "labels": [lb["name"] for lb in issue.get("labels", [])],
        "milestone": (issue.get("milestone") or {}).get("title"),
        "raw": issue,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def scrape(max_items: int = GITHUB_MAX_ITEMS) -> list[dict]:
    """
    Fetch up to `max_items` merged PRs and `max_items` closed issues.
    Returns combined list of normalised dicts.
    """
    repo_url = f"{GITHUB_API}/repos/{GITHUB_REPO}"

    print(f"Fetching up to {max_items} merged PRs from {GITHUB_REPO}...")
    raw_prs = _paginate(
        f"{repo_url}/pulls",
        {"state": "closed", "sort": "updated", "direction": "desc"},
        max_items * 2,  # fetch extra to account for unmerged closed PRs
    )
    merged_prs = [pr for pr in raw_prs if pr.get("merged_at")][:max_items]
    known_pr_numbers = {pr["number"] for pr in merged_prs}
    print(f"  Got {len(merged_prs)} merged PRs")

    print(f"Fetching up to {max_items} closed issues from {GITHUB_REPO}...")
    raw_issues_page = _paginate(
        f"{repo_url}/issues",
        {"state": "closed", "sort": "updated", "direction": "desc"},
        max_items * 2,  # issues endpoint returns both PRs and issues
    )
    pure_issues = [i for i in raw_issues_page if "pull_request" not in i][:max_items]
    print(f"  Got {len(pure_issues)} closed issues")

    print("Fetching reviews for each PR (this takes a moment)...")
    normalised: list[dict] = []
    for pr in tqdm(merged_prs, desc="PRs"):
        normalised.append(_normalise_pr(pr, known_pr_numbers))

    for issue in tqdm(pure_issues, desc="Issues"):
        normalised.append(_normalise_issue(issue, known_pr_numbers))

    return normalised


def save(items: list[dict], path: Path = DATA_DIR / "github_raw.json") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclude `raw` field to keep file readable; it's only for in-process debugging
    slim = [{k: v for k, v in item.items() if k != "raw"} for item in items]
    path.write_text(json.dumps(slim, indent=2, default=str))
    print(f"Saved {len(slim)} items to {path}")


if __name__ == "__main__":
    items = scrape()
    save(items)
