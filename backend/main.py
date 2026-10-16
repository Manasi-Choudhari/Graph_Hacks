"""
FraudScope AI — FastAPI Backend
Main application: REST API + WebSocket for real-time agent streaming.
"""

import os
import sys
import uuid
import json
import asyncio
from typing import Any
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(override=True)

from db import init_schema, get_graph
import tools as graph_tools
from agent import run_agent

# ── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="FraudScope AI",
    description="AI agent for financial fraud investigation powered by FalkorDB graph database",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store (conversation histories)
# In production, this would be stored in FalkorDB memory graphs
sessions: dict[str, list[dict]] = {}


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    print("🚀 FraudScope AI starting up...")
    try:
        init_schema()
        print("✅ FalkorDB connected and schema initialized")
    except Exception as e:
        print(f"⚠️  FalkorDB not ready yet: {e}")
        print("   Make sure FalkorDB is running: docker run -p 6379:6379 falkordb/falkordb:latest")


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    try:
        g = get_graph()
        result = g.query("RETURN 1 AS ok")
        db_ok = result.result_set[0][0] == 1
    except Exception as e:
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "falkordb": "connected" if db_ok else "disconnected",
        "llm_provider": os.getenv("LLM_PROVIDER", "groq"),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── Graph overview ────────────────────────────────────────────────────────────

@app.get("/api/overview")
async def overview():
    try:
        return graph_tools.get_graph_overview()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Alerts ────────────────────────────────────────────────────────────────────

@app.get("/api/alerts")
async def get_alerts(limit: int = 20):
    try:
        return graph_tools.get_active_alerts(limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Account search ────────────────────────────────────────────────────────────

@app.get("/api/accounts/search")
async def search_accounts(q: str):
    try:
        return graph_tools.search_accounts(q)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Account detail ────────────────────────────────────────────────────────────

@app.get("/api/accounts/{account_id}")
async def get_account(account_id: str):
    try:
        risk = graph_tools.compute_risk_score(account_id)
        if "error" in risk:
            raise HTTPException(status_code=404, detail=risk["error"])
        return risk
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Graph subgraph for visualization ──────────────────────────────────────────

@app.get("/api/graph/subgraph/{account_id}")
async def get_subgraph(account_id: str, hops: int = 3):
    try:
        return graph_tools.find_fraud_rings(account_id, max_hops=hops)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/graph/full")
async def get_full_graph(limit: int = 150):
    """Return the full graph for the overview visualization."""
    g = get_graph()
    try:
        # Get nodes
        node_query = """
        MATCH (n)
        WHERE n:Account OR n:IPAddress OR n:Device OR n:Entity
        RETURN 
            n.id as id,
            labels(n)[0] as type,
            n.name as name,
            n.risk_score as risk_score,
            n.is_suspicious as is_suspicious,
            n.country as country,
            n.entity_type as entity_type
        LIMIT $limit
        """
        node_result = g.query(node_query, {"limit": limit})
        nodes = []
        for row in node_result.result_set:
            nodes.append({
                "id": row[0] or "?",
                "type": row[1] or "Unknown",
                "name": row[2] or row[0] or "",
                "risk_score": row[3] or 0,
                "is_suspicious": row[4] or False,
                "country": row[5] or "",
                "entity_type": row[6],
            })

        # Get edges
        edge_query = """
        MATCH (src)-[r]->(dst)
        WHERE (src:Account OR src:IPAddress OR src:Device)
          AND (dst:Account OR dst:IPAddress OR dst:Device OR dst:Entity)
        RETURN 
            src.id as src,
            dst.id as dst,
            type(r) as rel_type,
            r.amount as amount,
            r.is_suspicious as is_suspicious
        LIMIT $limit
        """
        edge_result = g.query(edge_query, {"limit": limit * 2})
        edges = []
        for row in edge_result.result_set:
            if row[0] and row[1]:
                edges.append({
                    "source": row[0],
                    "target": row[1],
                    "type": row[2] or "CONNECTED",
                    "amount": row[3],
                    "is_suspicious": row[4] or False,
                })

        return {"nodes": nodes, "edges": edges}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Money flow ────────────────────────────────────────────────────────────────

@app.get("/api/accounts/{account_id}/flow")
async def get_money_flow(account_id: str):
    try:
        return graph_tools.trace_money_flow(account_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/accounts/{account_id}/infrastructure")
async def get_infrastructure(account_id: str):
    try:
        return graph_tools.find_shared_infrastructure(account_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Session management ────────────────────────────────────────────────────────

@app.post("/api/sessions")
async def create_session():
    session_id = str(uuid.uuid4())[:12]
    sessions[session_id] = []
    return {"session_id": session_id}


@app.get("/api/sessions/{session_id}/memory")
async def get_memory(session_id: str):
    try:
        return graph_tools.recall_investigation_memory(session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Chat (REST) ───────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str


@app.post("/api/chat")
async def chat(req: ChatRequest):
    history = sessions.get(req.session_id, [])
    try:
        result = await run_agent(req.message, req.session_id, history)

        # Append to history
        if req.session_id not in sessions:
            sessions[req.session_id] = []
        sessions[req.session_id].append({"role": "user", "content": req.message})
        sessions[req.session_id].append({"role": "model", "content": result["response"]})

        # Keep last 20 messages
        sessions[req.session_id] = sessions[req.session_id][-20:]

        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ── WebSocket chat (streaming simulation) ────────────────────────────────────

@app.websocket("/ws/chat/{session_id}")
async def ws_chat(websocket: WebSocket, session_id: str):
    await websocket.accept()
    print(f"🔌 WebSocket connected: session {session_id}")

    if session_id not in sessions:
        sessions[session_id] = []

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            user_message = payload.get("message", "")

            if not user_message:
                continue

            # Send typing indicator
            await websocket.send_json({"type": "typing", "session_id": session_id})

            try:
                result = await run_agent(user_message, session_id, sessions[session_id])

                # Stream tool calls as they come
                for i, tc in enumerate(result.get("tool_calls", [])):
                    await websocket.send_json({
                        "type": "tool_call",
                        "tool": tc["tool"],
                        "args": tc["args"],
                        "cypher": tc.get("cypher", ""),
                        "result": result["tool_results"][i] if i < len(result["tool_results"]) else {},
                    })
                    await asyncio.sleep(0.1)

                # Send final response
                await websocket.send_json({
                    "type": "response",
                    "content": result["response"],
                    "tool_calls": result["tool_calls"],
                    "session_id": session_id,
                })

                # Update history
                sessions[session_id].append({"role": "user", "content": user_message})
                sessions[session_id].append({"role": "model", "content": result["response"]})
                sessions[session_id] = sessions[session_id][-20:]

            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "content": str(e),
                })

    except WebSocketDisconnect:
        print(f"🔌 WebSocket disconnected: session {session_id}")


# ── Seed endpoint ─────────────────────────────────────────────────────────────

@app.post("/api/seed")
async def seed_database():
    """Seed the FalkorDB graph with synthetic fraud data."""
    try:
        import seed
        seed.seed_graph()
        overview = graph_tools.get_graph_overview()
        return {"status": "seeded", "overview": overview}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
