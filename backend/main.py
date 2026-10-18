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

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(override=True)

from db import init_schema, get_graph
import tools as graph_tools
from agent import run_agent, clear_tool_cache
from mcp_server import mcp
from multi_agent import run_collaborative_swarm, run_single_agent
import ingestion

# ── App setup ────────────────────────────────────────────────────────────────

mcp_app = mcp.streamable_http_app(streamable_http_path="/", host=os.getenv("MCP_HOST", "127.0.0.1"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    print("🚀 FraudScope AI starting up...")
    try:
        init_schema()
        print("✅ FalkorDB connected and schema initialized")
    except Exception as e:
        print(f"⚠️  FalkorDB not ready yet: {e}")
        print("   Make sure FalkorDB is running: docker run -p 6379:6379 falkordb/falkordb:latest")
    async with mcp.session_manager.run():
        print("🔌 MCP server available at /mcp/")
        yield


app = FastAPI(
    title="FraudScope AI",
    description="AI agent for financial fraud investigation powered by FalkorDB graph database",
    version="1.0.0",
    lifespan=lifespan,
)
app.mount("/mcp", mcp_app)

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
        MATCH (src)-[r:TRANSACTED_WITH|USES_IP|USES_DEVICE|OWNED_BY]->(dst)
        WHERE (src:Account OR src:IPAddress OR src:Device)
          AND (dst:Account OR dst:IPAddress OR dst:Device OR dst:Entity)
        RETURN 
            src.id as src,
            dst.id as dst,
            type(r) as rel_type,
            r.amount as amount,
            r.is_suspicious as is_suspicious,
            r.timestamp as timestamp,
            r.channel as channel,
            r.pattern as pattern
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
                    "timestamp": row[5] or "",
                    "channel": row[6] or "",
                    "pattern": row[7] or "",
                })

        return {"nodes": nodes, "edges": edges}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Temporal Velocity & Sliding Window Replay ───────────────────────────────────

