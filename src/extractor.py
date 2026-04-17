"""
Source-agnostic entity extractor.

Takes a list of normalised scraper dicts and enriches each one with
Claude-extracted decision knowledge:

    {
        ...original fields...,
        "logic_nodes": [
            {
                "name": "V2 format requires explicit schema assignment",
                "domain": "format-spec",
                "description": "All V2 tables must have a schema explicitly assigned to each partition field",
            },
            ...
        ],
        "artifacts": ["TableMetadata", "PartitionSpec"],
        "decision_type": "breaking-change",
        "rationale_summary": "Needed to support row-level deletes without schema ambiguity.",
    }

Items with no extractable decision content get empty logic_nodes and
decision_type = "other".

Run directly (reads data/github_raw.json, writes data/enriched_data.json):
    python -m src.extractor
"""

import json
import time
from pathlib import Path

import anthropic
from tqdm import tqdm

from src.config import ANTHROPIC_API_KEY

DATA_DIR = Path(__file__).parent.parent / "data"

_CLIENT = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_SYSTEM_PROMPT = """\
You are an expert Apache Iceberg contributor analysing GitHub PRs and issues.
Your job is to extract the **decision knowledge** buried in each item — the architectural \
rules, trade-offs, and rationale that explain *why* the project is the way it is.

For EACH item in the JSON array you receive, return a JSON object with these fields:
- "logic_nodes": array of objects, each with:
    - "name": short phrase naming the architectural rule or trade-off (max 12 words)
    - "domain": one of [partitioning, catalog, format-spec, delete-files, api, \
compatibility, performance, testing, other]
    - "description": 1-2 sentences explaining the rule (what it means and why it exists)
- "artifacts": array of concrete Iceberg components/classes/spec sections this touches \
(e.g. "TableMetadata", "PartitionSpec", "Avro writer", "REST catalog", "V2 format")
- "decision_type": one of [new-feature, breaking-change, bug-fix, trade-off, \
deprecation, refactor, docs, other]
- "rationale_summary": one sentence (max 25 words) capturing the *Why* behind this change

Rules:
- If the item is trivial (CI fix, typo, dependency bump) return empty logic_nodes and \
decision_type "other"
- Keep logic_node names unique and precise — avoid generic names like "improve performance"
- Return a JSON array with one object per input item, in the same order
- Return ONLY the JSON array, no markdown fences, no explanation
"""

_BATCH_SIZE = 5  # items per Claude call


def _strip_body(body: str, max_chars: int = 1500) -> str:
    """Truncate very long bodies to keep prompt size manageable."""
    if not body:
        return ""
    return body[:max_chars] + ("..." if len(body) > max_chars else "")


def _build_user_message(batch: list[dict]) -> str:
    items = []
    for item in batch:
        items.append({
            "id": item["id"],
            "type": item["type"],
            "title": item["title"],
            "body": _strip_body(item.get("body", "")),
            "labels": item.get("labels", []),
        })
    return json.dumps(items, ensure_ascii=False)


def _call_claude(batch: list[dict], retries: int = 2) -> list[dict]:
    """Call Claude once for a batch; return list of enrichment dicts."""
    for attempt in range(retries + 1):
        try:
            msg = _CLIENT.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": _build_user_message(batch)}],
            )
            raw = msg.content[0].text.strip()
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            if attempt == retries:
                print(f"  JSON parse failed after {retries+1} attempts: {exc}")
                return [_empty_enrichment() for _ in batch]
            time.sleep(2)
        except anthropic.RateLimitError:
            wait = 30 * (attempt + 1)
            print(f"  Rate limited, sleeping {wait}s...")
            time.sleep(wait)
    return [_empty_enrichment() for _ in batch]


def _empty_enrichment() -> dict:
    return {
        "logic_nodes": [],
        "artifacts": [],
        "decision_type": "other",
        "rationale_summary": "",
    }


def enrich(items: list[dict]) -> list[dict]:
    """
    Enrich a list of normalised scraper dicts with Claude-extracted decision knowledge.
    Returns a new list with enrichment fields merged in.
    """
    enriched = []
    batches = [items[i:i + _BATCH_SIZE] for i in range(0, len(items), _BATCH_SIZE)]

    for batch in tqdm(batches, desc="Extracting decision knowledge"):
        results = _call_claude(batch)
        # Pad if Claude returned fewer items than expected
        while len(results) < len(batch):
            results.append(_empty_enrichment())
        for item, extra in zip(batch, results):
            enriched.append({**item, **extra})

    return enriched


def load(path: Path = DATA_DIR / "github_raw.json") -> list[dict]:
    return json.loads(path.read_text())


def save(items: list[dict], path: Path = DATA_DIR / "enriched_data.json") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2, default=str))
    non_trivial = sum(1 for i in items if i.get("logic_nodes"))
    print(f"Saved {len(items)} items ({non_trivial} with logic nodes) to {path}")


if __name__ == "__main__":
    raw = load()
    print(f"Loaded {len(raw)} items from github_raw.json")
    enriched = enrich(raw)
    save(enriched)
