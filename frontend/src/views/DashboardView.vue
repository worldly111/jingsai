<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { agentLabel, can, ensureAgents, ensureHealth, ensureOptions, store } from '../store'
import { AGENT_ICONS, AGENT_PATHS, daysUntil, fmtDateTime, fmtNumber, greeting, todayText } from '../utils'
import StatCard from '../components/StatCard.vue'
import EChart from '../components/EChart.vue'
import EmptyState from '../components/EmptyState.vue'

const router = useRouter()
const loading = ref(true)
const overview = ref(null)
const trendOption = ref(null)
const upcoming = ref([])
const recentRuns = ref([])
const logs = ref(null)
const finance = ref(null)

const canUseFinance = computed(() => can('finance.use'))
const canViewLogs = computed(() => can('logs.view'))
const canViewWorkflows = computed(() => can('workflows.use'))
const showSideStack = computed(() => canUseFinance.value || canViewLogs.value)

const agentCards = computed(() => {
  const descriptions = {
    qa: '通知、规程与时间节点问答，逐条引用原文',
    recommend: '按专业、年级、技术方向匹配适合的赛事',
    prep: '倒排备赛计划、任务清单与材料准备',
    review: '申报书与作品说明初检，生成答辩问题',
    budget: '依据费用标准测算预算并生成申请',
    loan: '按已批准预算生成借款单',
    reimbursement: '票据完整性检查与报销单生成',
    stats: '结构化台账统计与可视化分析'
  }
  const financeAgents = new Set(['budget', 'loan', 'reimbursement'])
  return store.agents
    .filter((agent) => canUseFinance.value || !financeAgents.has(agent.agent))
    .map((agent) => ({
      ...agent,
      icon: AGENT_ICONS[agent.agent] || 'MagicStick',
      desc: descriptions[agent.agent] || agent.description,
      path: AGENT_PATHS[agent.agent] || '/'
    }))
})

const healthItems = computed(() => {
  const h = store.health
  if (!h) return []
  return [
    {
      label: '大模型通道',
      value: h.llm?.available ? `${h.llm.provider} · ${h.llm.model}` : '离线规则引擎就绪',
      ok: true
    },
    { label: '知识库', value: `${fmtNumber(h.knowledge_documents)} 份原始文件 · ${h.embedding?.dim || 0} 维向量`, ok: h.knowledge_documents > 0 },
    { label: '结构化台账', value: `${fmtNumber(overview.value?.registrations)} 支队伍 · ${fmtNumber(overview.value?.awards)} 项获奖`, ok: true },
    { label: '智能体工作流', value: `${h.agents} 条 LangGraph 工作流校验通过`, ok: true }
  ]
})

const nextMilestones = computed(() => upcoming.value.slice(0, 6))

function goAgent(agent) {
  if (agent === 'budget' || agent === 'loan' || agent === 'reimbursement') {
    if (!canUseFinance.value) return
    router.push({ name: 'finance', query: { tab: agent } })
  } else {
    router.push(AGENT_PATHS[agent])
  }
}

async function load() {
  loading.value = true
  const requests = {
    health: ensureHealth(),
    options: ensureOptions(),
    agents: ensureAgents(),
    overview: api.statsOverview(),
    trend: api.statsChart('trend'),
    upcoming: api.upcoming(180),
    logs: canViewLogs.value ? api.logRuns({ limit: 6 }) : Promise.resolve(null),
    logStats: canViewLogs.value ? api.logStats() : Promise.resolve(null),
    finance: canUseFinance.value ? api.financeSummary() : Promise.resolve(null)
  }
  const keys = Object.keys(requests)
  const settled = await Promise.allSettled(Object.values(requests))
  const result = Object.fromEntries(
    keys.map((key, index) => [
      key,
      settled[index].status === 'fulfilled' ? settled[index].value : null
    ])
  )
  overview.value = result.overview?.overview || null
  trendOption.value = result.trend || null
  upcoming.value = result.upcoming?.items || []
  recentRuns.value = result.logs?.items || []
  logs.value = result.logStats
  finance.value = result.finance
  loading.value = false
}

