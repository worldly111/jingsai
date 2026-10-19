<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { ensureOptions, store } from '../store'
import { fmtDate, fmtMoney, fmtNumber, levelType, tagType } from '../utils'
import PageHeader from '../components/PageHeader.vue'
import StatCard from '../components/StatCard.vue'
import EmptyState from '../components/EmptyState.vue'

const router = useRouter()

const filters = reactive({
  year: null,
  competition: '',
  level: '',
  status: '',
  major: '',
  teacher: '',
  student: '',
  keyword: ''
})

const page = ref(1)
const size = ref(20)
const total = ref(0)
const items = ref([])
const loading = ref(false)
const exporting = ref(false)
const overview = ref(null)
const detailOpen = ref(false)
const current = ref(null)

const statusOptions = ['报名中', '备赛中', '参赛中', '已完赛', '获奖']
const yearOptions = computed(() => (store.options?.years || []).slice().sort((a, b) => b - a))

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / size.value)))

function filterPayload() {
  return {
    years: filters.year || undefined,
    competitions: filters.competition || undefined,
    levels: filters.level || undefined,
    majors: filters.major || undefined,
    teachers: filters.teacher || undefined,
    students: filters.student || undefined,
    keyword: filters.keyword || undefined
  }
}

async function load() {
  loading.value = true
  try {
    const [ledger, stats] = await Promise.all([
      api.ledger({
        year: filters.year || undefined,
        competition: filters.competition,
        level: filters.level,
        status: filters.status,
        major: filters.major,
        teacher: filters.teacher,
        student: filters.student,
        keyword: filters.keyword,
        offset: (page.value - 1) * size.value,
        limit: size.value
      }),
      api.statsOverview(filterPayload()).catch(() => null)
    ])
    items.value = ledger.items || []
    total.value = ledger.total || 0
    overview.value = stats?.overview || null
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

function handleSizeChange() {
  page.value = 1
  load()
}

function reset() {
  Object.assign(filters, {
    year: null,
    competition: '',
    level: '',
    status: '',
    major: '',
    teacher: '',
    student: '',
    keyword: ''
  })
  page.value = 1
  load()
}

async function exportExcel() {
  try {
    exporting.value = true
    await api.exportRegistrations(filterPayload())
    if (filters.status) ElMessage.info('导出报表按年度、赛事、级别、专业等字段生成，状态筛选仅作用于页面列表')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    exporting.value = false
  }
}

function openDetail(row) {
  current.value = row
  detailOpen.value = true
}

function goStats() {
  router.push({ name: 'stats', query: { year: filters.year || undefined, competition: filters.competition || undefined } })
}

onMounted(async () => {
  await ensureOptions()
  await load()
})
</script>

<template>
  <div>
    <PageHeader
      eyebrow="Ledger"
      title="参赛与获奖台账"
      description="按年度、赛事、专业、教师与学生检索参赛记录，展开可查看团队成员与获奖明细。统计与导出均以结构化台账为准。"
    >
      <template #actions>
        <el-button :loading="exporting" @click="exportExcel"><el-icon><Download /></el-icon> 导出台账</el-button>
        <el-button type="primary" @click="goStats"><el-icon><DataAnalysis /></el-icon> 统计分析</el-button>
      </template>
    </PageHeader>

    <div class="stat-grid" style="margin-bottom: 16px">
      <StatCard label="参赛队次" :value="fmtNumber(overview?.registrations)" note="当前筛选范围" icon="Tickets" tone="ink" />
      <StatCard label="获奖项数" :value="fmtNumber(overview?.awards)" :note="`获奖率 ${overview?.award_rate ?? 0}%`" icon="Trophy" tone="gold" />
      <StatCard label="参赛学生" :value="fmtNumber(overview?.participants)" note="按人次统计" icon="User" />
      <StatCard label="指导教师" :value="fmtNumber(overview?.teachers)" note="参与指导的教师" icon="Avatar" />
    </div>

    <div class="panel filter-panel">
      <div class="filter-row">
        <el-select v-model="filters.year" clearable placeholder="年度" style="width: 110px" @change="search">
          <el-option v-for="year in yearOptions" :key="year" :label="`${year} 年`" :value="year" />
        </el-select>
        <el-select v-model="filters.competition" clearable filterable placeholder="赛事" style="width: 190px" @change="search">
          <el-option v-for="comp in store.options?.competitions || []" :key="comp.id" :label="comp.name" :value="comp.name" />
        </el-select>
        <el-select v-model="filters.level" clearable placeholder="级别" style="width: 110px" @change="search">
          <el-option v-for="level in store.options?.levels || []" :key="level" :label="level" :value="level" />
        </el-select>
        <el-select v-model="filters.status" clearable placeholder="状态" style="width: 110px" @change="search">
          <el-option v-for="status in statusOptions" :key="status" :label="status" :value="status" />
        </el-select>
        <el-select v-model="filters.major" clearable filterable placeholder="专业" style="width: 160px" @change="search">
          <el-option v-for="major in store.options?.majors || []" :key="major" :label="major" :value="major" />
        </el-select>
        <el-select v-model="filters.teacher" clearable filterable placeholder="指导教师" style="width: 130px" @change="search">
          <el-option v-for="teacher in store.options?.teachers || []" :key="teacher" :label="teacher" :value="teacher" />
        </el-select>
        <el-select v-model="filters.student" clearable filterable placeholder="学生" style="width: 120px" @change="search">
          <el-option v-for="student in store.options?.students || []" :key="student" :label="student" :value="student" />
        </el-select>
        <el-input v-model="filters.keyword" clearable placeholder="队名 / 项目 / 关键词" style="width: 200px" @keyup.enter="search" @clear="search">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-button type="primary" :loading="loading" @click="search">查询</el-button>
        <el-button @click="reset">重置</el-button>
      </div>
    </div>

    <div class="panel ledger-panel">
      <div class="panel-head">
        <h3>台账明细</h3>
        <span class="sub">共 {{ fmtNumber(total) }} 条 · 第 {{ page }} / {{ totalPages }} 页</span>
        <div class="right">
          <span class="muted small">点击行首箭头展开成员与获奖</span>
        </div>
      </div>

      <el-table :data="items" v-loading="loading" size="small" row-key="id" style="width: 100%">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expand-wrap">
              <div class="expand-col">
                <div class="expand-title">团队成员（{{ row.members?.length || 0 }}）</div>
                <el-table v-if="row.members?.length" :data="row.members" size="small" border>
                  <el-table-column prop="student_no" label="学号" width="110" />
                  <el-table-column prop="student_name" label="姓名" width="90" />
                  <el-table-column prop="major_name" label="专业" min-width="150" />
                  <el-table-column prop="grade" label="年级" width="90" />
                  <el-table-column prop="role" label="角色" width="100" />
                </el-table>
                <div v-else class="muted small">暂无成员信息</div>
                <div class="expand-title" style="margin-top: 14px">指导教师（{{ row.mentors?.length || 0 }}）</div>
                <div class="mentor-row">
                  <span v-for="mentor in row.mentors || []" :key="mentor.teacher_name" class="tag-soft teal">
                    {{ mentor.teacher_name }}<template v-if="mentor.role"> · {{ mentor.role }}</template>
                  </span>
                  <span v-if="!row.mentors?.length" class="muted small">暂无指导教师信息</span>
                </div>
              </div>
              <div class="expand-col">
                <div class="expand-title">获奖记录（{{ row.awards?.length || 0 }}）</div>
                <el-table v-if="row.awards?.length" :data="row.awards" size="small" border>
                  <el-table-column prop="award_year" label="年度" width="70" />
                  <el-table-column prop="award_level" label="等级" width="80" />
                  <el-table-column prop="award_grade" label="奖项" width="90" />
                  <el-table-column prop="project_title" label="项目" min-width="150" show-overflow-tooltip />
                  <el-table-column prop="points" label="积分" width="70" />
                  <el-table-column prop="certificate_no" label="证书编号" min-width="130" />
                  <el-table-column label="获奖日期" width="110">
                    <template #default="{ row: award }">{{ fmtDate(award.award_date) }}</template>
                  </el-table-column>
                </el-table>
                <div v-else class="muted small">该记录暂无获奖信息</div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="year" label="年度" width="70" />
        <el-table-column label="赛事 / 级别" min-width="185">
          <template #default="{ row }">
            <div class="cell-stack">
              <span class="cell-main">{{ row.competition_name }}</span>
              <span class="cell-sub">
                <el-tag size="small" :type="levelType[row.competition_level] || 'info'">{{ row.competition_level || '未认定' }}</el-tag>
                <span v-if="row.track_name">{{ row.track_name }}</span>
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="团队 / 项目" min-width="190">
          <template #default="{ row }">
            <div class="cell-stack">
              <span class="cell-main">{{ row.team_name || '—' }}</span>
              <span class="cell-sub">{{ row.project_title || '—' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="负责人" width="130">
          <template #default="{ row }">
            <div class="cell-stack">
              <span class="cell-main">{{ row.leader_name || '—' }}</span>
              <span class="cell-sub">{{ row.lead_major || '—' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="mentor_names" label="指导教师" min-width="130" show-overflow-tooltip />
        <el-table-column label="状态" width="85">
          <template #default="{ row }"><el-tag size="small" :type="tagType(row.status)">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="获奖" width="150">
          <template #default="{ row }">
            <span v-if="row.awards?.length" class="award-badge">
              <el-icon><Trophy /></el-icon>
              {{ row.awards.map((a) => `${a.award_level}${a.award_grade}`).join(' / ') }}
            </span>
            <span v-else class="muted small">—</span>
          </template>
        </el-table-column>
        <el-table-column label="报名日期" width="105">
          <template #default="{ row }">{{ fmtDate(row.register_date) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <EmptyState title="没有匹配的台账记录" description="尝试调整年度、赛事或关键词筛选条件。" />
        </template>
      </el-table>

      <div class="pager-row">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="size"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          background
          @current-change="load"
          @size-change="handleSizeChange"
        />
      </div>
    </div>

    <el-drawer v-model="detailOpen" :title="current?.competition_name || '参赛记录'" size="640px">
      <template v-if="current">
        <div class="drawer-head">
          <el-tag :type="levelType[current.competition_level] || 'info'">{{ current.competition_level }}</el-tag>
          <el-tag :type="tagType(current.status)">{{ current.status }}</el-tag>
          <span class="mono muted">{{ current.code }}</span>
          <span class="muted">{{ current.year }} 年</span>
        </div>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="赛事">{{ current.competition_name }}</el-descriptions-item>
          <el-descriptions-item label="赛道">{{ current.track_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="团队名称">{{ current.team_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="项目名称">{{ current.project_title || '—' }}</el-descriptions-item>
          <el-descriptions-item label="负责人">{{ current.leader_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="负责人专业">{{ current.lead_major || '—' }}</el-descriptions-item>
          <el-descriptions-item label="报名日期">{{ fmtDate(current.register_date) }}</el-descriptions-item>
          <el-descriptions-item label="完成日期">{{ fmtDate(current.finish_date) }}</el-descriptions-item>
          <el-descriptions-item label="到达阶段">{{ current.stage_reached || '—' }}</el-descriptions-item>
          <el-descriptions-item label="获奖项数">{{ current.awards?.length || 0 }}</el-descriptions-item>
        </el-descriptions>

        <div class="drawer-section">
          <div class="result-section-title">团队成员</div>
          <el-table :data="current.members || []" size="small" border>
            <el-table-column prop="student_no" label="学号" width="110" />
            <el-table-column prop="student_name" label="姓名" width="90" />
            <el-table-column prop="major_name" label="专业" min-width="140" />
            <el-table-column prop="grade" label="年级" width="90" />
            <el-table-column prop="role" label="角色" width="100" />
          </el-table>
        </div>

        <div class="drawer-section">
          <div class="result-section-title">获奖记录</div>
          <el-table :data="current.awards || []" size="small" border>
            <el-table-column prop="award_level" label="等级" width="80" />
            <el-table-column prop="award_grade" label="奖项" width="90" />
            <el-table-column prop="project_title" label="项目" min-width="150" show-overflow-tooltip />
            <el-table-column prop="students" label="学生" min-width="140" show-overflow-tooltip />
            <el-table-column prop="mentors" label="教师" width="100" show-overflow-tooltip />
            <el-table-column prop="points" label="积分" width="70" />
          </el-table>
          <p v-if="!current.awards?.length" class="muted small">暂无获奖记录</p>
        </div>
      </template>
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

.ledger-panel {
  padding: 0;
  overflow: hidden;
}

.ledger-panel .panel-head {
  margin: 0;
  padding: 14px 18px;
}

.cell-stack {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.cell-main {
  font-size: 12px;
  color: var(--text-1);
  line-height: 1.5;
}

.cell-sub {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 10.5px;
  color: var(--muted-2);
  line-height: 1.5;
}

.award-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10.5px;
  color: #9a6b1d;
  background: rgba(196, 146, 50, 0.12);
  padding: 2px 7px;
  border-radius: 20px;
  line-height: 1.5;
}

.expand-wrap {
  display: grid;
  grid-template-columns: 1fr 1.15fr;
  gap: 22px;
  padding: 12px 26px 18px;
  background: #fbfcfc;
}

.expand-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--teal-700);
  margin-bottom: 7px;
}

.mentor-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.pager-row {
  display: flex;
  justify-content: flex-end;
  padding: 14px 18px;
  border-top: 1px solid var(--line);
}

.drawer-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.drawer-section {
  margin-top: 18px;
}

@media (max-width: 1100px) {
  .expand-wrap {
    grid-template-columns: 1fr;
  }
}
</style>
