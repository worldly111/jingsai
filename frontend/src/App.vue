<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ROLES, can as hasPermission, setRole } from './auth'
import { ensureAgents, ensureHealth, store } from './store'

const route = useRoute()
const router = useRouter()
const drawer = ref(false)

const navGroups = [
  {
    caption: '工作台',
    items: [{ name: 'dashboard', label: '总览工作台', icon: 'Odometer', permission: 'dashboard.view' }]
  },
  {
    caption: '智能体服务',
    items: [
      { name: 'qa', label: '竞赛知识问答', icon: 'ChatLineRound', badge: 'RAG', permission: 'qa.use' },
      { name: 'model-chat', label: '通用模型问答', icon: 'Cpu', badge: 'LLM', permission: 'llm.use' },
      { name: 'recommend', label: '竞赛推荐', icon: 'Compass', permission: 'recommend.use' },
      { name: 'prep', label: '备赛辅助', icon: 'Calendar', permission: 'prep.use' },
      { name: 'review', label: '项目指导辅助', icon: 'DocumentChecked', permission: 'review.use' },
      { name: 'finance', label: '预算 · 借款 · 报销', icon: 'Wallet', permission: 'finance.use' }
    ]
  },
  {
    caption: '数据与知识',
    items: [
      { name: 'competitions', label: '赛事台账', icon: 'TrophyBase', permission: 'competitions.read' },
      { name: 'ledger', label: '参赛获奖台账', icon: 'Notebook', permission: 'ledger.read' },
      { name: 'stats', label: '统计分析', icon: 'DataAnalysis', permission: 'stats.view' },
      { name: 'knowledge', label: '知识库', icon: 'Collection', permission: 'knowledge.read' }
    ]
  },
  {
    caption: '交付与运维',
    items: [
      { name: 'export', label: '结果导出', icon: 'Download', permission: 'export.use' },
      { name: 'workflows', label: '智能体工作流', icon: 'Share', permission: 'workflows.use' }
    ]
  }
]

const visibleNavGroups = computed(() =>
  navGroups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => hasPermission(item.permission, store.role))
    }))
    .filter((group) => group.items.length)
)

const activeName = computed(() => route.name)
const title = computed(() => route.meta.title || '工作台')
const eyebrow = computed(() => route.meta.eyebrow || 'Workspace')

const statusText = computed(() => {
  const h = store.health
  if (!h) return '连接中'
  return h.llm?.available ? `${h.llm.provider} · ${h.llm.model}` : '离线规则引擎'
})

const isOffline = computed(() => !store.health?.llm?.available)

function go(name) {
  router.push({ name })
  drawer.value = false
}

watch(
  () => store.role,
  async (role) => {
    setRole(role)
    await ensureAgents(true).catch(() => {})
    if (route.meta.permission && !hasPermission(route.meta.permission, role)) {
      router.replace({ name: 'dashboard' })
    }
  }
)

