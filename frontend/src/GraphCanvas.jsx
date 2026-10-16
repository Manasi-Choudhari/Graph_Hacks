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
}

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

export default function GraphCanvas({ graphData, onNodeClick, highlightIds = [] }) {
  const svgRef = useRef(null)
  const simRef = useRef(null)
  const [tooltip, setTooltip] = useState(null)
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

    // Arrow marker
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

    // Edges
    const link = g.append('g')
      .selectAll('line')
      .data(links)
      .join('line')
      .attr('stroke', d => d.is_suspicious ? '#ef4444' : (EDGE_COLORS[d.type] || EDGE_COLORS.default))
      .attr('stroke-width', d => d.is_suspicious ? 2 : 1)
      .attr('stroke-opacity', d => d.is_suspicious ? 0.8 : 0.4)
      .attr('marker-end', d => d.type === 'TRANSACTED_WITH'
        ? (d.is_suspicious ? 'url(#arrow-suspicious)' : 'url(#arrow)')
        : null)

    // Node groups
    const node = g.append('g')
      .selectAll('g')
      .data(nodes)
      .join('g')
      .attr('cursor', 'pointer')
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
      .attr('fill-opacity', 0.85)
      .attr('stroke', d => {
        if (highlightIds.includes(d.id)) return '#fff'
        if (d.is_suspicious) return '#ef4444'
        return 'rgba(255,255,255,0.15)'
      })
      .attr('stroke-width', d => highlightIds.includes(d.id) ? 3 : 1.5)
      .attr('filter', d => (d.is_suspicious || highlightIds.includes(d.id)) ? 'url(#glow)' : null)

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
      .attr('fill', d => d.is_suspicious ? '#fca5a5' : '#94a3b8')
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
  }, [graphData, highlightIds, onNodeClick])

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
