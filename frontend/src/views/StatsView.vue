<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { can, ensureOptions, store } from '../store'
import { fmtNumber, pct } from '../utils'
import PageHeader from '../components/PageHeader.vue'
import StatCard from '../components/StatCard.vue'
import EChart from '../components/EChart.vue'
import ResultView from '../components/ResultView.vue'
import EmptyState from '../components/EmptyState.vue'

const route = useRoute()
const canExport = computed(() => can('export.use'))

const filters = reactive({
  years: [],
  competitions: [],
  levels: [],
  majors: [],
  keyword: ''
})

const overview = ref(null)
const charts = ref({})
const loading = ref(false)
const chartsLoading = ref(false)
const exporting = ref('')
const dimension = ref('year')

const analysisOpen = ref(false)
const analysisLoading = ref(false)
const analysisResult = ref(null)

const chartKinds = [
  { kind: 'trend', name: '年度趋势', icon: 'TrendCharts' },
  { kind: 'competition', name: '赛事对比', icon: 'Histogram' },
  { kind: 'award_level', name: '获奖等级构成', icon: 'PieChart' },
  { kind: 'major', name: '专业分布', icon: 'School' },
  { kind: 'teacher', name: '教师排行', icon: 'Avatar' },
  { kind: 'level', name: '赛事级别构成', icon: 'CollectionTag' },
  { kind: 'workload', name: '教师工作量', icon: 'Odometer' }
]

const yearOptions = computed(() => (store.options?.years || []).slice().sort((a, b) => b - a))

const filterParams = computed(() => ({
  years: filters.years.length ? filters.years.join(',') : undefined,
  competitions: filters.competitions.length ? filters.competitions.join(',') : undefined,
  levels: filters.levels.length ? filters.levels.join(',') : undefined,
  majors: filters.majors.length ? filters.majors.join(',') : undefined,
  keyword: filters.keyword || undefined
}))

const filterText = computed(() => overview.value?.filter_text || '全部台账数据')
const ov = computed(() => overview.value?.overview || {})

const heatmapOption = computed(() => {
  const data = overview.value?.year_major_awards
  if (!data?.rows?.length || !data?.columns?.length) return null
  const points = []
  let max = 0
  data.matrix.forEach((line, rowIndex) => {
    line.forEach((value, colIndex) => {
      points.push([colIndex, rowIndex, value])
      if (value > max) max = value
    })
  })
  return {
    tooltip: { position: 'top', formatter: (p) => `${data.rows[p.value[1]]} 年 · ${data.columns[p.value[0]]}：${p.value[2]} 项` },
    grid: { left: 70, right: 30, top: 20, bottom: 90 },
    xAxis: { type: 'category', data: data.columns, axisLabel: { rotate: 35, fontSize: 10 }, splitArea: { show: true } },
    yAxis: { type: 'category', data: data.rows.map((y) => `${y} 年`), splitArea: { show: true } },
    visualMap: {
      min: 0,
      max: Math.max(max, 1),
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      itemWidth: 12,
      itemHeight: 90,
      textStyle: { fontSize: 10, color: '#617980' },
      inRange: { color: ['#f2f8f7', '#bfe3de', '#6ec3b8', '#1e9d90', '#0a5b57'] }
    },
    series: [{
      name: '获奖项数',
      type: 'heatmap',
      data: points,
      label: { show: true, fontSize: 10, color: '#17323d' },
      emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'rgba(0,0,0,.2)' } }
    }]
  }
})

