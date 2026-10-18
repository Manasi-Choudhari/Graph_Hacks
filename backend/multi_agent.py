"""
FraudScope AI — Agent Architectures
Two modes of operation:

  Single-Agent: One unified investigator with access to ALL tools. Autonomously performs
  rapid triage, deep forensic graph queries (WCC, max flow, betweenness, SPpaths), and
  compliance summarization (FinCEN SAR narrative + action proposals) in one streamlined pass.

  Multi-Agent Swarm: Coordinates 3 specialist agents in sequence —
    1. Triage Specialist: Rapid alert prioritization, anomaly filtering, risk triage.
    2. Forensics Specialist: Deep multi-hop graph traversal, centrality, max flow, ring detection.
    3. Compliance Officer: Regulatory evaluation, FinCEN SAR drafting, action proposals.
"""

import time
import asyncio
from typing import Any, Awaitable, Callable
from agent import (
    EventCallback,
    _format_tool_result_for_llm,
    _run_tool,
    _trim_history,
    _gemini_history,
    _clean_schema,
    _prepare_args,
    _groq_complete,
    _auto_save_memory,
    PartialRunError,
    MAX_TOOL_ROUNDS,
    SYSTEM_PROMPT,
)
from mcp_server import mcp

# ── Role Definitions & Specialized System Prompts ─────────────────────────────

AGENT_ROLES = {
    "triage": {
        "title": "Triage Specialist",
        "badge": "🛡️ Triage",
        "color": "var(--accent-cyan)",
        "description": "Rapid alert prioritization, anomaly filtering, and initial threat triage.",
        "tools": {
            "get_active_alerts",
            "compute_risk_score",
            "find_shared_infrastructure",
            "search_accounts",
            "get_graph_overview",
        },
    },
    "forensics": {
        "title": "Graph Forensics Specialist",
        "badge": "🔬 Forensics",
        "color": "var(--accent-primary)",
        "description": "Deep multi-hop graph traversal, WCC community detection, max flow, and evidence paths.",
        "tools": {
            "detect_fraud_communities",
            "find_fraud_rings",
            "trace_money_flow",
            "compute_max_flow",
            "rank_key_accounts",
            "explain_connection",
            "compute_risk_score",
        },
    },
    "compliance": {
        "title": "AML Compliance Officer",
        "badge": "📋 Compliance",
        "color": "var(--accent-purple)",
        "description": "Regulatory filings, FinCEN SAR narrative drafting, and action proposals.",
        "tools": {
            "propose_action",
            "list_actions",
            "save_investigation_memory",
            "recall_investigation_memory",
            "compute_risk_score",
        },
    },
}

TRIAGE_PROMPT = """You are the Triage Specialist for FraudScope AI.
Your role:
- Conduct the first line of defense assessment on alerts, suspect accounts, and new entities.
- Filter false alarms vs urgent threats. Check active alerts, composite risk scores, and immediate shared infrastructure.
- Categorize account threat level (CRITICAL, HIGH, MEDIUM, LOW) and urgency.
- Determine whether a full forensic graph traversal is recommended.
- Keep your verdict crisp, factual, and concise. Do NOT jump into proposing final actions yet; flag the key signals for the Forensics team.
"""

FORENSICS_PROMPT = """You are the Graph Forensics Specialist for FraudScope AI.
Your role:
- Conduct deep mathematical and topological graph analysis using FalkorDB procedures.
- Detect fraud rings using Weakly Connected Components (algo.WCC) and multi-hop Cypher traversals (1-4 hops).
- Quantify layering volume using max flow (algo.maxFlow) and identify critical broker accounts (algo.betweenness, algo.pageRank).
- Uncover shortest evidence paths between suspects (algo.SPpaths).
- Focus on concrete graph metrics: exact dollar amounts, intermediary hop counts, structuring patterns ($9,000–$9,999), and shared digital fingerprints.
- Provide objective forensic proof for the Compliance team.
"""

