"""
FraudScope AI Agent — Gemini / Groq powered investigative agent.

Tools are discovered from and executed through the FraudScope MCP server
(mcp_server.py), so the agent, Claude Desktop and Cursor all share one tool
registry. Session memory lives in per-session FalkorDB graphs.
"""

import os
import re
import sys
import json
import time
import asyncio
from typing import Any, Awaitable, Callable
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

load_dotenv(override=True)

import tools as graph_tools
from mcp_server import mcp

EventCallback = Callable[[dict], Awaitable[None]] | None

# ── Tool discovery via MCP ────────────────────────────────────────────────────

SESSION_PARAM = "session_id"
MEMORY_TOOLS = {"save_investigation_memory", "recall_investigation_memory"}
# Findings are auto-saved after each answer, so the LLM doesn't need the save tool.
HIDDEN_FROM_LLM = {"save_investigation_memory"}
_SCHEMA_KEYS = {"type", "description", "enum", "items", "properties", "required"}
_tool_specs: list[dict] | None = None


def _clean_schema(schema: dict) -> dict:
    """Reduce a pydantic JSON schema to the subset both Groq and Gemini accept."""
    if "anyOf" in schema:
        non_null = [s for s in schema["anyOf"] if s.get("type") != "null"]
        merged = {**(non_null[0] if non_null else {}), **{k: v for k, v in schema.items() if k != "anyOf"}}
        return _clean_schema(merged)
    out = {k: v for k, v in schema.items() if k in _SCHEMA_KEYS}
    if "properties" in out:
        out["properties"] = {k: _clean_schema(v) for k, v in out["properties"].items()}
    if "items" in out:
        out["items"] = _clean_schema(out["items"])
    return out


async def get_tool_specs() -> list[dict]:
    """Tool name/description/parameters as advertised by the MCP server (session_id hidden)."""
    global _tool_specs
    if _tool_specs is None:
        specs = []
        for tool in await mcp.list_tools():
            if tool.name in HIDDEN_FROM_LLM:
                continue
            params = _clean_schema(tool.input_schema)
            params.setdefault("type", "object")
            params.setdefault("properties", {})
            params["properties"].pop(SESSION_PARAM, None)
            if SESSION_PARAM in params.get("required", []):
                params["required"] = [r for r in params["required"] if r != SESSION_PARAM]
            if not params.get("required"):
                params.pop("required", None)
            specs.append({"name": tool.name, "description": tool.description or "", "parameters": params})
        _tool_specs = specs
    return _tool_specs


async def _session_aware_tools() -> set[str]:
    return {t.name for t in await mcp.list_tools() if SESSION_PARAM in t.input_schema.get("properties", {})}


# ── Tool execution via MCP (with a short read cache) ─────────────────────────

TOOL_CACHE_TTL = 120
UNCACHEABLE = MEMORY_TOOLS | {"propose_action", "list_actions"}
_tool_cache: dict[str, tuple[float, Any]] = {}


def clear_tool_cache() -> None:
    _tool_cache.clear()


async def dispatch_tool(name: str, args: dict) -> Any:
    cacheable = name not in UNCACHEABLE
    key = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
    if cacheable:
        hit = _tool_cache.get(key)
        if hit and time.time() - hit[0] < TOOL_CACHE_TTL:
            return hit[1]

    try:
        call = await mcp.call_tool(name, args)
        text = "".join(getattr(c, "text", "") for c in call.content)
        result = json.loads(text) if text else {}
        if call.is_error:
            result = {"error": text, "tool": name}
    except Exception as e:
        return {"error": str(e), "tool": name}

    if name == "propose_action":
        clear_tool_cache()
    if cacheable and isinstance(result, dict) and "error" not in result:
        _tool_cache[key] = (time.time(), result)
    return result