@app.get("/api/temporal/velocity")
async def get_temporal_velocity(
    account_id: str | None = None,
    window_minutes: int = 30,
    min_amount: float = 500.0,
    limit: int = 50,
):
    try:
        return graph_tools.analyze_temporal_velocity(
            account_id=account_id,
            window_minutes=window_minutes,
            min_amount=min_amount,
            limit=limit,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/temporal/timeline")
async def get_temporal_timeline(window_minutes: int = 30):
    try:
        return graph_tools.get_temporal_timeline(window_minutes=window_minutes)
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
        _remember(req.session_id, req.message, result["response"])
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _remember(session_id: str, user_message: str, response: str) -> None:
    history = sessions.setdefault(session_id, [])
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": response})
    sessions[session_id] = history[-20:]


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """Server-Sent Events: tool calls are pushed the moment they run, then the final answer."""
    queue: asyncio.Queue = asyncio.Queue()

    async def on_event(event: dict):
        await queue.put(event)

    async def worker():
        try:
            result = await run_agent(req.message, req.session_id, sessions.get(req.session_id, []), on_event)
            _remember(req.session_id, req.message, result["response"])
            await queue.put({
                "type": "response",
                "content": result["response"],
                "elapsed_ms": result.get("elapsed_ms"),
                "tool_count": len(result.get("tool_calls", [])),
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            await queue.put({"type": "error", "content": str(e)})
        finally:
            await queue.put(None)

    async def events():
        task = asyncio.create_task(worker())
        try:
            while (event := await queue.get()) is not None:
                yield _sse(event)
        finally:
            task.cancel()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/chat/stream/single")
async def chat_stream_single(req: ChatRequest):
    """SSE: Run the Single-Agent Unified Investigator (triage + forensics + compliance in one pass)."""
    queue: asyncio.Queue = asyncio.Queue()

    async def on_event(event: dict):
        await queue.put(event)

    async def worker():
        try:
            result = await run_single_agent(
                req.message, req.session_id, sessions.get(req.session_id, []), on_event
            )
            _remember(req.session_id, req.message, result["response"])
            await queue.put({
                "type": "response",
                "content": result["response"],
                "elapsed_ms": result.get("elapsed_ms"),
                "tool_count": len(result.get("tool_calls", [])),
                "is_single_agent": True,
                "phases_completed": result.get("phases_completed", 3),
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            await queue.put({"type": "error", "content": str(e)})
        finally:
            await queue.put(None)

    async def events():
        task = asyncio.create_task(worker())
        try:
            while (event := await queue.get()) is not None:
                yield _sse(event)
        finally:
            task.cancel()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/chat/stream/swarm")
async def chat_stream_swarm(req: ChatRequest):
    """SSE: Run the Multi-Agent Specialist Swarm (Triage → Forensics → Compliance pipeline)."""
    queue: asyncio.Queue = asyncio.Queue()

    async def on_event(event: dict):
        await queue.put(event)

    async def worker():
        try:
            result = await run_collaborative_swarm(
                req.message, req.session_id, sessions.get(req.session_id, []), on_event
            )
            _remember(req.session_id, req.message, result["response"])
            await queue.put({
                "type": "response",
                "content": result["response"],
                "elapsed_ms": result.get("elapsed_ms"),
                "tool_count": len(result.get("tool_calls", [])),
                "is_swarm": True,
                "stages": result.get("stages", []),
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            await queue.put({"type": "error", "content": str(e)})
        finally:
            await queue.put(None)

    async def events():
        task = asyncio.create_task(worker())
        try:
            while (event := await queue.get()) is not None:
                yield _sse(event)
        finally:
            task.cancel()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})




# ── Actions (human-in-the-loop) ───────────────────────────────────────────────

class ReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    reviewer: str = "analyst"


@app.get("/api/actions")
async def get_actions(status: str | None = None):
    return graph_tools.list_actions(status)


@app.post("/api/actions/{action_id}/review")
async def review_action(action_id: str, req: ReviewRequest):
    result = graph_tools.review_action(action_id, req.decision, req.reviewer)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    clear_tool_cache()
    return result


# ── Graph algorithms ──────────────────────────────────────────────────────────

@app.get("/api/graph/communities")
async def get_communities():
    try:
        return graph_tools.detect_fraud_communities()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/graph/rank")
async def get_ranking(metric: str = "pagerank", limit: int = 10):
    try:
        return graph_tools.rank_key_accounts(metric, limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── WebSocket chat ────────────────────────────────────────────────────────────

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

            async def on_event(event: dict):
                await websocket.send_text(json.dumps(event, default=str))

            try:
                result = await run_agent(user_message, session_id, sessions[session_id], on_event)
                await websocket.send_json({
                    "type": "response",
                    "content": result["response"],
                    "tool_calls": result["tool_calls"],
                    "session_id": session_id,
                })
                _remember(session_id, user_message, result["response"])

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
        clear_tool_cache()
        overview = graph_tools.get_graph_overview()
        return {"status": "seeded", "overview": overview}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Dynamic Ingestion Endpoints ───────────────────────────────────────────────

@app.post("/api/ingest/file")
async def ingest_file(
    file: UploadFile = File(...),
    mode: str = Form("append"),
):
    """
    Ingest a CSV or JSON file containing accounts, transactions, or infrastructure.
    mode: 'append' (default) preserves existing data; 'replace' wipes before importing.
    """
    try:
        content_bytes = await file.read()
        filename = file.filename or ""
        text = content_bytes.decode("utf-8", errors="replace")

        if filename.endswith(".json") or file.content_type == "application/json":
            parsed = ingestion.parse_json_content(text)
        else:
            parsed = ingestion.parse_csv_content(text)

        result = ingestion.ingest_into_falkordb(parsed, mode=mode)
        clear_tool_cache()
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ingestion failed: {str(e)}")


class IngestJsonRequest(BaseModel):
    data: Any
    mode: str = "append"


@app.post("/api/ingest/json")
async def ingest_json(req: IngestJsonRequest):
    """
    Ingest raw JSON accounts/transactions bundle directly.
    """
    try:
        parsed = ingestion.parse_json_content(req.data)
        result = ingestion.ingest_into_falkordb(parsed, mode=req.mode)
        clear_tool_cache()
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"JSON ingestion failed: {str(e)}")


@app.get("/api/ingest/template")
async def download_template(type: str = "csv"):
    """
    Download a sample CSV or JSON template for structuring data.
    """
    tpl = ingestion.get_template(type)
    return Response(
        content=tpl["content"],
        media_type=tpl["content_type"],
        headers={"Content-Disposition": f'attachment; filename="{tpl["filename"]}"'},
    )


@app.post("/api/ingest/sample")
async def ingest_sample_syndicate(mode: str = "append"):
    """
    One-click import of an international layering syndicate dataset.
    """
    try:
        sample_data = ingestion.get_sample_syndicate_dataset()
        result = ingestion.ingest_into_falkordb(sample_data, mode=mode)
        clear_tool_cache()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
