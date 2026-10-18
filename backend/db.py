"""
FalkorDB connection and graph initialization for FraudScope AI.
"""

import os
from falkordb import FalkorDB
from dotenv import load_dotenv

load_dotenv()

_client: FalkorDB | None = None


def get_client() -> FalkorDB:
    global _client
    if _client is None:
        host = os.getenv("FALKORDB_HOST", "localhost")
        port = int(os.getenv("FALKORDB_PORT", "6379"))
        _client = FalkorDB(
            host=host,
            port=port,
            username=os.getenv("FALKORDB_USERNAME") or None,
            password=os.getenv("FALKORDB_PASSWORD") or None,
            ssl=os.getenv("FALKORDB_SSL", "false").lower() == "true",
        )
    return _client


def get_graph(name: str = "fraudscope"):
    """Return a FalkorDB graph object, creating it if needed."""
    client = get_client()
    return client.select_graph(name)


def get_memory_graph(session_id: str):
    """Each session gets its own isolated memory graph."""
    client = get_client()
    return client.select_graph(f"memory_{session_id}")


def init_schema():
    """
    Create indexes for fast lookups.
    FalkorDB supports per-graph indexes.
    """
    g = get_graph()
    try:
        g.query("CREATE INDEX ON :Account(id)")
    except Exception:
        pass
    try:
        g.query("CREATE INDEX ON :Transaction(id)")
    except Exception:
        pass
    try:
        g.query("CREATE INDEX ON :Entity(id)")
    except Exception:
        pass
    try:
        g.query("CREATE INDEX ON :IPAddress(address)")
    except Exception:
        pass
    try:
        g.query("CREATE INDEX ON :Device(fingerprint)")
    except Exception:
        pass
    try:
        g.query("CREATE INDEX ON :AlertEvent(id)")
    except Exception:
        pass
    print("✅ FalkorDB schema indexes created.")
