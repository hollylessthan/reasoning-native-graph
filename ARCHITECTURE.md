# Architecture: How the Pipeline Works

This document explains what the pipeline does at each stage, why the graph is modeled the way
it is, and how retrieval differs from standard RAG.

---

## Stage 1 — Scraping: Collecting Raw Decision Material

**File:** [`src/scrapers/github.py`](src/scrapers/github.py)  
**Output:** [`data/github_raw.json`](data/github_raw.json)

The scraper hits the GitHub REST API and collects:

- **200 merged PRs** — title, body, author, reviewer list with approval states, labels, dates
- **200 closed issues** — same fields minus reviews
- **Cross-references** — any `#1234` mention in a PR/issue body is parsed as an explicit link
  to another decision

At this stage the data is structured text only — no intelligence has been applied. Each item
is normalised to a shared schema:

```python
{
  "id":     "github-pr-9876",      # source-type-number
  "title":  "...",
  "body":   "...",                 # full PR/issue description
  "source": "github",
  "type":   "PR",
  "date":   "2024-01-15T10:00:00Z",
  "url":    "https://...",
  "author": "login",
  "refs":   ["github-pr-100", "github-issue-200"],   # parsed #N links
  "reviews": [{"reviewer": "login", "state": "APPROVED"}],
  "labels": ["bug", "improvement"],
  "raw":    { ... }                # original API response
}
```

This normalised schema is intentionally source-agnostic — a future Slack scraper
([`src/scrapers/slack.py`](src/scrapers/slack.py)) produces identical dicts, so
`extractor.py` and `graph_builder.py` need no changes.

---

## Stage 2 — Extraction: Claude as a Structured Parser

**File:** [`src/extractor.py`](src/extractor.py)  
**Output:** [`data/enriched_data.json`](data/enriched_data.json)

This is the key step. Each PR/issue body is sent to Claude with a prompt that asks it to
extract the *decision knowledge* embedded in the prose:

```
For this GitHub item, extract:
- logic_nodes: list of architectural rules or trade-offs captured
  each with: name, domain, description
- artifacts: concrete components or spec sections affected
- decision_type: new-feature | breaking-change | bug-fix | trade-off | deprecation | ...
- rationale_summary: one sentence capturing the "Why" (max 25 words)
```

A PR about a delete file bug becomes:

```json
{
  "logic_nodes": [{
    "name": "Equality delete schema must be ordered by field ID",
    "domain": "delete-files",
    "description": "Without sorting by field ID, SparkExecutorCache can serve records with
                    mismatched field ordering, causing silent delete misses."
  }],
  "decision_type": "bug-fix",
  "rationale_summary": "Field ordering mismatch in SparkExecutorCache causes silent delete misses."
}
```

**Why this matters:** Claude is converting unstructured human reasoning — scattered across PR
descriptions, review comments, and issue threads — into named, typed, traversable graph entities.
This is the "dark logic made explicit" step. The Foundation Capital framing calls this capturing
*decision traces*: the exceptions, precedents, and judgment calls that normally exist only as
tribal knowledge.

Items are batched in groups of 5. Claude returns JSON; failures retry once with the error
appended. Processing 400 items takes ~10-15 min and ~$0.50 in API credits.

---

## Stage 3 — Graph Modeling: Decisions as First-Class Nodes

**File:** [`src/graph_builder.py`](src/graph_builder.py)  
**Schema:** [`cypher/schema.cypher`](cypher/schema.cypher)

The enriched data is loaded into Neo4j as a property graph.

```
(Actor)-[:PROPOSED]->(DecisionEvent)-[:ESTABLISHES]->(LogicNode)-[:APPLIES_TO]->(Artifact)
         [:VALIDATED {state}]        [:SUPERSEDES]
                                      [:REFERENCES]->(DecisionEvent)
         (DecisionEvent)-[:LABELLED]->(Label)
```

### Why a graph, not a table?

The critical modeling choice: **decisions are first-class nodes, not metadata on rows**.

A `LogicNode` like *"Deletion vectors must always be merged on commit path"* exists as its own
node in the graph. Multiple `DecisionEvent` nodes can point to it (`ESTABLISHES`, `SUPERSEDES`),
letting you traverse:

- *"Who first established this rule?"* — follow `ESTABLISHES` back to the PR
- *"Was this rule ever reversed?"* — find `SUPERSEDES` edges on the same `LogicNode`
- *"Who are the experts in this domain?"* — count `PROPOSED + VALIDATED` by `Actor` filtered
  by `LogicNode.domain`
- *"What components are affected by this rule?"* — follow `APPLIES_TO` to `Artifact` nodes

None of these questions are answerable from a flat table of PR descriptions — they require
explicit, traversable relationships.

All writes use `MERGE` (upsert), so re-running the pipeline is safe and idempotent.

---

## Stage 4 — Retrieval: Graph Traversal, Not RAG

**File:** [`src/agent.py`](src/agent.py)

When you ask a question, the agent makes two Claude calls:

### Stage 4a — Cypher generation

Claude receives the full graph schema description and the question, and writes a Cypher query:

```
Question: "Who are the domain experts for partition spec decisions?"

→ MATCH (a:Actor)-[:PROPOSED|VALIDATED]->(:DecisionEvent)-[:ESTABLISHES]->
         (:LogicNode {domain: 'partitioning'})
  RETURN a.login, count(*) AS decisions
  ORDER BY decisions DESC LIMIT 10
```

If Neo4j returns a query error, the error is appended to the prompt and Claude retries once.

### Stage 4b — Answer synthesis

Neo4j executes the Cypher and returns typed rows. Claude synthesises a human answer, citing
specific PR numbers and actor logins from the results.

### Why this is not RAG

| RAG (vector search) | This project (graph traversal) |
|---|---|
| Embeds text chunks into vectors | Extracts structured entities into a graph |
| Retrieves by cosine similarity | Retrieves by explicit typed relationships |
| Returns text passages | Returns typed nodes with provenance |
| "Approximately relevant" results | Exact, deterministic results |
| Can't count reviewers per domain | Traverses `VALIDATED` edges directly |
| Can't follow decision chains | Multi-hop: PR → LogicNode → Artifact → Actor |

The Foundation Capital essay frames this as the difference between *systems of record* (what
happened) and *context graphs* (why it happened). RAG retrieves stored text; a context graph
traverses causal relationships.

---

## Data Flow Summary

```
GitHub API
    │  200 PRs + 200 issues
    ▼
github_raw.json          ← structured text, no intelligence
    │  Claude extraction (batches of 5)
    ▼
enriched_data.json       ← named LogicNodes, typed decision_type, rationale
    │  Neo4j MERGE operations
    ▼
Neo4j graph              ← traversable decision trace graph
    │  question → Cypher → rows
    ▼
Agent answer             ← grounded, cited, exact
```
