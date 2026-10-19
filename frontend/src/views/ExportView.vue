<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { ensureOptions, store } from '../store'
import { fmtDateTime, fmtNumber } from '../utils'
import PageHeader from '../components/PageHeader.vue'
import EmptyState from '../components/EmptyState.vue'

const filters = reactive({
  year: null,
  competition: '',
  level: '',
  major: '',
  keyword: ''
})

const loading = ref('')
const sessions = ref([])
const sessionLoading = ref(false)
const currentSession = ref(null)
const sessionDetailLoading = ref(false)
const logStats = ref(null)

const yearOptions = computed(() => (store.options?.years || []).slice().sort((a, b) => b - a))

const params = computed(() => ({
  years: filters.year || undefined,
  competitions: filters.competition || undefined,
  levels: filters.level || undefined,
  majors: filters.major || undefined,
  keyword: filters.keyword || undefined
}))

const scopeText = computed(() => {
  const parts = []
  if (filters.year) parts.push(`${filters.year} 年`)
  if (filters.competition) parts.push(filters.competition)
  if (filters.level) parts.push(filters.level)
  if (filters.major) parts.push(filters.major)
  if (filters.keyword) parts.push(`关键词「${filters.keyword}」`)
  return parts.length ? parts.join(' · ') : '全部竞赛台账'
})

const reports = [
  {
    key: 'stats',
    title: '竞赛统计报表',
    desc: '年度、赛事、专业、获奖等级、教师与学生等多维汇总，含多个工作表。',
    icon: 'DataAnalysis',
    formats: [
      { format: 'xlsx', label: 'Excel 工作簿' },
      { format: 'csv', label: 'CSV 汇总' }
    ]
  },
  {
    key: 'awards',
    title: '获奖明细表',
    desc: '逐项列出获奖年度、赛事、等级、项目、学生、教师、积分与证书编号。',
    icon: 'Trophy',
    formats: [{ format: 'xlsx', label: 'Excel 明细' }]
  },
  {
    key: 'registrations',
    title: '参赛台账报表',
    desc: '完整参赛记录，适合学院归档、考核核对与竞赛工作总结。',
    icon: 'Tickets',
    formats: [{ format: 'xlsx', label: 'Excel 台账' }]
  },
  {
    key: 'knowledge',
    title: '知识文档清单',
    desc: '知识库文档目录、类型、年度、片段数、核对状态与来源信息。',
    icon: 'Files',
    formats: [{ format: 'xlsx', label: 'Excel 清单' }]
  },
  {
    key: 'standards',
    title: '费用标准表',
    desc: '现行竞赛经费费用标准，含类别、级别、地区、计量方式与依据。',
    icon: 'Wallet',
    formats: [{ format: 'xlsx', label: 'Excel 标准' }]
  },
  {
    key: 'award_rules',
    title: '获奖积分与工作量规则',
    desc: '按获奖等级与赛事级别配置的学生积分和教师工作量折算。',
    icon: 'Medal',
    formats: [{ format: 'xlsx', label: 'Excel 规则' }]
  }
]

async function downloadReport(key, format = 'xlsx') {
  loading.value = `${key}-${format}`
  try {
    if (key === 'stats') await api.exportStats(params.value, format)
    else if (key === 'awards') await api.exportAwards(params.value)
    else if (key === 'registrations') await api.exportRegistrations(params.value)
    else if (key === 'knowledge') await exportKnowledge()
    else if (key === 'standards') await exportStandards()
    else if (key === 'award_rules') await exportAwardRules()
    ElMessage.success('导出文件已开始下载')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = ''
  }
}

async function exportKnowledge() {
  const data = await api.knowledgeDocuments()
  const rows = (data.items || []).map((d) => ({
    title: d.title,
    doc_type: d.doc_type,
    year: d.year || '',
    competition_name: d.competition_name,
    issuing_body: d.issuing_body,
    doc_no: d.doc_no,
    chunk_count: d.chunk_count,
    char_count: d.char_count,
    status: d.status,
    file_name: d.file_name,
    source_url: d.source_url,
    created_at: d.created_at?.slice(0, 10) || ''
  }))
  await api.exportTable({
    title: '知识文档清单',
    columns: [
      { key: 'title', label: '文档标题', width: 260 },
      { key: 'doc_type', label: '类型', width: 100 },
      { key: 'year', label: '年度', width: 70 },
      { key: 'competition_name', label: '关联赛事', width: 180 },
      { key: 'issuing_body', label: '发文单位', width: 160 },
      { key: 'doc_no', label: '文号', width: 160 },
      { key: 'chunk_count', label: '片段数', width: 80 },
      { key: 'char_count', label: '字数', width: 90 },
      { key: 'status', label: '状态', width: 80 },
      { key: 'file_name', label: '文件名', width: 220 },
      { key: 'source_url', label: '原文链接', width: 240 },
      { key: 'created_at', label: '入库日期', width: 100 }
    ],
    rows
  }, 'xlsx')
}

