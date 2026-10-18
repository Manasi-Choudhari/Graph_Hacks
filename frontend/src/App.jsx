import { useState, useEffect, useRef, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import GraphCanvas from './GraphCanvas.jsx'
import {
  createSession, getOverview, getAlerts, getFullGraph,
  getSubgraph, streamChat, streamSingleAgent, streamSwarm,
  seedDatabase, searchAccounts, getMemory,
  getActions, reviewAction, getCommunities,
  getTemporalVelocity, getTemporalTimeline,
  ingestFile, ingestSample, getTemplateUrl
} from './api.js'

/* ── Icons (inline SVG, no deps) ─────────────────────────────────────── */
const Icon = {
  Send:     () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>,
  Search:   () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>,
  Alert:    () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>,
  Graph:    () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="5" r="3"/><circle cx="19" cy="19" r="3"/><circle cx="5" cy="19" r="3"/><line x1="12" y1="8" x2="5" y2="16"/><line x1="12" y1="8" x2="19" y2="16"/></svg>,
  Stats:    () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>,
  Brain:    () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9.5 2a2.5 2.5 0 015 0"/><path d="M14.5 22a2.5 2.5 0 01-5 0"/><path d="M20 6a2 2 0 012 2v8a2 2 0 01-2 2"/><path d="M4 18a2 2 0 01-2-2V8a2 2 0 012-2"/><path d="M14.5 2A3.5 3.5 0 0118 5.5v13a3.5 3.5 0 01-3.5 3.5"/><path d="M9.5 2A3.5 3.5 0 006 5.5v13A3.5 3.5 0 009.5 22"/></svg>,
  Seed:     () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 22V12"/><path d="M12 12C12 7 7 4 2 4c0 5 3 9 10 8"/><path d="M12 12c0-5 5-8 10-8-0 5-3 9-10 8"/></svg>,
  Tool:     () => <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/></svg>,
  Chevron:  ({ open }) => <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ transform: open ? 'rotate(90deg)' : 'rotate(0)', transition: '200ms' }}><polyline points="9 18 15 12 9 6"/></svg>,
  Memory:   () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="6" width="20" height="12" rx="2"/><line x1="6" y1="12" x2="6" y2="12"/><line x1="10" y1="12" x2="10" y2="12"/><line x1="14" y1="12" x2="14" y2="12"/><line x1="18" y1="12" x2="18" y2="12"/></svg>,
  Upload:   () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>,
  Download: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>,
}

/* ── Risk helpers ─────────────────────────────────────────────────────── */
function riskColor(score) {
  if (score > 0.75) return 'var(--risk-critical)'
  if (score > 0.5)  return 'var(--risk-high)'
  if (score > 0.25) return 'var(--risk-medium)'
  return 'var(--risk-low)'
}
function riskLabel(score) {
  if (score > 0.75) return 'CRITICAL'
  if (score > 0.5)  return 'HIGH'
  if (score > 0.25) return 'MEDIUM'
  return 'LOW'
}

/* ── Evidence: turn a tool result into what the graph should show ────── */
const ACCOUNT_PREFIX_TYPES = { SHELL_: 'shell_company', MULE_: 'mule', CASHOUT_: 'crypto_exchange' }
const PREVIEW_HIDDEN_KEYS = [
  'nodes', 'edges', 'outflows', 'inflows', 'shared_accounts', 'memories', 'alerts',
  'communities', 'ranked_accounts', 'paths', 'flow_edges', 'actions',
]

function accountStub(id) {
  const prefix = Object.keys(ACCOUNT_PREFIX_TYPES).find(p => id.startsWith(p))
  return { id, type: 'Account', name: id, entity_type: prefix ? ACCOUNT_PREFIX_TYPES[prefix] : null, is_suspicious: !!prefix && prefix !== 'CASHOUT_', risk_score: prefix ? 0.8 : 0.1 }
}

const edgeKeys = edges => edges.map(e => `${e.source}|${e.target}`)
const usd = n => `$${Math.round(n || 0).toLocaleString()}`

function evidenceFromResult(r) {
  if (!r || r.error) return null
  switch (r.tool) {
    case 'explain_connection':
      if (!r.nodes?.length) return null
      return {
        graph: { nodes: r.nodes, edges: r.edges },
        ids: r.nodes.map(n => n.id),
        edges: edgeKeys(r.edges),
        caption: `Evidence path ${r.source_id} → ${r.target_id}: ${r.paths.length} path(s), shortest ${r.shortest_length} hops · algo.SPpaths`,
      }
    case 'compute_max_flow': {
      if (!r.edges?.length) return null
      const ids = [...new Set(r.edges.flatMap(e => [e.source, e.target]))]
      return {
        graph: { nodes: ids.map(accountStub), edges: r.edges },
        ids,
        edges: edgeKeys(r.edges),
        caption: `Max flow ${usd(r.max_flow)} from ${r.source_id} to ${r.target_id} — ${usd(r.indirect_flow)} layered through ${r.intermediary_accounts.length} intermediaries · algo.maxFlow`,
      }
    }
    case 'detect_fraud_communities':
      if (!r.nodes?.length) return null
      return {
        graph: { nodes: r.nodes, edges: r.edges },
        ids: [],
        edges: [],
        caption: `${r.likely_fraud_rings} fraud ring(s) discovered by algo.WCC over shared IPs/devices — no labels used`,
      }
    case 'find_fraud_rings':
      if (!r.nodes?.length) return null
      return {
        graph: { nodes: r.nodes, edges: r.edges },
        ids: r.account_id && r.account_id !== 'ALL' ? [r.account_id] : [],
        edges: [],
        caption: `${r.nodes.length} nodes within ${r.max_hops} hops of ${r.account_id} · multi-hop Cypher traversal`,
      }
    case 'rank_key_accounts':
      return {
        ids: r.ranked_accounts.map(a => a.account_id),
        edges: [],
        caption: `Top accounts by ${r.metric} · algo.${r.metric === 'pagerank' ? 'pageRank' : 'betweenness'}`,
      }
    default:
      return null
  }
}

/* ── ToolCallCard ────────────────────────────────────────────────────── */
const MARKDOWN_COMPONENTS = {
  table: ({ node, ...props }) => (
    <div className="table-wrap"><table {...props} /></div>
  ),
}