COMPLIANCE_PROMPT = """You are the AML/CFT Compliance Officer for FraudScope AI.
Your role:
- Review forensic graph findings and assess legal/regulatory obligations (BSA, FinCEN 31 CFR § 1020.320, FATF red flags).
- Draft a formal, audit-ready Suspicious Activity Report (SAR) narrative citing:
  1. Primary Subject(s) and role (shell company, money mule, cash-out desk).
  2. Transaction Summary (amounts, frequency, structuring indicators, flow direction).
  3. Graph Evidence (corroborating IP/device links, community clusters, layering chains).
- PROPOSE concrete actions using `propose_action` (e.g. freeze_account, open_case, file_sar, escalate_alert, or clear_account).
- Note that all proposed actions remain PENDING_APPROVAL until reviewed by a human analyst.
"""


# ── Scoped Tool Retrieval ─────────────────────────────────────────────────────

async def get_scoped_tool_specs(allowed_tool_names: set[str] | None = None) -> list[dict]:
    """Retrieve MCP tool specifications filtered to an agent's allowed permissions."""
    specs = []
    for tool in await mcp.list_tools():
        if allowed_tool_names and tool.name not in allowed_tool_names:
            continue
        params = _clean_schema(tool.input_schema)
        params.setdefault("type", "object")
        params.setdefault("properties", {})
        params["properties"].pop("session_id", None)
        if "session_id" in params.get("required", []):
            params["required"] = [r for r in params["required"] if r != "session_id"]
        if not params.get("required"):
            params.pop("required", None)
        specs.append({"name": tool.name, "description": tool.description or "", "parameters": params})
    return specs


# ── Single Specialist Execution ───────────────────────────────────────────────

async def run_specialist_agent(
    role: str,
    user_message: str,
    session_id: str,
    conversation_history: list,
    on_event: EventCallback = None,
) -> dict:
    """Execute a specific specialist agent (triage, forensics, compliance) with role-scoped prompt and tools."""
    role_info = AGENT_ROLES.get(role, AGENT_ROLES["forensics"])
    prompt = (
        TRIAGE_PROMPT if role == "triage"
        else FORENSICS_PROMPT if role == "forensics"
        else COMPLIANCE_PROMPT if role == "compliance"
        else SYSTEM_PROMPT
    )

    scoped_tools = await get_scoped_tool_specs(role_info["tools"])

    if on_event:
        await on_event({
            "type": "agent_start",
            "role": role,
            "title": role_info["title"],
            "badge": role_info["badge"],
            "color": role_info["color"],
        })

    # Execute using provider fallback with scoped tools & role prompt
    import os
    groq_first = os.getenv("LLM_PROVIDER", "groq").lower() == "groq"

    if groq_first:
        try:
            return await _run_specialist_groq(role_info, prompt, scoped_tools, user_message, session_id, conversation_history, on_event)
        except Exception as e:
            print(f"[WARN] Specialist {role} (Groq) failed: {e}. Fallback to Gemini...")
            return await _run_specialist_gemini(role_info, prompt, scoped_tools, user_message, session_id, conversation_history, on_event)
    else:
        try:
            return await _run_specialist_gemini(role_info, prompt, scoped_tools, user_message, session_id, conversation_history, on_event)
        except Exception as e:
            print(f"[WARN] Specialist {role} (Gemini) failed: {e}. Fallback to Groq...")
            return await _run_specialist_groq(role_info, prompt, scoped_tools, user_message, session_id, conversation_history, on_event)


