import { reactive } from 'vue'
import { api } from './api'
import { can as hasPermission, getRole, setRole as persistRole } from './auth'

export const store = reactive({
  health: null,
  options: null,
  agents: [],
  agentProblems: [],
  loadingOptions: false,
  loadingHealth: false,
  role: getRole()
})

export function can(permission) {
  return hasPermission(permission, store.role)
}

export function changeRole(role) {
  store.role = role
  persistRole(role)
}

const AGENT_LABELS = {
  qa: '竞赛知识问答',
  recommend: '竞赛推荐',
  prep: '备赛辅助',
  review: '项目指导辅助',
  budget: '预算申请辅助',
  loan: '借款辅助',
  reimbursement: '报销辅助',
  stats: '竞赛数据统计'
}

let optionsPromise = null
let healthPromise = null

export function agentLabel(key) {
  return store.agents.find((a) => a.agent === key)?.name || AGENT_LABELS[key] || key
}

export async function ensureOptions(force = false) {
  if (store.options && !force) return store.options
  if (!optionsPromise || force) {
    store.loadingOptions = true
    optionsPromise = api
      .options()
      .then((data) => {
        store.options = data
        return data
      })
      .finally(() => {
        store.loadingOptions = false
      })
  }
  return optionsPromise
}

export async function ensureHealth(force = false) {
  if (store.health && !force) return store.health
  if (!healthPromise || force) {
    store.loadingHealth = true
    healthPromise = api
      .health()
      .then((data) => {
        store.health = data
        return data
      })
      .finally(() => {
        store.loadingHealth = false
      })
  }
  return healthPromise
}

export async function ensureAgents(force = false) {
  if (store.agents.length && !force) return store.agents
  const data = await api.agents()
  store.agents = data.items || []
  store.agentProblems = data.problems || []
  return store.agents
}