watch(() => store.role, () => load())

onMounted(load)
</script>

<template>
  <div>
    <section class="hero">
      <div class="hero-grid" aria-hidden="true" />
      <div class="hero-main">
        <div class="hero-eyebrow">
          <span class="dot" :class="{ offline: !store.health?.llm?.available }" />
          计算与智能技术学院 · 学科竞赛智能服务
        </div>
        <h1>让每一次参赛，<br /><em>都有据可依。</em></h1>
        <p class="hero-desc">
          从赛事查询、推荐与备赛，到项目材料检查、经费办理与获奖统计，
          用结构化台账与可溯源的原始文件，支撑学院竞赛管理的每一个环节。
        </p>
        <div class="hero-actions">
          <el-button type="primary" size="large" @click="router.push('/qa')">
            <el-icon><ChatLineRound /></el-icon> 向知识库提问
          </el-button>
          <el-button size="large" class="hero-ghost" @click="router.push('/recommend')">
            <el-icon><Compass /></el-icon> 为我匹配赛事
          </el-button>
        </div>
        <div class="hero-date">{{ greeting() }}，今天是 {{ todayText() }}</div>
      </div>
      <div class="hero-side">
        <div class="hero-side-head">
          <span>PLATFORM STATUS</span>
          <span class="status-chip">运行中</span>
        </div>
        <div class="health-list">
          <div v-for="item in healthItems" :key="item.label" class="health-row">
            <span class="health-dot" :class="{ warn: !item.ok }" />
            <span class="health-label">{{ item.label }}</span>
            <span class="health-value">{{ item.value }}</span>
          </div>
        </div>
        <div v-if="canViewLogs" class="hero-side-foot">
          <span>今日运行 {{ fmtNumber(logs?.runs) }} 次</span>
          <span>引用覆盖率 {{ logs?.citation_rate ?? 0 }}%</span>
        </div>
      </div>
    </section>

    <div v-loading="loading" class="content-area">
      <div class="stat-grid" style="margin-bottom: 20px">
        <StatCard label="在库赛事" :value="overview?.competitions ?? '—'" suffix="项" note="赛事台账与届次信息" icon="Trophy" />
        <StatCard label="参赛队伍" :value="overview?.registrations ?? '—'" suffix="支" note="结构化业务台账累计" icon="Flag" tone="ink" />
        <StatCard label="获奖记录" :value="overview?.awards ?? '—'" suffix="项" :note="`获奖率 ${overview?.award_rate ?? 0}%`" icon="Medal" tone="gold" />
        <StatCard label="知识库文件" :value="store.health?.knowledge_documents ?? '—'" suffix="份" note="RAG 原文引用与溯源" icon="Collection" />
        <StatCard v-if="canViewLogs" label="智能体调用" :value="logs?.runs ?? '—'" suffix="次" :note="`平均 ${logs?.avg_duration_ms ?? 0} ms`" icon="MagicStick" tone="ink" />
        <StatCard v-if="canViewLogs" label="问答引用率" :value="logs?.citation_rate ?? 0" suffix="%" :note="`${logs?.qa_with_citations ?? 0} 次带原文依据`" icon="Link" tone="gold" />
      </div>

      <div class="dashboard-grid">
        <div class="panel">
          <div class="panel-head">
            <h3>参赛与获奖趋势</h3>
            <span class="sub">按年度 · 结构化台账口径</span>
            <div class="right">
              <el-button text size="small" @click="router.push('/stats')">
                进入分析 <el-icon><ArrowRight /></el-icon>
              </el-button>
            </div>
          </div>
          <div style="padding: 6px 10px 8px">
            <EChart v-if="trendOption" :option="trendOption" :height="318" />
            <EmptyState v-else title="暂无趋势数据" description="导入参赛台账后自动生成年度趋势。" />
          </div>
        </div>

        <div class="panel deadline-panel">
          <div class="panel-head">
            <h3>近期节点</h3>
            <span class="sub">未来 180 天</span>
            <div class="right">
              <el-button text size="small" @click="router.push('/competitions')">
                赛事台账 <el-icon><ArrowRight /></el-icon>
              </el-button>
            </div>
          </div>
          <div v-if="nextMilestones.length" class="deadline-list">
            <div
              v-for="item in nextMilestones"
              :key="`${item.competition_id}-${item.milestone}-${item.date}`"
              class="deadline-row"
              style="cursor: pointer"
              @click="router.push(`/competitions?open=${item.competition_id}`)"
            >
              <div class="deadline-date">
                <div class="d">{{ String(item.date).slice(8, 10) }}</div>
                <div class="m">{{ String(item.date).slice(5, 7) }} 月</div>
              </div>
              <div class="deadline-main">
                <div class="t">{{ item.milestone }}</div>
                <div class="s">{{ item.competition_name }} · {{ item.year }} 届 · {{ item.level }}</div>
              </div>
              <div
                class="deadline-days"
                :class="{ soon: item.days_left >= 0 && item.days_left <= 14, overdue: item.days_left < 0 }"
              >
                <template v-if="item.days_left >= 0">
                  还有 <strong>{{ item.days_left }}</strong> 天
                </template>
                <template v-else>已过 {{ Math.abs(item.days_left) }} 天</template>
              </div>
            </div>
          </div>
          <EmptyState v-else title="近期暂无节点" description="可在赛事台账中补充届次与里程碑。" />
        </div>
      </div>

      <div class="lower-grid" :class="{ single: !showSideStack }">
        <div>
          <div class="section-label">智能体服务入口</div>
          <div class="agent-grid">
            <div v-for="agent in agentCards" :key="agent.agent" class="agent-card" @click="goAgent(agent.agent)">
              <div class="agent-icon"><el-icon><component :is="agent.icon" /></el-icon></div>
              <div class="agent-main">
                <div class="agent-name">{{ agent.name || agentLabel(agent.agent) }}</div>
                <div class="agent-desc">{{ agent.desc }}</div>
              </div>
              <el-icon class="agent-arrow"><ArrowRight /></el-icon>
            </div>
          </div>
        </div>

        <div v-if="showSideStack" class="side-stack">
          <div v-if="canViewLogs" class="panel">
            <div class="panel-head">
              <h3>最近运行</h3>
              <div class="right">
                <el-button v-if="canViewWorkflows" text size="small" @click="router.push('/workflows')">全部</el-button>
              </div>
            </div>
            <div class="run-list">
              <div v-for="run in recentRuns" :key="run.id" class="run-row">
                <span class="run-status" :class="run.status" />
                <div class="run-main">
                  <div class="run-agent">{{ agentLabel(run.agent) }}</div>
                  <div class="run-time">{{ fmtDateTime(run.created_at) }}</div>
                </div>
                <span class="run-duration">{{ run.duration_ms }} ms</span>
              </div>
              <EmptyState v-if="!recentRuns.length" title="暂无运行记录" description="运行任一智能体后将在此显示审计轨迹。" />
            </div>
          </div>

          <div v-if="canUseFinance" class="panel attention-card">
            <div class="panel-head">
              <h3>经费办理</h3>
              <div class="right">
                <el-button text size="small" @click="router.push('/finance')">办理</el-button>
              </div>
            </div>
            <div class="attention-body">
              <div>
                <span class="attention-value">¥{{ fmtNumber(finance?.budget_total) }}</span>
                <span class="attention-label">累计预算申报</span>
              </div>
              <div class="attention-split">
                <div>
                  <strong>{{ finance?.budgets_pending ?? 0 }}</strong>
                  <span>笔待审批</span>
                </div>
                <div>
                  <strong>{{ finance?.loans ?? 0 }}</strong>
                  <span>笔借款</span>
                </div>
                <div>
                  <strong>{{ finance?.reimbursements ?? 0 }}</strong>
                  <span>笔报销</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hero {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(300px, 0.7fr);
  gap: 40px;
  padding: 38px 42px 36px;
  border-radius: 18px;
  background:
    radial-gradient(560px 320px at 88% -20%, rgba(37, 205, 190, 0.28), transparent 70%),
    radial-gradient(420px 240px at 8% 110%, rgba(196, 161, 91, 0.16), transparent 70%),
    linear-gradient(128deg, #0b2536 0%, #0a1f2e 55%, #071a27 100%);
  color: #e6f2f3;
  overflow: hidden;
  box-shadow: 0 18px 46px rgba(7, 27, 39, 0.2);
}

.hero-grid {
  position: absolute;
  inset: 0;
  background-image: linear-gradient(rgba(255, 255, 255, 0.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.045) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: radial-gradient(ellipse at 73% 18%, #000 22%, transparent 72%);
  pointer-events: none;
}

.hero-main {
  position: relative;
  z-index: 1;
}

.hero-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 10.5px;
  letter-spacing: 0.14em;
  color: rgba(210, 236, 235, 0.65);
  text-transform: uppercase;
}

.hero h1 {
  font-family: var(--font-display);
  font-size: clamp(31px, 3.5vw, 46px);
  line-height: 1.32;
  letter-spacing: 0.02em;
  color: #f4fbfb;
  margin: 17px 0 14px;
  font-weight: 700;
}

.hero h1 em {
  font-style: normal;
  color: #64e2d4;
  position: relative;
}

.hero h1 em::after {
  content: '';
  position: absolute;
  left: 0;
  right: 3px;
  bottom: 4px;
  height: 7px;
  background: rgba(30, 185, 170, 0.2);
  border-radius: 2px;
  z-index: -1;
}

.hero-desc {
  max-width: 580px;
  color: rgba(214, 232, 234, 0.62);
  font-size: 13px;
  line-height: 1.85;
}

.hero-actions {
  display: flex;
  gap: 11px;
  margin-top: 24px;
  flex-wrap: wrap;
}

.hero-ghost {
  background: rgba(255, 255, 255, 0.06) !important;
  border-color: rgba(255, 255, 255, 0.16) !important;
  color: #e3f2f0 !important;
}

.hero-ghost:hover {
  background: rgba(255, 255, 255, 0.11) !important;
  border-color: rgba(255, 255, 255, 0.28) !important;
}

.hero-date {
  margin-top: 20px;
  font-size: 10.5px;
  color: rgba(210, 236, 235, 0.36);
  letter-spacing: 0.05em;
}

.hero-side {
  position: relative;
  z-index: 1;
  border: 1px solid rgba(174, 231, 224, 0.14);
  background: rgba(255, 255, 255, 0.035);
  backdrop-filter: blur(6px);
  border-radius: 13px;
  padding: 18px 20px 15px;
  align-self: center;
}

.hero-side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 9.5px;
  letter-spacing: 0.2em;
  color: rgba(210, 236, 235, 0.42);
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.075);
}

