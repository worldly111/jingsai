export const ROLES = ['学生', '教师', '管理员']

const ROLE_KEY = 'ci.role'
const HEADER_KEYS = { 学生: 'student', 教师: 'teacher', 管理员: 'admin' }

const READER = [
  'dashboard.view',
  'qa.use',
  'recommend.use',
  'prep.use',
  'review.use',
  'llm.use',
  'stats.view',
  'competitions.read',
  'export.result'
]

const STAFF = [
  ...READER,
  'ledger.read',
  'finance.use',
  'knowledge.read',
  'export.use',
  'logs.view'
]

export const ROLE_PERMISSIONS = {
  学生: READER,
  教师: STAFF,
  管理员: [
    ...STAFF,
    'competitions.write',
    'finance.approve',
    'knowledge.write',
    'workflows.use'
  ]
}

export function getRole() {
  try {
    const saved = localStorage.getItem(ROLE_KEY)
    return ROLE_PERMISSIONS[saved] ? saved : '学生'
  } catch {
    return '学生'
  }
}

export function setRole(role) {
  if (!ROLE_PERMISSIONS[role]) return
  try {
    localStorage.setItem(ROLE_KEY, role)
  } catch {
    /* 无 localStorage 时仅在本次会话生效 */
  }
}

export function getRoleKey(role = getRole()) {
  return HEADER_KEYS[role] || 'student'
}

export function can(permission, role = getRole()) {
  return Boolean(permission && ROLE_PERMISSIONS[role]?.includes(permission))
}
