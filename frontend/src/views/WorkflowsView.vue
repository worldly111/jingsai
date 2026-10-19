<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { ensureAgents, ensureHealth, ensureOptions, store } from '../store'
import { AGENT_ICONS, fmtDateTime } from '../utils'
import PageHeader from '../components/PageHeader.vue'
import ResultView from '../components/ResultView.vue'
import EmptyState from '../components/EmptyState.vue'

const selectedAgent = ref('qa')
const question = ref('')
const payloadText = ref('{}')
const running = ref(false)
const result = ref(null)
const resultRef = ref(null)
const runs = ref([])
const runsLoading = ref(false)
const validating = ref(false)
const approvedBudget = ref(null)

const samples = computed(() => ({
  qa: {
    question: '2026 年蓝桥杯的报名截止时间和参赛对象是什么？',
    payload: {}
  },
  recommend: {
    question: '我是软件工程专业大二学生，会 Python 和数据分析，参加过校级项目，推荐参加什么竞赛？',
    payload: {
      major: '软件工程',
      grade: '2025级',
      tech_tags: ['Python', '数据分析'],
      has_project: true,
      project_title: '校园二手交易平台'
    }
  },
  prep: {
    question: '帮我制定蓝桥杯软件赛的备赛计划',
    payload: { competition_name: '蓝桥杯' }
  },
  review: {
    question: '帮我检查这份项目申报书',
    payload: {
      material_type: '项目申报书',
      competition_name: '中国国际大学生创新大赛',
      text: '项目名称：智农云。本项目面向乡村振兴，团队成员共5人。项目创新性强，但尚未说明核心技术方案与数据来源，也没有给出经费预算和阶段性目标。'
    }
  },
  budget: {
    question: '参加蓝桥杯省赛，5名学生，往返高铁，住宿2晚，需要申请多少预算？',
    payload: {
      competition_name: '蓝桥杯',
      competition_level: '省级',
      year: 2027,
      student_count: 5,
      teacher_count: 1,
      mentor_trip: true,
      destination: '杭州',
      trip_days: 2,
      transport_mode: '高铁',
      registration_fee_per_person: 300
    }
  },
  loan: {
    question: '根据已批准的预算生成借款单',
    payload: {
      budget_doc_no: approvedBudget.value?.doc_no || '',
      borrower: { name: '王建国', teacher_no: 'T2008' }
    }
  },
  reimbursement: {
    question: '帮我检查这些票据能否报销',
    payload: {
      budget_doc_no: approvedBudget.value?.doc_no || '',
      claimant_name: '王建国',
      event_end_date: '2026-04-12',
      items: [
        { category: '交通费', item_name: '5人往返高铁', amount: 1200, invoice_no: '12345678901234567890', has_invoice: true, expense_date: '2026-04-10', payee: '铁路12306' },
        { category: '住宿费', item_name: '住宿2晚', amount: 900, invoice_no: '22345678901234567890', has_invoice: true, expense_date: '2026-04-10', payee: '杭州某酒店' },
        { category: '餐费', item_name: '工作餐', amount: 600, has_invoice: false, expense_date: '2026-04-11', payee: '某餐馆' }
      ]
    }
  },
  stats: {
    question: '统计 2026 年各竞赛获奖数量与获奖等级分布',
    payload: {}
  }
}))

const agent = computed(() => store.agents.find((a) => a.agent === selectedAgent.value) || null)
const problems = computed(() => store.agentProblems || [])
const health = computed(() => store.health)

function applySample(key) {
  const sample = samples.value[key]
  if (!sample) return
  question.value = sample.question
  payloadText.value = JSON.stringify(sample.payload, null, 2)
}

function selectAgent(key) {
  selectedAgent.value = key
  result.value = null
  applySample(key)
}

async function runTest() {
  if (!agent.value) return
  let parsed = {}
  try {
    parsed = payloadText.value.trim() ? JSON.parse(payloadText.value) : {}
  } catch (error) {
    ElMessage.error(`运行参数不是合法 JSON：${error.message}`)
    return
  }
  const body = {
    question: question.value,
    payload: parsed.payload || parsed,
    user_role: store.role
  }
  if (selectedAgent.value === 'recommend') {
    body.profile = parsed.profile || parsed
  }
  running.value = true
  result.value = null
  try {
    result.value = await api.runAgent(selectedAgent.value, body)
    await loadRuns()
    await nextTick()
    resultRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    running.value = false
  }
}

