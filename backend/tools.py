"""
Graph tool definitions for the FraudScope AI agent.

These are the tools the agent selects via MCP / function calling.
Each tool wraps one or more FalkorDB Cypher queries.
"""

from db import get_graph, get_memory_graph
from datetime import datetime
import uuid


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 1 – Multi-hop fraud ring detection
# ─────────────────────────────────────────────────────────────────────────────
def find_all_fraud_rings() -> dict:
    g = get_graph()
    query = """
    MATCH (a:Account) WHERE a.ring_id IS NOT NULL
    RETURN 
        a.id as id,
        'Account' as type,
        a.name as name,
        a.risk_score as risk_score,
        a.is_suspicious as is_suspicious,
        a.ring_id as ring_id
    """
    res = g.query(query)
    nodes = []
    seen_nodes = set()
    for row in res.result_set:
        if row[0] not in seen_nodes:
            seen_nodes.add(row[0])
            nodes.append({
                "id": row[0],
                "type": row[1],
                "name": row[2] or row[0],
                "risk_score": row[3] or 0,
                "is_suspicious": row[4] or False,
                "ring_id": row[5],
                "hops": 0
            })

    infra_query = """
    MATCH (a:Account)-[:USES_IP|USES_DEVICE]->(infra)
    WHERE a.ring_id IS NOT NULL
    RETURN DISTINCT 
        coalesce(infra.address, infra.fingerprint, infra.id) as id,
        labels(infra)[0] as type,
        coalesce(infra.address, infra.fingerprint, infra.id) as name,
        coalesce(infra.risk_score, 0) as risk_score,
        coalesce(infra.is_suspicious, false) as is_suspicious
    """
    infra_res = g.query(infra_query)
    for row in infra_res.result_set:
        if row[0] and row[0] not in seen_nodes:
            seen_nodes.add(row[0])
            nodes.append({
                "id": row[0],
                "type": row[1] or "Infrastructure",
                "name": row[2] or row[0],
                "risk_score": row[3] or 0,
                "is_suspicious": row[4] or False,
                "ring_id": None,
                "hops": 1
            })

    edge_query = """
    MATCH (src)-[r]->(dst)
    WHERE (src.ring_id IS NOT NULL OR src:IPAddress OR src:Device)
      AND (dst.ring_id IS NOT NULL OR dst:IPAddress OR dst:Device)
    RETURN DISTINCT
        coalesce(src.id, src.fingerprint, src.address) as src,
        coalesce(dst.id, dst.fingerprint, dst.address) as dst,
        type(r) as rel_type,
        r.amount as amount,
        r.is_suspicious as is_suspicious
    LIMIT 150
    """
    edge_res = g.query(edge_query)
    edges = []
    seen_edges = set()
    for row in edge_res.result_set:
        k = f"{row[0]}-{row[1]}-{row[2]}"
        if k not in seen_edges and row[0] in seen_nodes and row[1] in seen_nodes:
            seen_edges.add(k)
            edges.append({
                "source": row[0],
                "target": row[1],
                "type": row[2] or "CONNECTED",
                "amount": row[3],
                "is_suspicious": row[4] or False
            })

    ring_ids = list(set(n["ring_id"] for n in nodes if n.get("ring_id")))
    return {
        "tool": "find_fraud_rings",
        "account_id": "ALL",
        "max_hops": 0,
        "nodes": nodes,
        "edges": edges,
        "rings_detected": ring_ids,
        "suspicious_node_count": sum(1 for n in nodes if n.get("is_suspicious")),
        "cypher": "MATCH (a:Account) WHERE a.ring_id IS NOT NULL MATCH (a)-[r]-(dst) RETURN a, r, dst",
    }


