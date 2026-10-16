import { useState, useEffect, useRef, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import GraphCanvas from './GraphCanvas.jsx'
import {
  createSession, getOverview, getAlerts, getFullGraph,
  getSubgraph, sendChat, seedDatabase, searchAccounts, getMemory
} from './api.js'

/* ── Icons (inline SVG, no deps) ─────────────────────────────────────── */
const Icon = {
  Send:    () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>,
  Search:  () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>,
  Alert:   () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>,
  Graph:   () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="5" r="3"/><circle cx="19" cy="19" r="3"/><circle cx="5" cy="19" r="3"/><line x1="12" y1="8" x2="5" y2="16"/><line x1="12" y1="8" x2="19" y2="16"/></svg>,
  Stats:   () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>,
  Brain:   () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9.5 2a2.5 2.5 0 015 0"/><path d="M14.5 22a2.5 2.5 0 01-5 0"/><path d="M20 6a2 2 0 012 2v8a2 2 0 01-2 2"/><path d="M4 18a2 2 0 01-2-2V8a2 2 0 012-2"/><path d="M14.5 2A3.5 3.5 0 0118 5.5v13a3.5 3.5 0 01-3.5 3.5"/><path d="M9.5 2A3.5 3.5 0 006 5.5v13A3.5 3.5 0 009.5 22"/></svg>,
  Seed:    () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 22V12"/><path d="M12 12C12 7 7 4 2 4c0 5 3 9 10 8"/><path d="M12 12c0-5 5-8 10-8-0 5-3 9-10 8"/></svg>,
  Tool:    () => <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/></svg>,
  Chevron: ({ open }) => <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ transform: open ? 'rotate(90deg)' : 'rotate(0)', transition: '200ms' }}><polyline points="9 18 15 12 9 6"/></svg>,
  Memory:  () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="6" width="20" height="12" rx="2"/><line x1="6" y1="12" x2="6" y2="12"/><line x1="10" y1="12" x2="10" y2="12"/><line x1="14" y1="12" x2="14" y2="12"/><line x1="18" y1="12" x2="18" y2="12"/></svg>,
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

/* ── ToolCallCard ────────────────────────────────────────────────────── */
function ToolCallCard({ tc, result }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="tool-call-card">
      <div className="tool-call-header" onClick={() => setOpen(o => !o)}>
        <Icon.Tool />
        <span className="tool-name">{tc.tool}()</span>
        <Icon.Chevron open={open} />
        <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-muted)' }}>
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
                    Object.entries(result).filter(([k]) => !['nodes','edges','outflows','inflows','shared_accounts','memories','alerts'].includes(k))
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

