import { useEffect, useRef, useState, useCallback } from 'react'
import * as d3 from 'd3'

/* ── Color mapping ─────────────────────────────────────────────────── */
const NODE_COLORS = {
  Account: '#3b82f6',
  IPAddress: '#8b5cf6',
  Device: '#06b6d4',
  Entity: '#10b981',
  shell_company: '#dc2626',
  mule: '#ea580c',
  crypto_exchange: '#eab308',
}

const EVIDENCE_COLOR = '#facc15'

const EDGE_COLORS = {
  TRANSACTED_WITH: '#3b82f6',
  USES_IP: '#8b5cf6',
  USES_DEVICE: '#06b6d4',
  OWNED_BY: '#10b981',
  HAS_ALERT: '#f59e0b',
  default: '#334155',
}

function getNodeColor(node) {
  if (node.entity_type === 'shell_company') return NODE_COLORS.shell_company
  if (node.entity_type === 'mule') return NODE_COLORS.mule
  if (node.entity_type === 'crypto_exchange') return NODE_COLORS.crypto_exchange
  if (node.is_suspicious) return '#ef4444'
  return NODE_COLORS[node.type] || '#64748b'
}

function getNodeRadius(node) {
  const risk = node.risk_score || 0
  if (node.type === 'Account') return 10 + risk * 14
  if (node.type === 'IPAddress') return 7
  if (node.type === 'Device') return 7
  return 9
}

