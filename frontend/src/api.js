import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export const createSession = () => api.post('/sessions').then(r => r.data)
export const getOverview   = () => api.get('/overview').then(r => r.data)
export const getAlerts     = (limit = 30) => api.get(`/alerts?limit=${limit}`).then(r => r.data)
export const searchAccounts = (q) => api.get(`/accounts/search?q=${encodeURIComponent(q)}`).then(r => r.data)
export const getAccount    = (id) => api.get(`/accounts/${id}`).then(r => r.data)
export const getSubgraph   = (id, hops = 3) => api.get(`/graph/subgraph/${id}?hops=${hops}`).then(r => r.data)
export const getFullGraph  = () => api.get('/graph/full').then(r => r.data)
export const getMoneyFlow  = (id) => api.get(`/accounts/${id}/flow`).then(r => r.data)
export const getInfra      = (id) => api.get(`/accounts/${id}/infrastructure`).then(r => r.data)
export const getMemory     = (sid) => api.get(`/sessions/${sid}/memory`).then(r => r.data)
export const seedDatabase  = () => api.post('/seed').then(r => r.data)
export const sendChat      = (message, session_id) => api.post('/chat', { message, session_id }).then(r => r.data)
export const getActions    = (status) => api.get('/actions', { params: status ? { status } : {} }).then(r => r.data)
export const reviewAction  = (id, decision) => api.post(`/actions/${id}/review`, { decision }).then(r => r.data)
export const getCommunities = () => api.get('/graph/communities').then(r => r.data)
export const getTemporalVelocity = (params = {}) => api.get('/temporal/velocity', { params }).then(r => r.data)
export const getTemporalTimeline = (window_minutes = 30) => api.get('/temporal/timeline', { params: { window_minutes } }).then(r => r.data)
export const ingestFile    = (formData) => api.post('/ingest/file', formData, { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data)
export const ingestJson    = (data, mode = 'append') => api.post('/ingest/json', { data, mode }).then(r => r.data)
export const ingestSample  = (mode = 'append') => api.post('/ingest/sample', null, { params: { mode } }).then(r => r.data)
export const getTemplateUrl = (type = 'csv') => `/api/ingest/template?type=${type}`

/** POST /api/chat/stream and invoke onEvent for every Server-Sent Event. */
export async function streamChat(message, session_id, onEvent) {
  const res = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id }),
  })
  if (!res.ok || !res.body) throw new Error(`Stream failed: HTTP ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let sep
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const chunk = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const data = chunk.split('\n').filter(l => l.startsWith('data: ')).map(l => l.slice(6)).join('')
      if (data) onEvent(JSON.parse(data))
    }
  }
}

/** POST /api/chat/stream/single — Single-Agent Unified Investigator SSE stream. */
export async function streamSingleAgent(message, session_id, onEvent) {
  const res = await fetch('/api/chat/stream/single', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id }),
  })
  if (!res.ok || !res.body) throw new Error(`Single-agent stream failed: HTTP ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let sep
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const chunk = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const data = chunk.split('\n').filter(l => l.startsWith('data: ')).map(l => l.slice(6)).join('')
      if (data) onEvent(JSON.parse(data))
    }
  }
}

/** POST /api/chat/stream/swarm — Multi-Agent Swarm SSE stream. */
export async function streamSwarm(message, session_id, onEvent) {
  const res = await fetch('/api/chat/stream/swarm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id }),
  })
  if (!res.ok || !res.body) throw new Error(`Swarm stream failed: HTTP ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let sep
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const chunk = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const data = chunk.split('\n').filter(l => l.startsWith('data: ')).map(l => l.slice(6)).join('')
      if (data) onEvent(JSON.parse(data))
    }
  }
}