async function exportStandards() {
  const data = await api.rules()
  const rows = (data.expense_standards || []).map((s) => ({
    code: s.code,
    name: s.name,
    category: s.category,
    competition_level: s.competition_level,
    region: s.region,
    value_type: s.value_type,
    value: s.value,
    unit: s.unit,
    description: s.description,
    source: s.source,
    effective_from: s.effective_from,
    effective_to: s.effective_to
  }))
  await api.exportTable({
    title: '竞赛经费费用标准表',
    columns: [
      { key: 'code', label: '标准编号', width: 120 },
      { key: 'name', label: '标准名称', width: 180 },
      { key: 'category', label: '类别', width: 100 },
      { key: 'competition_level', label: '赛事级别', width: 100 },
      { key: 'region', label: '地区', width: 90 },
      { key: 'value_type', label: '计量方式', width: 90 },
      { key: 'value', label: '标准值', width: 90 },
      { key: 'unit', label: '单位', width: 110 },
      { key: 'description', label: '说明', width: 260 },
      { key: 'source', label: '依据', width: 220 },
      { key: 'effective_from', label: '生效日期', width: 100 },
      { key: 'effective_to', label: '失效日期', width: 100 }
    ],
    rows
  }, 'xlsx')
}

async function exportAwardRules() {
  const data = await api.rules()
  const rows = (data.award_point_rules || []).map((a) => ({
    award_grade: a.award_grade,
    award_level: a.award_level,
    student_points: a.student_points,
    teacher_workload: a.teacher_workload,
    note: a.note,
    source: a.source
  }))
  await api.exportTable({
    title: '获奖积分与教师工作量规则',
    columns: [
      { key: 'award_grade', label: '奖项等级', width: 100 },
      { key: 'award_level', label: '赛事级别', width: 100 },
      { key: 'student_points', label: '学生积分', width: 100 },
      { key: 'teacher_workload', label: '教师工作量', width: 110 },
      { key: 'note', label: '说明', width: 260 },
      { key: 'source', label: '依据', width: 240 }
    ],
    rows
  }, 'xlsx')
}

async function loadSessions() {
  sessionLoading.value = true
  try {
    const data = await api.qaSessions(30)
    sessions.value = data.items || []
    if (!currentSession.value && sessions.value.length) {
      await selectSession(sessions.value[0].id)
    }
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    sessionLoading.value = false
  }
}

async function selectSession(id) {
  sessionDetailLoading.value = true
  try {
    currentSession.value = await api.qaSession(id)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    sessionDetailLoading.value = false
  }
}

const sessionMarkdown = computed(() => {
  if (!currentSession.value) return ''
  const lines = [`# ${currentSession.value.title}`, '']
  for (const message of currentSession.value.messages || []) {
    lines.push(message.role === 'user' ? '## 用户提问' : '## 智能体回答')
    lines.push('', message.content || '', '')
    if (message.citations?.length) {
      lines.push('**参考依据：**')
      message.citations.forEach((c, index) => {
        lines.push(`${index + 1}. ${c.title}${c.location ? ` · ${c.location}` : ''}`)
      })
      lines.push('')
    }
  }
  return lines.join('\n')
})

async function exportSession(format) {
  if (!currentSession.value || !sessionMarkdown.value) {
    ElMessage.warning('请选择包含消息的会话')
    return
  }
  loading.value = `session-${format}`
  try {
    await api.exportAgent({
      title: `知识问答会话-${currentSession.value.title}`,
      answer: sessionMarkdown.value,
      tables: []
    }, format)
    ElMessage.success('会话记录已导出')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = ''
  }
}

function resetFilters() {
  filters.year = null
  filters.competition = ''
  filters.level = ''
  filters.major = ''
  filters.keyword = ''
}

onMounted(async () => {
  await ensureOptions()
  try {
    logStats.value = await api.logStats()
  } catch {
    /* 运行统计不影响导出 */
  }
  await loadSessions()
})
</script>