function ToolCallCard({ tc, result }) {
  const [open, setOpen] = useState(false)
  const failed = result && result.error
  return (
    <div className={`tool-call-card ${tc.running ? 'running' : ''} ${failed ? 'failed' : ''}`}>
      <div className="tool-call-header" onClick={() => setOpen(o => !o)}>
        {tc.running ? <div className="tool-spinner" /> : <Icon.Tool />}
        <span className="tool-name">{tc.tool}()</span>
        <Icon.Chevron open={open} />
        {tc.ms != null && <span className="tool-ms">{tc.ms} ms</span>}
        <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 160 }}>
          {Object.keys(tc.args || {}).map(k => `${k}="${tc.args[k]}"`).join(', ')}
        </span>
      </div>
      {open && (
        <div className="tool-call-body">
          {tc.cypher && (
            <>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Cypher Query:</div>
              <div className="cypher-block">{tc.cypher}</div>
            </>
          )}
          {result && (
            <>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8, marginBottom: 4 }}>Result Preview:</div>
              <div className="cypher-block" style={{ color: 'var(--text-secondary)' }}>
                {JSON.stringify(
                  Object.fromEntries(
                    Object.entries(result).filter(([k]) => !PREVIEW_HIDDEN_KEYS.includes(k))
                  ),
                  null, 2
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

/* ── Agent Mode Badge ────────────────────────────────────────────────── */
const AGENT_MODES = [
  {
    id: 'standard',
    label: 'Standard',
    badge: '🤖 Standard',
    color: 'var(--accent-cyan)',
    desc: 'Single tool-calling agent — fast, direct answers.',
  },
  {
    id: 'single_agent',
    label: 'Single-Agent Investigator',
    badge: '🕵️ Single Agent',
    color: 'var(--accent-glow)',
    desc: 'One unified investigator: triage → forensics → compliance in one autonomous pass.',
  },
  {
    id: 'swarm',
    label: 'Multi-Agent Swarm',
    badge: '🐝 Swarm',
    color: 'var(--accent-purple)',
    desc: '3 specialist agents: Triage → Graph Forensics → AML Compliance Officer.',
  },
]

/* ── Phase Progress Bar (Single-Agent) ───────────────────────────────── */
function SingleAgentPhaseBar({ phase }) {
  const phases = [
    { n: 1, icon: '🛡️', label: 'Triage' },
    { n: 2, icon: '🔬', label: 'Forensics' },
    { n: 3, icon: '📋', label: 'Compliance' },
  ]
  return (
    <div style={{
      display: 'flex', gap: 0, margin: '8px 0 4px', borderRadius: 8,
      overflow: 'hidden', border: '1px solid var(--border)',
    }}>
      {phases.map(p => (
        <div key={p.n} style={{
          flex: 1, padding: '6px 4px', textAlign: 'center', fontSize: 11,
          background: phase >= p.n ? 'rgba(99,102,241,0.18)' : 'var(--bg-elevated)',
          borderRight: p.n < 3 ? '1px solid var(--border)' : 'none',
          color: phase >= p.n ? 'var(--accent-glow)' : 'var(--text-muted)',
          fontWeight: phase === p.n ? 700 : 400,
          transition: 'all 0.3s',
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4,
        }}>
          <span>{p.icon}</span>
          <span>{p.label}</span>
          {phase > p.n && <span style={{ color: 'var(--success)' }}>✓</span>}
          {phase === p.n && <span style={{ color: 'var(--accent-primary)' }}>●</span>}
        </div>
      ))}
    </div>
  )
}

/* ── Swarm Stage Banner ──────────────────────────────────────────────── */
function SwarmStageBanner({ stage, totalStages, title, role }) {
  const roleColors = { triage: 'var(--accent-cyan)', forensics: 'var(--accent-primary)', compliance: 'var(--accent-purple)' }
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px',
      background: 'var(--bg-elevated)', borderRadius: 8,
      border: `1px solid ${roleColors[role] || 'var(--border)'}`,
      margin: '6px 0', fontSize: 12,
    }}>
      <div style={{
        width: 22, height: 22, borderRadius: '50%',
        background: roleColors[role] || 'var(--accent-primary)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 11, fontWeight: 700, color: '#fff', flexShrink: 0,
      }}>{stage}</div>
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{title}</div>
        <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>Stage {stage} of {totalStages}</div>
      </div>
      <div style={{
        display: 'flex', gap: 2,
      }}>
        {Array.from({ length: totalStages }).map((_, i) => (
          <div key={i} style={{
            width: 18, height: 4, borderRadius: 2,
            background: i < stage ? (roleColors[role] || 'var(--accent-primary)') : 'var(--border)',
            transition: 'background 0.3s',
          }} />
        ))}
      </div>
    </div>
  )
}

/* ── ChatPanel ───────────────────────────────────────────────────────── */
function ChatPanel({ sessionId, onEvidence, onActionProposed, agentMode = 'standard', onAgentModeChange }) {
  const modeInfo = AGENT_MODES.find(m => m.id === agentMode) || AGENT_MODES[0]
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: `👋 **FraudScope AI** is ready. I have access to the FalkorDB fraud graph.

Try asking me:
- *"Find all fraud rings"* — community detection, no labels
- *"Who are the money hubs?"* — PageRank / betweenness
- *"How is MULE_x connected to SHELL_y?"* — shortest evidence paths
- *"How much money reached the cash-out exchange?"* — max flow
- *"Sweep the graph and propose actions"* — you approve them in the Actions tab

💡 **Tip:** Use **Single-Agent Investigator** or **Multi-Agent Swarm** mode for a full triage → forensics → compliance report.`,
      toolCalls: [],
      toolResults: [],
    }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [showModeMenu, setShowModeMenu] = useState(false)
  const [fontSize, setFontSize] = useState(() => Number(localStorage.getItem('fs-chat-font')) || 13)
  useEffect(() => { localStorage.setItem('fs-chat-font', fontSize) }, [fontSize])
  const bumpFont = (d) => setFontSize(s => Math.min(20, Math.max(11, s + d)))
  const bottomRef = useRef(null)
  const inputRef = useRef(null)

  const QUICK_PROMPTS = [
    'Find all fraud rings',
    'Who are the money hubs?',
    'Trace layering from the top shell company to its cash-out exchange',
    'Sweep the graph and propose actions',
    'Show active alerts',
    'What did I investigate before?',
  ]

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = useCallback(async (text) => {
    const msg = text || input.trim()
    if (!msg || loading || !sessionId) return

    setInput('')
    setShowModeMenu(false)
    const isSwarm = agentMode === 'swarm'
    const isSingle = agentMode === 'single_agent'

    setMessages(prev => [
      ...prev,
      { role: 'user', content: msg, toolCalls: [], toolResults: [] },
      {
        role: 'assistant',
        content: '',
        toolCalls: [],
        toolResults: [],
        live: true,
        status: isSingle ? '🕵️ Unified investigator initializing…' : isSwarm ? '🐝 Swarm initializing…' : 'Thinking…',
        agentMode,
        // phase tracking for single-agent
        currentPhase: isSingle ? 1 : null,
        // swarm stage tracking
        swarmStage: isSwarm ? null : undefined,
        swarmStageTitle: null,
        swarmStageRole: null,
      },
    ])
    setLoading(true)

    const updateLive = (fn) => setMessages(prev => {
      const copy = [...prev]
      copy[copy.length - 1] = fn({ ...copy[copy.length - 1] })
      return copy
    })

    const handleEvent = (ev) => {
      switch (ev.type) {
        case 'status':
          updateLive(m => ({ ...m, status: ev.message }))
          break
        case 'single_agent_phase':
          updateLive(m => ({ ...m, currentPhase: ev.phase, status: ev.message }))
          break
        case 'swarm_stage_start':
          updateLive(m => ({
            ...m,
            swarmStage: ev.stage,
            swarmStageTitle: ev.title,
            swarmStageRole: ev.role,
            status: ev.message,
          }))
          break
        case 'agent_start':
          updateLive(m => ({ ...m, status: `${ev.badge} starting…` }))
          break
        case 'tool_start':
          updateLive(m => ({
            ...m,
            status: `Running ${ev.tool}…`,
            toolCalls: [...m.toolCalls, { tool: ev.tool, args: ev.args, running: true }],
            toolResults: [...m.toolResults, null],
          }))
          break
        case 'tool_result':
          updateLive(m => {
            const i = m.toolCalls.findIndex(tc => tc.running && tc.tool === ev.tool)
            if (i === -1) return m
            const toolCalls = [...m.toolCalls]
            const toolResults = [...m.toolResults]
            toolCalls[i] = { tool: ev.tool, args: ev.args, cypher: ev.cypher, ms: ev.ms, running: false }
            toolResults[i] = ev.result
            return { ...m, toolCalls, toolResults }
          })
          {
            const evidence = evidenceFromResult(ev.result)
            if (evidence) onEvidence?.(evidence)
            if (ev.tool === 'propose_action') onActionProposed?.()
          }
          break
        case 'response': {
          const modeLabel = ev.is_swarm
            ? `🐝 Swarm · ${ev.tool_count} tool calls · ${(ev.elapsed_ms / 1000).toFixed(1)}s`
            : ev.is_single_agent
              ? `🕵️ Single Agent · Phase ${ev.phases_completed}/3 · ${ev.tool_count} tool calls · ${(ev.elapsed_ms / 1000).toFixed(1)}s`
              : `${ev.tool_count} graph tool call(s) · ${(ev.elapsed_ms / 1000).toFixed(1)}s`
          updateLive(m => ({
            ...m,
            content: ev.content,
            live: false,
            meta: modeLabel,
            currentPhase: isSingle ? 3 : m.currentPhase,
          }))
          break
        }
        case 'error':
          updateLive(m => ({ ...m, content: `❌ Error: ${ev.content}`, live: false }))
          break
        default:
          break
      }
    }

    try {
      if (isSingle) {
        await streamSingleAgent(msg, sessionId, handleEvent)
      } else if (isSwarm) {
        await streamSwarm(msg, sessionId, handleEvent)
      } else {
        await streamChat(msg, sessionId, handleEvent)
      }
    } catch (err) {
      updateLive(m => ({ ...m, content: `❌ Error: ${err.message || 'Request failed'}`, live: false }))
    } finally {
      setLoading(false)
    }
  }, [input, loading, sessionId, onEvidence, onActionProposed, agentMode])

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  return (
    <>
      <div className="chat-header">
        <div className="chat-title">
          <div className="agent-avatar" style={{ fontSize: 18 }}>
            {agentMode === 'swarm' ? '🐝' : agentMode === 'single_agent' ? '🕵️' : '🤖'}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>FraudScope AI</span>
              {/* Mode Pill */}
              <button
                id="agent-mode-toggle"
                onClick={() => setShowModeMenu(m => !m)}
                style={{
                  background: 'rgba(99,102,241,0.12)',
                  border: `1px solid ${modeInfo.color}55`,
                  borderRadius: 20,
                  padding: '2px 8px',
                  fontSize: 10,
                  color: modeInfo.color,
                  cursor: 'pointer',
                  fontFamily: 'Inter, sans-serif',
                  fontWeight: 600,
                  display: 'flex', alignItems: 'center', gap: 3,
                  whiteSpace: 'nowrap',
                }}
              >
                {modeInfo.badge} <span style={{ opacity: 0.7 }}>▾</span>
              </button>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 400 }}>
              {loading ? (
                <span style={{ color: modeInfo.color }}>● Investigating…</span>
              ) : '● Online'}
            </div>
          </div>
        </div>
        <div className="font-controls" title="Chat text size">
          <button onClick={() => bumpFont(-1)} disabled={fontSize <= 11} aria-label="Smaller text">A−</button>
          <button onClick={() => bumpFont(1)} disabled={fontSize >= 20} aria-label="Larger text">A+</button>
        </div>
        {sessionId && <div className="session-badge">{sessionId.slice(0, 8)}</div>}
      </div>

      {/* Agent Mode Dropdown */}
      {showModeMenu && (
        <div style={{
          position: 'absolute', top: 62, right: 12, zIndex: 100,
          background: 'var(--bg-card)', border: '1px solid var(--border)',
          borderRadius: 12, padding: 8, width: 260, boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', padding: '4px 8px 8px', letterSpacing: 1 }}>SELECT AGENT MODE</div>
          {AGENT_MODES.map(m => (
            <button
              key={m.id}
              id={`mode-${m.id}`}
              onClick={() => { onAgentModeChange?.(m.id); setShowModeMenu(false) }}
              style={{
                width: '100%', textAlign: 'left', background: agentMode === m.id ? `${m.color}18` : 'transparent',
                border: `1px solid ${agentMode === m.id ? m.color + '55' : 'transparent'}`,
                borderRadius: 8, padding: '8px 10px', cursor: 'pointer',
                marginBottom: 4, color: 'var(--text-primary)', fontFamily: 'Inter, sans-serif',
              }}
            >
              <div style={{ fontSize: 12, fontWeight: 600, color: agentMode === m.id ? m.color : 'var(--text-primary)', marginBottom: 2 }}>
                {m.badge}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.4 }}>{m.desc}</div>
            </button>
          ))}
        </div>
      )}

      <div className="chat-messages" style={{ '--chat-font': `${fontSize}px` }}>
        {messages.map((msg, i) => (
          <div key={i} className={`message ${msg.role === 'user' ? 'user' : 'assistant'}`}>

            {/* Single-Agent Phase Progress Bar */}
            {msg.role === 'assistant' && msg.agentMode === 'single_agent' && msg.currentPhase && (
              <SingleAgentPhaseBar phase={msg.currentPhase} />
            )}

            {/* Swarm Stage Banner */}
            {msg.role === 'assistant' && msg.agentMode === 'swarm' && msg.swarmStage && (
              <SwarmStageBanner
                stage={msg.swarmStage}
                totalStages={3}
                title={msg.swarmStageTitle}
                role={msg.swarmStageRole}
              />
            )}

            {/* Tool calls (before response) */}
            {msg.role === 'assistant' && msg.toolCalls?.length > 0 && (
              <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 6 }}>
                {msg.toolCalls.map((tc, j) => (
                  <ToolCallCard key={j} tc={tc} result={msg.toolResults?.[j]} />
                ))}
              </div>
            )}
            {msg.live && (
              <div className="typing-indicator">
                <div className="typing-dot" />
                <div className="typing-dot" />
                <div className="typing-dot" />
                <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 4 }}>{msg.status}</span>
              </div>
            )}
            {msg.content && (
              <div className="message-bubble">
                {msg.role === 'assistant' ? (
                  <div className="markdown-body">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>{msg.content}</ReactMarkdown>
                  </div>
                ) : msg.content}
              </div>
            )}
            {msg.meta && <div className="response-meta">{msg.meta}</div>}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="chat-input-area">
        <div className="quick-prompts">
          {QUICK_PROMPTS.map(p => (
            <button key={p} className="quick-prompt-chip" onClick={() => send(p)}>
              {p}
            </button>
          ))}
        </div>
        <div className="chat-input-row">
          <textarea
            ref={inputRef}
            className="chat-input"
            placeholder="Ask the agent to investigate… (Enter to send)"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            rows={1}
          />
          <button className="send-btn" onClick={() => send()} disabled={loading || !input.trim()}>
            <Icon.Send />
          </button>
        </div>
      </div>
    </>
  )
}

