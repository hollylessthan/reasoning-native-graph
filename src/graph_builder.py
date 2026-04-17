"""
Graph builder — loads enriched scraper data into Neo4j.

Reads data/enriched_data.json and MERGEs all nodes + relationships into
the schema defined in cypher/schema.cypher.

Run directly:
    python -m src.graph_builder

Or call build() from Python:
    from src.graph_builder import build
    build(items)   # items = output of extractor.enrich()
"""

import json
from pathlib import Path

from neo4j import Session
from tqdm import tqdm

from src.config import get_neo4j_driver

DATA_DIR = Path(__file__).parent.parent / "data"
SCHEMA_FILE = Path(__file__).parent.parent / "cypher" / "schema.cypher"


# ── Schema setup ──────────────────────────────────────────────────────────────

def apply_schema(session: Session) -> None:
    """Run schema.cypher statements against the live database."""
    cypher = SCHEMA_FILE.read_text()
    # Split on semicolons and run each statement separately
    for stmt in cypher.split(";"):
        stmt = stmt.strip()
        # Skip comment-only blocks and empty strings
        if not stmt or all(line.startswith("//") for line in stmt.splitlines() if line.strip()):
            continue
        # Remove leading comment lines
        lines = [l for l in stmt.splitlines() if not l.strip().startswith("//")]
        clean = "\n".join(lines).strip()
        if clean:
            try:
                session.run(clean)
            except Exception as exc:
                # Constraints/indexes may already exist — that's fine
                if "already exists" not in str(exc).lower():
                    print(f"  Schema warning: {exc}")


# ── Cypher helpers ────────────────────────────────────────────────────────────

_UPSERT_DECISION = """
MERGE (d:DecisionEvent {id: $id})
SET d.title          = $title,
    d.type           = $type,
    d.date           = $date,
    d.url            = $url,
    d.author         = $author,
    d.decision_type  = $decision_type,
    d.rationale_summary = $rationale_summary,
    d.source         = $source,
    d.body_excerpt   = $body_excerpt
"""

_UPSERT_ACTOR_PROPOSED = """
MERGE (a:Actor {login: $login})
ON CREATE SET a.author_association = $author_association
WITH a
MATCH (d:DecisionEvent {id: $id})
MERGE (a)-[:PROPOSED]->(d)
"""

_UPSERT_REVIEWER = """
MERGE (a:Actor {login: $login})
WITH a
MATCH (d:DecisionEvent {id: $id})
MERGE (a)-[r:VALIDATED]->(d)
SET r.state = $state
"""

_UPSERT_LOGIC_ESTABLISHES = """
MERGE (l:LogicNode {name: $name})
SET l.domain      = $domain,
    l.description = $description
WITH l
MATCH (d:DecisionEvent {id: $event_id})
MERGE (d)-[:ESTABLISHES]->(l)
"""

_UPSERT_ARTIFACT = """
MERGE (ar:Artifact {name: $name})
WITH ar
MATCH (l:LogicNode {name: $logic_name})
MERGE (l)-[:APPLIES_TO]->(ar)
"""

_UPSERT_LABEL = """
MERGE (lb:Label {name: $name})
WITH lb
MATCH (d:DecisionEvent {id: $id})
MERGE (d)-[:LABELLED]->(lb)
"""

_UPSERT_REFERENCE = """
MATCH (d:DecisionEvent {id: $from_id})
MERGE (ref:DecisionEvent {id: $to_id})
MERGE (d)-[:REFERENCES]->(ref)
"""


# ── Per-item loader ───────────────────────────────────────────────────────────

def _load_item(session: Session, item: dict) -> None:
    body = item.get("body") or ""

    # 1. Core DecisionEvent node
    session.run(_UPSERT_DECISION, {
        "id":                item["id"],
        "title":             item.get("title", ""),
        "type":              item.get("type", "unknown"),
        "date":              item.get("date"),
        "url":               item.get("url", ""),
        "author":            item.get("author", "unknown"),
        "decision_type":     item.get("decision_type", "other"),
        "rationale_summary": item.get("rationale_summary", ""),
        "source":            item.get("source", "github"),
        "body_excerpt":      body[:500],
    })

    # 2. Author → DecisionEvent
    if item.get("author"):
        session.run(_UPSERT_ACTOR_PROPOSED, {
            "login":              item["author"],
            "author_association": item.get("author_association", ""),
            "id":                 item["id"],
        })

    # 3. Reviewer → DecisionEvent  (PRs only)
    for review in item.get("reviews", []):
        if review.get("reviewer"):
            session.run(_UPSERT_REVIEWER, {
                "login": review["reviewer"],
                "id":    item["id"],
                "state": review.get("state", "COMMENTED"),
            })

    # 4. LogicNodes + Artifacts
    for ln in item.get("logic_nodes", []):
        name = ln.get("name", "").strip()
        if not name:
            continue
        session.run(_UPSERT_LOGIC_ESTABLISHES, {
            "name":        name,
            "domain":      ln.get("domain", "other"),
            "description": ln.get("description", ""),
            "event_id":    item["id"],
        })
        for artifact in item.get("artifacts", []):
            artifact = artifact.strip()
            if artifact:
                session.run(_UPSERT_ARTIFACT, {
                    "name":       artifact,
                    "logic_name": name,
                })

    # 5. Labels
    for label in item.get("labels", []):
        if label:
            session.run(_UPSERT_LABEL, {"name": label, "id": item["id"]})

    # 6. Cross-references (#-links parsed from body)
    for ref_id in item.get("refs", []):
        session.run(_UPSERT_REFERENCE, {
            "from_id": item["id"],
            "to_id":   ref_id,
        })


# ── Public API ────────────────────────────────────────────────────────────────

def build(items: list[dict]) -> None:
    """Load a list of enriched dicts into Neo4j."""
    driver = get_neo4j_driver()
    try:
        with driver.session() as session:
            print("Applying schema constraints and indexes...")
            apply_schema(session)

            print(f"Loading {len(items)} items into Neo4j...")
            for item in tqdm(items, desc="Building graph"):
                _load_item(session, item)

        print("Done. Run the following in Neo4j Browser to verify:")
        print("  MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC")
        print("  MATCH ()-[r]->() RETURN type(r) AS rel, count(r) AS count ORDER BY count DESC")
    finally:
        driver.close()


def load(path: Path = DATA_DIR / "enriched_data.json") -> list[dict]:
    return json.loads(path.read_text())


if __name__ == "__main__":
    items = load()
    print(f"Loaded {len(items)} enriched items")
    build(items)