async def _run_specialist_gemini(role_info, prompt, scoped_tools, user_message, session_id, conversation_history, on_event, max_rounds: int = MAX_TOOL_ROUNDS):
    import google.generativeai as genai
    from google.generativeai.types import FunctionDeclaration, Tool
    import google.generativeai.protos as protos
    import os

    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    gemini_tools = Tool(function_declarations=[
        FunctionDeclaration(name=s["name"], description=s["description"], parameters=s["parameters"])
        for s in scoped_tools
    ])

    requested_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    candidates = [requested_model]
    for fb in ["gemini-3.5-flash", "gemini-3.7-flash", "gemini-3.8-flash", "gemini-2.5-flash"]:
        if fb not in candidates:
            candidates.append(fb)

    last_err = None
    for model_name in candidates:
        try:
            model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction=prompt,
                tools=[gemini_tools],
                generation_config={"max_output_tokens": 1024, "temperature": 0.2},
            )
            chat = model.start_chat(history=_gemini_history(conversation_history))
            trace: dict = {"tool_calls": [], "tool_results": []}
            response_text = ""

            if on_event:
                await on_event({"type": "status", "message": f"{role_info['title']} is analyzing…", "role": role_info["title"]})

            response = await asyncio.to_thread(chat.send_message, user_message)

            for round_idx in range(max_rounds + 1):
                function_calls, text_parts = [], []
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "function_call") and part.function_call.name:
                        function_calls.append(part.function_call)
                    elif hasattr(part, "text") and part.text:
                        text_parts.append(part.text)

                if not function_calls:
                    response_text = " ".join(text_parts)
                    break

                is_last_round = (round_idx >= max_rounds)
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
                    await on_event({"type": "status", "message": f"{role_info['title']} is evaluating graph findings…", "role": role_info["title"]})

                if tool_cfg:
                    response = await asyncio.to_thread(chat.send_message, function_responses, tool_config=tool_cfg)
                    parts = [p.text for p in response.candidates[0].content.parts if hasattr(p, "text") and p.text]
                    response_text = " ".join(parts)
                    break
                else:
                    response = await asyncio.to_thread(chat.send_message, function_responses)

            return {
                "response": response_text,
                "role": role_info["title"],
                "badge": role_info["badge"],
                **trace,
                "session_id": session_id,
            }
        except Exception as e:
            print(f"[WARN] Specialist {role_info.get('title')} with Gemini model {model_name} failed: {e}")
            last_err = e
            continue

    raise last_err or RuntimeError("All Gemini model candidates failed")


async def _run_specialist_groq(role_info, prompt, scoped_tools, user_message, session_id, conversation_history, on_event, max_rounds: int = MAX_TOOL_ROUNDS):
    from groq import Groq
    import os

    client = Groq(api_key=os.getenv("GROQ_API_KEY"), max_retries=0, timeout=45)
    tool_schemas = [{"type": "function", "function": s} for s in scoped_tools]

    messages: list[dict] = [{"role": "system", "content": prompt}]
    for m in _trim_history(conversation_history):
        role = "assistant" if m["role"] in ("assistant", "model") else "user"
        messages.append({"role": role, "content": m["content"]})
    messages.append({"role": "user", "content": user_message})

    trace: dict = {"tool_calls": [], "tool_results": []}
    response_text = ""

    for round_idx in range(max_rounds + 1):
        allow_tools = round_idx < max_rounds
        if on_event:
            await on_event({"type": "status", "message": f"{role_info['title']} reasoning…", "role": role_info["title"]})

        completion = await asyncio.to_thread(_groq_complete, client, messages, tool_schemas, allow_tools)
        choice = completion.choices[0]
        msg = choice.message
        messages.append(msg)

        if msg.content:
            response_text = msg.content

        if not msg.tool_calls:
            break

        for tc in msg.tool_calls:
            import json
            try:
                raw_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except Exception:
                raw_args = {}
            result = await _run_tool(tc.function.name, raw_args, session_id, trace, on_event)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": _format_tool_result_for_llm(tc.function.name, result),
            })

    return {
        "response": response_text,
        "role": role_info["title"],
        "badge": role_info["badge"],
        **trace,
        "session_id": session_id,
    }


# ── Collaborative Multi-Agent Swarm ──────────────────────────────────────────