.status-chip {
  letter-spacing: 0.08em;
  color: #75e3d6;
  background: rgba(31, 184, 170, 0.13);
  border: 1px solid rgba(60, 203, 189, 0.22);
  border-radius: 20px;
  padding: 1px 8px;
  font-size: 9.5px;
}

.health-list {
  padding: 7px 0 3px;
}

.health-row {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 8px 0;
  border-bottom: 1px dashed rgba(255, 255, 255, 0.06);
  font-size: 11px;
}

.health-row:last-child {
  border-bottom: 0;
}

.health-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #43d6c5;
  margin-top: 7px;
  flex-shrink: 0;
  box-shadow: 0 0 0 3px rgba(67, 214, 197, 0.11);
}

.health-dot.warn {
  background: #d3a552;
  box-shadow: 0 0 0 3px rgba(211, 165, 82, 0.12);
}

.health-label {
  color: rgba(210, 236, 235, 0.45);
  flex-shrink: 0;
  width: 76px;
}

.health-value {
  color: rgba(233, 246, 246, 0.8);
  margin-left: auto;
  text-align: right;
  line-height: 1.55;
}

.hero-side-foot {
  display: flex;
  justify-content: space-between;
  padding-top: 11px;
  margin-top: 4px;
  border-top: 1px solid rgba(255, 255, 255, 0.075);
  font-size: 9.5px;
  color: rgba(210, 236, 235, 0.36);
}

