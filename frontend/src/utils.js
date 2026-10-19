export function fmtMoney(value, digits = 2) {
  const n = Number(value || 0)
  return n.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function fmtNumber(value) {
  return Number(value || 0).toLocaleString('zh-CN')
}

export function fmtDate(value) {
  if (!value) return '—'
  return String(value).slice(0, 10)
}

export function fmtDateTime(value) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 16)
}

export function pct(value, digits = 1) {
  return `${Number(value || 0).toFixed(digits)}%`
}

export const levelType = {
  国家级: 'danger',
  省级: 'warning',
  校级: 'info'
}

export const statusType = {
  已批准: 'success',
  已借出: 'warning',
  已报销: 'success',
  已通过: 'success',
  待审批: 'warning',
  待审核: 'warning',
  草稿: 'info',
  已驳回: 'danger',
  已冲销: 'success',
  报名中: 'primary',
  备赛中: 'warning',
  参赛中: 'primary',
  获奖: 'success',
  已入库: 'success',
  处理中: 'warning',
  失败: 'danger',
  进行中: 'primary',
  筹备中: 'info',
  已完赛: 'success'
}

export function tagType(value, map = statusType) {
  return map[value] || 'info'
}

export function displayValue(value) {
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) return value.join('、')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export function splitNames(value) {
  return String(value || '')
    .replace(/，/g, '、')
    .replace(/,/g, '、')
    .split('、')
    .map((x) => x.trim())
    .filter(Boolean)
}

export function greeting() {
  const h = new Date().getHours()
  if (h < 6) return '夜深了'
  if (h < 11) return '上午好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
}

export function todayText() {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'long'
  }).format(new Date())
}

export function daysUntil(value) {
  if (!value) return null
  const target = new Date(`${String(value).slice(0, 10)}T00:00:00`)
  const now = new Date()
  now.setHours(0, 0, 0, 0)
  return Math.round((target - now) / 86400000)
}

export const AGENT_ICONS = {
  qa: 'ChatLineRound',
  recommend: 'Compass',
  prep: 'Calendar',
  review: 'DocumentChecked',
  budget: 'Wallet',
  loan: 'CreditCard',
  reimbursement: 'Tickets',
  stats: 'DataAnalysis'
}

export const AGENT_PATHS = {
  qa: '/qa',
  recommend: '/recommend',
  prep: '/prep',
  review: '/review',
  budget: '/finance',
  loan: '/finance',
  reimbursement: '/finance',
  stats: '/stats'
}