const dimensionTabs = computed(() => {
  const o = overview.value
  if (!o) return []
  return [
    {
      key: 'year',
      label: '年度',
      rows: o.by_year || [],
      columns: [
        { prop: 'year', label: '年度', width: 80 },
        { prop: 'registrations', label: '参赛队次', width: 100 },
        { prop: 'participants', label: '参赛人次', width: 100 },
        { prop: 'awards', label: '获奖项数', width: 100 },
        { prop: 'high_level_awards', label: '高等级奖', width: 100 },
        { prop: 'award_rate', label: '获奖率(%)', width: 100 }
      ]
    },
    {
      key: 'competition',
      label: '赛事',
      rows: o.by_competition || [],
      columns: [
        { prop: 'competition_name', label: '赛事', minWidth: 220 },
        { prop: 'registrations', label: '参赛队次', width: 100 },
        { prop: 'awards', label: '获奖项数', width: 100 },
        { prop: 'high_level_awards', label: '高等级奖', width: 100 },
        { prop: 'award_rate', label: '获奖率(%)', width: 100 }
      ]
    },
    {
      key: 'major',
      label: '专业',
      rows: o.by_major || [],
      columns: [
        { prop: 'major', label: '专业', minWidth: 200 },
        { prop: 'registrations', label: '参赛队次', width: 100 },
        { prop: 'awards', label: '获奖项数', width: 100 },
        { prop: 'award_rate', label: '获奖率(%)', width: 100 }
      ]
    },
    {
      key: 'award_level',
      label: '获奖等级',
      rows: o.by_award_level || [],
      columns: [
        { prop: 'award_level', label: '等级', width: 110 },
        { prop: 'award_grade', label: '奖项', width: 110 },
        { prop: 'count', label: '数量', width: 100 },
        { prop: 'ratio', label: '占比(%)', width: 100 }
      ]
    },
    {
      key: 'level',
      label: '赛事级别',
      rows: o.by_level || [],
      columns: [
        { prop: 'level', label: '级别', width: 140 },
        { prop: 'registrations', label: '参赛队次', width: 110 },
        { prop: 'awards', label: '获奖项数', width: 110 }
      ]
    },
    {
      key: 'teacher',
      label: '指导教师',
      rows: o.by_teacher || [],
      columns: [
        { prop: 'teacher', label: '教师', width: 120 },
        { prop: 'registrations', label: '指导队次', width: 100 },
        { prop: 'awards', label: '获奖项数', width: 100 },
        { prop: 'high_level_awards', label: '高等级奖', width: 100 },
        { prop: 'student_count', label: '指导学生数', width: 110 },
        { prop: 'competition_count', label: '指导赛事数', width: 110 }
      ]
    },
    {
      key: 'student',
      label: '学生',
      rows: o.by_student || [],
      columns: [
        { prop: 'student', label: '学生', width: 120 },
        { prop: 'majors', label: '专业', minWidth: 180 },
        { prop: 'registrations', label: '参赛次数', width: 100 },
        { prop: 'awards', label: '获奖项数', width: 100 },
        { prop: 'points', label: '获奖积分', width: 100 },
        { prop: 'award_rate', label: '获奖率(%)', width: 100 }
      ]
    },
    {
      key: 'workload',
      label: '教师工作量',
      rows: o.teacher_workload || [],
      columns: [
        { prop: 'teacher', label: '教师', width: 120 },
        { prop: 'awards', label: '获奖项数', width: 100 },
        { prop: 'workload', label: '折算工作量', width: 110 },
        { prop: 'student_points', label: '学生积分', width: 100 }
      ]
    }
  ]
})

const currentTab = computed(() => dimensionTabs.value.find((t) => t.key === dimension.value) || dimensionTabs.value[0])

async function load() {
  loading.value = true
  chartsLoading.value = true
  try {
    const params = filterParams.value
    overview.value = await api.statsOverview(params)
    const results = await Promise.all(
      chartKinds.map((item) => api.statsChart(item.kind, params).catch(() => null))
    )
    const next = {}
    results.forEach((option, index) => {
      if (option) next[chartKinds[index].kind] = option
    })
    charts.value = next
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
    chartsLoading.value = false
  }
}

function reset() {
  filters.years = []
  filters.competitions = []
  filters.levels = []
  filters.majors = []
  filters.keyword = ''
  load()
}

async function doExport(kind, format = 'xlsx') {
  exporting.value = `${kind}-${format}`
  try {
    if (kind === 'stats') await api.exportStats(filterParams.value, format)
    if (kind === 'awards') await api.exportAwards(filterParams.value)
    if (kind === 'registrations') await api.exportRegistrations(filterParams.value)
    ElMessage.success('报表已开始下载')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    exporting.value = ''
  }
}