async def run_collaborative_swarm(
    user_query: str,
    session_id: str,
    conversation_history: list,
    on_event: EventCallback = None,
) -> dict:
    """
    Run an autonomous 3-stage multi-agent investigation pipeline:
      Stage 1 (Triage): Rapid risk assessment & priority filtering.
      Stage 2 (Forensics): Deep graph traversal, clustering, structuring, max flow.
      Stage 3 (Compliance): FinCEN SAR narrative drafting and action proposals.
    """
    started = time.time()
    all_tool_calls = []
    all_tool_results = []
    swarm_stages = []

    # ── Stage 1: Triage
    if on_event:
        await on_event({
            "type": "swarm_stage_start",
            "stage": 1,
            "total_stages": 3,
            "role": "triage",
            "title": "Stage 1: Triage & Initial Threat Assessment",
            "message": "Triage Specialist is scanning alerts, base risk scores, and digital infrastructure…",
        })

    triage_input = f"Initial Triage Request: {user_query}. Check alerts, risk scores, and immediate infrastructure."
    triage_result = await run_specialist_agent("triage", triage_input, session_id, conversation_history, on_event)
    all_tool_calls.extend(triage_result.get("tool_calls", []))
    all_tool_results.extend(triage_result.get("tool_results", []))
    swarm_stages.append({
        "stage": 1,
        "role": "triage",
        "title": "Triage Specialist",
        "summary": triage_result.get("response", ""),
        "tools_used": [c["tool"] for c in triage_result.get("tool_calls", [])],
    })

    # ── Stage 2: Forensics
    if on_event:
        await on_event({
            "type": "swarm_stage_start",
            "stage": 2,
            "total_stages": 3,
            "role": "forensics",
            "title": "Stage 2: Deep Graph Forensics & Network Analysis",
            "message": "Forensics Specialist is traversing graph paths, running WCC clustering, and computing max flow…",
        })

    forensics_input = (
        f"Forensic Investigation for query: '{user_query}'\n\n"
        f"[Findings from Triage Specialist]:\n{triage_result.get('response', '')}\n\n"
        f"Perform deep graph forensics: trace money flows, check structuring, detect ring clusters, and quantify layering volume."
    )
    forensics_result = await run_specialist_agent("forensics", forensics_input, session_id, conversation_history, on_event)
    all_tool_calls.extend(forensics_result.get("tool_calls", []))
    all_tool_results.extend(forensics_result.get("tool_results", []))
    swarm_stages.append({
        "stage": 2,
        "role": "forensics",
        "title": "Graph Forensics Specialist",
        "summary": forensics_result.get("response", ""),
        "tools_used": [c["tool"] for c in forensics_result.get("tool_calls", [])],
    })

    # ── Stage 3: Compliance & Action Proposal
    if on_event:
        await on_event({
            "type": "swarm_stage_start",
            "stage": 3,
            "total_stages": 3,
            "role": "compliance",
            "title": "Stage 3: AML Compliance & Regulatory Action Proposal",
            "message": "Compliance Officer is evaluating BSA/FinCEN standards, drafting SAR narrative, and proposing actions…",
        })

    compliance_input = (
        f"Compliance Review for: '{user_query}'\n\n"
        f"[Triage Findings]:\n{triage_result.get('response', '')}\n\n"
        f"[Forensics Proof]:\n{forensics_result.get('response', '')}\n\n"
        f"Draft a formal SAR narrative citing specific accounts, structuring amounts, and evidence paths. "
        f"Propose appropriate actions (freeze_account, open_case, file_sar) with exact justifications."
    )
    compliance_result = await run_specialist_agent("compliance", compliance_input, session_id, conversation_history, on_event)
    all_tool_calls.extend(compliance_result.get("tool_calls", []))
    all_tool_results.extend(compliance_result.get("tool_results", []))
    swarm_stages.append({
        "stage": 3,
        "role": "compliance",
        "title": "AML Compliance Officer",
        "summary": compliance_result.get("response", ""),
        "tools_used": [c["tool"] for c in compliance_result.get("tool_calls", [])],
    })

    elapsed_ms = round((time.time() - started) * 1000)

    # Compile the final Multi-Agent Report
    compiled_report = (
        f"### 🛡️ Multi-Agent Investigation Report\n\n"
        f"**Target Inquiry**: *{user_query}*\n\n"
        f"----\n\n"
        f"#### 1. 🛡️ Triage Assessment (Triage Specialist)\n"
        f"{triage_result.get('response', '')}\n\n"
        f"----\n\n"
        f"#### 2. 🔬 Graph Forensic Evidence (Forensics Specialist)\n"
        f"{forensics_result.get('response', '')}\n\n"
        f"----\n\n"
        f"#### 3. 📋 Regulatory Action & SAR Narrative (Compliance Officer)\n"
        f"{compliance_result.get('response', '')}\n"
    )

    final_result = {
        "response": compiled_report,
        "is_swarm": True,
        "stages": swarm_stages,
        "tool_calls": all_tool_calls,
        "tool_results": all_tool_results,
        "elapsed_ms": elapsed_ms,
        "session_id": session_id,
    }

    await asyncio.to_thread(_auto_save_memory, user_query, session_id, final_result)
    return final_result


# ── Single-Agent Architecture ─────────────────────────────────────────────────

