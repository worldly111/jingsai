import { getRoleKey } from './auth'

const BASE = import.meta.env.VITE_API_BASE || '/api'

export function qs(params = {}) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    if (Array.isArray(value)) {
      if (!value.length) return
      search.append(key, value.join(','))
    } else if (typeof value === 'boolean') {
      search.append(key, String(value))
    } else {
      search.append(key, String(value))
    }
  })
  const text = search.toString()
  return text ? `?${text}` : ''
}

async function request(path, { method = 'GET', body, headers = {}, signal } = {}) {
  const init = { method, headers: { 'X-User-Role': getRoleKey(), ...headers }, signal }
  if (body instanceof FormData) {
    init.body = body
  } else if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }
  const response = await fetch(`${BASE}${path}`, init)
  const type = response.headers.get('content-type') || ''
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`
    try {
      const data = type.includes('json') ? await response.json() : null
      detail = data?.detail || data?.message || detail
      if (Array.isArray(detail)) detail = detail.map((d) => d.msg || d).join('；')
    } catch {
      /* keep default message */
    }
    throw new Error(detail)
  }
  if (type.includes('application/json')) return response.json()
  return response
}

function filenameFrom(disposition, fallback) {
  if (!disposition) return fallback
  const utf = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf) {
    try {
      return decodeURIComponent(utf[1])
    } catch {
      return utf[1]
    }
  }
  const plain = disposition.match(/filename="?([^";]+)"?/i)
  return plain ? plain[1] : fallback
}

export async function download(path, fallbackName = '下载文件', { method = 'GET', body } = {}) {
  const init = { method, headers: { 'X-User-Role': getRoleKey() } }
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }
  const response = await fetch(`${BASE}${path}`, init)
  if (!response.ok) {
    let detail = `下载失败（${response.status}）`
    try {
      const data = await response.json()
      detail = data?.detail || detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  const blob = await response.blob()
  const name = filenameFrom(response.headers.get('content-disposition'), fallbackName)
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 4000)
  return name
}

export const api = {
  health: () => request('/health'),
  agents: () => request('/meta/agents'),
  agentDetail: (agent) => request(`/meta/agents/${agent}`),
  options: () => request('/meta/options'),

  runAgent: (agent, body) => request(`/agents/${agent}/run`, { method: 'POST', body }),

  qaSessions: (limit = 30) => request(`/qa/sessions${qs({ limit })}`),
  qaSession: (id) => request(`/qa/sessions/${id}`),
  qaAsk: (body) => request('/qa/ask', { method: 'POST', body }),
  deleteSession: (id) => request(`/qa/sessions/${id}`, { method: 'DELETE' }),

  llmModels: () => request('/llm/models'),
  llmChat: (body) => request('/llm/chat', { method: 'POST', body }),

  competitions: (params = {}) => request(`/competitions${qs(params)}`),
  competition: (id, year) => request(`/competitions/${id}${qs({ year })}`),
  upcoming: (days = 180) => request(`/competitions/upcoming${qs({ days })}`),
  createCompetition: (body) => request('/competitions', { method: 'POST', body }),
  updateCompetition: (id, body) => request(`/competitions/${id}`, { method: 'PUT', body }),
  upsertEdition: (id, body) => request(`/competitions/${id}/editions`, { method: 'POST', body }),
  ledger: (params = {}) => request(`/ledger/registrations${qs(params)}`),
  rules: () => request('/rules'),

  planBudget: (payload) => request('/finance/budgets/plan', { method: 'POST', body: { payload } }),
  createBudget: (body) => request('/finance/budgets', { method: 'POST', body }),
  budgets: () => request('/finance/budgets'),
  budget: (id) => request(`/finance/budgets/${id}`),
  budgetStatus: (id, body) => request(`/finance/budgets/${id}/status`, { method: 'PATCH', body }),
  budgetDoc: (id, format = 'docx') => download(`/finance/budgets/${id}/doc${qs({ format })}`, `预算单.${format}`),

  planLoan: (payload) => request('/finance/loans/plan', { method: 'POST', body: { payload } }),
  createLoan: (body) => request('/finance/loans', { method: 'POST', body }),
  loans: () => request('/finance/loans'),
  loan: (id) => request(`/finance/loans/${id}`),
  loanStatus: (id, body) => request(`/finance/loans/${id}/status`, { method: 'PATCH', body }),
  loanDoc: (id, format = 'docx') => download(`/finance/loans/${id}/doc${qs({ format })}`, `借款单.${format}`),

  planReimbursement: (payload) => request('/finance/reimbursements/plan', { method: 'POST', body: { payload } }),
  createReimbursement: (body) => request('/finance/reimbursements', { method: 'POST', body }),
  reimbursements: () => request('/finance/reimbursements'),
  reimbursement: (id) => request(`/finance/reimbursements/${id}`),
  reimbursementStatus: (id, body) => request(`/finance/reimbursements/${id}/status`, { method: 'PATCH', body }),
  reimbursementDoc: (id, format = 'docx') => download(`/finance/reimbursements/${id}/doc${qs({ format })}`, `报销单.${format}`),
  financeSummary: () => request('/finance/summary'),

  statsOverview: (params = {}) => request(`/stats/overview${qs(params)}`),
  statsDimension: (dimension, params = {}) => request(`/stats/dimensions/${dimension}${qs(params)}`),
  statsCharts: () => request('/stats/charts'),
  statsChart: (kind, params = {}) => request(`/stats/chart/${kind}${qs(params)}`),

  knowledgeStats: () => request('/knowledge/stats'),
  knowledgeDocuments: (params = {}) => request(`/knowledge/documents${qs(params)}`),
  knowledgeDocument: (id) => request(`/knowledge/documents/${id}`),
  knowledgeSearch: (q, topK = 6) => request(`/knowledge/search${qs({ q, top_k: topK })}`),
  knowledgeReindex: () => request('/knowledge/reindex', { method: 'POST' }),
  knowledgeReindexOne: (id) => request(`/knowledge/documents/${id}/reindex`, { method: 'POST' }),
  knowledgeDelete: (id) => request(`/knowledge/documents/${id}`, { method: 'DELETE' }),
  knowledgeUpload: (form) => request('/knowledge/upload', { method: 'POST', body: form }),
  knowledgeFile: (id, name = '原始文件') => download(`/knowledge/documents/${id}/file`, name),
  reviewExtract: (form) => request('/review/extract', { method: 'POST', body: form }),

  logRuns: (params = {}) => request(`/logs/runs${qs(params)}`),
  logQa: (limit = 50) => request(`/logs/qa${qs({ limit })}`),
  logStats: () => request('/logs/stats'),
  qaFeedback: (id, body) => request(`/logs/qa/${id}/feedback`, { method: 'POST', body }),

  exportAgent: (body, format = 'docx') =>
    download(`/export/agent${qs({ format })}`, `${body.title || '智能体结果'}.${format}`, { method: 'POST', body }),
  exportTable: (body, format = 'xlsx') =>
    download('/export/table', `${body.title || '数据表'}.${format}`, { method: 'POST', body: { ...body, format } }),
  exportStats: (params, format = 'xlsx') => download(`/export/stats${qs({ ...params, format })}`, `竞赛统计报表.${format}`),
  exportAwards: (params) => download(`/export/awards${qs(params)}`, '获奖明细.xlsx'),
  exportRegistrations: (params) => download(`/export/registrations${qs(params)}`, '参赛台账.xlsx')
}