def find_fraud_rings(account_id: str | None = None, max_hops: int = 4) -> dict:
    if not account_id or str(account_id).strip().upper() in ("ALL", "NONE", "*", ""):
        return find_all_fraud_rings()

    max_hops = int(max_hops) if max_hops else 4
    g = get_graph()

    nodes = []
    seen_nodes = set()

    # Include start node
    start_res = g.query(
        "MATCH (start:Account {id: $id}) RETURN start.id, labels(start)[0], start.name, start.risk_score, start.is_suspicious, start.ring_id",
        {"id": account_id},
    )
    if start_res.result_set:
        s_row = start_res.result_set[0]
        nodes.append({
            "id": s_row[0],
            "type": s_row[1] or "Account",
            "name": s_row[2] or s_row[0],
            "risk_score": s_row[3] or 0,
            "is_suspicious": s_row[4] or False,
            "ring_id": s_row[5],
            "hops": 0,
        })
        seen_nodes.add(s_row[0])

    query = """
    MATCH (start:Account {id: $id})
    MATCH path = (start)-[*1..4]-(connected)
    WHERE (connected:Account OR connected:IPAddress OR connected:Device)
    WITH connected, min(length(path)) as hops
    RETURN 
        coalesce(connected.id, connected.fingerprint, connected.address) as node_id,
        labels(connected)[0] as node_type,
        coalesce(connected.name, connected.fingerprint, connected.address, connected.id) as name,
        connected.risk_score as risk_score,
        connected.is_suspicious as is_suspicious,
        connected.ring_id as ring_id,
        hops
    ORDER BY hops ASC
    LIMIT 100
    """
    result = g.query(query, {"id": account_id})

    for row in result.result_set:
        nid = row[0]
        if nid and nid not in seen_nodes:
            seen_nodes.add(nid)
            nodes.append(
                {
                    "id": nid,
                    "type": row[1] or "Unknown",
                    "name": row[2] or nid,
                    "risk_score": row[3] or 0,
                    "is_suspicious": row[4] or False,
                    "ring_id": row[5],
                    "hops": row[6],
                }
            )

    # Get edges in the subgraph using relationships(path)
    edge_query = """
    MATCH path = (start:Account {id: $id})-[*1..4]-(connected)
    WHERE (connected:Account OR connected:IPAddress OR connected:Device)
    UNWIND relationships(path) as rel
    RETURN DISTINCT 
        coalesce(startNode(rel).id, startNode(rel).fingerprint, startNode(rel).address) as src,
        coalesce(endNode(rel).id, endNode(rel).fingerprint, endNode(rel).address) as dst,
        type(rel) as rel_type,
        rel.amount as amount,
        rel.is_suspicious as is_suspicious
    LIMIT 200
    """
    edge_result = g.query(edge_query, {"id": account_id})
    edges = []
    seen = set()
    for row in edge_result.result_set:
        key = f"{row[0]}-{row[1]}-{row[2]}"
        if key not in seen and row[0] and row[1]:
            seen.add(key)
            edges.append(
                {
                    "source": row[0],
                    "target": row[1],
                    "type": row[2] or "CONNECTED",
                    "amount": row[3],
                    "is_suspicious": row[4] or False,
                }
            )

    # Determine if rings detected
    ring_ids = set(n["ring_id"] for n in nodes if n.get("ring_id"))
    suspicious_count = sum(1 for n in nodes if n.get("is_suspicious"))

    return {
        "tool": "find_fraud_rings",
        "account_id": account_id,
        "max_hops": max_hops,
        "nodes": nodes,
        "edges": edges,
        "rings_detected": list(ring_ids),
        "suspicious_node_count": suspicious_count,
        "cypher": f"MATCH (start:Account {{id: '{account_id}'}})-[*1..{max_hops}]-(connected) RETURN path",
    }


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 2 – Money laundering chain tracing
# ─────────────────────────────────────────────────────────────────────────────
def trace_money_flow(account_id: str) -> dict:
    """
    Follow transaction flows from a given account to detect layering,
    structuring, and circular patterns (hallmarks of money laundering).

    Cypher used:
        MATCH (src:Account {id: $id})-[t:TRANSACTED_WITH*1..6]->(dst)
        RETURN src, t, dst
    """
    g = get_graph()

    # Outflow chain
    outflow_query = """
    MATCH (start:Account {id: $id})-[t:TRANSACTED_WITH]->(dst:Account)
    RETURN 
        dst.id as dst_id,
        dst.name as dst_name,
        dst.risk_score as dst_risk,
        t.amount as amount,
        t.currency as currency,
        t.timestamp as ts,
        t.channel as channel,
        t.pattern as pattern,
        t.is_suspicious as is_suspicious
    ORDER BY t.amount DESC
    LIMIT 50
    """
    out_result = g.query(outflow_query, {"id": account_id})
    outflows = []
    for row in out_result.result_set:
        outflows.append(
            {
                "dst_id": row[0],
                "dst_name": row[1],
                "dst_risk": row[2] or 0,
                "amount": row[3] or 0,
                "currency": row[4] or "USD",
                "timestamp": row[5] or "",
                "channel": row[6] or "",
                "pattern": row[7],
                "is_suspicious": row[8] or False,
            }
        )

    # Inflow chain
    inflow_query = """
    MATCH (src:Account)-[t:TRANSACTED_WITH]->(end:Account {id: $id})
    RETURN 
        src.id as src_id,
        src.name as src_name,
        src.risk_score as src_risk,
        t.amount as amount,
        t.currency as currency,
        t.timestamp as ts,
        t.channel as channel,
        t.pattern as pattern,
        t.is_suspicious as is_suspicious
    ORDER BY t.amount DESC
    LIMIT 50
    """
    in_result = g.query(inflow_query, {"id": account_id})
    inflows = []
    for row in in_result.result_set:
        inflows.append(
            {
                "src_id": row[0],
                "src_name": row[1],
                "src_risk": row[2] or 0,
                "amount": row[3] or 0,
                "currency": row[4] or "USD",
                "timestamp": row[5] or "",
                "channel": row[6] or "",
                "pattern": row[7],
                "is_suspicious": row[8] or False,
            }
        )

    # Detect circular flows (money returning to origin)
    circular_query = """
    MATCH cycle = (start:Account {id: $id})-[:TRANSACTED_WITH*2..6]->(start)
    RETURN length(cycle) as cycle_length
    LIMIT 5
    """
    try:
        circ_result = g.query(circular_query, {"id": account_id})
        cycles = [row[0] for row in circ_result.result_set]
    except Exception:
        cycles = []

    total_out = sum(o["amount"] for o in outflows)
    total_in = sum(i["amount"] for i in inflows)
    suspicious_tx = sum(1 for o in outflows if o["is_suspicious"]) + sum(
        1 for i in inflows if i["is_suspicious"]
    )

    return {
        "tool": "trace_money_flow",
        "account_id": account_id,
        "outflows": outflows,
        "inflows": inflows,
        "total_outflow": round(total_out, 2),
        "total_inflow": round(total_in, 2),
        "suspicious_transactions": suspicious_tx,
        "circular_flows_detected": len(cycles) > 0,
        "cycle_lengths": cycles,
        "structuring_detected": any(
            9000 <= o["amount"] <= 9999 for o in outflows
        ),
        "cypher": f"MATCH (a:Account {{id: '{account_id}'}})-[t:TRANSACTED_WITH*1..6]->(dst) RETURN a, t, dst",
    }


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 3 – Anomaly / Risk score propagation
# ─────────────────────────────────────────────────────────────────────────────
def compute_risk_score(account_id: str) -> dict:
    """
    Compute a composite risk score for an account based on:
    - Its own risk_score
    - Risk scores of neighboring accounts (PageRank-style propagation)
    - Number of suspicious transactions
    - Shared IPs/devices with known bad actors
    - Alert events attached

    Cypher used:
        MATCH (a:Account {id: $id})-[*1..2]-(neighbor)
        RETURN neighbor.risk_score
    """
    g = get_graph()

    # Get account itself
    acc_query = """
    MATCH (a:Account {id: $id})
    RETURN 
        a.name as name,
        a.risk_score as base_risk,
        a.is_suspicious as suspicious,
        a.country as country,
        a.entity_type as entity_type,
        a.balance as balance
    """
    acc_result = g.query(acc_query, {"id": account_id})
    if not acc_result.result_set:
        return {"error": f"Account {account_id} not found"}

    row = acc_result.result_set[0]
    base_risk = row[1] or 0.0

    # Neighbor risk (1-hop)
    nbr_query = """
    MATCH (a:Account {id: $id})-[:TRANSACTED_WITH]-(nbr:Account)
    RETURN avg(nbr.risk_score) as avg_nbr_risk, count(nbr) as nbr_count
    """
    nbr_result = g.query(nbr_query, {"id": account_id})
    avg_nbr_risk = 0.0
    nbr_count = 0
    if nbr_result.result_set:
        avg_nbr_risk = nbr_result.result_set[0][0] or 0.0
        nbr_count = nbr_result.result_set[0][1] or 0

    # Shared IP penalty
    ip_query = """
    MATCH (a:Account {id: $id})-[:USES_IP]->(ip:IPAddress)<-[:USES_IP]-(other:Account)
    WHERE other.id <> $id AND other.is_suspicious = true
    RETURN count(other) as bad_ip_neighbors
    """
    ip_result = g.query(ip_query, {"id": account_id})
    bad_ip_neighbors = 0
    if ip_result.result_set:
        bad_ip_neighbors = ip_result.result_set[0][0] or 0

    # Alert count
    alert_query = """
    MATCH (a:Account {id: $id})-[:HAS_ALERT]->(al:AlertEvent)
    RETURN count(al) as alert_count, 
           collect(al.severity) as severities,
           collect(al.type) as types
    """
    alert_result = g.query(alert_query, {"id": account_id})
    alert_count = 0
    severities = []
    alert_types = []
    if alert_result.result_set:
        alert_count = alert_result.result_set[0][0] or 0
        severities = alert_result.result_set[0][1] or []
        alert_types = alert_result.result_set[0][2] or []

    # Composite score calculation
    # Weighted formula: base(40%) + neighbor_influence(20%) + ip_penalty(20%) + alert_penalty(20%)
    ip_penalty = min(bad_ip_neighbors * 0.15, 0.3)
    alert_penalty = min(alert_count * 0.1, 0.2)
    composite = (
        0.4 * base_risk
        + 0.2 * avg_nbr_risk
        + 0.2 * ip_penalty
        + 0.2 * alert_penalty
    )
    composite = min(round(composite, 3), 1.0)

    risk_label = (
        "CRITICAL" if composite > 0.75
        else "HIGH" if composite > 0.5
        else "MEDIUM" if composite > 0.25
        else "LOW"
    )

    return {
        "tool": "compute_risk_score",
        "account_id": account_id,
        "account_name": row[0],
        "base_risk": base_risk,
        "neighbor_avg_risk": round(avg_nbr_risk, 3),
        "neighbor_count": nbr_count,
        "bad_ip_neighbors": bad_ip_neighbors,
        "alert_count": alert_count,
        "alert_severities": severities,
        "alert_types": alert_types,
        "composite_risk_score": composite,
        "risk_label": risk_label,
        "country": row[4],
        "entity_type": row[5],
        "balance": row[6],
        "cypher": f"""MATCH (a:Account {{id: '{account_id}'}})
OPTIONAL MATCH (a)-[:TRANSACTED_WITH]-(nbr:Account)
OPTIONAL MATCH (a)-[:USES_IP]->(ip)<-[:USES_IP]-(bad {{is_suspicious: true}})
OPTIONAL MATCH (a)-[:HAS_ALERT]->(al)
RETURN a, avg(nbr.risk_score), count(bad), count(al)""",
    }


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 4 – Shared infrastructure lookup
# ─────────────────────────────────────────────────────────────────────────────
def find_shared_infrastructure(account_id: str) -> dict:
    """
    Find accounts that share the same IP addresses or device fingerprints.
    This is a classic fraud detection signal — legitimate users rarely share devices.

    Cypher used:
        MATCH (a:Account {id: $id})-[:USES_IP|USES_DEVICE]->(infra)
              <-[:USES_IP|USES_DEVICE]-(other:Account)
        RETURN other, infra
    """
    g = get_graph()

    query = """
    MATCH (a:Account {id: $id})-[r1:USES_IP|USES_DEVICE]->(infra)<-[r2:USES_IP|USES_DEVICE]-(other:Account)
    WHERE other.id <> $id
    RETURN 
        other.id as other_id,
        other.name as other_name,
        other.risk_score as other_risk,
        other.is_suspicious as other_suspicious,
        labels(infra)[0] as infra_type,
        infra.id as infra_id,
        type(r1) as rel_type
    """
    result = g.query(query, {"id": account_id})

    shared = []
    for row in result.result_set:
        shared.append(
            {
                "account_id": row[0],
                "account_name": row[1],
                "risk_score": row[2] or 0,
                "is_suspicious": row[3] or False,
                "infrastructure_type": row[4],
                "infrastructure_id": row[5],
                "relationship": row[6],
            }
        )

    return {
        "tool": "find_shared_infrastructure",
        "account_id": account_id,
        "shared_accounts": shared,
        "total_shared": len(shared),
        "suspicious_shared": sum(1 for s in shared if s["is_suspicious"]),
        "cypher": f"MATCH (a:Account {{id: '{account_id}'}})-[:USES_IP|USES_DEVICE]->(infra)<-[:USES_IP|USES_DEVICE]-(other) RETURN other, infra",
    }


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 5 – Get active alerts
# ─────────────────────────────────────────────────────────────────────────────
def get_active_alerts(limit: int = 20) -> dict:
    limit = int(limit) if limit else 20
    g = get_graph()

    query = """
    MATCH (a:Account)-[:HAS_ALERT]->(al:AlertEvent)
    WHERE al.resolved = false
    RETURN 
        a.id as account_id,
        a.name as account_name,
        a.country as country,
        a.risk_score as risk_score,
        al.id as alert_id,
        al.type as alert_type,
        al.severity as severity,
        al.timestamp as timestamp
    ORDER BY al.timestamp DESC
    LIMIT $limit
    """
    result = g.query(query, {"limit": limit})

    alerts = []
    for row in result.result_set:
        alerts.append(
            {
                "account_id": row[0],
                "account_name": row[1],
                "country": row[2],
                "risk_score": row[3] or 0,
                "alert_id": row[4],
                "alert_type": row[5],
                "severity": row[6],
                "timestamp": row[7],
            }
        )

    return {
        "tool": "get_active_alerts",
        "alerts": alerts,
        "total_alerts": len(alerts),
        "critical_count": sum(1 for a in alerts if a["severity"] == "CRITICAL"),
        "high_count": sum(1 for a in alerts if a["severity"] == "HIGH"),
        "cypher": "MATCH (a:Account)-[:HAS_ALERT]->(al:AlertEvent {resolved: false}) RETURN a, al ORDER BY al.timestamp DESC",
    }


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 6 – Agent memory: save finding
# ─────────────────────────────────────────────────────────────────────────────
def save_investigation_memory(
    session_id: str, finding: str, account_id: str | None = None, tags: list[str] | None = None
) -> dict:
    """
    Persist an agent finding to the session memory graph in FalkorDB.
    Each session has its own isolated graph: memory_<session_id>

    Cypher used:
        MERGE (m:Memory {id: $id})
        SET m.finding = $finding, m.timestamp = $ts
    """
    mg = get_memory_graph(session_id)
    mem_id = f"MEM_{str(uuid.uuid4())[:8]}"
    ts = datetime.utcnow().isoformat()

    mg.query(
        """
        MERGE (m:Memory {id: $id})
        SET m.finding = $finding,
            m.timestamp = $ts,
            m.account_id = $acc,
            m.tags = $tags,
            m.session_id = $session
        """,
        {
            "id": mem_id,
            "finding": finding,
            "ts": ts,
            "acc": account_id or "",
            "tags": tags or [],
            "session": session_id,
        },
    )

    # Link to previous memory in same session (chain of thought)
    mg.query(
        """
        MATCH (m:Memory {id: $id})
        OPTIONAL MATCH (prev:Memory)
        WHERE prev.id <> $id AND prev.session_id = $session
        WITH m, prev ORDER BY prev.timestamp DESC LIMIT 1
        FOREACH (p IN CASE WHEN prev IS NOT NULL THEN [prev] ELSE [] END |
            MERGE (prev)-[:FOLLOWED_BY]->(m)
        )
        """,
        {"id": mem_id, "session": session_id},
    )

    return {
        "tool": "save_investigation_memory",
        "memory_id": mem_id,
        "session_id": session_id,
        "saved": True,
        "cypher": f"MERGE (m:Memory {{id: '{mem_id}'}}) SET m.finding = '...'",
    }


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 7 – Agent memory: recall findings
# ─────────────────────────────────────────────────────────────────────────────
def recall_investigation_memory(session_id: str, account_id: str | None = None) -> dict:
    """
    Retrieve past investigation findings from the session memory graph.

    Cypher used:
        MATCH (m:Memory {session_id: $session})
        RETURN m ORDER BY m.timestamp DESC
    """
    mg = get_memory_graph(session_id)

    query = """
    MATCH (m:Memory {session_id: $session})
    RETURN m.id, m.finding, m.timestamp, m.account_id, m.tags
    ORDER BY m.timestamp DESC
    LIMIT 20
    """
    params = {"session": session_id}
    if account_id:
        query = """
        MATCH (m:Memory {session_id: $session, account_id: $acc})
        RETURN m.id, m.finding, m.timestamp, m.account_id, m.tags
        ORDER BY m.timestamp DESC LIMIT 20
        """
        params["acc"] = account_id

    try:
        result = mg.query(query, params)
        memories = []
        for row in result.result_set:
            memories.append(
                {
                    "id": row[0],
                    "finding": row[1],
                    "timestamp": row[2],
                    "account_id": row[3],
                    "tags": row[4] or [],
                }
            )
    except Exception:
        memories = []

    return {
        "tool": "recall_investigation_memory",
        "session_id": session_id,
        "memories": memories,
        "count": len(memories),
        "cypher": f"MATCH (m:Memory {{session_id: '{session_id}'}}) RETURN m ORDER BY m.timestamp DESC",
    }


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 8 – Search accounts by name / keyword
# ─────────────────────────────────────────────────────────────────────────────
def search_accounts(query_str: str) -> dict:
    """
    Full-text search over account names and IDs.

    Cypher used:
        MATCH (a:Account)
        WHERE toLower(a.name) CONTAINS toLower($q) OR a.id CONTAINS $q
        RETURN a
    """
    g = get_graph()

    cypher = """
    MATCH (a:Account)
    WHERE toLower(a.name) CONTAINS toLower($q) OR a.id CONTAINS $q
    RETURN 
        a.id as id,
        a.name as name,
        a.country as country,
        a.risk_score as risk_score,
        a.is_suspicious as is_suspicious,
        a.balance as balance,
        a.entity_type as entity_type
    LIMIT 20
    """
    result = g.query(cypher, {"q": query_str})

    accounts = []
    for row in result.result_set:
        accounts.append(
            {
                "id": row[0],
                "name": row[1],
                "country": row[2],
                "risk_score": row[3] or 0,
                "is_suspicious": row[4] or False,
                "balance": row[5] or 0,
                "entity_type": row[6],
            }
        )

    return {
        "tool": "search_accounts",
        "query": query_str,
        "accounts": accounts,
        "count": len(accounts),
        "cypher": f"MATCH (a:Account) WHERE toLower(a.name) CONTAINS '{query_str.lower()}' RETURN a",
    }


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 9 – Graph stats overview
# ─────────────────────────────────────────────────────────────────────────────
def get_graph_overview() -> dict:
    """
    Return high-level statistics about the fraud graph.
    Used by the agent to orient itself at the start of an investigation.
    """
    g = get_graph()

    stats_query = """
    MATCH (n)
    RETURN labels(n)[0] as label, count(n) as cnt
    """
    result = g.query(stats_query)
    node_counts = {}
    for row in result.result_set:
        node_counts[row[0] or "Unknown"] = row[1]

    suspicious_query = """
    MATCH (a:Account {is_suspicious: true})
    RETURN count(a) as suspicious_accounts
    """
    susp_result = g.query(suspicious_query)
    suspicious_count = susp_result.result_set[0][0] if susp_result.result_set else 0

    alert_query = """
    MATCH (al:AlertEvent {resolved: false})
    RETURN count(al) as open_alerts
    """
    alert_result = g.query(alert_query)
    open_alerts = alert_result.result_set[0][0] if alert_result.result_set else 0

    tx_query = """
    MATCH ()-[t:TRANSACTED_WITH]->()
    RETURN count(t) as tx_count, sum(t.amount) as total_volume
    """
    tx_result = g.query(tx_query)
    tx_count = 0
    tx_volume = 0
    if tx_result.result_set:
        tx_count = tx_result.result_set[0][0] or 0
        tx_volume = round(tx_result.result_set[0][1] or 0, 2)

    return {
        "tool": "get_graph_overview",
        "node_counts": node_counts,
        "suspicious_accounts": suspicious_count,
        "open_alerts": open_alerts,
        "total_transactions": tx_count,
        "total_volume_usd": tx_volume,
        "cypher": "MATCH (n) RETURN labels(n)[0], count(n)",
    }