onMounted(() => {
  ensureHealth().catch(() => {})
})
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">
          <svg viewBox="0 0 32 32" fill="none" aria-hidden="true">
            <path d="M7 8h18v3H7zM7 14.5h11v3H7zM7 21h14v3H7z" fill="#f2fffd" />
            <circle cx="24" cy="23" r="5.4" fill="#0a3c3c" stroke="#7df0e2" stroke-width="1.4" />
            <path d="M21.7 23l1.7 1.7 3-3.4" stroke="#7df0e2" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </div>
        <div class="brand-text">
          <strong>竞智</strong>
          <span>Competition Intelligence</span>
        </div>
      </div>

      <nav>
        <div v-for="group in visibleNavGroups" :key="group.caption" class="nav-group">
          <div class="nav-caption">{{ group.caption }}</div>
          <div
            v-for="item in group.items"
            :key="item.name"
            class="nav-item"
            :class="{ active: activeName === item.name }"
            @click="go(item.name)"
          >
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
            <span v-if="item.badge" class="nav-badge">{{ item.badge }}</span>
          </div>
        </div>
      </nav>

      <div class="sidebar-spacer" />
      <div class="sidebar-note">
        <div class="note-title">
          <span class="dot" :class="{ offline: isOffline }" />
          {{ isOffline ? '离线规则通道运行中' : '大模型通道已启用' }}
        </div>
        <p>
          结构化台账负责事实与数据，知识库引用负责出处；大模型不可用时自动降级，答案仍然可追溯。
        </p>
      </div>
      <div class="sidebar-foot">
        <span>计算与智能技术学院</span>
        <span>v1.0</span>
      </div>
    </aside>

    <div class="main-col">
      <header class="topbar">
        <el-button class="mobile-menu" text circle @click="drawer = true">
          <el-icon size="19"><Menu /></el-icon>
        </el-button>
        <div class="crumb">
          <span class="eyebrow">{{ eyebrow }}</span>
          <strong>{{ title }}</strong>
        </div>
        <div class="topbar-right">
          <div class="system-pill hide-sm">
            <span class="dot" :class="{ offline: isOffline }" />
            {{ statusText }}
          </div>
          <select
            v-model="store.role"
            class="top-role"
            aria-label="当前身份"
            title="演示身份：切换后菜单与接口权限同步变化；正式部署由统一身份认证注入"
          >
            <option v-for="role in ROLES" :key="role" :value="role">{{ role }}</option>
          </select>
          <div class="avatar" title="计算与智能技术学院">计</div>
        </div>
      </header>

      <main class="page-wrap">
        <router-view v-slot="{ Component }">
          <transition name="page" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>

    <el-drawer v-model="drawer" direction="ltr" size="272px" :with-header="false" class="mobile-drawer">
      <div class="drawer-inner">
        <div class="brand">
          <div class="brand-mark">
            <svg viewBox="0 0 32 32" fill="none" aria-hidden="true">
              <path d="M7 8h18v3H7zM7 14.5h11v3H7zM7 21h14v3H7z" fill="#f2fffd" />
              <circle cx="24" cy="23" r="5.4" fill="#0a3c3c" stroke="#7df0e2" stroke-width="1.4" />
              <path d="M21.7 23l1.7 1.7 3-3.4" stroke="#7df0e2" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </div>
          <div class="brand-text">
            <strong>竞智</strong>
            <span>Competition Intelligence</span>
          </div>
        </div>
        <div v-for="group in visibleNavGroups" :key="group.caption" class="nav-group">
          <div class="nav-caption">{{ group.caption }}</div>
          <div
            v-for="item in group.items"
            :key="item.name"
            class="nav-item"
            :class="{ active: activeName === item.name }"
            @click="go(item.name)"
          >
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </div>
        </div>
        <div class="sidebar-note">
          <div class="note-title">
            <span class="dot" :class="{ offline: isOffline }" />
            {{ statusText }}
          </div>
          <p>结构化数据 + 原始文件引用，重要结论不依赖大模型自由生成。</p>
        </div>
        <label class="drawer-role">
          <span>当前身份（演示）</span>
          <select v-model="store.role" class="top-role drawer-role-select" aria-label="当前身份">
            <option v-for="role in ROLES" :key="role" :value="role">{{ role }}</option>
          </select>
        </label>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.drawer-inner {
  min-height: 100%;
  padding: 24px 16px 20px;
  background: linear-gradient(172deg, #0c2435 0%, #0a1d2b 60%, #081927 100%);
  color: #d7e3e7;
}

:global(.mobile-drawer .el-drawer__body) {
  padding: 0;
}

.drawer-inner :deep(.brand) {
  padding-left: 8px;
}

.drawer-role {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 18px 8px 0;
  padding: 12px 14px;
  border: 1px solid rgba(125, 240, 226, 0.18);
  border-radius: 10px;
  background: rgba(125, 240, 226, 0.06);
  font-size: 12px;
  color: #9fb4bd;
}

.drawer-role-select {
  border-color: rgba(125, 240, 226, 0.25);
  background: #0c2435;
  color: #d7e3e7;
}
</style>