/* ── ChatPanel ───────────────────────────────────────────────────────── */
function ChatPanel({ sessionId, onGraphUpdate, onAccountFocus }) {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: `👋 **FraudScope AI** is ready. I have access to the FalkorDB fraud graph.

Try asking me:
- *"Give me an overview of the fraud graph"*
- *"Show me all active critical alerts"*
- *"Investigate account ACC_xxxxx for fraud rings"*
- *"Trace the money flow from SHELL_xxxxx"*`,
      toolCalls: [],
      toolResults: [],
    }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef(null)
  const inputRef = useRef(null)

  const QUICK_PROMPTS = [
    'Graph overview',
    'Show active alerts',
    'Find all fraud rings',
    'Explain your last finding',
    'What did I investigate before?',
    'Show high-risk accounts',
  ]

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = useCallback(async (text) => {
    const msg = text || input.trim()
    if (!msg || loading || !sessionId) return

    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: msg, toolCalls: [], toolResults: [] }])
    setLoading(true)

    try {
      const result = await sendChat(msg, sessionId)
      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          content: result.response,
          toolCalls: result.tool_calls || [],
          toolResults: result.tool_results || [],
        }
      ])

      // Update graph if subgraph data returned
      const subgraphResult = result.tool_results?.find(r =>
        r.tool === 'find_fraud_rings' && r.nodes
      )
      if (subgraphResult) onGraphUpdate?.({ nodes: subgraphResult.nodes, edges: subgraphResult.edges })

      // Focus account if investigated
      const riskResult = result.tool_results?.find(r => r.tool === 'compute_risk_score' && r.account_id)
      if (riskResult) onAccountFocus?.(riskResult.account_id)

    } catch (err) {
      const detail = err.response?.data?.detail || err.message || 'Request failed'
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: `❌ Error: ${detail}`, toolCalls: [], toolResults: [] }
      ])
    } finally {
      setLoading(false)
    }
  }, [input, loading, sessionId, onGraphUpdate, onAccountFocus])

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  return (
    <>
      <div className="chat-header">
        <div className="chat-title">
          <div className="agent-avatar">🕵️</div>
          <div>
            <div>FraudScope Agent</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 400 }}>
              {loading ? (
                <span style={{ color: 'var(--accent-cyan)' }}>● Investigating…</span>
              ) : '● Online'}
            </div>
          </div>
        </div>
        {sessionId && <div className="session-badge">{sessionId.slice(0, 8)}</div>}
      </div>

      <div className="chat-messages">
        {messages.map((msg, i) => (
          <div key={i} className={`message ${msg.role === 'user' ? 'user' : 'assistant'}`}>
            {/* Tool calls (before response) */}
            {msg.role === 'assistant' && msg.toolCalls?.length > 0 && (
              <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 6 }}>
                {msg.toolCalls.map((tc, j) => (
                  <ToolCallCard key={j} tc={tc} result={msg.toolResults?.[j]} />
                ))}
              </div>
            )}
            {msg.content && (
              <div className="message-bubble">
                {msg.role === 'assistant' ? (
                  <div className="markdown-body">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                  </div>
                ) : msg.content}
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div className="message assistant">
            <div className="typing-indicator">
              <div className="typing-dot" />
              <div className="typing-dot" />
              <div className="typing-dot" />
              <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 4 }}>Querying graph…</span>
            </div>
          </div>
        )}
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
            {['Account', 'Transaction', 'Entity', 'IPAddress', 'Device', 'AlertEvent', 'Memory'].map(n => (
              <div key={n} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '2px 0' }}>
                <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent-cyan)' }} />
                {n}
              </div>
            ))}
          </div>
          <div>
            <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>Edge Types</div>
            {['TRANSACTED_WITH', 'USES_IP', 'USES_DEVICE', 'OWNED_BY', 'HAS_ALERT', 'FOLLOWED_BY'].map(e => (
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

/* ── App ──────────────────────────────────────────────────────────────── */
export default function App() {
  const [sessionId, setSessionId] = useState(null)
  const [overview, setOverview] = useState(null)
  const [alerts, setAlerts] = useState([])
  const [graphData, setGraphData] = useState(null)
  const [activeTab, setActiveTab] = useState('graph')
  const [loading, setLoading] = useState(true)
  const [seeding, setSeeding] = useState(false)
  const [highlightIds, setHighlightIds] = useState([])
  const [dbStatus, setDbStatus] = useState('checking')

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
      } catch (e) {
        setDbStatus('error')
        console.error('Init error:', e)
      } finally {
        setLoading(false)
      }
    }
    init()
  }, [])

  const handleSeed = async () => {
    setSeeding(true)
    try {
      await seedDatabase()
      const [ov, al, gd] = await Promise.all([
        getOverview(), getAlerts(30), getFullGraph()
      ])
      setOverview(ov)
      setAlerts(al?.alerts || [])
      if (gd?.nodes?.length) setGraphData(gd)
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
      if (subgraph?.nodes?.length) {
        setGraphData({ nodes: subgraph.nodes, edges: subgraph.edges })
        setHighlightIds([node.id])
      }
    } catch (e) { console.error(e) }
  }

  const handleAlertClick = async (alert) => {
    const accountId = alert.account_id || alert.id
    if (!accountId) return
    setActiveTab('graph')
    try {
      const subgraph = await getSubgraph(accountId, 3)
      if (subgraph?.nodes?.length) {
        setGraphData({ nodes: subgraph.nodes, edges: subgraph.edges })
        setHighlightIds([accountId])
      }
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
    if (gd?.nodes?.length) setGraphData(gd)
  }

  const TABS = [
    { id: 'graph',    label: 'Knowledge Graph', Icon: Icon.Graph },
    { id: 'overview', label: 'Overview',         Icon: Icon.Stats },
    { id: 'memory',   label: 'Agent Memory',     Icon: Icon.Memory },
  ]

  return (
    <div className="app-shell">
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
            style={{ borderColor: 'rgba(59,130,246,0.3)', color: 'var(--accent-glow)' }}
            onClick={async () => {
              const full = await getFullGraph().catch(() => null)
              if (full?.nodes?.length) { setGraphData(full); setHighlightIds([]) }
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
          {TABS.map(({ id, label, Icon: TabIcon }) => (
            <div
              key={id}
              className={`tab ${activeTab === id ? 'active' : ''}`}
              onClick={() => setActiveTab(id)}
            >
              <TabIcon />
              {label}
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
            <div className="fade-in" style={{ height: '100%' }}>
              {graphData ? (
                <GraphCanvas
                  graphData={graphData}
                  onNodeClick={handleNodeClick}
                  highlightIds={highlightIds}
                />
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
      <aside className="chat-panel">
        <ChatPanel
          sessionId={sessionId}
          onGraphUpdate={(data) => { setGraphData(data); setActiveTab('graph') }}
          onAccountFocus={(id) => setHighlightIds([id])}
        />
      </aside>
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