SINGLE_AGENT_PROMPT = """You are FraudScope AI — a unified financial crime investigator with full access to all tools.

You operate in a structured 3-phase investigation pipeline. Work through each phase systematically:

━━━ PHASE 1: TRIAGE ━━━
- Check active alerts and compute composite risk scores for the account(s) in question.
- Identify urgency level (CRITICAL / HIGH / MEDIUM / LOW).
- Detect shared IPs/devices that signal coordinated fraud.
- Emit your triage assessment before proceeding.

━━━ PHASE 2: DEEP GRAPH FORENSICS ━━━
- Run WCC community detection (detect_fraud_communities) to find ring clusters.
- Trace multi-hop transaction flows (find_fraud_rings, trace_money_flow).
- Compute max flow to quantify total layering volume (compute_max_flow).
- Identify broker accounts by centrality (rank_key_accounts with betweenness/pagerank).
- Find shortest evidence paths between suspects (explain_connection).
- Report exact dollar amounts, hop counts, and structuring signals ($9,000–$9,999).

━━━ PHASE 3: COMPLIANCE SUMMARY ━━━
- Evaluate regulatory obligations under BSA/FinCEN 31 CFR § 1020.320 and FATF red flags.
- Draft a concise SAR narrative: primary subject(s), transaction summary, graph evidence.
- Propose concrete actions via propose_action (freeze_account, open_case, file_sar, etc.).
- Note all actions remain PENDING_APPROVAL until reviewed by a human analyst.

After completing all phases, produce a structured final report with clear headings for each phase.
Be thorough but concise — cite exact metrics from tool results rather than vague descriptions.
"""

# All tools that the single unified agent may use
SINGLE_AGENT_TOOLS = {
    # Triage tools
    "get_active_alerts",
    "compute_risk_score",
    "find_shared_infrastructure",
    "search_accounts",
    "get_graph_overview",
    # Forensics tools
    "detect_fraud_communities",
    "find_fraud_rings",
    "trace_money_flow",
    "compute_max_flow",
    "rank_key_accounts",
    "explain_connection",
    # Compliance / action tools
    "propose_action",
    "list_actions",
    "save_investigation_memory",
    "recall_investigation_memory",
}

_SINGLE_AGENT_ROLE_INFO = {
    "title": "FraudScope Unified Investigator",
    "badge": "🕵️ Single Agent",
    "color": "var(--accent-glow)",
    "description": "One agent handles triage, deep forensic graph queries, and compliance summaries.",
}

_PHASE_EVENTS = [
    {"phase": 1, "label": "🛡️ Phase 1 — Triage & Risk Assessment", "message": "Scanning alerts and computing risk scores…"},
    {"phase": 2, "label": "🔬 Phase 2 — Deep Graph Forensics",      "message": "Running WCC, max flow, betweenness, and evidence paths…"},
    {"phase": 3, "label": "📋 Phase 3 — Compliance & SAR Narrative", "message": "Evaluating regulatory obligations and drafting SAR…"},
]


