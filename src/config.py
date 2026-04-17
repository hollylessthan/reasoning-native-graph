"""
Centralised configuration and shared clients.
"""

import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

# ── Anthropic ────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]

# ── Neo4j ────────────────────────────────────────────────────────────────────
NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD: str = os.environ["NEO4J_PASSWORD"]


def get_neo4j_driver():
    """Return an authenticated Neo4j driver (call .close() when done)."""
    import os, certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


# ── GitHub ───────────────────────────────────────────────────────────────────
GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPO: str = os.getenv("GITHUB_REPO", "apache/iceberg")
GITHUB_MAX_ITEMS: int = int(os.getenv("GITHUB_MAX_ITEMS", "200"))