async function loadRuns() {
  runsLoading.value = true
  try {
    const data = await api.logRuns({ limit: 25 })
    runs.value = data.items || []
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    runsLoading.value = false
  }
}

async function validate() {
  validating.value = true
  try {
    await Promise.all([ensureAgents(true), ensureHealth(true)])
    if (problems.value.length) ElMessage.warning(`发现 ${problems.value.length} 项工作流配置问题`)
    else ElMessage.success('8 个智能体工作流与 Prompt 节点配置校验通过')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    validating.value = false
  }
}

function nodeTitle(node) {
  return node.title || node.id
}

onMounted(async () => {
  await Promise.all([ensureOptions(), ensureHealth()])
  try {
    await ensureAgents()
  } catch (error) {
    ElMessage.error(error.message)
  }
  try {
    const data = await api.budgets()
    approvedBudget.value = (data.items || []).find((b) => b.status === '已批准') || null
  } catch {
    approvedBudget.value = null
  }
  selectAgent('qa')
  await loadRuns()
})
</script>

<template>
  <div>
    <PageHeader
      eyebrow="Orchestration"
      title="智能体工作流"
      description="8 个智能体均由 LangGraph 状态图编排，节点与 Prompt 配置一一对应。未配置大模型时自动切换离线规则通道，关键数据始终来自台账与规则表。"
    >
      <template #actions>
        <el-button :loading="validating" @click="validate"><el-icon><CircleCheck /></el-icon> 校验配置</el-button>
        <el-button @click="loadRuns"><el-icon><Refresh /></el-icon> 刷新运行记录</el-button>
      </template>
    </PageHeader>

    <div class="runtime-strip">
      <div class="runtime-item">
        <span class="runtime-label">运行通道</span>
        <strong>{{ health?.llm?.available ? `${health.llm.provider} · ${health.llm.model}` : '内置离线规则引擎' }}</strong>
        <span class="dot" :class="{ offline: !health?.llm?.available }" />
      </div>
      <div class="runtime-item">
        <span class="runtime-label">向量模型</span>
        <strong>{{ health?.embedding?.provider }} · {{ health?.embedding?.dim }} 维</strong>
      </div>
      <div class="runtime-item">
        <span class="runtime-label">智能体</span>
        <strong>{{ store.agents.length }} 个</strong>
      </div>
      <div class="runtime-item">
        <span class="runtime-label">工作流校验</span>
        <strong :class="problems.length ? 'bad' : 'good'">{{ problems.length ? `${problems.length} 项待修复` : '全部通过' }}</strong>
      </div>
      <div class="runtime-item wide">
        <span class="runtime-label">知识库</span>
        <strong>{{ health?.knowledge_documents ?? 0 }} 份文档 · {{ health?.competitions ?? 0 }} 项赛事</strong>
      </div>
    </div>

    <el-alert
      v-if="problems.length"
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: 14px"
      title="工作流配置校验未通过"
    >
      <div v-for="problem in problems" :key="problem" class="problem-line">{{ problem }}</div>
    </el-alert>

    <div class="workflow-layout">
      <aside class="agent-rail">
        <button
          v-for="item in store.agents"
          :key="item.agent"
          class="agent-item"
          :class="{ active: item.agent === selectedAgent }"
          @click="selectAgent(item.agent)"
        >
          <span class="agent-icon"><el-icon><component :is="AGENT_ICONS[item.agent] || 'MagicStick'" /></el-icon></span>
          <span class="agent-copy">
            <strong>{{ item.name }}</strong>
            <span>{{ item.nodes?.length || 0 }} 个节点 · {{ item.mode || '工作流' }}</span>
          </span>
          <el-icon class="agent-arrow"><ArrowRight /></el-icon>
        </button>
      </aside>

      <div class="workflow-main">
        <div v-if="agent" class="panel pipeline-panel">
          <div class="pipeline-head">
            <div>
              <div class="pipeline-name">{{ agent.name }}</div>
              <p class="pipeline-desc">{{ agent.description }}</p>
            </div>
            <span class="tag-soft teal">{{ agent.mode || 'state graph' }}</span>
          </div>

          <div class="pipeline-flow">
            <template v-for="(node, index) in agent.nodes" :key="node.id">
              <div class="flow-node">
                <span class="flow-index">{{ index + 1 }}</span>
                <div>
                  <strong>{{ nodeTitle(node) }}</strong>
                  <p>{{ node.desc || '工作流节点' }}</p>
                </div>
              </div>
              <span v-if="index < agent.nodes.length - 1" class="flow-arrow">→</span>
            </template>
          </div>

          <div class="pipeline-meta">
            <div class="edge-block">
              <span class="meta-label">图结构</span>
              <div class="edge-list">
                <span v-for="(edge, index) in agent.edges" :key="`${edge.from}-${edge.to}-${index}`" class="edge-chip">
                  {{ edge.from }} → {{ edge.to }}<em v-if="edge.when">（{{ edge.when }}）</em>
                </span>
              </div>
            </div>
            <div v-if="agent.answer_rules?.length" class="edge-block">
              <span class="meta-label">回答规则</span>
              <ul class="rule-list">
                <li v-for="rule in agent.answer_rules" :key="rule">{{ rule }}</li>
              </ul>
            </div>
          </div>
        </div>

        <div class="panel runner-panel">
          <div class="panel-head">
            <h3>在线测试台</h3>
            <span class="sub">直接调用 {{ agent?.name || '智能体' }}，结果与页面调用共用同一工作流</span>
            <div class="right">
              <el-button size="small" text @click="applySample(selectedAgent)">恢复示例参数</el-button>
            </div>
          </div>
          <div class="runner-body">
            <div class="form-grid">
              <div class="span-2">
                <label class="field-label">用户问题</label>
                <el-input v-model="question" type="textarea" :rows="2" placeholder="输入问题或任务描述" />
              </div>
              <div class="span-2">
                <label class="field-label">运行参数（JSON）</label>
                <el-input v-model="payloadText" type="textarea" :rows="8" class="json-input" spellcheck="false" />
                <div class="field-hint">参数原样传入工作流 payload；推荐智能体的专业画像会同时作为 profile 传入。</div>
              </div>
            </div>
            <div class="form-actions">
              <el-button type="primary" :loading="running" @click="runTest">
                <el-icon><VideoPlay /></el-icon> 运行工作流
              </el-button>
              <span class="muted small">未配置大模型时使用离线规则通道，同样会记录节点轨迹与运行日志。</span>
            </div>
          </div>
        </div>

        <div ref="resultRef">
          <ResultView v-if="result" :result="result" :title="`${agent?.name || ''} · 测试结果`" />
          <div v-else class="panel result-placeholder">
            <EmptyState
              title="选择智能体并运行"
              description="运行后可查看回答、结构化数据、图表、校验结果、引用依据与逐节点执行轨迹。"
            />
          </div>
        </div>

        <div class="panel runs-panel">
          <div class="panel-head">
            <h3>最近运行记录</h3>
            <span class="sub">共 {{ runs.length }} 条</span>
            <div class="right">
              <el-button size="small" text :loading="runsLoading" @click="loadRuns"><el-icon><Refresh /></el-icon> 刷新</el-button>
            </div>
          </div>
          <el-table :data="runs" size="small" v-loading="runsLoading" style="width: 100%">
            <el-table-column prop="run_id" label="Run ID" width="150">
              <template #default="{ row }"><span class="mono small">{{ row.run_id }}</span></template>
            </el-table-column>
            <el-table-column prop="agent" label="智能体" width="110" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="row.status === 'success' ? 'success' : 'danger'">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="duration_ms" label="耗时(ms)" width="90" />
            <el-table-column label="输出摘要" min-width="260" show-overflow-tooltip>
              <template #default="{ row }">{{ typeof row.summary === 'string' ? row.summary : JSON.stringify(row.summary) }}</template>
            </el-table-column>
            <el-table-column label="运行时间" width="140">
              <template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.runtime-strip {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  padding: 12px 16px;
  margin-bottom: 16px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 10px;
}