async function analyze() {
  analysisOpen.value = true
  analysisLoading.value = true
  analysisResult.value = null
  try {
    const question = `请统计并分析${filterText.value}的竞赛参赛与获奖情况，重点说明年度趋势、获奖等级分布、表现突出的赛事与专业，并给出竞赛组织管理建议。`
    analysisResult.value = await api.runAgent('stats', { question, user_role: store.role })
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    analysisLoading.value = false
  }
}

onMounted(async () => {
  await ensureOptions()
  if (route.query.year) filters.years = [Number(route.query.year)]
  if (route.query.competition) filters.competitions = [String(route.query.competition)]
  await load()
})
</script>

<template>
  <div>
    <PageHeader
      eyebrow="Analytics"
      title="统计分析"
      description="从结构化台账实时汇总年度、赛事、专业、学生、教师与获奖等级维度，ECharts 可视化辅助竞赛管理决策。"
    >
      <template #actions>
        <template v-if="canExport">
          <el-button :loading="exporting === 'stats-xlsx'" @click="doExport('stats', 'xlsx')"><el-icon><Download /></el-icon> 统计报表</el-button>
          <el-button :loading="exporting === 'stats-csv'" @click="doExport('stats', 'csv')">CSV</el-button>
        </template>
        <el-button type="primary" @click="analyze"><el-icon><MagicStick /></el-icon> 智能分析简报</el-button>
      </template>
    </PageHeader>

    <div class="panel filter-panel">
      <div class="filter-row">
        <el-select v-model="filters.years" multiple collapse-tags clearable placeholder="年度" style="width: 140px">
          <el-option v-for="year in yearOptions" :key="year" :label="`${year} 年`" :value="year" />
        </el-select>
        <el-select v-model="filters.competitions" multiple collapse-tags filterable clearable placeholder="赛事" style="width: 230px">
          <el-option v-for="comp in store.options?.competitions || []" :key="comp.id" :label="comp.name" :value="comp.name" />
        </el-select>
        <el-select v-model="filters.levels" multiple collapse-tags clearable placeholder="赛事级别" style="width: 140px">
          <el-option v-for="level in store.options?.levels || []" :key="level" :label="level" :value="level" />
        </el-select>
        <el-select v-model="filters.majors" multiple collapse-tags filterable clearable placeholder="专业" style="width: 190px">
          <el-option v-for="major in store.options?.majors || []" :key="major" :label="major" :value="major" />
        </el-select>
        <el-input v-model="filters.keyword" clearable placeholder="项目 / 团队 / 关键词" style="width: 190px" @keyup.enter="load" @clear="load">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-button type="primary" :loading="loading" @click="load">生成分析</el-button>
        <el-button @click="reset">重置</el-button>
        <span class="filter-text">{{ filterText }}</span>
      </div>
    </div>

    <div class="stat-grid" style="margin-bottom: 16px">
      <StatCard label="参赛队次" :value="fmtNumber(ov.registrations)" :note="`覆盖 ${fmtNumber(ov.competitions)} 项赛事`" icon="Tickets" tone="ink" />
      <StatCard label="参赛人次" :value="fmtNumber(ov.participants)" :note="`${fmtNumber(ov.students)} 名学生`" icon="User" />
      <StatCard label="获奖项数" :value="fmtNumber(ov.awards)" :note="`获奖率 ${pct(ov.award_rate)}`" icon="Trophy" tone="gold" />
      <StatCard label="高等级奖" :value="fmtNumber(ov.high_level_awards)" note="特等奖与一等奖" icon="Medal" />
    </div>

    <div class="chart-grid" v-loading="chartsLoading">
      <div v-for="item in chartKinds" :key="item.kind" class="chart-card">
        <div class="chart-card-head">
          <h4>{{ item.name }}</h4>
          <span class="tag-soft" style="margin-left: auto">{{ item.kind }}</span>
        </div>
        <div class="chart-card-body">
          <EChart v-if="charts[item.kind]" :option="charts[item.kind]" :height="320" />
          <div v-else class="chart-empty">暂无数据</div>
        </div>
      </div>
      <div class="chart-card heatmap-card">
        <div class="chart-card-head">
          <h4>年度 × 专业获奖热力图</h4>
          <span class="tag-soft gold" style="margin-left: auto">heatmap</span>
        </div>
        <div class="chart-card-body">
          <EChart v-if="heatmapOption" :option="heatmapOption" :height="340" />
          <div v-else class="chart-empty">暂无获奖数据</div>
        </div>
      </div>
    </div>

    <div class="panel dimension-panel">
      <div class="panel-head">
        <h3>多维明细</h3>
        <span class="sub">按结构化台账实时计算</span>
        <div class="right">
          <template v-if="canExport">
            <el-button size="small" text :loading="exporting === 'awards'" @click="doExport('awards')"><el-icon><Download /></el-icon> 获奖明细</el-button>
            <el-button size="small" text :loading="exporting === 'registrations'" @click="doExport('registrations')"><el-icon><Download /></el-icon> 参赛台账</el-button>
          </template>
        </div>
      </div>
      <el-tabs v-model="dimension" class="dimension-tabs">
        <el-tab-pane v-for="tab in dimensionTabs" :key="tab.key" :label="tab.label" :name="tab.key">
          <el-table v-if="currentTab && currentTab.key === tab.key" :data="tab.rows" size="small" stripe max-height="460" style="width: 100%">
            <el-table-column
              v-for="col in tab.columns"
              :key="col.prop"
              :prop="col.prop"
              :label="col.label"
              :width="col.width"
              :min-width="col.minWidth"
              show-overflow-tooltip
            />
            <template #empty>
              <div style="padding: 26px 0; color: var(--muted-2); font-size: 12px">当前筛选范围暂无数据</div>
            </template>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>

    <div class="data-source-note">
      <el-icon><Lock /></el-icon>
      统计口径：{{ filterText }}。数据来源：{{ overview?.data_source || '结构化业务数据' }}；重要数据不依赖大模型生成。
    </div>

    <el-drawer v-model="analysisOpen" title="智能分析简报" size="760px">
      <div v-if="analysisLoading" class="analysis-loading">
        <el-skeleton :rows="8" animated />
        <p class="muted">正在调用统计智能体汇总台账数据…</p>
      </div>
      <ResultView
        v-else-if="analysisResult"
        :result="analysisResult"
        title="竞赛统计智能体 · 分析简报"
        :show-charts="true"
        :show-tables="true"
      />
      <EmptyState v-else title="分析未生成" description="关闭后重试，或检查后端服务状态。" />
    </el-drawer>
  </div>
</template>

<style scoped>
.filter-panel {
  padding: 14px 16px;
  margin-bottom: 16px;
}

.filter-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.filter-text {
  margin-left: auto;
  font-size: 11px;
  color: var(--muted-2);
}

.chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 18px;
  min-height: 200px;
}

.heatmap-card {
  grid-column: 1 / -1;
}

.chart-empty {
  height: 320px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted-2);
  font-size: 12px;
}

.dimension-panel {
  padding: 0 18px 18px;
}

.dimension-panel .panel-head {
  margin: 0 -18px;
  padding: 14px 18px;
}

.dimension-tabs {
  margin-top: 4px;
}

.dimension-tabs :deep(.el-tabs__item) {
  font-size: 12px;
  padding: 0 14px;
  height: 40px;
}

.data-source-note {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 12px 4px 0;
  font-size: 11px;
  color: var(--muted-2);
}

.analysis-loading {
  padding: 12px 4px;
}

.analysis-loading p {
  text-align: center;
  margin-top: 18px;
}

@media (max-width: 1100px) {
  .chart-grid {
    grid-template-columns: 1fr;
  }
  .heatmap-card {
    grid-column: auto;
  }
}
</style>
