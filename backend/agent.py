"""
FraudScope AI Agent — Gemini / Groq powered investigative agent.

The agent uses function calling (MCP-style tool selection) to choose
which graph tools to invoke. It maintains session memory in FalkorDB.
"""

import os
import sys
import json
from typing import Any
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

load_dotenv(override=True)

import tools as graph_tools

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()

# ── LLM setup ────────────────────────────────────────────────────────────────

def _setup_gemini():
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    return genai


def _setup_groq():
    from groq import Groq
    return Groq(api_key=os.getenv("GROQ_API_KEY"))


# ── Tool schema for function calling ─────────────────────────────────────────

TOOL_SCHEMAS_GEMINI = [
    {
        "name": "find_fraud_rings",
        "description": "Detect fraud rings in the graph. Provide an account_id to investigate a specific account's ring, or omit account_id to find ALL fraud rings across the graph.",
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "The Account ID to investigate (optional; omit to detect all fraud rings)"},
                "max_hops": {"type": "integer", "description": "Max traversal depth (1-4)"},
            },
        },
    },
    {
        "name": "trace_money_flow",
        "description": "Follow transaction chains from an account to detect layering, structuring (<$10k transactions), and circular money flows.",
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "The Account ID to trace"},
            },
            "required": ["account_id"],
        },
    },
    {
        "name": "compute_risk_score",
        "description": "Compute a composite risk score for an account using graph-propagated signals: base risk, neighbor risk, shared infrastructure, and alerts.",
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "The Account ID to score"},
            },
            "required": ["account_id"],
        },
    },
    {
        "name": "find_shared_infrastructure",
        "description": "Find other accounts that share the same IP addresses or device fingerprints as the target account.",
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "The Account ID to check"},
            },
            "required": ["account_id"],
        },
    },
    {
        "name": "get_active_alerts",
        "description": "Retrieve all unresolved HIGH and CRITICAL fraud alerts currently in the graph.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max alerts to return"},
            },
        },
    },
    {
        "name": "save_investigation_memory",
        "description": "Save an important finding to the session memory graph so it can be recalled later.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Current session ID"},
                "finding": {"type": "string", "description": "The finding or insight to save"},
                "account_id": {"type": "string", "description": "Related account ID (optional)"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags like ['fraud', 'ring_0']"},
            },
            "required": ["session_id", "finding"],
        },
    },
    {
        "name": "recall_investigation_memory",
        "description": "Recall past investigation findings from the session memory graph.",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Current session ID"},
                "account_id": {"type": "string", "description": "Filter by account ID (optional)"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "search_accounts",
        "description": "Search for accounts by name or ID substring.",
        "parameters": {
            "type": "object",
            "properties": {
                "query_str": {"type": "string", "description": "Name or ID to search for"},
            },
            "required": ["query_str"],
        },
    },
    {
        "name": "get_graph_overview",
        "description": "Get high-level statistics about the fraud graph: node counts, suspicious accounts, open alerts, transaction volume.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
]

TOOL_SCHEMAS_GROQ = [
    {
        "type": "function",
        "function": {
            "name": s["name"],
            "description": s["description"],
            "parameters": s["parameters"],
        },
    }
    for s in TOOL_SCHEMAS_GEMINI
]

# ── Tool dispatcher ───────────────────────────────────────────────────────────

TOOL_MAP = {
    "find_fraud_rings": graph_tools.find_fraud_rings,
    "trace_money_flow": graph_tools.trace_money_flow,
    "compute_risk_score": graph_tools.compute_risk_score,
    "find_shared_infrastructure": graph_tools.find_shared_infrastructure,
    "get_active_alerts": graph_tools.get_active_alerts,
    "save_investigation_memory": graph_tools.save_investigation_memory,
    "recall_investigation_memory": graph_tools.recall_investigation_memory,
    "search_accounts": graph_tools.search_accounts,
    "get_graph_overview": graph_tools.get_graph_overview,
}


def dispatch_tool(name: str, args: dict) -> Any:
    func = TOOL_MAP.get(name)
    if not func:
        return {"error": f"Unknown tool: {name}"}
    try:
        return func(**args)
    except Exception as e:
        return {"error": str(e), "tool": name}


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are FraudScope AI, an expert financial crime investigator powered by a FalkorDB knowledge graph.

Your job is to investigate financial fraud by querying a graph database that stores accounts, transactions, entities, IPs, devices, and alert events as interconnected nodes and edges.

## Your Capabilities (Tools)
You have 9 graph tools you can call:
1. **find_fraud_rings** - Multi-hop traversal to find hidden fraud networks
2. **trace_money_flow** - Follow transaction chains to detect layering/structuring
3. **compute_risk_score** - Graph-propagated composite risk scoring
4. **find_shared_infrastructure** - Find accounts sharing IPs/devices (fraud signal)
5. **get_active_alerts** - See all current HIGH/CRITICAL alerts
6. **save_investigation_memory** - Persist findings to your memory graph
7. **recall_investigation_memory** - Recall past findings from memory
8. **search_accounts** - Search for accounts by name/ID
9. **get_graph_overview** - Get graph statistics to orient your investigation

## Investigation Approach
- Call the most relevant tool directly to answer the user's request quickly and accurately.
- Only call get_graph_overview if the user asked for a general overview or if context is missing.
- Avoid redundant sequential tool queries when one or two tools suffice.
- Look for: structuring (amounts just under $10k), circular flows, shared IPs/devices.
- Save key findings to memory when notable insights are discovered.
- Explain the Cypher queries you used and what the findings mean.

Keep responses concise, clear, and structured with markdown.
"""


# ── Main agent loop ───────────────────────────────────────────────────────────

async def _execute_gemini_agent(model_name: str, gemini_tools, user_message: str, session_id: str, conversation_history: list) -> dict:
    import google.generativeai as genai
    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=SYSTEM_PROMPT,
        tools=[gemini_tools],
    )

    # Build conversation
    history = []
    for msg in conversation_history:
        history.append({"role": msg["role"], "parts": [msg["content"]]})

    chat = model.start_chat(history=history)

    tool_calls_made = []
    tool_results = []
    response_text = ""

    # Initial message
    response = chat.send_message(user_message)

    max_iterations = 8
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        candidate = response.candidates[0]

        # Check for function calls
        function_calls = []
        text_parts = []

        for part in candidate.content.parts:
            if hasattr(part, "function_call") and part.function_call.name:
                function_calls.append(part.function_call)
            elif hasattr(part, "text") and part.text:
                text_parts.append(part.text)

        if not function_calls:
            # No more tool calls - final response
            response_text = " ".join(text_parts)
            break

        # Execute all tool calls
        function_responses = []
        for fc in function_calls:
            tool_name = fc.name
            tool_args = {}
            for k, v in fc.args.items():
                if isinstance(v, float) and v.is_integer():
                    tool_args[k] = int(v)
                else:
                    tool_args[k] = v

            # Inject session_id for memory tools
            if "session_id" in TOOL_SCHEMAS_GEMINI[
                next(i for i, s in enumerate(TOOL_SCHEMAS_GEMINI) if s["name"] == tool_name)
            ]["parameters"].get("properties", {}):
                if "session_id" not in tool_args:
                    tool_args["session_id"] = session_id

            result = dispatch_tool(tool_name, tool_args)

            tool_calls_made.append({
                "tool": tool_name,
                "args": tool_args,
                "cypher": result.get("cypher", ""),
            })
            tool_results.append(result)

            import google.generativeai.protos as protos
            function_responses.append(
                protos.Part(
                    function_response=protos.FunctionResponse(
                        name=tool_name,
                        response={"result": json.dumps(result, default=str)},
                    )
                )
            )

        # Send results back to model
        response = chat.send_message(function_responses)

    return {
        "response": response_text,
        "tool_calls": tool_calls_made,
        "tool_results": tool_results,
        "session_id": session_id,
    }


async def run_agent_gemini(user_message: str, session_id: str, conversation_history: list) -> dict:
    import google.generativeai as genai
    from google.api_core.exceptions import ResourceExhausted
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

    from google.generativeai.types import FunctionDeclaration, Tool

    # Build Gemini tool declarations
    tool_declarations = []
    for schema in TOOL_SCHEMAS_GEMINI:
        tool_declarations.append(
            FunctionDeclaration(
                name=schema["name"],
                description=schema["description"],
                parameters=schema["parameters"],
            )
        )
    gemini_tools = Tool(function_declarations=tool_declarations)

    requested_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    candidates = [requested_model]
    for fb in ["gemini-3.5-flash", "gemini-3.7-flash", "gemini-3.8-flash"]:
        if fb not in candidates:
            candidates.append(fb)

    last_error = None
    for model_name in candidates:
        try:
            return await _execute_gemini_agent(model_name, gemini_tools, user_message, session_id, conversation_history)
        except ResourceExhausted as e:
            print(f"[WARN] Gemini model {model_name} quota exhausted. Trying fallback...")
            last_error = e
            continue

    if last_error:
        raise last_error


def _format_tool_result_for_llm(tool_name: str, result: Any) -> str:
    if not isinstance(result, dict):
        s = str(result)
        return s[:500] + "..." if len(s) > 500 else s

    if tool_name == "find_fraud_rings":
        nodes = result.get("nodes", [])
        return json.dumps({
            "tool": "find_fraud_rings",
            "account_id": result.get("account_id"),
            "nodes_count": len(nodes),
            "edges_count": len(result.get("edges", [])),
            "accounts_in_ring": [n.get("id") for n in nodes if n.get("type") == "Account"][:8],
            "cypher": result.get("cypher", "")
        })
    elif tool_name == "get_active_alerts":
        alerts = result.get("alerts", [])[:6]
        return json.dumps({
            "tool": "get_active_alerts",
            "total_alerts": result.get("total_alerts", len(alerts)),
            "alerts": [
                {"account": a.get("account_id"), "name": a.get("account_name"), "type": a.get("alert_type"), "severity": a.get("severity")}
                for a in alerts
            ],
            "cypher": result.get("cypher", "")
        })
    elif tool_name == "trace_money_flow":
        return json.dumps({
            "tool": "trace_money_flow",
            "account_id": result.get("account_id"),
            "total_inflow": result.get("total_inflow"),
            "total_outflow": result.get("total_outflow"),
            "potential_structuring": result.get("potential_structuring"),
            "sample_inflows": result.get("inflows", [])[:3],
            "sample_outflows": result.get("outflows", [])[:3],
            "cypher": result.get("cypher", "")
        })

    s = json.dumps(result, default=str)
    return s[:600] + "..." if len(s) > 600 else s


async def _execute_groq_agent(model_name: str, user_message: str, session_id: str, conversation_history: list) -> dict:
    from groq import Groq
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in conversation_history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    tool_calls_made = []
    tool_results = []
    response_text = ""

    max_iterations = 4
    iteration = 0

    while iteration < max_iterations:
        iteration += 1

        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=TOOL_SCHEMAS_GROQ,
            tool_choice="auto",
            max_tokens=800,
        )

        msg = response.choices[0].message

        if not msg.tool_calls:
            response_text = msg.content or ""
            break

        messages.append(msg)

        for tc in msg.tool_calls:
            tool_name = tc.function.name
            try:
                tool_args = json.loads(tc.function.arguments)
            except Exception:
                tool_args = {}

            # Inject session_id for memory tools
            if tool_name in ("save_investigation_memory", "recall_investigation_memory"):
                if "session_id" not in tool_args:
                    tool_args["session_id"] = session_id

            result = dispatch_tool(tool_name, tool_args)

            tool_calls_made.append({
                "tool": tool_name,
                "args": tool_args,
                "cypher": result.get("cypher", ""),
            })
            tool_results.append(result)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": _format_tool_result_for_llm(tool_name, result),
            })

    return {
        "response": response_text,
        "tool_calls": tool_calls_made,
        "tool_results": tool_results,
        "session_id": session_id,
    }


async def run_agent_groq(user_message: str, session_id: str, conversation_history: list) -> dict:
    requested_model = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
    candidates = [requested_model]
    for m in ["qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]:
        if m not in candidates:
            candidates.append(m)

    last_error = None
    for model_name in candidates:
        try:
            return await _execute_groq_agent(model_name, user_message, session_id, conversation_history)
        except Exception as e:
            print(f"[WARN] Groq model {model_name} failed: {e}. Trying fallback...")
            last_error = e
            continue

    if last_error:
        raise last_error


async def run_agent(user_message: str, session_id: str, conversation_history: list) -> dict:
    """Route to the configured LLM provider with automatic cross-provider fallback."""
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    
    if provider == "groq":
        try:
            return await run_agent_groq(user_message, session_id, conversation_history)
        except Exception as e:
            print(f"[WARN] Groq failed: {e}. Falling back to Gemini...")
            if os.getenv("GEMINI_API_KEY"):
                return await run_agent_gemini(user_message, session_id, conversation_history)
            raise e
    else:
        try:
            return await run_agent_gemini(user_message, session_id, conversation_history)
        except Exception as e:
            print(f"[WARN] Gemini failed: {e}. Falling back to Groq...")
            if os.getenv("GROQ_API_KEY"):
                return await run_agent_groq(user_message, session_id, conversation_history)
            raise e