async def _prepare_args(tool_name: str, tool_args: dict, session_id: str) -> dict:
    tool_args = {
        k: int(v) if isinstance(v, float) and v.is_integer() else v
        for k, v in (tool_args or {}).items()
        if v is not None
    }
    if tool_name in await _session_aware_tools():
        tool_args[SESSION_PARAM] = session_id
    return tool_args


# ── History handling ──────────────────────────────────────────────────────────

HISTORY_TURNS = 4
HISTORY_MSG_CHARS = 700


def _trim_history(conversation_history: list) -> list:
    trimmed = []
    for msg in conversation_history[-HISTORY_TURNS:]:
        content = msg.get("content") or ""
        if len(content) > HISTORY_MSG_CHARS:
            content = content[:HISTORY_MSG_CHARS] + "…"
        trimmed.append({"role": msg["role"], "content": content})
    return trimmed


def _strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are FraudScope AI, an expert financial crime investigator. Your context is a FalkorDB knowledge graph of accounts, transactions (TRANSACTED_WITH), IP addresses, devices, legal entities and alert events. Your tools come from the FraudScope MCP server.

## How to investigate
- Account ID prefixes: SHELL_ = shell company, MULE_ = money mule, CASHOUT_ = crypto cash-out exchange, ACC_ = regular customer. To find accounts of a type, call search_accounts once with the entity type (e.g. "crypto_exchange").
- Pick the most relevant tool(s) directly. When you need several independent tools, request them all in the SAME turn.
- "Find all fraud rings" → detect_fraud_communities (label-free community detection). One account's ring → find_fraud_rings with account_id.
- "Who are the key players / hubs / brokers" → rank_key_accounts (pagerank for collection hubs, betweenness for brokers).
- "How is A connected to B" → explain_connection. "How much money moved from A to B / layering" → compute_max_flow.
- Never call the same tool twice with the same arguments. Only call get_graph_overview for overview questions.
- Signals that matter: structuring (amounts just under $10k), circular or layered flows, shared IPs/devices with suspicious accounts, centrality.

## Taking action
- When the evidence is strong (confirmed ring membership, structuring, layering, shared infrastructure with suspicious accounts), PROPOSE concrete actions with propose_action (freeze_account, open_case, escalate_alert, file_sar, or clear_account for false positives). Cite the evidence in `reason` and list related accounts in evidence_account_ids.
- Proposed actions are NOT executed: say they await analyst approval in the Actions tab.
- Don't propose actions on legitimate-looking accounts without evidence.

