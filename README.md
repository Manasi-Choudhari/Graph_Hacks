# 🕵️ FraudScope AI

> **Graph Hacks Hackathon — Track: Agents That Act on Connected Data**
> Powered by [FalkorDB](https://www.falkordb.com) · Built with Gemini + Groq

An AI agent that investigates financial fraud by reasoning over a **FalkorDB graph database**. The graph is not a visualization layer — it **is** the intelligence. Every decision the agent makes is driven by multi-hop graph traversals, Cypher queries, and graph-propagated risk scores.

---

## 🎯 What It Does

FraudScope AI is a financial crime investigation agent that:

- **Detects fraud rings** via multi-hop graph traversal (up to 4 hops)
- **Traces money laundering chains** by following TRANSACTED_WITH relationships
- **Computes risk scores** propagated through neighbor relationships, shared infrastructure, and alert signals
- **Finds shared IPs and devices** — the strongest fraud cohabitation signal
- **Remembers what it learns** — each session gets its own isolated memory graph in FalkorDB
- **Explains every step** — shows the exact Cypher query used for each decision

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
| `Memory` | id, finding, timestamp, session_id, tags |

### Edge Types
| Edge | Meaning |
|------|---------|
| `TRANSACTED_WITH` | Financial transaction (has amount, currency, channel, pattern) |
| `USES_IP` | Account accessed via this IP address |
| `USES_DEVICE` | Account accessed from this device fingerprint |
| `OWNED_BY` | Account owned by legal entity |
| `HAS_ALERT` | Account has a fraud alert event |
| `FOLLOWED_BY` | Memory chain (agent reasoning sequence) |

---

## 🔍 Key Cypher Queries

### Multi-hop Fraud Ring Detection
```cypher
MATCH (start:Account {id: $id})-[*1..4]-(connected)
WHERE connected:Account OR connected:IPAddress OR connected:Device
RETURN DISTINCT connected, length(path) as hops
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
│                              │      Graph Tools        │ │
│                              │  (9 Cypher-backed tools)│ │
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
LLM_PROVIDER=gemini             # or "groq"
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

This creates:
- 60 legitimate accounts
- 3 fraud rings (each with 1 shell company + 5 mule accounts)
- 150+ transactions (including structuring patterns)
- Shared IPs / devices per ring
- AlertEvents for all suspicious accounts

---

## 🤖 Agent Tools (MCP-style)

| Tool | Graph Query Type | What It Finds |
|------|-----------------|---------------|
| `find_fraud_rings` | Multi-hop traversal | Hidden fraud networks |
| `trace_money_flow` | Directed path following | Layering, structuring, circular flows |
| `compute_risk_score` | Neighborhood aggregation | Composite risk with propagation |
| `find_shared_infrastructure` | Bipartite traversal | Shared IPs/devices (fraud signal) |
| `get_active_alerts` | Filtered node retrieval | Open HIGH/CRITICAL alerts |
| `save_investigation_memory` | Node creation + chain | Persist findings to memory graph |
| `recall_investigation_memory` | Node retrieval | Recall past findings |
| `search_accounts` | String matching | Find accounts by name/ID |
| `get_graph_overview` | Aggregation | Graph-wide statistics |

---

## 📸 Demo

The agent can:
1. **Spot fraud rings** that span 3-4 hops with shared IP addresses
2. **Detect structuring** — transactions deliberately kept under $10,000
3. **Trace the full money laundering cycle**: inject → layer → collect
4. **Remember** what it found in previous queries within the same session
5. **Show the Cypher** for every decision it makes

---

## 🏆 Hackathon Track

**Track:** Agents That Act on Connected Data

**Key focus areas addressed:**
- ✅ Multi-hop reasoning (fraud ring detection across 4 hops)
- ✅ Graph queries and algorithms as agent tools (9 Cypher-backed tools)
- ✅ Tool selection through MCP-style function calling
- ✅ Actions based on what the graph shows
- ✅ Explainable results (Cypher shown for every decision)

---

## 📜 Disclosure

This project was built with the assistance of AI coding tools (Antigravity IDE / Gemini). All graph models, Cypher queries, fraud detection logic, and architecture decisions were designed and verified by the team.

---

*Built for Graph Hacks — WeMakeDevs × FalkorDB | October 2026*