.content-area {
  margin-top: 20px;
  min-height: 300px;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.58fr) minmax(320px, 0.86fr);
  gap: 18px;
  align-items: stretch;
}

.deadline-panel {
  display: flex;
  flex-direction: column;
}

.deadline-panel .deadline-list {
  flex: 1;
}

.lower-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(320px, 0.8fr);
  gap: 18px;
  margin-top: 4px;
}

.lower-grid.single {
  grid-template-columns: 1fr;
}

.agent-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 11px;
}

.agent-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 15px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 11px;
  cursor: pointer;
  transition: border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}

.agent-card:hover {
  border-color: #b9deda;
  box-shadow: 0 8px 22px rgba(13, 63, 76, 0.07);
  transform: translateY(-1px);
}

.agent-icon {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  background: #eff7f6;
  color: var(--teal-dark);
  font-size: 16px;
  flex-shrink: 0;
}

.agent-main {
  min-width: 0;
  flex: 1;
}

.agent-name {
  font-size: 12.5px;
  font-weight: 650;
  color: #2c444f;
}

.agent-desc {
  font-size: 10.5px;
  color: var(--muted-2);
  margin-top: 2px;
  line-height: 1.55;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.agent-arrow {
  color: #b9c7cd;
  font-size: 13px;
  flex-shrink: 0;
}

.side-stack {
  display: grid;
  gap: 16px;
  align-content: start;
}

.run-list {
  padding: 2px 0;
}

.run-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 18px;
  border-bottom: 1px solid #f0f3f4;
}