export default function GraphCanvas({
  graphData,
  onNodeClick,
  highlightIds = [],
  highlightEdges = [],
  caption,
  temporalFilter = null,
}) {
  const svgRef = useRef(null)
  const simRef = useRef(null)
  const [tooltip, setTooltip] = useState(null)
  const [edgeTooltip, setEdgeTooltip] = useState(null)
  const [selectedNode, setSelectedNode] = useState(null)

  const renderGraph = useCallback(() => {
    if (!svgRef.current || !graphData) return

    const { nodes: rawNodes, edges: rawEdges } = graphData
    if (!rawNodes?.length) return

    // Clear previous
    d3.select(svgRef.current).selectAll('*').remove()

    const el = svgRef.current
    const W = el.clientWidth || 800
    const H = el.clientHeight || 600

    const svg = d3.select(el)
      .attr('width', W)
      .attr('height', H)

    // Defs: arrow markers + glow filter
    const defs = svg.append('defs')

    // Glow filter
    const filter = defs.append('filter').attr('id', 'glow')
    filter.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'blur')
    const feMerge = filter.append('feMerge')
    feMerge.append('feMergeNode').attr('in', 'blur')
    feMerge.append('feMergeNode').attr('in', 'SourceGraphic')

    // Arrow marker standard
    defs.append('marker')
      .attr('id', 'arrow')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 22)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', '#334155')

    // Arrow marker suspicious
    defs.append('marker')
      .attr('id', 'arrow-suspicious')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 22)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', '#ef4444')

    // Arrow marker rapid relay
    defs.append('marker')
      .attr('id', 'arrow-rapid')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 24)
      .attr('refY', 0)
      .attr('markerWidth', 7)
      .attr('markerHeight', 7)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', '#f59e0b')

    // Zoom
    const g = svg.append('g')
    const zoom = d3.zoom()
      .scaleExtent([0.2, 4])
      .on('zoom', (e) => g.attr('transform', e.transform))
    svg.call(zoom)

    // Initial zoom to fit
    const initialScale = Math.min(W / 900, H / 700, 0.85)
    svg.call(zoom.transform, d3.zoomIdentity
      .translate(W / 2, H / 2)
      .scale(initialScale)
      .translate(-W / 2, -H / 2))

    // Build node/edge maps for D3
    const nodeIds = new Set(rawNodes.map(n => n.id))
    const nodes = rawNodes.map(n => ({ ...n }))
    const links = rawEdges
      .filter(e => nodeIds.has(e.source) && nodeIds.has(e.target) && e.source !== e.target)
      .map(e => ({ ...e }))

    // Simulation
    const sim = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links)
        .id(d => d.id)
        .distance(d => d.is_suspicious ? 80 : 120)
        .strength(0.5))
      .force('charge', d3.forceManyBody()
        .strength(d => d.is_suspicious ? -300 : -180))
      .force('center', d3.forceCenter(W / 2, H / 2))
      .force('collision', d3.forceCollide().radius(d => getNodeRadius(d) + 8))
    simRef.current = sim

    const evidenceEdges = new Set(highlightEdges)
    const hasEvidence = evidenceEdges.size > 0
    const endId = v => (typeof v === 'object' ? v.id : v)
    const isEvidence = d => {
      const s = endId(d.source), t = endId(d.target)
      return evidenceEdges.has(`${s}|${t}`) || evidenceEdges.has(`${t}|${s}`)
    }
    links.forEach(l => { l.evidence = isEvidence(l) })

    // Temporal filter evaluation
    const isTemporalActive = Boolean(temporalFilter?.active)
    const rapidEdgeSet = new Set(temporalFilter?.rapidEdges || [])
    const windowMs = (temporalFilter?.windowMinutes || 30) * 60 * 1000
    const currentTimeMs = temporalFilter?.currentTimeMs || Date.now()
    const isAllTime = (temporalFilter?.windowMinutes === 0)

    const isLinkActiveInTemporal = (d) => {
      if (!isTemporalActive) return true
      const s = endId(d.source), t = endId(d.target)
      const isRapid = Boolean(d.is_rapid_relay || rapidEdgeSet.has(`${s}|${t}`) || rapidEdgeSet.has(`${t}|${s}`))
      if (temporalFilter?.rapidOnly && !isRapid) return false
      if (isAllTime) return true
      if (!d.timestamp) return false
      try {
        const tMs = new Date(d.timestamp).getTime()
        return tMs <= currentTimeMs && tMs >= (currentTimeMs - windowMs)
      } catch {
        return false
      }
    }

    const activeNodeIds = new Set()
    links.forEach(l => {
      const s = endId(l.source), t = endId(l.target)
      l.isRapid = Boolean(l.is_rapid_relay || rapidEdgeSet.has(`${s}|${t}`) || rapidEdgeSet.has(`${t}|${s}`))
      l.temporalActive = isLinkActiveInTemporal(l)
      if (l.temporalActive) {
        activeNodeIds.add(s)
        activeNodeIds.add(t)
      }
    })

    const focusNodes = new Set(highlightIds)
    const dimNode = d => {
      if (focusNodes.size > 0 && hasEvidence && !focusNodes.has(d.id)) return true
      if (isTemporalActive && activeNodeIds.size > 0 && !activeNodeIds.has(d.id)) return true
      return false
    }

    // Edges
    const link = g.append('g')
      .selectAll('line')
      .data(links)
      .join('line')
      .attr('stroke', d => {
        if (d.evidence) return EVIDENCE_COLOR
        if (isTemporalActive) {
          if (d.temporalActive) {
            return d.isRapid ? '#f59e0b' : '#38bdf8'
          }
          return '#1e293b'
        }
        return d.is_suspicious ? '#ef4444' : (EDGE_COLORS[d.type] || EDGE_COLORS.default)
      })
      .attr('stroke-width', d => {
        if (d.evidence) return 3.5
        if (isTemporalActive) {
          if (d.temporalActive) return d.isRapid ? 4 : 2.5
          return 1
        }
        return d.is_suspicious ? 2 : 1
      })
      .attr('stroke-opacity', d => {
        if (d.evidence) return 1
        if (isTemporalActive) {
          return d.temporalActive ? (d.isRapid ? 1 : 0.85) : 0.08
        }
        return hasEvidence ? 0.12 : d.is_suspicious ? 0.8 : 0.4
      })
      .attr('stroke-dasharray', d => (isTemporalActive && d.temporalActive && d.isRapid) ? '6, 4' : null)
      .style('animation', d => (isTemporalActive && d.temporalActive && d.isRapid) ? 'dash-flow 1.2s linear infinite' : null)
      .attr('filter', d => (d.evidence || (isTemporalActive && d.temporalActive && d.isRapid)) ? 'url(#glow)' : null)
      .attr('marker-end', d => {
        if (d.type !== 'TRANSACTED_WITH') return null
        if (isTemporalActive && d.temporalActive && d.isRapid) return 'url(#arrow-rapid)'
        return d.is_suspicious ? 'url(#arrow-suspicious)' : 'url(#arrow)'
      })
      .attr('cursor', 'pointer')
      .on('mouseenter', (event, d) => {
        const [x, y] = d3.pointer(event, el)
        setEdgeTooltip({ edge: d, x, y })
      })
      .on('mouseleave', () => setEdgeTooltip(null))

    // Node groups
    const node = g.append('g')
      .selectAll('g')
      .data(nodes)
      .join('g')
      .attr('cursor', 'pointer')
      .attr('opacity', d => dimNode(d) ? 0.22 : 1)
      .call(
        d3.drag()
          .on('start', (event, d) => {
            if (!event.active) sim.alphaTarget(0.3).restart()
            d.fx = d.x; d.fy = d.y
          })
          .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y })
          .on('end', (event, d) => {
            if (!event.active) sim.alphaTarget(0)
            d.fx = null; d.fy = null
          })
      )

    // Circles
    node.append('circle')
      .attr('r', d => getNodeRadius(d))
      .attr('fill', d => getNodeColor(d))
      .attr('fill-opacity', d => (isTemporalActive && !activeNodeIds.has(d.id)) ? 0.35 : 0.85)
      .attr('stroke', d => {
        if (highlightIds.includes(d.id)) return hasEvidence ? EVIDENCE_COLOR : '#fff'
        if (isTemporalActive && activeNodeIds.has(d.id)) return '#f59e0b'
        if (d.is_suspicious) return '#ef4444'
        return 'rgba(255,255,255,0.15)'
      })
      .attr('stroke-width', d => {
        if (highlightIds.includes(d.id)) return 3
        if (isTemporalActive && activeNodeIds.has(d.id)) return 3
        return 1.5
      })
      .attr('filter', d => (d.is_suspicious || highlightIds.includes(d.id) || (isTemporalActive && activeNodeIds.has(d.id))) ? 'url(#glow)' : null)

    // Suspicious ring pulse overlay
    node.filter(d => d.is_suspicious)
      .append('circle')
      .attr('r', d => getNodeRadius(d) + 4)
      .attr('fill', 'none')
      .attr('stroke', '#ef4444')
      .attr('stroke-width', 1)
      .attr('stroke-opacity', 0.4)
      .style('animation', 'alert-pulse 2s ease infinite')

    // Labels
    node.append('text')
      .text(d => {
        const name = d.name || d.id || ''
        return name.length > 14 ? name.slice(0, 12) + '…' : name
      })
      .attr('text-anchor', 'middle')
      .attr('dy', d => getNodeRadius(d) + 13)
      .attr('font-size', '10px')
      .attr('font-family', 'Inter, sans-serif')
      .attr('fill', d => {
        if (isTemporalActive && activeNodeIds.has(d.id)) return '#fde68a'
        return d.is_suspicious ? '#fca5a5' : '#94a3b8'
      })
      .attr('pointer-events', 'none')

    // Interaction
    node
      .on('mouseenter', (event, d) => {
        const [x, y] = d3.pointer(event, el)
        setTooltip({ node: d, x, y })
      })
      .on('mouseleave', () => setTooltip(null))
      .on('click', (event, d) => {
        event.stopPropagation()
        setSelectedNode(d)
        onNodeClick?.(d)
      })

    svg.on('click', () => setSelectedNode(null))

    // Tick
    sim.on('tick', () => {
      link
        .attr('x1', d => d.source.x)
        .attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x)
        .attr('y2', d => d.target.y)
      node.attr('transform', d => `translate(${d.x},${d.y})`)
    })

    return () => sim.stop()
  }, [graphData, highlightIds, highlightEdges, onNodeClick, temporalFilter])

  useEffect(() => {
    const cleanup = renderGraph()
    return cleanup
  }, [renderGraph])

  // Handle resize
  useEffect(() => {
    const ro = new ResizeObserver(() => renderGraph())
    if (svgRef.current) ro.observe(svgRef.current.parentElement)
    return () => ro.disconnect()
  }, [renderGraph])

  const riskColor = (score) => {
    if (score > 0.75) return 'var(--risk-critical)'
    if (score > 0.5)  return 'var(--risk-high)'
    if (score > 0.25) return 'var(--risk-medium)'
    return 'var(--risk-low)'
  }

  return (
    <div className="graph-canvas-wrapper">
      <svg ref={svgRef} />

      {caption && <div className="graph-caption">{caption}</div>}

      {/* Tooltip */}
      {tooltip && (
        <div
          className="graph-tooltip"
          style={{
            left: Math.min(tooltip.x + 16, window.innerWidth - 220),
            top: tooltip.y - 8,
          }}
        >
          <div className="tooltip-id">{tooltip.node.id}</div>
          <div className="tooltip-name">{tooltip.node.name || tooltip.node.type}</div>
          <div className="tooltip-row">
            <span>Type</span><span>{tooltip.node.type}</span>
          </div>
          {tooltip.node.risk_score !== undefined && (
            <div className="tooltip-row">
              <span>Risk</span>
              <span style={{ color: riskColor(tooltip.node.risk_score), fontWeight: 600 }}>
                {(tooltip.node.risk_score * 100).toFixed(0)}%
              </span>
            </div>
          )}
          {tooltip.node.country && (
            <div className="tooltip-row">
              <span>Country</span><span>{tooltip.node.country}</span>
            </div>
          )}
          {tooltip.node.is_suspicious && (
            <div style={{ color: 'var(--risk-critical)', fontWeight: 600, marginTop: 6, fontSize: 11 }}>
              ⚠ SUSPICIOUS
            </div>
          )}
          {tooltip.node.ring_id && (
            <div style={{ color: 'var(--risk-high)', fontSize: 11, marginTop: 2 }}>
              Ring: {tooltip.node.ring_id}
            </div>
          )}
        </div>
      )}

      {/* Edge Tooltip */}
      {edgeTooltip && (
        <div
          className="graph-tooltip"
          style={{
            left: Math.min(edgeTooltip.x + 16, window.innerWidth - 240),
            top: edgeTooltip.y - 8,
            borderColor: edgeTooltip.edge.isRapid ? 'var(--warning)' : 'var(--border-bright)',
          }}
        >
          <div className="tooltip-id" style={{ color: edgeTooltip.edge.isRapid ? 'var(--warning)' : 'var(--accent-cyan)' }}>
            {edgeTooltip.edge.isRapid ? '⚡ RAPID MULE RELAY' : 'TRANSACTION'}
          </div>
          <div className="tooltip-name">
            ${Number(edgeTooltip.edge.amount || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className="tooltip-row">
            <span>Route</span>
            <span style={{ fontSize: 11 }}>{(edgeTooltip.edge.source?.id || edgeTooltip.edge.source)} → {(edgeTooltip.edge.target?.id || edgeTooltip.edge.target)}</span>
          </div>
          {edgeTooltip.edge.timestamp && (
            <div className="tooltip-row">
              <span>Timestamp</span>
              <span style={{ fontSize: 10 }}>{new Date(edgeTooltip.edge.timestamp).toLocaleString()}</span>
            </div>
          )}
          {edgeTooltip.edge.channel && (
            <div className="tooltip-row">
              <span>Channel</span>
              <span style={{ textTransform: 'uppercase' }}>{edgeTooltip.edge.channel}</span>
            </div>
          )}
          {edgeTooltip.edge.turnaround_str && (
            <div className="tooltip-row" style={{ color: 'var(--warning)', fontWeight: 600 }}>
              <span>Turnaround</span>
              <span>⚡ {edgeTooltip.edge.turnaround_str}</span>
            </div>
          )}
          {edgeTooltip.edge.velocity_usd_per_min && (
            <div className="tooltip-row" style={{ color: 'var(--warning)' }}>
              <span>Velocity</span>
              <span>${edgeTooltip.edge.velocity_usd_per_min}/min</span>
            </div>
          )}
        </div>
      )}

      {/* Node detail panel */}
      {selectedNode && (
        <div className="node-detail-panel">
          <div className="node-detail-title">
            <span>Node Detail</span>
            <button
              onClick={() => setSelectedNode(null)}
              style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 16 }}
            >×</button>
          </div>
          {[
            ['ID', selectedNode.id],
            ['Name', selectedNode.name || '—'],
            ['Type', selectedNode.type],
            ['Country', selectedNode.country || '—'],
            ['Risk Score', selectedNode.risk_score != null ? `${(selectedNode.risk_score * 100).toFixed(1)}%` : '—'],
            ['Entity Type', selectedNode.entity_type || '—'],
            ['Ring ID', selectedNode.ring_id || '—'],
            ['Suspicious', selectedNode.is_suspicious ? '⚠ YES' : 'No'],
          ].map(([k, v]) => (
            <div key={k} className="detail-row">
              <span className="detail-key">{k}</span>
              <span className="detail-val" style={k === 'Suspicious' && v.includes('YES') ? { color: 'var(--risk-critical)' } : {}}>
                {v}
              </span>
            </div>
          ))}
          <button
            className="btn btn-primary"
            style={{ marginTop: 12, width: '100%', justifyContent: 'center' }}
            onClick={() => onNodeClick?.(selectedNode)}
          >
            Investigate →
          </button>
        </div>
      )}

      {/* Legend */}
      <div className="graph-legend">
        {[
          { color: '#3b82f6', label: 'Account' },
          { color: '#dc2626', label: 'Shell Company' },
          { color: '#ea580c', label: 'Mule Account' },
          { color: '#eab308', label: 'Cash-out Exchange' },
          { color: '#8b5cf6', label: 'IP Address' },
          { color: '#06b6d4', label: 'Device' },
          { color: '#10b981', label: 'Entity' },
        ].map(({ color, label }) => (
          <div key={label} className="legend-item">
            <div className="legend-dot" style={{ background: color }} />
            {label}
          </div>
        ))}
      </div>
    </div>
  )
}