async def run_single_agent(
    user_query: str,
    session_id: str,
    conversation_history: list,
    on_event: EventCallback = None,
) -> dict:
    """
    Single-agent investigation: one unified LLM with ALL tools performs triage,
    deep graph forensics, and compliance drafting in one autonomous pass.
    Emits phase-progress events for the frontend so users can follow the investigation live.
    """
    import os
    started = time.time()

    if on_event:
        await on_event({
            "type": "agent_start",
            "role": "single_agent",
            "title": _SINGLE_AGENT_ROLE_INFO["title"],
            "badge": _SINGLE_AGENT_ROLE_INFO["badge"],
            "color": _SINGLE_AGENT_ROLE_INFO["color"],
            "phases": _PHASE_EVENTS,
        })
        await on_event({
            "type": "single_agent_phase",
            "phase": 1,
            "label": _PHASE_EVENTS[0]["label"],
            "message": _PHASE_EVENTS[0]["message"],
        })

    scoped_tools = await get_scoped_tool_specs(SINGLE_AGENT_TOOLS)

    # Construct an enriched prompt that embeds conversation context + query
    full_query = (
        f"INVESTIGATION REQUEST: {user_query}\n\n"
        f"Work through all 3 phases (Triage → Forensics → Compliance) methodically. "
        f"Use as many tool calls as needed to gather complete evidence before writing your report."
    )

    groq_first = os.getenv("LLM_PROVIDER", "groq").lower() == "groq"

    # We override on_event to intercept status messages and inject phase markers
    phase_tracker = {"current": 1}

    async def phase_aware_event(ev: dict):
        if on_event is None:
            return
        # Detect phase transitions based on status message keywords
        if ev.get("type") == "status":
            msg = ev.get("message", "").lower()
            if phase_tracker["current"] == 1 and any(k in msg for k in ("forensic", "wcc", "flow", "ring", "community", "betweenness", "pagerank")):
                phase_tracker["current"] = 2
                await on_event({
                    "type": "single_agent_phase",
                    "phase": 2,
                    "label": _PHASE_EVENTS[1]["label"],
                    "message": _PHASE_EVENTS[1]["message"],
                })
            elif phase_tracker["current"] == 2 and any(k in msg for k in ("compliance", "sar", "regulatory", "action", "propose", "filing")):
                phase_tracker["current"] = 3
                await on_event({
                    "type": "single_agent_phase",
                    "phase": 3,
                    "label": _PHASE_EVENTS[2]["label"],
                    "message": _PHASE_EVENTS[2]["message"],
                })
        await on_event(ev)

    # Also detect phase transitions from tool calls
    async def tool_aware_event(ev: dict):
        if on_event is None:
            return
        if ev.get("type") == "tool_start":
            tool = ev.get("tool", "")
            if phase_tracker["current"] == 1 and tool in {
                "detect_fraud_communities", "find_fraud_rings", "trace_money_flow",
                "compute_max_flow", "rank_key_accounts", "explain_connection",
            }:
                phase_tracker["current"] = 2
                await on_event({
                    "type": "single_agent_phase",
                    "phase": 2,
                    "label": _PHASE_EVENTS[1]["label"],
                    "message": _PHASE_EVENTS[1]["message"],
                })
            elif phase_tracker["current"] == 2 and tool in {
                "propose_action", "list_actions", "save_investigation_memory",
            }:
                phase_tracker["current"] = 3
                await on_event({
                    "type": "single_agent_phase",
                    "phase": 3,
                    "label": _PHASE_EVENTS[2]["label"],
                    "message": _PHASE_EVENTS[2]["message"],
                })
        await on_event(ev)

    # Wrap in a single role_info struct that matches specialist runner signature
    role_info = _SINGLE_AGENT_ROLE_INFO

    try:
        if groq_first:
            try:
                result = await _run_specialist_groq(
                    role_info, SINGLE_AGENT_PROMPT, scoped_tools,
                    full_query, session_id, conversation_history, tool_aware_event,
                    max_rounds=3,
                )
            except Exception as e:
                print(f"[WARN] Single-Agent (Groq) failed: {e}. Fallback to Gemini…")
                result = await _run_specialist_gemini(
                    role_info, SINGLE_AGENT_PROMPT, scoped_tools,
                    full_query, session_id, conversation_history, tool_aware_event,
                    max_rounds=3,
                )
        else:
            try:
                result = await _run_specialist_gemini(
                    role_info, SINGLE_AGENT_PROMPT, scoped_tools,
                    full_query, session_id, conversation_history, tool_aware_event,
                    max_rounds=3,
                )
            except Exception as e:
                print(f"[WARN] Single-Agent (Gemini) failed: {e}. Fallback to Groq…")
                result = await _run_specialist_groq(
                    role_info, SINGLE_AGENT_PROMPT, scoped_tools,
                    full_query, session_id, conversation_history, tool_aware_event,
                    max_rounds=3,
                )
    except Exception as e:
        result = {
            "response": f"❌ Single-agent investigation failed: {e}",
            "role": role_info["title"],
            "badge": role_info["badge"],
            "tool_calls": [],
            "tool_results": [],
            "session_id": session_id,
        }

    elapsed_ms = round((time.time() - started) * 1000)
    result["elapsed_ms"] = elapsed_ms
    result["is_single_agent"] = True
    result["phases_completed"] = phase_tracker["current"]

    await asyncio.to_thread(_auto_save_memory, user_query, session_id, result)
    return result
