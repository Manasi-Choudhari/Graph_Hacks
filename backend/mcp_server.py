"""
FraudScope MCP server — the single registry of graph tools.

The in-app agent discovers and calls tools through this server, and any MCP
client (Claude Desktop, Cursor, MCP Inspector) can connect to the same tools:

    stdio:            python mcp_server.py
    streamable HTTP:  served by the FastAPI app at http://localhost:8000/mcp/

review_action is deliberately NOT exposed: agents may propose actions, only a
human can approve them (via the REST API / UI).
"""

import sys
from typing import Annotated, Literal

from pydantic import Field
from mcp.server.mcpserver import MCPServer

import tools

if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

AccountId = Annotated[str, Field(description="Account ID")]

mcp = MCPServer(
    name="fraudscope",
    instructions=(
        "Financial-crime investigation tools over a FalkorDB graph of accounts, "
        "transactions, IPs, devices, entities and alerts. Every result includes the Cypher used."
    ),
)


@mcp.tool(description="Multi-hop traversal around one account to expose its fraud ring (accounts, shared IPs/devices within N hops). Omit account_id to discover ALL rings via community detection.")
def find_fraud_rings(
    account_id: Annotated[str | None, Field(description="Account to investigate; omit to scan the whole graph")] = None,
    max_hops: Annotated[int, Field(ge=1, le=4, description="Traversal depth")] = 4,
) -> dict:
    return tools.find_fraud_rings(account_id, max_hops)


@mcp.tool(description="Discover fraud rings with NO prior labels: Weakly Connected Components over shared IPs/devices, each cluster scored by structuring and internal money flow.")
def detect_fraud_communities(
    min_accounts: Annotated[int, Field(ge=2, description="Minimum accounts per cluster")] = 3,
) -> dict:
    return tools.detect_fraud_communities(min_accounts)


@mcp.tool(description="Follow an account's inflows/outflows to detect structuring (<$10k), layering and circular money flows.")
def trace_money_flow(account_id: AccountId) -> dict:
    return tools.trace_money_flow(account_id)


@mcp.tool(description="Composite risk score propagated from the graph: base risk, neighbour risk, shared IPs with suspicious accounts, open alerts. Also returns account status (ACTIVE/FROZEN/...).")
def compute_risk_score(account_id: AccountId) -> dict:
    return tools.compute_risk_score(account_id)


@mcp.tool(description="Other accounts sharing an IP address or device fingerprint with this account.")
def find_shared_infrastructure(account_id: AccountId) -> dict:
    return tools.find_shared_infrastructure(account_id)


@mcp.tool(description="Rank accounts by graph centrality on the money network. pagerank = where money concentrates (collection hubs); betweenness = brokers sitting on the most money paths.")
def rank_key_accounts(
    metric: Annotated[Literal["pagerank", "betweenness"], Field(description="Centrality algorithm")] = "pagerank",
    limit: Annotated[int, Field(ge=1, le=25)] = 10,
) -> dict:
    return tools.rank_key_accounts(metric, limit)


@mcp.tool(description="Shortest paths linking two accounts across money, IP, device and ownership edges — the evidence chain explaining HOW they are connected.")
def explain_connection(
    source_id: AccountId,
    target_id: AccountId,
    max_hops: Annotated[int, Field(ge=1, le=8)] = 6,
) -> dict:
    return tools.explain_connection(source_id, target_id, max_hops)


@mcp.tool(description="Maximum money that can flow from source to target through the transaction network, split into direct vs indirect (layered through intermediaries).")
def compute_max_flow(source_id: AccountId, target_id: AccountId) -> dict:
    return tools.compute_max_flow(source_id, target_id)


@mcp.tool(description="Open HIGH/CRITICAL fraud alerts, newest first.")
def get_active_alerts(limit: Annotated[int, Field(ge=1, le=100)] = 20) -> dict:
    return tools.get_active_alerts(limit)


@mcp.tool(description="Search accounts by name, ID or entity type (shell_company, mule, crypto_exchange).")
def search_accounts(query_str: Annotated[str, Field(description="Name, ID fragment or entity type")]) -> dict:
    return tools.search_accounts(query_str)


@mcp.tool(description="Graph-wide statistics: node counts, suspicious accounts, open alerts, transaction volume.")
def get_graph_overview() -> dict:
    return tools.get_graph_overview()


@mcp.tool(description="Propose an action on an account from graph evidence. Recorded as a PENDING_APPROVAL Action node linked to its evidence; a human must approve it. clear_account = false positive.")
def propose_action(
    action_type: Literal["freeze_account", "open_case", "escalate_alert", "file_sar", "clear_account"],
    account_id: AccountId,
    reason: Annotated[str, Field(description="One sentence citing the graph evidence")],
    evidence_account_ids: Annotated[list[str] | None, Field(description="Related accounts")] = None,
    session_id: Annotated[str, Field(description="Investigation session ID")] = "",
) -> dict:
    return tools.propose_action(action_type, account_id, reason, evidence_account_ids, session_id)


@mcp.tool(description="List proposed/approved/rejected actions and the evidence attached to each.")
def list_actions(
    status: Annotated[Literal["PENDING_APPROVAL", "APPROVED", "REJECTED"] | None, Field(description="Filter by status")] = None,
) -> dict:
    return tools.list_actions(status)


@mcp.tool(description="Persist a finding to this session's memory graph.")
def save_investigation_memory(
    session_id: Annotated[str, Field(description="Investigation session ID")],
    finding: Annotated[str, Field(description="The finding to remember")],
    account_id: Annotated[str | None, Field(description="Related account")] = None,
    tags: Annotated[list[str] | None, Field(description="Tags such as ['ring', 'structuring']")] = None,
) -> dict:
    return tools.save_investigation_memory(session_id, finding, account_id, tags)


@mcp.tool(description="Recall earlier findings from this session's memory graph.")
def recall_investigation_memory(
    session_id: Annotated[str, Field(description="Investigation session ID")],
    account_id: Annotated[str | None, Field(description="Only findings about this account")] = None,
) -> dict:
    return tools.recall_investigation_memory(session_id, account_id)


if __name__ == "__main__":
    mcp.run("stdio")