<template>
  <div>
    <PageHeader
      eyebrow="Export"
      title="结果导出"
      description="统计报表、获奖明细、参赛台账与规则清单统一从结构化数据生成；智能体问答会话可归档为 Word 或 Markdown，便于留痕与复核。"
    >
      <template #actions>
        <el-button @click="loadSessions"><el-icon><Refresh /></el-icon> 刷新会话</el-button>
      </template>
    </PageHeader>

    <div class="export-scope">
      <div class="scope-main">
        <span class="scope-label">报表范围</span>
        <el-select v-model="filters.year" clearable placeholder="年度" style="width: 110px">
          <el-option v-for="year in yearOptions" :key="year" :label="`${year} 年`" :value="year" />
        </el-select>
        <el-select v-model="filters.competition" clearable filterable placeholder="赛事" style="width: 210px">
          <el-option v-for="comp in store.options?.competitions || []" :key="comp.id" :label="comp.name" :value="comp.name" />
        </el-select>
        <el-select v-model="filters.level" clearable placeholder="级别" style="width: 110px">
          <el-option v-for="level in store.options?.levels || []" :key="level" :label="level" :value="level" />
        </el-select>
        <el-select v-model="filters.major" clearable filterable placeholder="专业" style="width: 170px">
          <el-option v-for="major in store.options?.majors || []" :key="major" :label="major" :value="major" />
        </el-select>
        <el-input v-model="filters.keyword" clearable placeholder="关键词" style="width: 160px" />
        <el-button size="small" text @click="resetFilters">清空</el-button>
      </div>
      <div class="scope-text">{{ scopeText }}</div>
    </div>

    <div class="report-grid">
      <div v-for="report in reports" :key="report.key" class="report-card">
        <div class="report-icon"><el-icon><component :is="report.icon" /></el-icon></div>
        <div class="report-body">
          <h3>{{ report.title }}</h3>
          <p>{{ report.desc }}</p>
          <div class="report-actions">
            <el-button
              v-for="fmt in report.formats"
              :key="fmt.format"
              size="small"
              :type="fmt.format === 'xlsx' ? 'primary' : 'default'"
              :plain="fmt.format !== 'xlsx'"
              :loading="loading === `${report.key}-${fmt.format}`"
              @click="downloadReport(report.key, fmt.format)"
            >
              <el-icon><Download /></el-icon> {{ fmt.label }}
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <div class="export-lower">
      <div class="panel session-panel">
        <div class="panel-head">
          <h3>知识问答会话归档</h3>
          <span class="sub">选择会话后可导出完整问答与引用依据</span>
        </div>
        <div class="session-body">
          <el-select
            :model-value="currentSession?.id"
            filterable
            placeholder="选择问答会话"
            style="width: 100%"
            :loading="sessionLoading"
            @change="selectSession"
          >
            <el-option v-for="session in sessions" :key="session.id" :label="session.title || `会话 ${session.id}`" :value="session.id">
              <span>{{ session.title }}</span>
              <span style="float: right; color: #96a6ae; font-size: 10px">{{ fmtDateTime(session.created_at) }}</span>
            </el-option>
          </el-select>

          <div v-loading="sessionDetailLoading" class="session-preview">
            <template v-if="currentSession">
              <div class="session-meta">
                <span class="tag-soft">{{ currentSession.messages?.length || 0 }} 条消息</span>
                <span class="tag-soft teal">{{ currentSession.agent }}</span>
                <span class="tag-soft mono">#{{ currentSession.id }}</span>
              </div>
              <div class="session-messages">
                <div v-for="message in currentSession.messages || []" :key="message.id" class="session-message" :class="message.role">
                  <div class="message-role">{{ message.role === 'user' ? '用户' : '智能体' }}</div>
                  <div class="message-content">{{ message.content }}</div>
                  <div v-if="message.citations?.length" class="message-cites">引用 {{ message.citations.length }} 条原文依据</div>
                </div>
                <EmptyState v-if="!currentSession.messages?.length" title="会话为空" description="该会话尚未产生问答消息。" />
              </div>
            </template>
            <EmptyState v-else title="暂无问答会话" description="前往「竞赛知识问答」发起一次提问后，即可在此归档。" />
          </div>

          <div class="form-actions">
            <el-button type="primary" :loading="loading === 'session-docx'" :disabled="!sessionMarkdown" @click="exportSession('docx')">
              <el-icon><Document /></el-icon> 导出 Word
            </el-button>
            <el-button :loading="loading === 'session-md'" :disabled="!sessionMarkdown" @click="exportSession('md')">导出 Markdown</el-button>
          </div>
        </div>
      </div>

      <div class="aside-col">
        <div class="panel ops-panel">
          <div class="panel-head">
            <h3>归档与留痕</h3>
          </div>
          <div class="ops-body">
            <div class="ops-item">
              <strong>{{ fmtNumber(logStats?.runs) }}</strong>
              <span>智能体运行记录</span>
            </div>
            <div class="ops-item">
              <strong>{{ fmtNumber(logStats?.qa_total) }}</strong>
              <span>知识问答记录</span>
            </div>
            <div class="ops-item">
              <strong>{{ logStats?.citation_rate ?? 0 }}%</strong>
              <span>引用覆盖率</span>
            </div>
            <p class="ops-note">
              导出报表中的金额、获奖、参赛与标准数据均来自结构化台账与规则表；知识问答归档保留原引用位置，便于审计复核。
            </p>
          </div>
        </div>

        <div class="panel tips-panel">
          <div class="panel-head">
            <h3>导出说明</h3>
          </div>
          <ul class="tips-list">
            <li>统计报表与获奖明细按上方「报表范围」生成，未选择时导出全量数据。</li>
            <li>参赛台账报表支持按年度、赛事、级别、专业与关键词筛选。</li>
            <li>费用标准与积分规则来自配置文件同步后的规则表，修改后无需改代码。</li>
            <li>智能体结果可在各页面结果卡中直接导出 Word / Markdown。</li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.export-scope {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  padding: 12px 16px;
  margin-bottom: 16px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 10px;
}

