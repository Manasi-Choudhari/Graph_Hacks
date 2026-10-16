"""
Graph tool definitions for the FraudScope AI agent.

These are the tools the agent selects via MCP / function calling.
Each tool wraps one or more FalkorDB Cypher queries.
"""

from db import get_graph, get_memory_graph
from datetime import datetime
import uuid

# HAS_ALERT is excluded: alert nodes are leaves and only multiply path enumeration.
RING_REL_TYPES = "TRANSACTED_WITH|USES_IP|USES_DEVICE|OWNED_BY"


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 1 – Multi-hop fraud ring detection
# ─────────────────────────────────────────────────────────────────────────────
def find_fraud_rings(account_id: str | None = None, max_hops: int = 4) -> dict:
    if not account_id or str(account_id).strip().upper() in ("ALL", "NONE", "*", ""):
        return detect_fraud_communities()

    max_hops = max(1, min(int(max_hops) if max_hops else 4, 4))
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

    query = f"""
    MATCH (start:Account {{id: $id}})
    MATCH path = (start)-[:{RING_REL_TYPES}*1..{max_hops}]-(connected)
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

    edge_query = f"""
    MATCH (src)-[rel:{RING_REL_TYPES}]->(dst)
    WITH src, rel, dst,
         coalesce(src.id, src.fingerprint, src.address) as src_key,
         coalesce(dst.id, dst.fingerprint, dst.address) as dst_key
    WHERE src_key IN $keys AND dst_key IN $keys
    RETURN DISTINCT src_key, dst_key, type(rel), rel.amount, rel.is_suspicious
    LIMIT 200
    """
    edge_result = g.query(edge_query, {"keys": list(seen_nodes)})
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
        "cypher": f"MATCH path = (start:Account {{id: '{account_id}'}})-[:{RING_REL_TYPES}*1..{max_hops}]-(connected) RETURN connected, min(length(path)) AS hops",
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

    query = """
    MATCH (a:Account {id: $id})
    OPTIONAL MATCH (a)-[:TRANSACTED_WITH]-(nbr:Account)
    WITH a, avg(nbr.risk_score) AS avg_nbr_risk, count(DISTINCT nbr) AS nbr_count
    OPTIONAL MATCH (a)-[:USES_IP]->(:IPAddress)<-[:USES_IP]-(bad:Account)
    WHERE bad.id <> a.id AND bad.is_suspicious = true
    WITH a, avg_nbr_risk, nbr_count, count(DISTINCT bad) AS bad_ip_neighbors
    OPTIONAL MATCH (a)-[:HAS_ALERT]->(al:AlertEvent)
    RETURN a.name, a.risk_score, a.country, a.entity_type, a.balance,
           avg_nbr_risk, nbr_count, bad_ip_neighbors,
           count(al), collect(al.severity), collect(al.type), a.status
    """
    result = g.query(query, {"id": account_id})
    if not result.result_set:
        return {"error": f"Account {account_id} not found"}

    row = result.result_set[0]
    base_risk = row[1] or 0.0
    avg_nbr_risk = row[5] or 0.0
    nbr_count = row[6] or 0
    bad_ip_neighbors = row[7] or 0
    alert_count = row[8] or 0
    severities = row[9] or []
    alert_types = row[10] or []

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
        "country": row[2],
        "entity_type": row[3],
        "balance": row[4],
        "account_status": row[11] or "ACTIVE",
        "cypher": " ".join(query.split()).replace("$id", f"'{account_id}'"),
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
    WHERE toLower(a.name) CONTAINS toLower($q) OR toLower(a.id) CONTAINS toLower($q)
       OR toLower(coalesce(a.entity_type, '')) CONTAINS toLower($q)
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
        "cypher": f"MATCH (a:Account) WHERE toLower(a.name) CONTAINS '{query_str.lower()}' OR toLower(a.id) CONTAINS '{query_str.lower()}' OR toLower(a.entity_type) CONTAINS '{query_str.lower()}' RETURN a",
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


# ─────────────────────────────────────────────────────────────────────────────
# ACTIONS – agent proposes, a human approves, the graph records both
# ─────────────────────────────────────────────────────────────────────────────

ACTION_TYPES = {
    "freeze_account": "Block all outgoing transactions from the account",
    "open_case": "Open an investigation case linking the account and its evidence",
    "escalate_alert": "Escalate the account's open alerts to CRITICAL for the compliance team",
    "file_sar": "File a Suspicious Activity Report with the regulator",
    "clear_account": "Mark the account as reviewed and resolve its alerts (false positive)",
}


def propose_action(
    action_type: str,
    account_id: str,
    reason: str,
    evidence_account_ids: list[str] | None = None,
    session_id: str = "",
) -> dict:
    """
    Record a proposed action as an (:Action {status: 'PENDING_APPROVAL'}) node
    linked to its target account and to the evidence that justifies it.
    Nothing changes on the account until a human approves it.
    """
    if action_type not in ACTION_TYPES:
        return {"error": f"Unknown action_type '{action_type}'. Use one of: {', '.join(ACTION_TYPES)}"}

    g = get_graph()
    existing = g.query(
        """
        MATCH (act:Action {type: $type, status: 'PENDING_APPROVAL'})-[:TARGETS]->(:Account {id: $acc})
        RETURN act.id
        """,
        {"type": action_type, "acc": account_id},
    ).result_set
    if existing:
        return {
            "tool": "propose_action",
            "action_id": existing[0][0],
            "status": "PENDING_APPROVAL",
            "note": "An identical action is already awaiting approval.",
            "cypher": "MATCH (act:Action {status: 'PENDING_APPROVAL'})-[:TARGETS]->(a:Account) RETURN act",
        }

    action_id = f"ACT_{uuid.uuid4().hex[:8]}"
    query = """
    MATCH (a:Account {id: $acc})
    CREATE (act:Action {id: $id, type: $type, status: 'PENDING_APPROVAL', reason: $reason,
                        proposed_by: 'FraudScope Agent', session_id: $session, created_at: $ts})
    CREATE (act)-[:TARGETS]->(a)
    WITH act, a
    OPTIONAL MATCH (a)-[:HAS_ALERT]->(al:AlertEvent {resolved: false})
    FOREACH (x IN CASE WHEN al IS NULL THEN [] ELSE [al] END | CREATE (act)-[:EVIDENCED_BY]->(x))
    WITH DISTINCT act
    OPTIONAL MATCH (ev:Account) WHERE ev.id IN $evidence
    FOREACH (x IN CASE WHEN ev IS NULL THEN [] ELSE [ev] END | CREATE (act)-[:EVIDENCED_BY]->(x))
    WITH DISTINCT act
    MATCH (act)-[:EVIDENCED_BY]->(e)
    RETURN act.id, count(e)
    """
    rows = g.query(query, {
        "acc": account_id,
        "id": action_id,
        "type": action_type,
        "reason": reason,
        "session": session_id or "",
        "ts": datetime.utcnow().isoformat(),
        "evidence": [e for e in (evidence_account_ids or []) if e != account_id],
    }).result_set
    if not rows:
        exists = g.query("MATCH (act:Action {id: $id}) RETURN act.id", {"id": action_id}).result_set
        if not exists:
            return {"error": f"Account {account_id} not found"}

    return {
        "tool": "propose_action",
        "action_id": action_id,
        "action_type": action_type,
        "description": ACTION_TYPES[action_type],
        "account_id": account_id,
        "status": "PENDING_APPROVAL",
        "evidence_links": rows[0][1] if rows else 0,
        "cypher": "CREATE (act:Action {status: 'PENDING_APPROVAL', ...})-[:TARGETS]->(a:Account {id: '"
                  + account_id + "'}) CREATE (act)-[:EVIDENCED_BY]->(evidence)",
    }


def list_actions(status: str | None = None, limit: int = 50) -> dict:
    g = get_graph()
    query = """
    MATCH (act:Action)-[:TARGETS]->(a:Account)
    WHERE $status IS NULL OR act.status = $status
    OPTIONAL MATCH (act)-[:EVIDENCED_BY]->(e)
    RETURN act.id, act.type, act.status, act.reason, act.created_at, act.reviewed_by, act.reviewed_at,
           a.id, a.name, a.risk_score, a.status,
           collect(DISTINCT coalesce(e.id, e.fingerprint, e.address))
    ORDER BY act.created_at DESC
    LIMIT $limit
    """
    rows = g.query(query, {"status": status or None, "limit": int(limit or 50)}).result_set
    actions = [
        {
            "action_id": r[0], "action_type": r[1], "status": r[2], "reason": r[3],
            "created_at": r[4], "reviewed_by": r[5], "reviewed_at": r[6],
            "account_id": r[7], "account_name": r[8], "risk_score": r[9] or 0,
            "account_status": r[10] or "ACTIVE", "evidence": r[11] or [],
        }
        for r in rows
    ]
    return {
        "tool": "list_actions",
        "actions": actions,
        "pending": sum(1 for a in actions if a["status"] == "PENDING_APPROVAL"),
        "cypher": "MATCH (act:Action)-[:TARGETS]->(a:Account) OPTIONAL MATCH (act)-[:EVIDENCED_BY]->(e) RETURN act, a, collect(e)",
    }


_ACTION_EFFECTS = {
    "freeze_account": "SET a.status = 'FROZEN', a.frozen_at = $ts",
    "open_case": """
        MERGE (c:Case {id: 'CASE_' + act.id})
        SET c.status = 'OPEN', c.opened_at = $ts, c.reason = act.reason
        MERGE (c)-[:CONCERNS]->(a)
        MERGE (act)-[:CREATED]->(c)
        SET a.status = coalesce(a.status, 'UNDER_INVESTIGATION')
    """,
    "escalate_alert": """
        WITH act, a
        OPTIONAL MATCH (a)-[:HAS_ALERT]->(al:AlertEvent {resolved: false})
        FOREACH (x IN CASE WHEN al IS NULL THEN [] ELSE [al] END | SET x.severity = 'CRITICAL', x.escalated = true)
    """,
    "file_sar": """
        MERGE (s:SAR {id: 'SAR_' + act.id})
        SET s.filed_at = $ts, s.narrative = act.reason
        MERGE (s)-[:REPORTS]->(a)
        MERGE (act)-[:CREATED]->(s)
    """,
    "clear_account": """
        SET a.is_suspicious = false, a.status = 'CLEARED'
        WITH act, a
        OPTIONAL MATCH (a)-[:HAS_ALERT]->(al:AlertEvent {resolved: false})
        FOREACH (x IN CASE WHEN al IS NULL THEN [] ELSE [al] END | SET x.resolved = true)
    """,
}


def review_action(action_id: str, decision: str, reviewer: str = "analyst") -> dict:
    """Human-in-the-loop: approve (and execute) or reject a proposed action."""
    decision = (decision or "").lower()
    if decision not in ("approve", "reject"):
        return {"error": "decision must be 'approve' or 'reject'"}

    g = get_graph()
    row = g.query(
        "MATCH (act:Action {id: $id})-[:TARGETS]->(a:Account) RETURN act.type, act.status, a.id",
        {"id": action_id},
    ).result_set
    if not row:
        return {"error": f"Action {action_id} not found"}
    action_type, status, account_id = row[0]
    if status != "PENDING_APPROVAL":
        return {"error": f"Action {action_id} is already {status}"}

    ts = datetime.utcnow().isoformat()
    new_status = "APPROVED" if decision == "approve" else "REJECTED"
    effect = _ACTION_EFFECTS[action_type] if decision == "approve" else ""
    g.query(
        f"""
        MATCH (act:Action {{id: $id}})-[:TARGETS]->(a:Account)
        SET act.status = $status, act.reviewed_by = $reviewer, act.reviewed_at = $ts
        {effect}
        """,
        {"id": action_id, "status": new_status, "reviewer": reviewer, "ts": ts},
    )
    return {
        "tool": "review_action",
        "action_id": action_id,
        "action_type": action_type,
        "account_id": account_id,
        "status": new_status,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GRAPH ALGORITHMS (FalkorDB built-in procedures exposed as agent tools)
# ─────────────────────────────────────────────────────────────────────────────

NODE_KEY = "coalesce({v}.id, {v}.fingerprint, {v}.address)"
STRUCTURING_MIN, STRUCTURING_MAX = 9000, 10000


def _node_dict(key, label, name, risk, suspicious, ring_id=None, entity_type=None, **extra) -> dict:
    return {
        "id": key,
        "type": label or "Unknown",
        "name": name or key,
        "risk_score": risk or 0,
        "is_suspicious": suspicious or False,
        "ring_id": ring_id,
        "entity_type": entity_type,
        **extra,
    }


def detect_fraud_communities(min_accounts: int = 3) -> dict:
    """
    Discover fraud rings WITHOUT using any labels: run Weakly Connected
    Components over the shared-identity subgraph (accounts linked through
    the same IP or device), then score each cluster by the money patterns
    flowing inside it (structuring, internal volume).
    """
    min_accounts = max(2, int(min_accounts or 3))
    g = get_graph()

    query = f"""
    CALL algo.WCC({{nodeLabels: ['Account', 'IPAddress', 'Device'], relationshipTypes: ['USES_IP', 'USES_DEVICE']}})
    YIELD node, componentId
    WITH componentId, collect(node) AS members
    WITH componentId,
         [m IN members WHERE m:Account] AS accounts,
         [m IN members WHERE NOT m:Account] AS infra
    WHERE size(accounts) >= $min_accounts
    UNWIND accounts AS a
    OPTIONAL MATCH (a)-[t:TRANSACTED_WITH]->(b:Account)
    WHERE b IN accounts
    WITH componentId, accounts, infra,
         count(t) AS internal_tx,
         sum(CASE WHEN t.amount >= {STRUCTURING_MIN} AND t.amount < {STRUCTURING_MAX} THEN 1 ELSE 0 END) AS structuring_tx,
         sum(coalesce(t.amount, 0)) AS internal_volume
    RETURN componentId,
           [x IN accounts | [x.id, x.name, x.risk_score, x.is_suspicious, x.ring_id, x.entity_type]],
           [x IN infra | [{NODE_KEY.format(v='x')}, labels(x)[0]]],
           internal_tx, structuring_tx, internal_volume
    """
    result = g.query(query, {"min_accounts": min_accounts})

    communities = []
    nodes, edges, seen = [], [], set()
    for row in result.result_set:
        comp_id, accounts, infra, internal_tx, structuring_tx, volume = row
        size_signal = min(len(accounts) / 6, 1.0)
        score = round(
            0.45 * min(structuring_tx / 10, 1.0)
            + 0.30 * min(internal_tx / 15, 1.0)
            + 0.25 * size_signal,
            3,
        )
        known_rings = sorted({a[4] for a in accounts if a[4]})
        communities.append({
            "community_id": comp_id,
            "account_count": len(accounts),
            "accounts": [{"id": a[0], "name": a[1], "risk_score": a[2] or 0, "entity_type": a[5]} for a in accounts],
            "shared_infrastructure": [{"id": i[0], "type": i[1]} for i in infra],
            "internal_transactions": internal_tx,
            "structuring_transactions": structuring_tx,
            "internal_volume": round(volume or 0, 2),
            "community_risk_score": score,
            "verdict": "LIKELY_FRAUD_RING" if structuring_tx >= 3 and len(accounts) >= 3 else "SHARED_INFRA_ONLY",
            "matches_known_ring": known_rings[0] if len(known_rings) == 1 else None,
        })
        for a in accounts:
            if a[0] not in seen:
                seen.add(a[0])
                nodes.append(_node_dict(a[0], "Account", a[1], a[2], a[3], a[4], a[5], community=comp_id))
        for i in infra:
            if i[0] not in seen:
                seen.add(i[0])
                nodes.append(_node_dict(i[0], i[1], i[0], 0, False, community=comp_id))

    communities.sort(key=lambda c: c["community_risk_score"], reverse=True)

    if seen:
        edge_query = f"""
        MATCH (src)-[r:TRANSACTED_WITH|USES_IP|USES_DEVICE]->(dst)
        WITH r, {NODE_KEY.format(v='src')} AS s, {NODE_KEY.format(v='dst')} AS d
        WHERE s IN $keys AND d IN $keys
        RETURN DISTINCT s, d, type(r), r.amount, r.is_suspicious
        LIMIT 300
        """
        for s, d, rel, amount, susp in g.query(edge_query, {"keys": list(seen)}).result_set:
            edges.append({"source": s, "target": d, "type": rel, "amount": amount, "is_suspicious": susp or False})

    return {
        "tool": "detect_fraud_communities",
        "algorithm": "algo.WCC (Weakly Connected Components) over USES_IP/USES_DEVICE",
        "communities": communities,
        "likely_fraud_rings": sum(1 for c in communities if c["verdict"] == "LIKELY_FRAUD_RING"),
        "nodes": nodes,
        "edges": edges,
        "cypher": "CALL algo.WCC({nodeLabels: ['Account','IPAddress','Device'], relationshipTypes: ['USES_IP','USES_DEVICE']}) "
                  "YIELD node, componentId WITH componentId, collect(node) AS members ... "
                  f"OPTIONAL MATCH (a)-[t:TRANSACTED_WITH]->(b) WHERE b IN accounts RETURN componentId, count(t), "
                  f"sum(CASE WHEN {STRUCTURING_MIN} <= t.amount < {STRUCTURING_MAX} THEN 1 END)",
    }


def rank_key_accounts(metric: str = "pagerank", limit: int = 10) -> dict:
    """
    Rank accounts by graph centrality over the money network.
    - pagerank:    where money ultimately concentrates (collection hubs)
    - betweenness: who sits on the most money paths (brokers / mules)
    """
    metric = (metric or "pagerank").lower()
    limit = max(1, min(int(limit or 10), 25))
    g = get_graph()

    if metric == "betweenness":
        call = "CALL algo.betweenness({nodeLabels: ['Account'], relationshipTypes: ['TRANSACTED_WITH']}) YIELD node, score"
    else:
        metric = "pagerank"
        call = "CALL algo.pageRank('Account', 'TRANSACTED_WITH') YIELD node, score"

    query = f"""
    {call}
    RETURN node.id, node.name, score, node.risk_score, node.is_suspicious, node.entity_type
    ORDER BY score DESC
    LIMIT $limit
    """
    rows = g.query(query, {"limit": limit}).result_set
    ranked = [
        {
            "rank": i + 1,
            "account_id": r[0],
            "name": r[1],
            "score": round(r[2] or 0, 5),
            "risk_score": r[3] or 0,
            "is_suspicious": r[4] or False,
            "entity_type": r[5],
        }
        for i, r in enumerate(rows)
    ]
    return {
        "tool": "rank_key_accounts",
        "metric": metric,
        "ranked_accounts": ranked,
        "suspicious_in_top": sum(1 for r in ranked if r["is_suspicious"]),
        "cypher": " ".join(query.split()).replace("$limit", str(limit)),
    }


def explain_connection(source_id: str, target_id: str, max_hops: int = 6) -> dict:
    """
    Find the shortest paths linking two accounts across money, IP, device and
    ownership edges. This is the evidence chain an investigator would cite.
    """
    max_hops = max(1, min(int(max_hops or 6), 8))
    g = get_graph()

    query = f"""
    MATCH (a:Account {{id: $src}}), (b:Account {{id: $dst}})
    CALL algo.SPpaths({{sourceNode: a, targetNode: b,
                        relTypes: ['TRANSACTED_WITH', 'USES_IP', 'USES_DEVICE', 'OWNED_BY'],
                        relDirection: 'both', maxLen: {max_hops}, pathCount: 3}})
    YIELD path
    RETURN [n IN nodes(path) | [{NODE_KEY.format(v='n')}, labels(n)[0], coalesce(n.name, {NODE_KEY.format(v='n')}), n.risk_score, n.is_suspicious, n.ring_id, n.entity_type]],
           [r IN relationships(path) | [{NODE_KEY.format(v='startNode(r)')}, {NODE_KEY.format(v='endNode(r)')}, type(r), r.amount, r.is_suspicious]]
    """
    rows = g.query(query, {"src": source_id, "dst": target_id}).result_set

    paths, nodes, edges = [], [], []
    seen_nodes, seen_edges, seen_paths = set(), set(), set()
    for path_nodes, path_rels in rows:
        signature = tuple(n[0] for n in path_nodes) + tuple(r[2] for r in path_rels)
        if signature in seen_paths:
            continue
        seen_paths.add(signature)
        steps = []
        for i, rel in enumerate(path_rels):
            steps.append(f"{path_nodes[i][0]} -[{rel[2]}]- {path_nodes[i + 1][0]}")
        paths.append({"length": len(path_rels), "nodes": [n[0] for n in path_nodes], "steps": steps})
        for n in path_nodes:
            if n[0] not in seen_nodes:
                seen_nodes.add(n[0])
                nodes.append(_node_dict(*n))
        for s, d, rel, amount, susp in path_rels:
            k = (s, d, rel)
            if k not in seen_edges:
                seen_edges.add(k)
                edges.append({"source": s, "target": d, "type": rel, "amount": amount, "is_suspicious": susp or False})

    return {
        "tool": "explain_connection",
        "source_id": source_id,
        "target_id": target_id,
        "connected": bool(paths),
        "shortest_length": min((p["length"] for p in paths), default=None),
        "paths": paths,
        "nodes": nodes,
        "edges": edges,
        "cypher": " ".join(query.split()).replace("$src", f"'{source_id}'").replace("$dst", f"'{target_id}'"),
    }


def build_flow_projection() -> int:
    """
    Collapse parallel TRANSACTED_WITH edges into one FLOWS_TO edge per ordered
    account pair (amount = total volume). algo.maxFlow rejects multi-edges.
    """
    g = get_graph()
    g.query("MATCH ()-[f:FLOWS_TO]->() DELETE f")
    res = g.query("""
    MATCH (a:Account)-[t:TRANSACTED_WITH]->(b:Account)
    WITH a, b, sum(t.amount) AS total, count(t) AS n
    CREATE (a)-[:FLOWS_TO {amount: total, tx_count: n}]->(b)
    """)
    return res.relationships_created


def _ensure_flow_projection(g) -> None:
    if not g.query("MATCH ()-[f:FLOWS_TO]->() RETURN f LIMIT 1").result_set:
        build_flow_projection()


def compute_max_flow(source_id: str, target_id: str) -> dict:
    """
    Maximum amount of money that can be routed from source to target through
    the directed transaction network (edge capacity = total amount sent).
    Reveals layering: large flow over indirect paths means funds were split
    and recombined to hide their origin.
    """
    g = get_graph()
    _ensure_flow_projection(g)
    query = f"""
    MATCH (s:Account {{id: $src}}), (t:Account {{id: $dst}})
    CALL algo.maxFlow({{sourceNodes: [s], targetNodes: [t], capacityProperty: 'amount', relationshipTypes: ['FLOWS_TO']}})
    YIELD edges, edgeFlows, maxFlow
    RETURN maxFlow,
           [i IN range(0, size(edges) - 1) | [startNode(edges[i]).id, endNode(edges[i]).id, edgeFlows[i]]]
    """
    rows = g.query(query, {"src": source_id, "dst": target_id}).result_set
    if not rows:
        return {"error": f"Account {source_id} or {target_id} not found"}

    max_flow, flow_edges = rows[0]
    flow_edges = flow_edges or []
    direct = sum(f for s, d, f in flow_edges if s == source_id and d == target_id)
    intermediaries = sorted(({s for s, _, _ in flow_edges} | {d for _, d, _ in flow_edges}) - {source_id, target_id})

    return {
        "tool": "compute_max_flow",
        "source_id": source_id,
        "target_id": target_id,
        "max_flow": max_flow or 0,
        "direct_flow": direct,
        "indirect_flow": (max_flow or 0) - direct,
        "intermediary_accounts": intermediaries,
        "flow_edges": [{"source": s, "target": d, "flow": f} for s, d, f in flow_edges][:30],
        "edges": [{"source": s, "target": d, "type": "TRANSACTED_WITH", "amount": f, "is_suspicious": True} for s, d, f in flow_edges],
        "cypher": " ".join(query.split()).replace("$src", f"'{source_id}'").replace("$dst", f"'{target_id}'"),
    }