## Answer format
- Lead with a one-line verdict, then the evidence (accounts, amounts, paths), then any actions proposed.
- Mention which graph algorithm or traversal produced each finding (the Cypher is shown to the user automatically).
- Findings are saved to memory automatically.
- Keep it concise markdown.
"""


# ── Compact tool output for the LLM ───────────────────────────────────────────

MAX_TOOL_ROUNDS = 3


def _format_tool_result_for_llm(tool_name: str, result: Any) -> str:
    """Compact tool output so the LLM sees the signal, not the full payload."""
    if not isinstance(result, dict):
        s = str(result)
        return s[:500] + "..." if len(s) > 500 else s

    if "error" in result:
        return json.dumps({"tool": tool_name, "error": str(result["error"])[:400]})

    slim: dict[str, Any]
    if tool_name == "find_fraud_rings":
        nodes = result.get("nodes", [])
        slim = {
            "account_id": result.get("account_id"),
            "nodes_count": len(nodes),
            "edges_count": len(result.get("edges", [])),
            "rings_detected": result.get("rings_detected"),
            "suspicious_node_count": result.get("suspicious_node_count"),
            "accounts": [
                {"id": n.get("id"), "name": n.get("name"), "risk": n.get("risk_score"), "hops": n.get("hops"), "type": n.get("entity_type")}
                for n in nodes if n.get("type") == "Account"
            ][:12],
            "shared_infrastructure": [n.get("id") for n in nodes if n.get("type") in ("IPAddress", "Device")][:6],
        }
    elif tool_name == "detect_fraud_communities":
        slim = {
            "algorithm": result.get("algorithm"),
            "likely_fraud_rings": result.get("likely_fraud_rings"),
            "communities": [
                {
                    "community_id": c["community_id"],
                    "verdict": c["verdict"],
                    "score": c["community_risk_score"],
                    "accounts": [f"{a['id']} ({a.get('entity_type') or 'account'})" for a in c["accounts"]][:8],
                    "shared_infrastructure": [i["id"] for i in c["shared_infrastructure"]],
                    "structuring_tx": c["structuring_transactions"],
                    "internal_tx": c["internal_transactions"],
                    "internal_volume": c["internal_volume"],
                }
                for c in result.get("communities", [])[:6]
            ],
        }
    elif tool_name == "get_active_alerts":
        slim = {
            "total_alerts": result.get("total_alerts"),
            "critical_count": result.get("critical_count"),
            "high_count": result.get("high_count"),
            "alerts": [
                {"account": a.get("account_id"), "name": a.get("account_name"), "type": a.get("alert_type"), "severity": a.get("severity")}
                for a in result.get("alerts", [])[:8]
            ],
        }
    elif tool_name == "trace_money_flow":
        slim = {k: result.get(k) for k in (
            "account_id", "total_inflow", "total_outflow", "suspicious_transactions",
            "structuring_detected", "circular_flows_detected", "cycle_lengths",
        )}
        slim["top_inflows"] = result.get("inflows", [])[:3]
        slim["top_outflows"] = result.get("outflows", [])[:3]
    elif tool_name == "find_shared_infrastructure":
        slim = {
            "account_id": result.get("account_id"),
            "total_shared": result.get("total_shared"),
            "suspicious_shared": result.get("suspicious_shared"),
            "shared_accounts": [
                {"id": s.get("account_id"), "name": s.get("account_name"), "suspicious": s.get("is_suspicious"), "via": s.get("infrastructure_type")}
                for s in result.get("shared_accounts", [])
            ][:10],
        }
    elif tool_name == "explain_connection":
        slim = {k: result.get(k) for k in ("source_id", "target_id", "connected", "shortest_length")}
        slim["paths"] = [p["steps"] for p in result.get("paths", [])]
    elif tool_name == "compute_max_flow":
        slim = {k: result.get(k) for k in ("source_id", "target_id", "max_flow", "direct_flow", "indirect_flow", "intermediary_accounts")}
    else:
        slim = {k: v for k, v in result.items() if k not in ("cypher", "nodes", "edges")}

    s = json.dumps({"tool": tool_name, **slim}, default=str)
    return s[:1500] + "..." if len(s) > 1500 else s


async def _run_tool(tool_name: str, raw_args: dict, session_id: str, trace: dict, on_event: EventCallback) -> Any:
    tool_args = await _prepare_args(tool_name, raw_args, session_id)
    visible_args = {k: v for k, v in tool_args.items() if k != SESSION_PARAM}
    if on_event:
        await on_event({"type": "tool_start", "tool": tool_name, "args": visible_args})

    started = time.time()
    result = await dispatch_tool(tool_name, tool_args)
    elapsed_ms = round((time.time() - started) * 1000)

    call = {
        "tool": tool_name,
        "args": visible_args,
        "cypher": result.get("cypher", "") if isinstance(result, dict) else "",
        "ms": elapsed_ms,
    }
    trace["tool_calls"].append(call)
    trace["tool_results"].append(result)
    if on_event:
        await on_event({"type": "tool_result", **call, "result": result})
    return result


# ── Gemini ────────────────────────────────────────────────────────────────────

def _gemini_history(conversation_history: list) -> list:
    return [
        {"role": "model" if m["role"] in ("assistant", "model") else "user", "parts": [m["content"]]}
        for m in _trim_history(conversation_history)
    ]


async def _execute_gemini_agent(model_name: str, gemini_tools, user_message: str, session_id: str,
                                conversation_history: list, on_event: EventCallback) -> dict:
    import google.generativeai as genai
    import google.generativeai.protos as protos

    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=SYSTEM_PROMPT,
        tools=[gemini_tools],
        generation_config={"max_output_tokens": 1024, "temperature": 0.2},
    )
    chat = model.start_chat(history=_gemini_history(conversation_history))

    trace: dict = {"tool_calls": [], "tool_results": []}
    response_text = ""

    if on_event:
        await on_event({"type": "status", "message": f"Thinking ({model_name})…"})
    response = await asyncio.to_thread(chat.send_message, user_message)

    for round_idx in range(MAX_TOOL_ROUNDS + 1):
        function_calls, text_parts = [], []
        for part in response.candidates[0].content.parts:
            if hasattr(part, "function_call") and part.function_call.name:
                function_calls.append(part.function_call)
            elif hasattr(part, "text") and part.text:
                text_parts.append(part.text)

        if not function_calls:
            response_text = " ".join(text_parts)
            break

        is_last_round = (round_idx >= MAX_TOOL_ROUNDS)
        tool_cfg = (
            protos.ToolConfig(function_calling_config=protos.FunctionCallingConfig(mode=protos.FunctionCallingConfig.Mode.NONE))
            if is_last_round else None
        )

        function_responses = []
        for fc in function_calls:
            raw_args = type(fc).to_dict(fc).get("args", {}) or {}
            result = await _run_tool(fc.name, raw_args, session_id, trace, on_event)
            function_responses.append(
                protos.Part(function_response=protos.FunctionResponse(
                    name=fc.name,
                    response={"result": _format_tool_result_for_llm(fc.name, result)},
                ))
            )

        if on_event:
            await on_event({"type": "status", "message": "Reasoning over graph results…"})
        try:
            if tool_cfg:
                response = await asyncio.to_thread(chat.send_message, function_responses, tool_config=tool_cfg)
                parts = [p.text for p in response.candidates[0].content.parts if hasattr(p, "text") and p.text]
                response_text = " ".join(parts)
                break
            else:
                response = await asyncio.to_thread(chat.send_message, function_responses)
        except Exception as e:
            raise PartialRunError(e, trace) from e

    return {"response": response_text, **trace, "session_id": session_id}


async def run_agent_gemini(user_message: str, session_id: str, conversation_history: list,
                           on_event: EventCallback = None) -> dict:
    import google.generativeai as genai
    from google.api_core.exceptions import ResourceExhausted
    from google.generativeai.types import FunctionDeclaration, Tool

    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    gemini_tools = Tool(function_declarations=[
        FunctionDeclaration(name=s["name"], description=s["description"], parameters=s["parameters"])
        for s in await get_tool_specs()
    ])

    requested_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    candidates = [requested_model]
    for fb in ["gemini-3.5-flash", "gemini-3.7-flash", "gemini-3.8-flash", "gemini-2.5-flash"]:
        if fb not in candidates:
            candidates.append(fb)

    last_error: Exception | None = None
    prior: dict = {"tool_calls": [], "tool_results": []}
    message = user_message
    for model_name in candidates:
        try:
            result = await _execute_gemini_agent(model_name, gemini_tools, message, session_id, conversation_history, on_event)
            result["tool_calls"] = prior["tool_calls"] + result["tool_calls"]
            result["tool_results"] = prior["tool_results"] + result["tool_results"]
            return result
        except PartialRunError as e:
            prior["tool_calls"] += e.trace["tool_calls"]
            prior["tool_results"] += e.trace["tool_results"]
            if not isinstance(e.__cause__, ResourceExhausted):
                raise PartialRunError(e.__cause__ or e, prior) from e
            print(f"[WARN] Gemini model {model_name} quota exhausted mid-run. Handing off...")
            message = _handoff_message(user_message, prior)
            last_error = e
        except ResourceExhausted as e:
            print(f"[WARN] Gemini model {model_name} quota exhausted. Trying fallback...")
            last_error = e
    if prior["tool_calls"]:
        raise PartialRunError(last_error or RuntimeError("Gemini unavailable"), prior)
    raise last_error or RuntimeError("No Gemini model available")


# ── Groq ──────────────────────────────────────────────────────────────────────

RATE_LIMIT_COOLDOWN = 60
_groq_cooldown: dict[str, float] = {}


def _groq_models() -> list[str]:
    requested = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    models = [requested]
    for m in ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]:
        if m not in models:
            models.append(m)
    return models


def _groq_complete(client, messages: list, tool_schemas: list, allow_tools: bool):
    """One chat completion, falling over to the next model only for this call."""
    from groq import RateLimitError, APIStatusError

    last_error = None
    now = time.time()
    models = [m for m in _groq_models() if _groq_cooldown.get(m, 0) <= now] or _groq_models()
    for model_name in models:
        try:
            started = time.time()
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                tools=tool_schemas,
                tool_choice="auto" if allow_tools else "none",
                max_tokens=1024,
                temperature=0.2,
            )
            print(f"[LLM] {model_name} {time.time() - started:.1f}s tools={'on' if allow_tools else 'off'}")
            return response
        except RateLimitError as e:
            print(f"[WARN] Groq {model_name} rate limited; cooling down {RATE_LIMIT_COOLDOWN}s")
            _groq_cooldown[model_name] = time.time() + RATE_LIMIT_COOLDOWN
            last_error = e
        except APIStatusError as e:
            print(f"[WARN] Groq {model_name} failed ({e.status_code}): {e}")
            last_error = e
    raise last_error or RuntimeError("No Groq model available")


async def run_agent_groq(user_message: str, session_id: str, conversation_history: list,
                         on_event: EventCallback = None) -> dict:
    from groq import Groq

    # Retries are handled by switching models in _groq_complete, not by the SDK sleeping on 429s.
    client = Groq(api_key=os.getenv("GROQ_API_KEY"), max_retries=0, timeout=45)
    tool_schemas = [{"type": "function", "function": s} for s in await get_tool_specs()]

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in _trim_history(conversation_history):
        role = "assistant" if m["role"] in ("assistant", "model") else "user"
        messages.append({"role": role, "content": m["content"]})
    messages.append({"role": "user", "content": user_message})

    trace: dict = {"tool_calls": [], "tool_results": []}
    response_text = ""
    interim_text: list[str] = []

    for round_idx in range(MAX_TOOL_ROUNDS + 1):
        allow_tools = round_idx < MAX_TOOL_ROUNDS
        if on_event:
            await on_event({"type": "status", "message": "Thinking…" if round_idx == 0 else "Reasoning over graph results…"})
        try:
            response = await asyncio.to_thread(_groq_complete, client, messages, tool_schemas, allow_tools)
        except Exception as e:
            if trace["tool_calls"]:
                raise PartialRunError(e, trace) from e
            raise
        msg = response.choices[0].message

        if not msg.tool_calls:
            response_text = _strip_think(msg.content)
            break

        if _strip_think(msg.content):
            interim_text.append(_strip_think(msg.content))

        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        })

        for tc in msg.tool_calls:
            try:
                raw_args = json.loads(tc.function.arguments or "{}")
            except Exception:
                raw_args = {}
            result = await _run_tool(tc.function.name, raw_args, session_id, trace, on_event)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": _format_tool_result_for_llm(tc.function.name, result),
            })

    if interim_text and len(response_text) < 300:
        response_text = "\n\n".join(interim_text + [response_text]).strip()

    return {"response": response_text, **trace, "session_id": session_id}


# ── Entry point ───────────────────────────────────────────────────────────────

def _auto_save_memory(user_message: str, session_id: str, result: dict) -> None:
    graph_calls = [c for c in result.get("tool_calls", []) if c["tool"] not in MEMORY_TOOLS]
    if not graph_calls or not result.get("response"):
        return
    account_id = next((c["args"].get("account_id") for c in graph_calls if c["args"].get("account_id")), None)
    summary = re.sub(r"[#*|`]", "", result["response"])
    summary = " ".join(summary.split())[:400]
    try:
        graph_tools.save_investigation_memory(
            session_id=session_id,
            finding=f"Q: {user_message[:150]} → {summary}",
            account_id=account_id,
            tags=sorted({c["tool"] for c in graph_calls}),
        )
    except Exception as e:
        print(f"[WARN] auto-save memory failed: {e}")


class PartialRunError(Exception):
    """Provider failed mid-investigation; carries the tool work already done."""

    def __init__(self, cause: Exception, trace: dict):
        super().__init__(str(cause))
        self.trace = trace


def _handoff_message(user_message: str, trace: dict) -> str:
    gathered = "\n".join(
        _format_tool_result_for_llm(c["tool"], r) for c, r in zip(trace["tool_calls"], trace["tool_results"])
    )
    return (
        f"{user_message}\n\n[These graph tools were already run for this question — "
        f"do not run them again, build on them]\n{gathered}"
    )


async def _run_with_fallback(user_message: str, session_id: str, conversation_history: list,
                             on_event: EventCallback) -> dict:
    groq_first = os.getenv("LLM_PROVIDER", "groq").lower() == "groq"
    primary, secondary = (run_agent_groq, run_agent_gemini) if groq_first else (run_agent_gemini, run_agent_groq)
    secondary_key = "GEMINI_API_KEY" if groq_first else "GROQ_API_KEY"

    done: dict = {"tool_calls": [], "tool_results": []}
    try:
        return await primary(user_message, session_id, conversation_history, on_event)
    except Exception as e:
        print(f"[WARN] {primary.__name__} failed: {e}. Falling back...")
        if isinstance(e, PartialRunError):
            done = e.trace
        if not os.getenv(secondary_key):
            if done["tool_calls"]:
                return _answer_without_llm(done, session_id)
            raise

    message = _handoff_message(user_message, done) if done["tool_calls"] else user_message
    try:
        result = await secondary(message, session_id, conversation_history, on_event)
    except Exception as e:
        print(f"[WARN] {secondary.__name__} failed too: {e}")
        if isinstance(e, PartialRunError):
            done = {k: done[k] + e.trace[k] for k in done}
        if done["tool_calls"]:
            return _answer_without_llm(done, session_id)
        raise
    result["tool_calls"] = done["tool_calls"] + result["tool_calls"]
    result["tool_results"] = done["tool_results"] + result["tool_results"]
    return result


def _answer_without_llm(trace: dict, session_id: str) -> dict:
    """All LLM providers are rate-limited: still return what the graph found."""
    lines = [
        "**⚠️ LLM rate limit reached — showing the raw graph findings gathered so far.** "
        "Expand the tool cards above for full results and Cypher.",
        "",
    ]
    for call, result in zip(trace["tool_calls"], trace["tool_results"]):
        if not isinstance(result, dict) or "error" in result:
            continue
        try:
            summary = json.loads(_format_tool_result_for_llm(call["tool"], result))
        except ValueError:
            summary = {}
        facts = ", ".join(
            f"{k}: {v}" for k, v in summary.items()
            if k != "tool" and not isinstance(v, (list, dict)) and v not in (None, "")
        )
        lines.append(f"- **{call['tool']}**({', '.join(f'{k}={v}' for k, v in call['args'].items())}) → {facts or 'see card'}")
    return {"response": "\n".join(lines), **trace, "session_id": session_id}


async def run_agent(user_message: str, session_id: str, conversation_history: list,
                    on_event: EventCallback = None) -> dict:
    """Route to the configured LLM provider with automatic cross-provider fallback."""
    started = time.time()
    result = await _run_with_fallback(user_message, session_id, conversation_history, on_event)
    result["elapsed_ms"] = round((time.time() - started) * 1000)
    await asyncio.to_thread(_auto_save_memory, user_message, session_id, result)
    return result
