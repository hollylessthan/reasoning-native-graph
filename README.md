# reasoning-native-graph

A POC that turns Apache Iceberg's GitHub history into a queryable **Context Graph** — making
10 years of institutional memory machine-readable for an LLM agent.

## The Idea

Foundation Capital's essay [*"Context Graphs: AI's Trillion-Dollar Opportunity"*](https://foundationcapital.com/ideas/context-graphs-ais-trillion-dollar-opportunity)
identifies a structural gap in enterprise AI: traditional systems of record capture *what happened*
but discard *why*. The logic behind decisions — exceptions, trade-offs, precedents — lives in
scattered conversations, PR comments, and tribal knowledge. AI agents can't reason over it.

This project makes that "dark logic" explicit. We scrape Apache Iceberg's GitHub history,
use Claude to extract named **decision traces** (who decided what, why, and what rule it established),
and load them into a Neo4j graph. An LLM agent can then answer questions like:

> *"What architectural rules govern delete file handling?"*  
> *"Who are the domain experts for partition spec decisions?"*  
> *"Which components have only 1-2 contributors — our bus-factor risk?"*

```
question
  └─► Claude generates Cypher query
        └─► Neo4j traverses the Decision Trace Graph
              └─► Claude synthesises a grounded answer with PR provenance
```

This is **graph traversal, not RAG**. Answers are exact and cited, not approximate.

## How It Works

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for a full walkthrough of the pipeline, modeling
decisions, and how retrieval differs from vector search.

## Graph Schema

```
(Actor)-[:PROPOSED]->(DecisionEvent)-[:ESTABLISHES]->(LogicNode)-[:APPLIES_TO]->(Artifact)
         [:VALIDATED]                [:SUPERSEDES]
                                      [:REFERENCES]->(DecisionEvent)
                                      [:LABELLED]->(Label)
```

- **DecisionEvent** — a merged PR or closed issue
- **LogicNode** — an architectural rule or trade-off extracted by Claude; the *why* behind the change
- **Actor** — a contributor (author or reviewer)
- **Artifact** — a concrete Iceberg component or spec section
- **Label** — GitHub labels

## Quickstart

### 1. Prerequisites

- Python 3.11+
- [Neo4j Aura](https://neo4j.com/cloud/aura/) (free tier) or Neo4j Desktop
- An Anthropic API key

### 2. Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env — add ANTHROPIC_API_KEY, NEO4J_URI, NEO4J_PASSWORD
```

### 3. Apply Neo4j schema

If using Neo4j Desktop, open the Neo4j Browser and paste [`cypher/schema.cypher`](cypher/schema.cypher).
Aura applies constraints automatically on first MERGE — no manual step needed.

### 4. Run the pipeline

```bash
# Step 1: Scrape GitHub (200 PRs + 200 issues, ~5-10 min with API token)
python -m src.scrapers.github

# Step 2: Enrich with Claude (extracts LogicNodes, ~10-15 min, ~$0.50 of API credits)
python -m src.extractor

# Step 3: Load into Neo4j (~1-2 min)
python -m src.graph_builder
```

### 5. Query the graph

```bash
python -m src.agent "Who are the domain experts for partition spec decisions?"
python -m src.agent "What architectural rules govern delete file handling?"
python -m src.agent "Which components have the fewest contributors?"
```

Or run the full demo notebook:

```bash
jupyter notebook notebooks/demo.ipynb
```

## Example Queries

| Question | What it reveals |
|---|---|
| "Who are the domain experts for partition spec decisions?" | Expertise map derived from actual decision history |
| "What architectural rules govern delete file handling?" | Dark logic surfaced as named `LogicNode` objects |
| "If I change the partition spec, what else breaks?" | Cross-domain impact via multi-hop graph traversal |
| "How did the delete file strategy evolve over time?" | Chronological decision chain with rationale |
| "What trade-offs exist in the format-spec domain?" | Unresolved tensions and deprecation signals |

## Rate Limits

Without a GitHub token: 60 requests/hour (will throttle during the 200-PR scrape with reviews).  
With `GITHUB_TOKEN` set: 5,000 requests/hour (recommended).

Generate a token at https://github.com/settings/tokens (no scopes needed for public repos).

## Adding Slack (Future)

A stub exists at [`src/scrapers/slack.py`](src/scrapers/slack.py). The normalised output
schema is identical to the GitHub scraper — `extractor.py` and `graph_builder.py` require
no changes. See the stub docstring for implementation guidance using the
[Linen.dev](https://linen.dev) public Iceberg archive.

## Concept Credit

The context graph framing comes from Foundation Capital:
[*"Context Graphs: AI's Trillion-Dollar Opportunity"*](https://foundationcapital.com/ideas/context-graphs-ais-trillion-dollar-opportunity)