.runtime-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 140px;
  padding-right: 18px;
  border-right: 1px solid var(--line);
}

.runtime-item.wide {
  border-right: 0;
}

.runtime-label {
  font-size: 9.5px;
  letter-spacing: 0.12em;
  color: var(--muted-2);
}

.runtime-item strong {
  font-size: 11.5px;
  font-weight: 500;
  color: var(--text-1);
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.runtime-item strong.good {
  color: #178a75;
}

.runtime-item strong.bad {
  color: #bf4a3f;
}

.problem-line {
  font-size: 11.5px;
  line-height: 1.7;
}

.workflow-layout {
  display: grid;
  grid-template-columns: 250px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.agent-rail {
  display: flex;
  flex-direction: column;
  gap: 6px;
  position: sticky;
  top: 80px;
}

.agent-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 12px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: #fff;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s ease, background 0.15s ease;
  font-family: inherit;
}

.agent-item:hover {
  border-color: rgba(15, 159, 147, 0.35);
  background: #fbfdfc;
}

.agent-item.active {
  border-color: rgba(15, 159, 147, 0.45);
  background: linear-gradient(90deg, rgba(15, 159, 147, 0.08), rgba(15, 159, 147, 0.02));
  box-shadow: inset 2px 0 0 var(--teal-500);
}

.agent-icon {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: rgba(15, 159, 147, 0.1);
  color: var(--teal-700);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.agent-copy {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.agent-copy strong {
  font-size: 12px;
  color: var(--ink-800);
  font-weight: 600;
}

.agent-copy span {
  font-size: 9.5px;
  color: var(--muted-2);
}

.agent-arrow {
  margin-left: auto;
  font-size: 11px;
  color: var(--muted-2);
}

.workflow-main {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.pipeline-panel {
  padding: 18px 20px;
}

.pipeline-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.pipeline-name {
  font-family: var(--font-serif);
  font-size: 19px;
  color: var(--ink-900);
}

.pipeline-desc {
  margin: 4px 0 0;
  font-size: 11.5px;
  line-height: 1.7;
  color: var(--muted);
  max-width: 720px;
}

.pipeline-flow {
  display: flex;
  align-items: stretch;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 6px;
}

.flow-node {
  flex: 1;
  min-width: 135px;
  display: flex;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: #fbfcfc;
}

.flow-index {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--teal-600);
  color: #fff;
  font-size: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 1px;
}

.flow-node strong {
  font-size: 11.5px;
  color: var(--text-1);
}

.flow-node p {
  margin: 3px 0 0;
  font-size: 10px;
  line-height: 1.6;
  color: var(--muted-2);
}

.flow-arrow {
  align-self: center;
  color: var(--teal-500);
  font-size: 12px;
  flex-shrink: 0;
}

.pipeline-meta {
  display: flex;
  gap: 26px;
  flex-wrap: wrap;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed var(--line);
}

.meta-label {
  display: block;
  font-size: 9.5px;
  letter-spacing: 0.12em;
  color: var(--muted-2);
  margin-bottom: 6px;
}

.edge-list {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  max-width: 720px;
}

.edge-chip {
  font-size: 9.5px;
  padding: 2px 8px;
  border-radius: 20px;
  background: #f4f8f7;
  color: var(--text-2);
  font-family: var(--font-mono);
}

.edge-chip em {
  font-style: normal;
  color: var(--gold-700);
}

.rule-list {
  margin: 0;
  padding-left: 16px;
  font-size: 10.5px;
  line-height: 1.8;
  color: var(--muted);
}

.runner-panel {
  padding: 0;
}

.runner-panel .panel-head {
  margin: 0;
  padding: 14px 18px;
}

.runner-body {
  padding: 16px 18px 18px;
}

.json-input :deep(textarea) {
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.7;
  background: #fbfcfc;
}

.result-placeholder {
  padding: 10px;
}

.runs-panel {
  padding: 0;
  overflow: hidden;
}

.runs-panel .panel-head {
  margin: 0;
  padding: 14px 18px;
}

@media (max-width: 1100px) {
  .workflow-layout {
    grid-template-columns: 1fr;
  }
  .agent-rail {
    position: static;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
