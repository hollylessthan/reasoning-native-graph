"""
Reasoning agent — the core of the Decision Trace Graph demo.

Flow:
    question
      └─► Stage 1: Claude generates Cypher query
            └─► Neo4j executes query
                  └─► Stage 2: Claude synthesises a grounded answer
                        └─► returns {question, cypher, raw_results, answer}

Usage:
    from src.agent import ask
    result = ask("Who are the domain experts for partition spec decisions?")
    print(result["answer"])

Or run as CLI:
    python -m src.agent "Who are the domain experts for partition spec decisions?"
"""

import json
import sys
from typing import Any

import anthropic
from neo4j import Session

from src.config import ANTHROPIC_API_KEY, get_neo4j_driver

_CLIENT = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── Schema description injected into every Cypher-generation prompt ───────────

_GRAPH_SCHEMA = """\
Node labels and key properties:
- DecisionEvent  { id, title, type (PR|Issue), date, url, author, decision_type, rationale_summary, source, body_excerpt }
- LogicNode      { name, domain (partitioning|catalog|format-spec|delete-files|api|compatibility|performance|testing|other), description }
- Actor          { login, author_association }
- Artifact       { name }
- Label          { name }

Relationship types:
- (Actor)-[:PROPOSED]->(DecisionEvent)              author of PR/issue
- (Actor)-[:VALIDATED {state}]->(DecisionEvent)     reviewer; state = APPROVED | CHANGES_REQUESTED | COMMENTED
- (DecisionEvent)-[:ESTABLISHES]->(LogicNode)       PR/issue created this architectural rule
- (DecisionEvent)-[:SUPERSEDES]->(LogicNode)        PR/issue changed/replaced this rule
- (DecisionEvent)-[:REFERENCES]->(DecisionEvent)    body contains a #-link to another PR/issue
- (LogicNode)-[:APPLIES_TO]->(Artifact)             rule touches this Iceberg component
- (DecisionEvent)-[:LABELLED]->(Label)              GitHub label

Useful patterns:
- decision_type values: new-feature, breaking-change, bug-fix, trade-off, deprecation, refactor, docs, other
- domain values: partitioning, catalog, format-spec, delete-files, api, compatibility, performance, testing, other
- id format: "github-pr-1234" or "github-issue-5678"
"""

_CYPHER_SYSTEM = f"""\
You are a Neo4j Cypher expert working with the Apache Iceberg Decision Trace Graph.

{_GRAPH_SCHEMA}

Rules:
- Return ONLY the Cypher query — no explanation, no markdown fences, no comments
- Always use LIMIT (default 20 unless the user implies otherwise)
- Prefer MATCH + RETURN over more complex patterns when possible
- Use toLower() for case-insensitive text matching
- When asked about "experts" or "contributors", count both PROPOSED and VALIDATED relationships
- When asked about "domain", filter on LogicNode.domain
"""

_SYNTHESIS_SYSTEM = """\
You are a data engineering analyst presenting findings from Apache Iceberg's Decision Trace Graph.

You will receive:
1. The original question
2. The Cypher query used to answer it
3. The raw graph results as JSON

Your job:
- Give a clear, concrete answer to the question
- Reference specific PR numbers, actor logins, or LogicNode names from the results
- Explain *why* the graph reveals what it does — connect the dots
- Keep it concise (3-8 sentences); this is a demo explanation, not an essay
- If the results are empty, explain what that implies (e.g. no breaking changes in this domain)
"""


# ── Cypher execution ──────────────────────────────────────────────────────────

def _run_cypher(session: Session, cypher: str) -> list[dict[str, Any]]:
    result = session.run(cypher)
    return [dict(record) for record in result]


# ── Two-stage reasoning ───────────────────────────────────────────────────────

def _generate_cypher(question: str, error_hint: str = "") -> str:
    """Stage 1: ask Claude to write a Cypher query for the question."""
    user_content = question
    if error_hint:
        user_content += f"\n\nPrevious attempt failed with error: {error_hint}\nPlease fix the query."

    msg = _CLIENT.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=_CYPHER_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
    )
    return msg.content[0].text.strip()


def _synthesise_answer(question: str, cypher: str, results: list[dict]) -> str:
    """Stage 2: ask Claude to turn raw results into a human answer."""
    payload = json.dumps(results[:50], indent=2, default=str)  # cap at 50 rows
    user_content = (
        f"Question: {question}\n\n"
        f"Cypher query:\n{cypher}\n\n"
        f"Results ({len(results)} rows):\n{payload}"
    )
    msg = _CLIENT.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=_SYNTHESIS_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
    )
    return msg.content[0].text.strip()


# ── Public API ────────────────────────────────────────────────────────────────

def ask(question: str) -> dict:
    """
    Answer a natural-language question about the Decision Trace Graph.

    Returns:
        {
            "question":    str,
            "cypher":      str,
            "raw_results": list[dict],
            "answer":      str,
        }
    """
    driver = get_neo4j_driver()
    cypher = ""
    raw_results = []
    try:
        with driver.session() as session:
            # Stage 1: generate Cypher (retry once on error)
            cypher = _generate_cypher(question)
            try:
                raw_results = _run_cypher(session, cypher)
            except Exception as exc:
                cypher = _generate_cypher(question, error_hint=str(exc))
                raw_results = _run_cypher(session, cypher)

        # Stage 2: synthesise answer (outside session — pure LLM call)
        answer = _synthesise_answer(question, cypher, raw_results)
    finally:
        driver.close()

    return {
        "question":    question,
        "cypher":      cypher,
        "raw_results": raw_results,
        "answer":      answer,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.agent \"Your question here\"")
        sys.exit(1)
    question = " ".join(sys.argv[1:])
    result = ask(question)
    print("\n── Question ─────────────────────────────────────────────────────────")
    print(result["question"])
    print("\n── Cypher ───────────────────────────────────────────────────────────")
    print(result["cypher"])
    print(f"\n── Raw results ({len(result['raw_results'])} rows) ───────────────────────────────────────────")
    print(json.dumps(result["raw_results"][:10], indent=2, default=str))
    print("\n── Answer ───────────────────────────────────────────────────────────")
    print(result["answer"])
