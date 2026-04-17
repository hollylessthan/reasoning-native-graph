// ── Unique constraints ────────────────────────────────────────────────────────
// Run this once when setting up a fresh Neo4j database.
// Neo4j Desktop: open the browser at bolt://localhost:7687 and paste this block.

CREATE CONSTRAINT decision_event_id IF NOT EXISTS
  FOR (d:DecisionEvent) REQUIRE d.id IS UNIQUE;

CREATE CONSTRAINT logic_node_name IF NOT EXISTS
  FOR (l:LogicNode) REQUIRE l.name IS UNIQUE;

CREATE CONSTRAINT actor_login IF NOT EXISTS
  FOR (a:Actor) REQUIRE a.login IS UNIQUE;

CREATE CONSTRAINT artifact_name IF NOT EXISTS
  FOR (ar:Artifact) REQUIRE ar.name IS UNIQUE;

CREATE CONSTRAINT label_name IF NOT EXISTS
  FOR (lb:Label) REQUIRE lb.name IS UNIQUE;

// ── Indexes for common query patterns ────────────────────────────────────────

CREATE INDEX decision_event_type IF NOT EXISTS
  FOR (d:DecisionEvent) ON (d.type);

CREATE INDEX decision_event_date IF NOT EXISTS
  FOR (d:DecisionEvent) ON (d.date);

CREATE INDEX logic_node_domain IF NOT EXISTS
  FOR (l:LogicNode) ON (l.domain);

CREATE INDEX decision_event_decision_type IF NOT EXISTS
  FOR (d:DecisionEvent) ON (d.decision_type);

// ── Graph schema reference (comment only) ────────────────────────────────────
//
// Nodes:
//   DecisionEvent  { id, title, body, type, date, url, author,
//                    decision_type, rationale_summary, source }
//   LogicNode      { name, domain, description }
//   Actor          { login, author_association }
//   Artifact       { name }
//   Label          { name }
//
// Relationships:
//   (Actor)-[:PROPOSED]->(DecisionEvent)
//   (Actor)-[:VALIDATED {state}]->(DecisionEvent)
//   (DecisionEvent)-[:ESTABLISHES]->(LogicNode)
//   (DecisionEvent)-[:SUPERSEDES]->(LogicNode)
//   (DecisionEvent)-[:REFERENCES]->(DecisionEvent)
//   (LogicNode)-[:APPLIES_TO]->(Artifact)
//   (DecisionEvent)-[:LABELLED]->(Label)
