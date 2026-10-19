import { createRouter, createWebHistory } from 'vue-router'
import { can, getRole } from './auth'

const routes = [
  { path: '/', name: 'dashboard', component: () => import('./views/DashboardView.vue'), meta: { title: '工作台', eyebrow: 'Overview', permission: 'dashboard.view' } },
  { path: '/qa', name: 'qa', component: () => import('./views/QaView.vue'), meta: { title: '竞赛知识问答', eyebrow: 'Knowledge QA', permission: 'qa.use' } },
  { path: '/model-chat', name: 'model-chat', component: () => import('./views/LlmChatView.vue'), meta: { title: '通用模型问答', eyebrow: 'General Chat', permission: 'llm.use' } },
  { path: '/recommend', name: 'recommend', component: () => import('./views/RecommendView.vue'), meta: { title: '竞赛推荐', eyebrow: 'Match', permission: 'recommend.use' } },
  { path: '/prep', name: 'prep', component: () => import('./views/PrepView.vue'), meta: { title: '备赛辅助', eyebrow: 'Preparation', permission: 'prep.use' } },
  { path: '/review', name: 'review', component: () => import('./views/ReviewView.vue'), meta: { title: '项目指导辅助', eyebrow: 'Review', permission: 'review.use' } },
  { path: '/finance', name: 'finance', component: () => import('./views/FinanceView.vue'), meta: { title: '经费辅助', eyebrow: 'Finance', permission: 'finance.use' } },
  { path: '/competitions', name: 'competitions', component: () => import('./views/CompetitionsView.vue'), meta: { title: '赛事台账', eyebrow: 'Competitions', permission: 'competitions.read' } },
  { path: '/ledger', name: 'ledger', component: () => import('./views/LedgerView.vue'), meta: { title: '参赛与获奖台账', eyebrow: 'Ledger', permission: 'ledger.read' } },
  { path: '/stats', name: 'stats', component: () => import('./views/StatsView.vue'), meta: { title: '统计分析', eyebrow: 'Analytics', permission: 'stats.view' } },
  { path: '/knowledge', name: 'knowledge', component: () => import('./views/KnowledgeView.vue'), meta: { title: '知识库', eyebrow: 'RAG Library', permission: 'knowledge.read' } },
  { path: '/export', name: 'export', component: () => import('./views/ExportView.vue'), meta: { title: '结果导出', eyebrow: 'Export', permission: 'export.use' } },
  { path: '/workflows', name: 'workflows', component: () => import('./views/WorkflowsView.vue'), meta: { title: '智能体工作流', eyebrow: 'Orchestration', permission: 'workflows.use' } },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 })
})

router.beforeEach((to) => {
  if (to.meta.permission && !can(to.meta.permission, getRole())) {
    return { name: 'dashboard' }
  }
})

router.afterEach((to) => {
  document.title = `${to.meta.title || '工作台'} · 竞智`
})

export default router
