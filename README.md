# 🕵️ FraudScope AI

> **Graph Hacks Hackathon — Track: Agents That Act on Connected Data**
> Powered by [FalkorDB](https://www.falkordb.com) · Built with Gemini + Groq

An AI agent that investigates financial fraud by reasoning over a **FalkorDB graph database**. The graph is not a visualization layer — it **is** the intelligence. Every decision the agent makes is driven by multi-hop graph traversals, Cypher queries, and graph-propagated risk scores.

---

## 🎯 What It Does

FraudScope AI is a financial crime investigation agent that:

- **Discovers fraud rings with no labels** — `algo.WCC` community detection over shared IPs/devices, scored by structuring and internal money flow
- **Finds the key players** — `algo.pageRank` (where money concentrates) and `algo.betweenness` (brokers on the most money paths)
- **Explains how any two accounts are connected** — `algo.SPpaths` returns the shortest evidence chains
- **Quantifies layering** — `algo.maxFlow` measures how much money can reach a cash-out account through intermediaries
- **Acts on what the graph shows** — proposes freeze / open case / escalate / file SAR actions, stored as `(:Action)` nodes linked to their evidence; a human approves before anything changes
- **Speaks MCP** — every tool is served by a real MCP server; the in-app agent, Claude Desktop and Cursor all use the same registry
- **Streams its reasoning** — tool calls appear live in the chat and the evidence path lights up on the graph
- **Remembers what it learns** — each session gets its own isolated memory graph in FalkorDB
- **Explains every step** — shows the exact Cypher query and latency for each tool call

---

## 🗃️ Graph Data Model

```
┌──────────────┐    TRANSACTED_WITH    ┌──────────────┐
│   Account    │──────────────────────▶│   Account    │
│  (id, name,  │                       │ (shell/mule) │
│  risk_score, │    USES_IP            └──────────────┘
│  country)    │──────────────────────▶ IPAddress
└──────────────┘    USES_DEVICE        Device
        │           OWNED_BY          Entity
        │           HAS_ALERT         AlertEvent
        └──────────────────────────────────────▶
                                       Memory (per session graph)
```

### Node Types
| Node | Key Properties |
|------|---------------|
| `Account` | id, name, country, balance, risk_score, is_suspicious, ring_id, entity_type |
| `Entity` | id, name, type, jurisdiction |
| `IPAddress` | id, address |
| `Device` | fingerprint |
| `AlertEvent` | id, type, severity, timestamp, resolved |
| `Action` | id, type, status (PENDING_APPROVAL / APPROVED / REJECTED), reason, reviewed_by |
| `Case` / `SAR` | created when an `open_case` / `file_sar` action is approved |
| `Memory` | id, finding, timestamp, session_id, tags |

### Edge Types
| Edge | Meaning |
|------|---------|
| `TRANSACTED_WITH` | Financial transaction (has amount, currency, channel, pattern) |
| `USES_IP` | Account accessed via this IP address |
| `USES_DEVICE` | Account accessed from this device fingerprint |
| `OWNED_BY` | Account owned by legal entity |
| `HAS_ALERT` | Account has a fraud alert event |
| `FLOWS_TO` | One edge per account pair summing its transactions (input to `algo.maxFlow`, which rejects multi-edges) |
| `TARGETS` / `EVIDENCED_BY` | Action → account it acts on / evidence that justifies it |
| `FOLLOWED_BY` | Memory chain (agent reasoning sequence) |

---

## 🔍 Key Cypher Queries

### Label-free Ring Discovery (community detection)
```cypher
CALL algo.WCC({nodeLabels: ['Account','IPAddress','Device'], relationshipTypes: ['USES_IP','USES_DEVICE']})
YIELD node, componentId
WITH componentId, collect(node) AS members
WITH componentId, [m IN members WHERE m:Account] AS accounts
UNWIND accounts AS a
OPTIONAL MATCH (a)-[t:TRANSACTED_WITH]->(b:Account) WHERE b IN accounts
RETURN componentId, count(t) AS internal_tx,
       sum(CASE WHEN t.amount >= 9000 AND t.amount < 10000 THEN 1 ELSE 0 END) AS structuring_tx
```

### Key Players (centrality)
```cypher
CALL algo.pageRank('Account', 'TRANSACTED_WITH') YIELD node, score
RETURN node.id, score ORDER BY score DESC LIMIT 10
```

### Evidence Path Between Two Accounts
```cypher
MATCH (a:Account {id: $src}), (b:Account {id: $dst})
CALL algo.SPpaths({sourceNode: a, targetNode: b,
                   relTypes: ['TRANSACTED_WITH','USES_IP','USES_DEVICE','OWNED_BY'],
                   relDirection: 'both', maxLen: 6, pathCount: 3})
YIELD path RETURN path
```

### Layering Volume (max flow)
```cypher
MATCH (s:Account {id: $src}), (t:Account {id: $dst})
CALL algo.maxFlow({sourceNodes: [s], targetNodes: [t], capacityProperty: 'amount', relationshipTypes: ['FLOWS_TO']})
YIELD maxFlow, edges, edgeFlows
RETURN maxFlow
```

### Multi-hop Neighbourhood of One Account
```cypher
MATCH path = (start:Account {id: $id})-[:TRANSACTED_WITH|USES_IP|USES_DEVICE|OWNED_BY*1..4]-(connected)
WHERE connected:Account OR connected:IPAddress OR connected:Device
RETURN connected, min(length(path)) AS hops
ORDER BY hops ASC
LIMIT 100
```

### Money Laundering Chain
```cypher
MATCH (src:Account {id: $id})-[t:TRANSACTED_WITH]->(dst:Account)
RETURN dst.id, dst.risk_score, t.amount, t.channel, t.pattern
ORDER BY t.amount DESC
```

### Circular Flow Detection (Layering)
```cypher
MATCH cycle = (start:Account {id: $id})-[:TRANSACTED_WITH*2..6]->(start)
RETURN length(cycle) as cycle_length
```

### Shared Infrastructure
```cypher
MATCH (a:Account {id: $id})-[:USES_IP|USES_DEVICE]->(infra)
      <-[:USES_IP|USES_DEVICE]-(other:Account)
WHERE other.id <> $id
RETURN other, labels(infra)[0] as infra_type
```

### Graph-Propagated Risk Score
```cypher
MATCH (a:Account {id: $id})
OPTIONAL MATCH (a)-[:TRANSACTED_WITH]-(nbr:Account)
OPTIONAL MATCH (a)-[:USES_IP]->(ip)<-[:USES_IP]-(bad {is_suspicious: true})
OPTIONAL MATCH (a)-[:HAS_ALERT]->(al)
RETURN a, avg(nbr.risk_score), count(bad), count(al)
```

### Agent Memory (Per-Session Graph)
```cypher
-- Save finding
MERGE (m:Memory {id: $id})
SET m.finding = $finding, m.timestamp = $ts, m.session_id = $session

-- Recall findings
MATCH (m:Memory {session_id: $session})
RETURN m ORDER BY m.timestamp DESC
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     FraudScope AI                        │
│                                                          │
│  ┌──────────┐    WebSocket/REST    ┌─────────────────┐  │
│  │  React   │◄────────────────────►│  FastAPI Server │  │
│  │  Vite    │                      │   (Python)      │  │
│  │  D3.js   │                      └────────┬────────┘  │
│  │  UI      │                               │            │
│  └──────────┘               ┌──────────────▼──────────┐ │
│                              │   Agent Loop (Gemini/   │ │
│                              │   Groq + Tool Calling)  │ │
│                              └──────────────┬──────────┘ │
│                                             │            │
│                              ┌──────────────▼──────────┐ │
│  Claude Desktop / Cursor ───►│   MCP server (/mcp/)    │ │
│                              │  15 Cypher + algo tools │ │
│                              └──────────────┬──────────┘ │
│                                             │            │
│                              ┌──────────────▼──────────┐ │
│                              │       FalkorDB          │ │
│                              │  fraudscope graph +     │ │
│                              │  memory_<session> graphs│ │
│                              └─────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### Why FalkorDB is Central
- **Every agent decision** goes through a graph query — no flat SQL
- **Built-in graph algorithms** (WCC, PageRank, betweenness, shortest paths, max flow) are the agent's tools
- **Actions are graph writes** — proposals, approvals, cases and SARs are nodes linked to the evidence that produced them
- **Multi-hop traversal** finds fraud rings that linear queries miss
- **Per-session memory graphs** — each investigation session is its own isolated FalkorDB graph
- **Risk propagation** runs as a graph algorithm, not a lookup
- If you replace FalkorDB with a relational DB, the agent cannot find fraud rings or propagate risk — **the graph is the product**

---

## 🚀 Setup & Running

### Prerequisites
- Docker (for FalkorDB)
- Python 3.10+
- Node.js 18+
- Gemini API key OR Groq API key

### 1. Start FalkorDB
```bash
docker compose up -d
# OR without compose:
docker run -p 6379:6379 falkordb/falkordb:latest
```

### 2. Backend Setup
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys
```

### 3. Configure Environment
```env
GEMINI_API_KEY=your_key_here   # Get from Google AI Studio
GROQ_API_KEY=your_key_here     # Get from console.groq.com
LLM_PROVIDER=groq               # or "gemini"; the other is used as fallback
GROQ_MODEL=openai/gpt-oss-120b
FALKORDB_HOST=localhost
FALKORDB_PORT=6379
```

### 4. Run Backend
```bash
cd backend
python main.py
# API runs at http://localhost:8000
```

### 5. Frontend Setup
```bash
cd frontend
npm install
npm run dev
# UI at http://localhost:5173
```

### 6. Seed the Graph
Click **"Seed DB"** in the UI, or:
```bash
cd backend
python seed.py
```

Seeding wipes the graph and rebuilds the same deterministic dataset every time:
- 60 legitimate accounts with 150 everyday transactions
- 3 fraud rings, each with 1 shell company + 5 mule accounts
- Structuring (transfers between $9,000 and $9,999), mule → shell collection, and a mule → mule → … → crypto cash-out layering chain per ring
- Shared IPs / devices per ring (plus a few innocent shared-WiFi pairs as noise)
- AlertEvents for all suspicious accounts

---

## 🤖 Agent Tools (served over MCP)

| Tool | Graph technique | What it finds |
|------|-----------------|---------------|
| `detect_fraud_communities` | `algo.WCC` + in-cluster money patterns | Fraud rings, without using any labels |
| `rank_key_accounts` | `algo.pageRank` / `algo.betweenness` | Collection hubs and broker accounts |
| `explain_connection` | `algo.SPpaths` | Shortest evidence paths between two accounts |
| `compute_max_flow` | `algo.maxFlow` | Money routed to a target, direct vs layered |
| `find_fraud_rings` | Multi-hop traversal (1–4 hops) | One account's ring and shared infrastructure |
| `trace_money_flow` | Directed path following + cycles | Layering, structuring, circular flows |
| `compute_risk_score` | Neighbourhood aggregation | Composite risk with propagation, account status |
| `find_shared_infrastructure` | Bipartite traversal | Shared IPs/devices (fraud signal) |
| `propose_action` | Node + edge creation | `(:Action)-[:TARGETS]->(account)`, `-[:EVIDENCED_BY]->(evidence)` |
| `list_actions` | Pattern match | Action queue with evidence |
| `get_active_alerts` | Filtered node retrieval | Open HIGH/CRITICAL alerts |
| `search_accounts` | String matching | Accounts by name, ID or entity type |
| `get_graph_overview` | Aggregation | Graph-wide statistics |
| `save_investigation_memory` / `recall_investigation_memory` | Per-session graph | Investigation memory |

`review_action` (approve / reject) is deliberately **not** an MCP tool: agents propose, only a human analyst can approve, from the **Actions** tab or `POST /api/actions/{id}/review`.

---

## 🔌 Use the tools from Claude Desktop, Cursor or any MCP client

The backend serves the MCP server over streamable HTTP at `http://localhost:8000/mcp/`. For a stdio connection:

```json
{
  "mcpServers": {
    "fraudscope": {
      "command": "<path-to-repo>/backend/.venv/Scripts/python.exe",
      "args": ["<path-to-repo>/backend/mcp_server.py"]
    }
  }
}
```

Add it to Claude Desktop's `claude_desktop_config.json` or Cursor's `.cursor/mcp.json` (on macOS/Linux use `.venv/bin/python`). FalkorDB must be running.

---

## ⚡ Performance

- Graph tools return in 3–150 ms; one answer typically takes 2–6 s end to end
- Independent tools are requested in a single LLM round; findings are saved to memory automatically, without an extra LLM round
- Tool results are compacted before going back to the LLM, history is trimmed, and identical tool calls are cached for 2 minutes
- A rate-limited model is skipped for 60 s and the next model takes over for that call only; if a provider fails mid-answer, the fallback continues from the tool results already gathered
- If every LLM is rate-limited, the agent still returns the graph findings instead of an error

---

## 📸 Demo

1. **"Find all fraud rings"** — WCC discovers the 3 rings; the graph shows them live
2. **"Who are the money hubs?"** — PageRank / betweenness highlight the key accounts
3. **"Trace layering from the top shell company to its cash-out exchange"** — max flow shows the money moved only through mules; the path lights up
4. **"Sweep the graph and propose actions"** — proposals appear in the **Actions** tab; approving one freezes the account / opens a case in FalkorDB
5. **"What did I investigate before?"** — recalled from the session's memory graph

---

## 🏆 Hackathon Track

**Track:** Agents That Act on Connected Data

**Key focus areas addressed:**
- ✅ Multi-hop reasoning — 4-hop ring traversal, shortest evidence paths, multi-hop max flow
- ✅ Graph queries and algorithms as agent tools — WCC, PageRank, betweenness, SPpaths, maxFlow
- ✅ Tool selection through MCP — real MCP server, shared by the agent, Claude Desktop and Cursor
- ✅ Actions based on what the graph shows — evidence-linked Action nodes with human approval
- ✅ Explainable results — live tool stream, Cypher + latency per call, evidence path highlighted on the graph

---

## 📜 Disclosure

This project was built with the assistance of AI coding tools (Antigravity IDE / Gemini). All graph models, Cypher queries, fraud detection logic, and architecture decisions were designed and verified by the team.

---

*Built for Graph Hacks — WeMakeDevs × FalkorDB | October 2026*
