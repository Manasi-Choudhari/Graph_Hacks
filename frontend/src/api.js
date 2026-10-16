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