.scope-main {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.scope-label {
  font-size: 10px;
  letter-spacing: 0.14em;
  color: var(--muted-2);
}

.scope-text {
  font-size: 11px;
  color: var(--teal-700);
  background: rgba(15, 159, 147, 0.08);
  padding: 4px 12px;
  border-radius: 20px;
}

.report-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 18px;
}

.report-card {
  display: flex;
  gap: 14px;
  padding: 18px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 12px;
  transition: box-shadow 0.18s ease, border-color 0.18s ease;
}

.report-card:hover {
  border-color: rgba(15, 159, 147, 0.35);
  box-shadow: 0 10px 26px rgba(10, 32, 45, 0.06);
}

.report-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: linear-gradient(145deg, rgba(15, 159, 147, 0.14), rgba(15, 159, 147, 0.04));
  color: var(--teal-700);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  flex-shrink: 0;
}

.report-body {
  min-width: 0;
}

.report-body h3 {
  margin: 0 0 4px;
  font-family: var(--font-serif);
  font-size: 15px;
  color: var(--ink-800);
}

.report-body p {
  margin: 0 0 10px;
  font-size: 11.5px;
  line-height: 1.7;
  color: var(--muted);
  min-height: 40px;
}

.report-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.export-lower {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(280px, 0.8fr);
  gap: 16px;
  align-items: start;
}

.session-panel {
  padding: 0;
}

.session-panel .panel-head {
  margin: 0;
  padding: 14px 18px;
}

.session-body {
  padding: 16px 18px 18px;
}

.session-preview {
  margin-top: 12px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: #fbfcfc;
  padding: 12px;
  min-height: 180px;
  max-height: 380px;
  overflow-y: auto;
}

.session-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.session-messages {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.session-message {
  padding: 10px 12px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid var(--line);
}

.session-message.user {
  background: #f3f8f7;
}

.message-role {
  font-size: 9.5px;
  letter-spacing: 0.12em;
  color: var(--muted-2);
  margin-bottom: 4px;
}

.message-content {
  font-size: 11.5px;
  line-height: 1.75;
  color: var(--text-2);
  white-space: pre-wrap;
  max-height: 120px;
  overflow: hidden;
}

.message-cites {
  margin-top: 5px;
  font-size: 10px;
  color: var(--teal-700);
}

.aside-col {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.ops-panel .panel-head,
.tips-panel .panel-head {
  margin-bottom: 10px;
}

.ops-body {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 0 18px 16px;
}

.ops-item {
  flex: 1;
  min-width: 90px;
  padding: 10px;
  background: #f8fbfa;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ops-item strong {
  font-family: var(--font-serif);
  font-size: 21px;
  line-height: 1;
  color: var(--teal-700);
}

.ops-item span {
  font-size: 10px;
  color: var(--muted-2);
}

.ops-note {
  width: 100%;
  margin: 4px 0 0;
  font-size: 10.5px;
  line-height: 1.7;
  color: var(--muted-2);
}

.tips-panel {
  padding: 16px 18px;
}

.tips-list {
  margin: 0;
  padding-left: 16px;
  display: flex;
  flex-direction: column;
  gap: 7px;
  font-size: 11px;
  line-height: 1.7;
  color: var(--muted);
}

@media (max-width: 1200px) {
  .report-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .export-lower {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .report-grid {
    grid-template-columns: 1fr;
  }
}
</style>