/* ── AlertsSidebar ───────────────────────────────────────────────────── */
function AlertsSidebar({ alerts, onAlertClick }) {
  const [search, setSearch] = useState('')
  const [searchResults, setSearchResults] = useState(null)
  const [searching, setSearching] = useState(false)

  const doSearch = async () => {
    if (!search.trim()) { setSearchResults(null); return }
    setSearching(true)
    try {
      const data = await searchAccounts(search)
      setSearchResults(data.accounts || [])
    } finally {
      setSearching(false)
    }
  }

  const filtered = alerts.filter(a =>
    !search || a.account_name?.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <>
      {/* Search */}
      <div className="sidebar-section">
        <div className="sidebar-label">Search Accounts</div>
        <div style={{ display: 'flex', gap: 6 }}>
          <input
            style={{
              flex: 1, background: 'var(--bg-elevated)', border: '1px solid var(--border)',
              borderRadius: 8, padding: '7px 10px', color: 'var(--text-primary)',
              fontSize: 12, outline: 'none', fontFamily: 'Inter, sans-serif',
            }}
            placeholder="Name or ID…"
            value={search}
            onChange={e => { setSearch(e.target.value); if (!e.target.value) setSearchResults(null) }}
            onKeyDown={e => e.key === 'Enter' && doSearch()}
          />
          <button className="btn btn-ghost" style={{ padding: '7px 10px' }} onClick={doSearch}>
            <Icon.Search />
          </button>
        </div>

        {/* Search results */}
        {searchResults && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {searchResults.length === 0 && (
              <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 4px' }}>No results</div>
            )}
            {searchResults.map(acc => (
              <div
                key={acc.id}
                className="alert-item"
                onClick={() => onAlertClick?.(acc)}
                style={{ borderLeft: `3px solid ${riskColor(acc.risk_score || 0)}` }}
              >
                <div className="alert-header">
                  <span className="alert-name">{acc.name}</span>
                  <span className={`alert-badge badge-${riskLabel(acc.risk_score || 0).toLowerCase()}`}>
                    {riskLabel(acc.risk_score || 0)}
                  </span>
                </div>
                <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>{acc.id}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Alerts */}
      <div className="sidebar-section" style={{ flex: 1 }}>
        <div className="sidebar-label" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>Active Alerts</span>
          <span style={{ fontSize: 10, background: 'var(--risk-critical)', color: '#fff', padding: '1px 6px', borderRadius: 10, fontWeight: 700 }}>
            {alerts.filter(a => a.severity === 'CRITICAL').length} CRIT
          </span>
        </div>
        {filtered.length === 0 && (
          <div className="empty-state" style={{ height: 120 }}>
            <div className="empty-icon">🎉</div>
            <div>No alerts</div>
          </div>
        )}
        {filtered.map(alert => (
          <div
            key={alert.alert_id}
            className={`alert-item ${alert.severity?.toLowerCase()}`}
            onClick={() => onAlertClick?.(alert)}
          >
            <div className="alert-header">
              <span className="alert-name">{alert.account_name}</span>
              <span className={`alert-badge badge-${alert.severity?.toLowerCase()}`}>
                {alert.severity}
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span className="alert-type">{alert.alert_type}</span>
              <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{alert.country}</span>
            </div>
            <div className="risk-bar-container">
              <div className="risk-bar-track">
                <div
                  className="risk-bar-fill"
                  style={{
                    width: `${(alert.risk_score || 0) * 100}%`,
                    background: riskColor(alert.risk_score || 0),
                  }}
                />
              </div>
              <span className="risk-label-small" style={{ color: riskColor(alert.risk_score || 0) }}>
                {((alert.risk_score || 0) * 100).toFixed(0)}%
              </span>
            </div>
          </div>
        ))}
      </div>
    </>
  )
}

/* ── OverviewPanel ────────────────────────────────────────────────────── */
function OverviewPanel({ overview }) {
  if (!overview) return (
    <div className="loading-overlay" style={{ position: 'relative', height: '100%' }}>
      <div className="spinner" />
      <div className="loading-text">Loading graph stats…</div>
    </div>
  )

  const cards = [
    { icon: '🏦', label: 'Total Accounts', value: overview.node_counts?.Account ?? 0, color: '#3b82f6' },
    { icon: '⚠️', label: 'Suspicious Accounts', value: overview.suspicious_accounts ?? 0, color: '#dc2626' },
    { icon: '🔔', label: 'Open Alerts', value: overview.open_alerts ?? 0, color: '#f59e0b' },
    { icon: '💸', label: 'Transactions', value: overview.total_transactions ?? 0, color: '#10b981' },
    { icon: '💰', label: 'Volume (USD)', value: `$${((overview.total_volume_usd || 0) / 1000).toFixed(0)}K`, color: '#8b5cf6' },
    { icon: '🖧', label: 'IP Addresses', value: overview.node_counts?.IPAddress ?? 0, color: '#8b5cf6' },
    { icon: '📱', label: 'Devices', value: overview.node_counts?.Device ?? 0, color: '#06b6d4' },
    { icon: '🏢', label: 'Entities', value: overview.node_counts?.Entity ?? 0, color: '#10b981' },
  ]

  return (
    <div className="overview-grid">
      {cards.map(({ icon, label, value, color }) => (
        <div key={label} className="stat-card">
          <div className="stat-card-icon" style={{ background: `${color}22` }}>
            {icon}
          </div>
          <div className="stat-card-value" style={{ color }}>{value}</div>
          <div className="stat-card-label">{label}</div>
        </div>
      ))}

      {/* Graph model info */}
      <div className="stat-card" style={{ gridColumn: '1 / -1', background: 'var(--bg-elevated)' }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent-glow)', marginBottom: 8 }}>
          🗃️ FalkorDB Graph Model
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 12, color: 'var(--text-secondary)' }}>
          <div>
            <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>Node Types</div>
            {['Account', 'Entity', 'IPAddress', 'Device', 'AlertEvent', 'Action', 'Case', 'SAR', 'Memory'].map(n => (
              <div key={n} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '2px 0' }}>
                <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent-cyan)' }} />
                {n}
              </div>
            ))}
          </div>
          <div>
            <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>Edge Types</div>
            {['TRANSACTED_WITH', 'FLOWS_TO', 'USES_IP', 'USES_DEVICE', 'OWNED_BY', 'HAS_ALERT', 'TARGETS', 'EVIDENCED_BY', 'FOLLOWED_BY'].map(e => (
              <div key={e} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '2px 0' }}>
                <div style={{ width: 6, height: 2, background: 'var(--accent-primary)' }} />
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{e}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

/* ── IngestModal ─────────────────────────────────────────────────────── */
function IngestModal({ isOpen, onClose, onIngested }) {
  const [mode, setMode] = useState('append')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef(null)

  if (!isOpen) return null

  const handleFile = async (file) => {
    if (!file) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('mode', mode)
      const res = await ingestFile(formData)
      setResult(res)
      if (onIngested) onIngested(res)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Upload failed')
    } finally {
      setLoading(false)
    }
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFile(e.dataTransfer.files[0])
    }
  }

  const handleSample = async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await ingestSample(mode)
      setResult(res)
      if (onIngested) onIngested(res)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Sample load failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">
            <span style={{ color: 'var(--accent-purple)' }}><Icon.Upload /></span>
            <span>Dynamic Graph Data Ingestion</span>
          </div>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>

        {/* Mode Selector */}
        <div style={{ marginBottom: 8, fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)' }}>Ingestion Mode</div>
        <div className="mode-selector">
          <div
            className={`mode-option ${mode === 'append' ? 'selected' : ''}`}
            onClick={() => setMode('append')}
          >
            <div className="mode-option-title">➕ Append to Graph</div>
            <div className="mode-option-desc">Preserves existing nodes and relationships, connects new entities dynamically.</div>
          </div>
          <div
            className={`mode-option ${mode === 'replace' ? 'selected' : ''}`}
            onClick={() => setMode('replace')}
          >
            <div className="mode-option-title" style={{ color: mode === 'replace' ? 'var(--warning)' : 'inherit' }}>🔄 Wipe &amp; Replace</div>
            <div className="mode-option-desc">Clears current graph completely before loading the new accounts and transactions dataset.</div>
          </div>
        </div>

        {/* Dropzone */}
        <div
          className={`dropzone ${dragOver ? 'active' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            type="file"
            ref={fileInputRef}
            style={{ display: 'none' }}
            accept=".csv,.json,text/csv,application/json"
            onChange={(e) => {
              if (e.target.files?.[0]) handleFile(e.target.files[0])
            }}
          />
          <div className="dropzone-icon">
            <Icon.Upload />
          </div>
          <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
            {loading ? 'Ingesting data into FalkorDB...' : 'Drop CSV or JSON file here, or click to browse'}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Supports transactions CSV (source_id, target_id, amount...) or accounts &amp; transactions JSON bundle
          </div>
        </div>

        {/* Templates and Sample Bar */}
        <div className="template-bar">
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-secondary)' }}>
            <Icon.Download />
            <span>Templates:</span>
            <a
              href={getTemplateUrl('csv')}
              download="fraudscope_transactions_template.csv"
              className="btn btn-ghost"
              style={{ fontSize: 11, padding: '3px 8px' }}
            >
              CSV Template
            </a>
            <a
              href={getTemplateUrl('json')}
              download="fraudscope_template.json"
              className="btn btn-ghost"
              style={{ fontSize: 11, padding: '3px 8px' }}
            >
              JSON Template
            </a>
          </div>
          <button
            className="btn btn-ghost"
            style={{ borderColor: 'rgba(139,92,246,0.4)', color: '#c084fc', fontSize: 11, padding: '4px 10px' }}
            onClick={handleSample}
            disabled={loading}
          >
            ⚡ Load Sample Syndicate (5 Accs, 6 TXs)
          </button>
        </div>

        {/* Error message */}
        {error && (
          <div style={{ padding: '10px 14px', background: 'rgba(239,68,68,0.15)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, color: 'var(--danger)', fontSize: 12, marginTop: 12 }}>
            ⚠️ {error}
          </div>
        )}

        {/* Result Summary */}
        {result && (
          <div className="ingest-result-card">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--success)', fontWeight: 600, fontSize: 13 }}>
              <span>✓ Ingestion Successful!</span>
              <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>({result.elapsed_ms}ms)</span>
            </div>
            <div className="ingest-stat-grid">
              <div className="ingest-stat-box">
                <div className="val">{result.accounts_created_or_updated}</div>
                <div className="lbl">Accounts</div>
              </div>
              <div className="ingest-stat-box">
                <div className="val">{result.transactions_created}</div>
                <div className="lbl">Transactions</div>
              </div>
              <div className="ingest-stat-box">
                <div className="val">{result.ips_linked + result.devices_linked}</div>
                <div className="lbl">Infra Links</div>
              </div>
              <div className="ingest-stat-box">
                <div className="val">${Math.round(result.total_volume_usd || 0).toLocaleString()}</div>
                <div className="lbl">Volume USD</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

/* ── TemporalReplayBar ──────────────────────────────────────────────── */
function TemporalReplayBar({
  timeline,
  velocityData,
  temporalFilter,
  onChangeFilter,
  onMuleClick,
  onClose,
}) {
  const [isPlaying, setIsPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)

  const minMs = timeline?.min_timestamp_ms || (timeline?.min_timestamp ? new Date(timeline.min_timestamp).getTime() : Date.now() - 24 * 3600 * 1000)
  const maxMs = timeline?.max_timestamp_ms || (timeline?.max_timestamp ? new Date(timeline.max_timestamp).getTime() : Date.now())
  const currentMs = Number(temporalFilter?.currentTimeMs) || maxMs
  const windowMinutes = temporalFilter?.windowMinutes ?? 30
  const rapidOnly = Boolean(temporalFilter?.rapidOnly)

  // Auto-advance playback loop
  useEffect(() => {
    if (!isPlaying) return
    const interval = setInterval(() => {
      onChangeFilter(prev => {
        const step = Math.max(60000, Math.round((maxMs - minMs) / 80)) * speed
        let next = (Number(prev.currentTimeMs) || minMs) + step
        if (next > maxMs) next = minMs
        return { ...prev, currentTimeMs: next }
      })
    }, 250)
    return () => clearInterval(interval)
  }, [isPlaying, speed, minMs, maxMs, onChangeFilter])

  const formatTime = (ms) => {
    try {
      const d = new Date(ms)
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' +
        d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    } catch {
      return ''
    }
  }

  const maxBinCount = Math.max(1, ...(timeline?.histogram_bins?.map(b => b.count) || [1]))

  return (
    <div className="temporal-dock">
      {/* Header Row */}
      <div className="temporal-header">
        <div className="temporal-title">
          <span style={{ fontSize: 16 }}>🕒</span>
          <span>Temporal Replay &amp; Money Velocity</span>
          <span className="temporal-badge live">
            {windowMinutes === 0 ? 'ALL TIME' : `SLIDING ${windowMinutes}M`}
          </span>
          {velocityData?.rapid_relay_count > 0 && (
            <span className="temporal-badge rapid">
              ⚡ {velocityData.rapid_relay_count} Rapid Relays (≤{velocityData.window_minutes || 30}m)
            </span>
          )}
        </div>

        <div className="temporal-controls-row">
          {/* Rapid Mule Filter Toggle */}
          <button
            id="temporal-rapid-filter-btn"
            className={`temporal-btn temporal-btn-rapid ${rapidOnly ? 'active' : ''}`}
            onClick={() => onChangeFilter(prev => ({ ...prev, rapidOnly: !prev.rapidOnly }))}
            title="Filter graph to ONLY rapid mule pass-throughs under 30 minutes"
          >
            ⚡ {rapidOnly ? 'Showing Rapid Mules Only' : 'Rapid Mule Filter (≤30m)'}
          </button>

          {/* Window Selectors */}
          {[15, 30, 60, 360, 1440, 0].map(mins => (
            <button
              key={mins}
              className={`temporal-btn ${windowMinutes === mins ? 'active' : ''}`}
              onClick={() => onChangeFilter(prev => ({ ...prev, windowMinutes: mins }))}
            >
              {mins === 0 ? 'All' : mins === 60 ? '1h' : mins === 360 ? '6h' : mins === 1440 ? '24h' : `${mins}m`}
            </button>
          ))}

          {/* Close Dock */}
          <button
            className="temporal-btn"
            style={{ color: 'var(--text-muted)' }}
            onClick={onClose}
            title="Close Temporal Replay"
          >
            ✕
          </button>
        </div>
      </div>

      {/* Histogram Bar Chart */}
      {timeline?.histogram_bins?.length > 0 && (
        <div className="temporal-histogram" title="Click any time bin to scrub timeline">
          {timeline.histogram_bins.map((bin, idx) => {
            const heightPct = Math.max(15, Math.round((bin.count / maxBinCount) * 100))
            const isActive = currentMs >= (bin.start_ms || 0) && currentMs <= (bin.end_ms || Infinity)
            const hasRapid = Boolean((bin.rapid_relays && bin.rapid_relays > 0) || (bin.rapid_count && bin.rapid_count > 0))
            return (
              <div
                key={idx}
                className={`temporal-hist-bar ${hasRapid ? 'has-rapid' : ''} ${isActive ? 'active-bin' : ''}`}
                style={{ height: `${heightPct}%` }}
                onClick={() => onChangeFilter(prev => ({ ...prev, currentTimeMs: bin.end_ms || bin.start_ms || currentMs }))}
                title={`${bin.start_time ? bin.start_time.slice(11, 16) : ''} - ${bin.end_time ? bin.end_time.slice(11, 16) : ''}: ${bin.count || 0} txs ($${Math.round(bin.volume || 0).toLocaleString()})${hasRapid ? ` · ⚡ ${bin.rapid_relays || bin.rapid_count} rapid relays` : ''}`}
              />
            )
          })}
        </div>
      )}

      {/* Scrubber & Playback Controls */}
      <div className="temporal-scrubber-track">
        <input
          type="range"
          className={`temporal-slider ${rapidOnly ? 'rapid-mode' : ''}`}
          min={minMs}
          max={maxMs}
          value={currentMs}
          onChange={(e) => onChangeFilter(prev => ({ ...prev, currentTimeMs: Number(e.target.value) }))}
        />

        <div className="temporal-hud">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {/* Play/Pause */}
            <button
              id="temporal-play-pause-btn"
              className="temporal-btn"
              onClick={() => setIsPlaying(p => !p)}
              style={{ fontWeight: 600, padding: '3px 9px' }}
            >
              {isPlaying ? '⏸ Pause' : '▶ Play Replay'}
            </button>

            {/* Step back/forward */}
            <button
              className="temporal-btn"
              onClick={() => onChangeFilter(prev => ({ ...prev, currentTimeMs: Math.max(minMs, currentMs - 15 * 60000) }))}
              title="Step back 15 minutes"
            >
              -15m
            </button>
            <button
              className="temporal-btn"
              onClick={() => onChangeFilter(prev => ({ ...prev, currentTimeMs: Math.min(maxMs, currentMs + 15 * 60000) }))}
              title="Step forward 15 minutes"
            >
              +15m
            </button>

            {/* Speed toggle */}
            {[1, 2, 5].map(s => (
              <button
                key={s}
                className={`temporal-btn ${speed === s ? 'active' : ''}`}
                style={{ padding: '2px 6px', fontSize: 10 }}
                onClick={() => setSpeed(s)}
              >
                {s}x
              </button>
            ))}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span>
              Window: <span style={{ color: '#fff', fontWeight: 600 }}>{windowMinutes === 0 ? 'Full History' : formatTime(currentMs - windowMinutes * 60000) + ' → ' + formatTime(currentMs)}</span>
            </span>
          </div>
        </div>
      </div>

      {/* Velocity Telemetry & Top Mules */}
      {velocityData && (
        <div className="temporal-telemetry">
          <div className="temporal-telemetry-item">
            <span className="label">⚡ Rapid Mules:</span>
            <span className="val">{velocityData.rapid_mule_count || velocityData.top_velocity_mules?.length || 0}</span>
          </div>
          <div className="temporal-telemetry-item">
            <span className="label">Turnaround:</span>
            <span className="val">{velocityData.fastest_turnaround_str || velocityData.fastest_turnaround || '—'}</span>
          </div>
          <div className="temporal-telemetry-item">
            <span className="label">Max Velocity:</span>
            <span className="val">${Math.round(velocityData.max_velocity_usd_per_min || 0).toLocaleString()}/min</span>
          </div>
          <div className="temporal-telemetry-item">
            <span className="label">Rapid Flow:</span>
            <span className="val">${Math.round(velocityData.total_rapid_volume || 0).toLocaleString()}</span>
          </div>

          {/* Quick Click Mules */}
          {velocityData.top_velocity_mules?.length > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 'auto', overflowX: 'auto' }}>
              <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Focus Mule:</span>
              {velocityData.top_velocity_mules.slice(0, 4).map(m => {
                const muleId = m.id || m.mule_id || ''
                const muleName = m.name || m.mule_name || muleId || 'Mule'
                const firstName = String(muleName).split(' ')[0]
                const turnaround = m.fastest_turnaround || (m.avg_turnaround_minutes ? `${m.avg_turnaround_minutes}m` : '—')
                const vel = m.max_velocity_usd_per_min || m.max_velocity || 0
                return (
                  <div
                    key={muleId}
                    className="temporal-mule-chip"
                    onClick={() => onMuleClick?.(muleId)}
                    title={`Click to focus on ${muleName}: ${turnaround} turnaround, $${Math.round(vel).toLocaleString()}/min velocity`}
                  >
                    <span>⚡</span>
                    <strong>{firstName}</strong>
                    <span style={{ opacity: 0.8, fontSize: 10 }}>({turnaround})</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/* ── App ──────────────────────────────────────────────────────────────── */
const DEFAULT_CHAT_WIDTH = 420

export default function App() {
  const [sessionId, setSessionId] = useState(null)
  const [overview, setOverview] = useState(null)
  const [alerts, setAlerts] = useState([])
  const [graphData, setGraphData] = useState(null)
  const [activeTab, setActiveTab] = useState('graph')
  const [loading, setLoading] = useState(true)
  const [seeding, setSeeding] = useState(false)
  const [highlightIds, setHighlightIds] = useState([])
  const [highlightEdges, setHighlightEdges] = useState([])
  const [caption, setCaption] = useState(null)
  const [dbStatus, setDbStatus] = useState('checking')
  const [actions, setActions] = useState([])
  const [showIngestModal, setShowIngestModal] = useState(false)
  const [agentMode, setAgentMode] = useState('standard')  // 'standard' | 'single_agent' | 'swarm'
  const [chatWidth, setChatWidth] = useState(() => Number(localStorage.getItem('fs-chat-width')) || DEFAULT_CHAT_WIDTH)
  useEffect(() => { localStorage.setItem('fs-chat-width', chatWidth) }, [chatWidth])

  const startChatResize = (e) => {
    e.preventDefault()
    const onMove = (ev) => {
      const max = Math.min(960, window.innerWidth - 420)
      setChatWidth(Math.round(Math.max(320, Math.min(max, window.innerWidth - ev.clientX))))
    }
    const onUp = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      document.body.classList.remove('resizing')
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    document.body.classList.add('resizing')
  }

  // Temporal Replay & Velocity Analysis States
  const [temporalActive, setTemporalActive] = useState(false)
  const [temporalTimeline, setTemporalTimeline] = useState(null)
  const [temporalVelocity, setTemporalVelocity] = useState(null)
  const [temporalFilter, setTemporalFilter] = useState({
    active: false,
    currentTimeMs: Date.now(),
    windowMinutes: 30,
    rapidOnly: false,
    rapidEdges: [],
  })

  const loadTemporalData = useCallback(async (winMins = 30) => {
    try {
      const [tl, vel] = await Promise.all([
        getTemporalTimeline(winMins).catch(() => null),
        getTemporalVelocity({ window_minutes: winMins }).catch(() => null),
      ])
      if (tl) {
        setTemporalTimeline(tl)
        const computedMax = tl.max_timestamp_ms || (tl.max_timestamp ? new Date(tl.max_timestamp).getTime() : Date.now())
        setTemporalFilter(prev => ({
          ...prev,
          currentTimeMs: prev.currentTimeMs && prev.currentTimeMs > 0 ? prev.currentTimeMs : computedMax,
        }))
      }
      if (vel) {
        setTemporalVelocity(vel)
        const edges = vel.rapid_relays?.flatMap(r => [
          `${r.source_account}|${r.mule_account}`,
          `${r.mule_account}|${r.target_account}`,
        ]) || []
        setTemporalFilter(prev => ({
          ...prev,
          rapidEdges: edges,
        }))
      }
    } catch (err) {
      console.error('Failed to load temporal data:', err)
    }
  }, [])

  const toggleTemporal = async () => {
    const next = !temporalActive
    setTemporalActive(next)
    setTemporalFilter(prev => ({ ...prev, active: next }))
    if (next && !temporalTimeline) {
      await loadTemporalData(temporalFilter.windowMinutes || 30)
    }
    setActiveTab('graph')
  }

  const handleMuleClick = async (muleId) => {
    try {
      const subgraph = await getSubgraph(muleId, 2)
      if (subgraph?.nodes?.length) {
        showGraph({ nodes: subgraph.nodes, edges: subgraph.edges }, [muleId])
      }
    } catch (e) { console.error(e) }
  }

  const handleIngestSuccess = async (res) => {
    await handleRefresh()
    if (res?.overview) setOverview(res.overview)
    const full = await getFullGraph().catch(() => null)
    if (full?.nodes?.length) showGraph(full)
  }

  const refreshActions = useCallback(() => {
    getActions().then(d => setActions(d.actions || [])).catch(() => {})
  }, [])

  const showGraph = useCallback((data, ids = [], edges = [], text = null) => {
    if (data) setGraphData(data)
    setHighlightIds(ids)
    setHighlightEdges(edges)
    setCaption(text)
  }, [])

  const handleEvidence = useCallback((ev) => {
    showGraph(ev.graph, ev.ids, ev.edges, ev.caption)
    setActiveTab('graph')
  }, [showGraph])

  const handleDetectRings = async () => {
    const res = await getCommunities().catch(() => null)
    const ev = evidenceFromResult(res && { ...res, tool: 'detect_fraud_communities' })
    if (ev) handleEvidence(ev)
  }

  const handleReview = async (actionId, decision) => {
    await reviewAction(actionId, decision).catch(e => alert(e.response?.data?.detail || e.message))
    refreshActions()
    const [ov, al] = await Promise.all([getOverview().catch(() => null), getAlerts(30).catch(() => null)])
    if (ov) setOverview(ov)
    if (al) setAlerts(al.alerts || [])
  }

  const pendingActions = actions.filter(a => a.status === 'PENDING_APPROVAL').length

  // Init
  useEffect(() => {
    async function init() {
      try {
        const sess = await createSession()
        setSessionId(sess.session_id)

        const [ov, al, gd] = await Promise.all([
          getOverview().catch(() => null),
          getAlerts(30).catch(() => ({ alerts: [] })),
          getFullGraph().catch(() => null),
        ])

        if (ov) { setOverview(ov); setDbStatus('connected') }
        else setDbStatus('error')
        setAlerts(al?.alerts || [])
        if (gd?.nodes?.length) setGraphData(gd)
        refreshActions()
        loadTemporalData()
      } catch (e) {
        setDbStatus('error')
        console.error('Init error:', e)
      } finally {
        setLoading(false)
      }
    }
    init()
  }, [refreshActions, loadTemporalData])

  const handleSeed = async () => {
    setSeeding(true)
    try {
      await seedDatabase()
      const [ov, al, gd] = await Promise.all([
        getOverview(), getAlerts(30), getFullGraph()
      ])
      setOverview(ov)
      setAlerts(al?.alerts || [])
      if (gd?.nodes?.length) showGraph(gd)
      refreshActions()
      loadTemporalData()
      setDbStatus('connected')
    } catch (e) {
      alert('Seeding failed: ' + e.message)
    } finally {
      setSeeding(false)
    }
  }

  const handleNodeClick = async (node) => {
    if (node.type !== 'Account') return
    try {
      const subgraph = await getSubgraph(node.id, 3)
      if (subgraph?.nodes?.length) showGraph({ nodes: subgraph.nodes, edges: subgraph.edges }, [node.id])
    } catch (e) { console.error(e) }
  }

  const handleAlertClick = async (alert) => {
    const accountId = alert.account_id || alert.id
    if (!accountId) return
    setActiveTab('graph')
    try {
      const subgraph = await getSubgraph(accountId, 3)
      if (subgraph?.nodes?.length) showGraph({ nodes: subgraph.nodes, edges: subgraph.edges }, [accountId])
    } catch (e) { console.error(e) }
  }

  const handleRefresh = async () => {
    const [ov, al, gd] = await Promise.all([
      getOverview().catch(() => null),
      getAlerts(30).catch(() => ({ alerts: [] })),
      getFullGraph().catch(() => null),
    ])
    if (ov) setOverview(ov)
    setAlerts(al?.alerts || [])
    if (gd?.nodes?.length) showGraph(gd)
    refreshActions()
    loadTemporalData()
  }

  const TABS = [
    { id: 'graph',    label: 'Knowledge Graph', Icon: Icon.Graph },
    { id: 'actions',  label: 'Actions',          Icon: Icon.Alert, count: pendingActions },
    { id: 'overview', label: 'Overview',         Icon: Icon.Stats },
    { id: 'memory',   label: 'Agent Memory',     Icon: Icon.Memory },
  ]

  return (
    <div className="app-shell" style={{ '--chat-w': `${chatWidth}px` }}>
      {/* ── Header ── */}
      <header className="header">
        <div className="header-brand">
          <div className="brand-icon">🕵️</div>
          <span className="brand-name">FraudScope AI</span>
          <span className="brand-badge">Powered by FalkorDB</span>
        </div>

        <div className="header-stats">
          <div className="stat-chip">
            <div className={`dot ${dbStatus === 'connected' ? '' : 'danger'}`} />
            <span>{dbStatus === 'connected' ? 'FalkorDB Connected' : 'FalkorDB Offline'}</span>
          </div>
          <div className="stat-chip">
            <div className="dot warning" />
            <span>Alerts: </span>
            <span className="stat-value">{alerts.filter(a => a.severity === 'CRITICAL').length}</span>
            <span> CRITICAL</span>
          </div>
          <div className="stat-chip">
            <div className="dot" />
            <span>Accounts: </span>
            <span className="stat-value">{overview?.node_counts?.Account ?? '—'}</span>
          </div>
        </div>

        <div className="header-actions">
          <button className="btn btn-ghost" onClick={handleRefresh}>
            ↻ Refresh
          </button>
          <button
            className="btn btn-ghost"
            style={{ borderColor: 'rgba(16,185,129,0.3)', color: 'var(--success)' }}
            onClick={handleSeed}
            disabled={seeding}
          >
            <Icon.Seed />
            {seeding ? 'Seeding…' : 'Seed DB'}
          </button>
          <button
            className="btn btn-ghost"
            style={{ borderColor: 'rgba(250,204,21,0.35)', color: '#facc15' }}
            onClick={handleDetectRings}
          >
            Detect Rings
          </button>
          <button
            id="temporal-replay-btn"
            className={`btn btn-ghost ${temporalActive ? 'active' : ''}`}
            style={{
              borderColor: temporalActive ? '#f59e0b' : 'rgba(245, 158, 11, 0.4)',
              color: '#f59e0b',
              background: temporalActive ? 'rgba(245, 158, 11, 0.18)' : 'transparent',
              boxShadow: temporalActive ? '0 0 14px rgba(245, 158, 11, 0.35)' : 'none',
              fontWeight: 600,
            }}
            onClick={toggleTemporal}
            title="Open Temporal Replay & Money Velocity scrubber"
          >
            <span>🕒 Time Replay</span>
            {temporalVelocity?.rapid_relay_count > 0 && (
              <span style={{
                background: '#f59e0b',
                color: '#090d16',
                fontSize: 10,
                padding: '1px 5px',
                borderRadius: 10,
                fontWeight: 700,
                marginLeft: 3,
              }}>
                {temporalVelocity.rapid_relay_count}⚡
              </span>
            )}
          </button>
          <button
            className="btn btn-ghost"
            style={{ borderColor: 'rgba(168,85,247,0.4)', color: '#c084fc' }}
            onClick={() => setShowIngestModal(true)}
          >
            <Icon.Upload />
            Ingest Data
          </button>
          <button
            className="btn btn-ghost"
            style={{ borderColor: 'rgba(59,130,246,0.3)', color: 'var(--accent-glow)' }}
            onClick={async () => {
              const full = await getFullGraph().catch(() => null)
              if (full?.nodes?.length) showGraph(full)
            }}
          >
            Full Graph
          </button>
        </div>
      </header>

      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <AlertsSidebar alerts={alerts} onAlertClick={handleAlertClick} />
      </aside>

      {/* ── Main ── */}
      <main className="main-panel">
        <div className="tab-bar">
          {TABS.map(({ id, label, Icon: TabIcon, count }) => (
            <div
              key={id}
              className={`tab ${activeTab === id ? 'active' : ''}`}
              onClick={() => { setActiveTab(id); if (id === 'actions') refreshActions() }}
            >
              <TabIcon />
              {label}
              {count > 0 && <span className="tab-count">{count}</span>}
            </div>
          ))}
        </div>

        <div className="tab-content">
          {loading && (
            <div className="loading-overlay">
              <div className="spinner" />
              <div className="loading-text">Connecting to FalkorDB…</div>
            </div>
          )}

          {!loading && activeTab === 'graph' && (
            <div className="fade-in" style={{ height: '100%', position: 'relative' }}>
              {graphData ? (
                <>
                  <GraphCanvas
                    graphData={graphData}
                    onNodeClick={handleNodeClick}
                    highlightIds={highlightIds}
                    highlightEdges={highlightEdges}
                    caption={caption}
                    temporalFilter={temporalActive ? temporalFilter : null}
                  />
                  {temporalActive && (
                    <TemporalReplayBar
                      timeline={temporalTimeline}
                      velocityData={temporalVelocity}
                      temporalFilter={temporalFilter}
                      onChangeFilter={setTemporalFilter}
                      onMuleClick={handleMuleClick}
                      onClose={() => {
                        setTemporalActive(false)
                        setTemporalFilter(prev => ({ ...prev, active: false }))
                      }}
                    />
                  )}
                </>
              ) : (
                <div className="empty-state">
                  <div className="empty-icon">🌐</div>
                  <div>No graph data loaded</div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    Click "Seed DB" to load synthetic fraud data
                  </div>
                  <button className="btn btn-primary" onClick={handleSeed} disabled={seeding}>
                    <Icon.Seed /> {seeding ? 'Seeding…' : 'Seed Database'}
                  </button>
                </div>
              )}
            </div>
          )}

          {!loading && activeTab === 'actions' && (
            <div className="fade-in" style={{ height: '100%', overflowY: 'auto', padding: 20 }}>
              <ActionsPanel actions={actions} onReview={handleReview} onRefresh={refreshActions} />
            </div>
          )}

          {!loading && activeTab === 'overview' && (
            <div className="fade-in" style={{ height: '100%', overflowY: 'auto' }}>
              <OverviewPanel overview={overview} />
            </div>
          )}

          {!loading && activeTab === 'memory' && (
            <div className="fade-in" style={{ height: '100%', overflowY: 'auto', padding: 20 }}>
              <AgentMemoryPanel sessionId={sessionId} />
            </div>
          )}
        </div>
      </main>

      {/* ── Chat ── */}
      <aside className="chat-panel" style={{ position: 'relative' }}>
        <div
          className="chat-resizer"
          onPointerDown={startChatResize}
          onDoubleClick={() => setChatWidth(DEFAULT_CHAT_WIDTH)}
          title="Drag to resize · double-click to reset"
        />
        <ChatPanel
          sessionId={sessionId}
          onEvidence={handleEvidence}
          onActionProposed={refreshActions}
          agentMode={agentMode}
          onAgentModeChange={setAgentMode}
        />
      </aside>

      {/* ── Ingestion Modal ── */}
      <IngestModal
        isOpen={showIngestModal}
        onClose={() => setShowIngestModal(false)}
        onIngested={handleIngestSuccess}
      />
    </div>
  )
}

/* ── AgentMemoryPanel ───────────────────────────────────────────────── */
function AgentMemoryPanel({ sessionId }) {
  const [memories, setMemories] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!sessionId) return
    getMemory(sessionId)
      .then(data => setMemories(data.memories || []))
      .catch(() => setMemories([]))
      .finally(() => setLoading(false))
  }, [sessionId])

  if (loading) return <div className="loading-overlay" style={{ position: 'relative' }}><div className="spinner" /></div>

  if (!memories.length) return (
    <div className="empty-state">
      <div className="empty-icon">🧠</div>
      <div>No memories yet</div>
      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
        The agent saves key findings here as it investigates
      </div>
    </div>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent-glow)', marginBottom: 4 }}>
        🧠 Agent Memory Graph — Session {sessionId?.slice(0, 8)}
      </div>
      {memories.map((m, i) => (
        <div key={m.id} className="stat-card" style={{ gap: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-muted)' }}>
            <span style={{ fontFamily: 'var(--font-mono)' }}>{m.id}</span>
            <span>{new Date(m.timestamp).toLocaleTimeString()}</span>
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-primary)', lineHeight: 1.5 }}>{m.finding}</div>
          {m.account_id && (
            <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--accent-cyan)' }}>
              Account: {m.account_id}
            </div>
          )}
          {m.tags?.length > 0 && (
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {m.tags.map(t => (
                <span key={t} style={{
                  fontSize: 10, background: 'var(--bg-elevated)', border: '1px solid var(--border)',
                  padding: '2px 6px', borderRadius: 10, color: 'var(--text-muted)'
                }}>{t}</span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

/* ── ActionsPanel (human-in-the-loop) ───────────────────────────────── */
const ACTION_LABELS = {
  freeze_account: '🧊 Freeze account',
  open_case: '📁 Open case',
  escalate_alert: '🚨 Escalate alerts',
  file_sar: '📝 File SAR',
  clear_account: '✅ Clear account',
}

function ActionsPanel({ actions, onReview, onRefresh }) {
  const [busy, setBusy] = useState(null)

  const review = async (id, decision) => {
    setBusy(id)
    try { await onReview(id, decision) } finally { setBusy(null) }
  }

  if (!actions.length) return (
    <div className="empty-state">
      <div className="empty-icon">🛡️</div>
      <div>No actions proposed yet</div>
      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
        Ask the agent to "sweep the graph and propose actions" — proposals land here for your approval
      </div>
    </div>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent-glow)' }}>
          🛡️ Agent-proposed actions — stored as (:Action)-[:TARGETS|EVIDENCED_BY]-&gt; nodes in FalkorDB
        </div>
        <button className="btn btn-ghost" onClick={onRefresh}>↻</button>
      </div>
      {actions.map(a => {
        const pending = a.status === 'PENDING_APPROVAL'
        return (
          <div key={a.action_id} className={`action-card ${pending ? 'pending' : a.status.toLowerCase()}`}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span className="action-type">{ACTION_LABELS[a.action_type] || a.action_type}</span>
              <span className={`status-pill ${a.status}`}>{a.status.replace('_', ' ')}</span>
            </div>
            <div style={{ fontSize: 13 }}>
              <strong>{a.account_name}</strong>{' '}
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>{a.account_id}</span>
              <span style={{ marginLeft: 8, fontSize: 11, color: riskColor(a.risk_score) }}>
                risk {(a.risk_score * 100).toFixed(0)}% · {a.account_status}
              </span>
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{a.reason}</div>
            {a.evidence?.length > 0 && (
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}>
                <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>EVIDENCED_BY</span>
                {a.evidence.map(e => <span key={e} className="evidence-chip">{e}</span>)}
              </div>
            )}
            {pending ? (
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn btn-success" disabled={busy === a.action_id} onClick={() => review(a.action_id, 'approve')}>
                  Approve &amp; execute
                </button>
                <button className="btn btn-ghost" disabled={busy === a.action_id} onClick={() => review(a.action_id, 'reject')}>
                  Reject
                </button>
              </div>
            ) : (
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                {a.status.toLowerCase()} by {a.reviewed_by} · {a.reviewed_at && new Date(a.reviewed_at).toLocaleString()}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