.run-row:last-child {
  border-bottom: 0;
}

.run-status {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #3aa47a;
  flex-shrink: 0;
}

.run-status.failed {
  background: #c75853;
}

.run-main {
  min-width: 0;
  flex: 1;
}

.run-agent {
  font-size: 12px;
  font-weight: 600;
  color: #334b56;
}

.run-time {
  font-size: 10px;
  color: var(--muted-2);
  margin-top: 1px;
}

.run-duration {
  font-size: 10px;
  color: var(--muted-2);
  font-family: monospace;
}

.attention-card .panel-head {
  border-bottom: 0;
  padding-bottom: 4px;
}

.attention-body {
  padding: 2px 20px 18px;
}

.attention-value {
  font-family: var(--font-display);
  font-size: 25px;
  font-weight: 700;
  color: var(--ink);
  letter-spacing: -0.01em;
}

.attention-label {
  font-size: 10.5px;
  color: var(--muted-2);
  margin-left: 8px;
}

.attention-split {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-top: 13px;
  padding-top: 13px;
  border-top: 1px dashed var(--line);
}

.attention-split div {
  display: flex;
  flex-direction: column;
}

.attention-split strong {
  font-family: var(--font-display);
  font-size: 18px;
  color: var(--ink-2);
  line-height: 1.2;
}

.attention-split span {
  font-size: 10px;
  color: var(--muted-2);
  margin-top: 2px;
}

@media (max-width: 1200px) {
  .hero {
    grid-template-columns: 1fr;
    gap: 26px;
    padding: 32px;
  }
  .hero-side {
    width: 100%;
  }
  .dashboard-grid,
  .lower-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .hero {
    padding: 26px 22px;
  }
  .hero h1 {
    font-size: 30px;
  }
  .agent-grid {
    grid-template-columns: 1fr;
  }
}
</style>
