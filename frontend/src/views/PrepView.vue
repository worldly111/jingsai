<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { ensureOptions, store } from '../store'
import { fmtDate, levelType } from '../utils'
import PageHeader from '../components/PageHeader.vue'
import ResultView from '../components/ResultView.vue'

const route = useRoute()
const router = useRouter()
const form = reactive({
  competition: '',
  year: null,
  target_date: ''
})
const loading = ref(false)
const result = ref(null)
const checked = reactive({})
const resultRef = ref(null)

const plan = computed(() => result.value?.structured?.plan)
const event = computed(() => result.value?.structured?.event)
const timeline = computed(() => plan.value?.timeline || [])
const materials = computed(() => plan.value?.materials || [])
const tracks = computed(() => plan.value?.tracks || [])
const notes = computed(() => plan.value?.notes || [])
const ledger = computed(() => plan.value?.ledger || {})

const materialDone = computed(() => materials.value.filter((m) => checked[m.name]).length)
const materialProgress = computed(() =>
  materials.value.length ? Math.round((materialDone.value / materials.value.length) * 100) : 0
)

const yearOptions = computed(() => (store.options?.years || []).slice().sort((a, b) => b - a))

const expired = computed(() => Boolean(plan.value?.expired))

const targetLabel = computed(() => {
  if (!plan.value) return ''
  if (expired.value) return `已过期 ${Math.abs(plan.value.days_left || 0)} 天`
  return `剩余 ${plan.value.days_left} 天`
})

async function generate() {
  if (!form.competition) {
    ElMessage.warning('请先选择要备赛的赛事')
    return
  }
  loading.value = true
  result.value = null
  Object.keys(checked).forEach((key) => delete checked[key])
  try {
    const data = await api.runAgent('prep', {
      question: `帮我制定${form.competition}的备赛计划`,
      payload: {
        competition_name: form.competition,
        year: form.year || undefined,
        target_date: form.target_date || undefined
      },
      user_role: store.role
    })
    result.value = data
    await nextTick()
    resultRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

async function exportPlan() {
  try {
    await api.exportAgent(
      { title: `${form.competition} 备赛计划`, answer: result.value?.answer || '', tables: result.value?.tables || [] },
      'docx'
    )
  } catch (error) {
    ElMessage.error(error.message)
  }
}

function goFinance() {
  router.push({ name: 'finance', query: { competition: form.competition, tab: 'budget' } })
}

function goReview() {
  router.push({ name: 'review', query: { competition: form.competition } })
}

onMounted(async () => {
  await ensureOptions()
  const q = String(route.query.competition || '')
  if (q) form.competition = q
  else if (store.options?.competitions?.length) form.competition = store.options.competitions[0].name
})
</script>

<template>
  <div>
    <PageHeader
      eyebrow="Preparation"
      title="备赛辅助"
      description="从赛事通知中提取报名窗口、材料与组队要求，结合剩余时间倒排阶段计划，并生成可直接执行的任务清单。"
    >
      <template #actions>
        <el-button @click="router.push('/review')"><el-icon><DocumentChecked /></el-icon> 材料初检</el-button>
      </template>
    </PageHeader>

    <div class="panel setup-panel">
      <div class="setup-copy">
        <div class="setup-eyebrow">PLAN GENERATOR</div>
        <h3>选择赛事，生成倒排计划</h3>
        <p>计划依据赛事台账中的报名截止日期与材料清单自动测算；新增赛事后无需修改代码。</p>
      </div>
      <div class="setup-form">
        <div class="setup-field grow">
          <label class="field-label">赛事<span class="req">*</span></label>
          <el-select
            v-model="form.competition"
            filterable
            allow-create
            placeholder="选择赛事"
            style="width: 100%"
          >
            <el-option
              v-for="comp in store.options?.competitions || []"
              :key="comp.id"
              :label="comp.name"
              :value="comp.name"
            >
              <span>{{ comp.name }}</span>
              <span style="float: right; color: #96a6ae; font-size: 10px">{{ comp.level }}</span>
            </el-option>
          </el-select>
        </div>
        <div class="setup-field">
          <label class="field-label">届次</label>
          <el-select v-model="form.year" clearable placeholder="最新" style="width: 100%">
            <el-option v-for="year in yearOptions" :key="year" :label="`${year} 年`" :value="year" />
          </el-select>
        </div>
        <div class="setup-field">
          <label class="field-label">目标日期</label>
          <el-date-picker
            v-model="form.target_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="默认报名截止"
            style="width: 100%"
          />
        </div>
        <el-button type="primary" :loading="loading" class="setup-button" @click="generate">
          <el-icon v-if="!loading"><Calendar /></el-icon>
          {{ loading ? '生成中' : '生成计划' }}
        </el-button>
      </div>
    </div>

    <div v-if="!result" class="prep-intro-grid">
      <div class="panel intro-card">
        <div class="intro-icon"><el-icon><Calendar /></el-icon></div>
        <h4>倒排阶段计划</h4>
        <p>以报名截止或指定日期为终点，按信息确认、方案设计、开发验证、材料打磨、提交答辩划分阶段。</p>
      </div>
      <div class="panel intro-card">
        <div class="intro-icon"><el-icon><List /></el-icon></div>
        <h4>材料与任务清单</h4>
        <p>从届次材料要求生成逐项清单，并附上容易被忽略的报名资格、组队、费用提醒。</p>
      </div>
      <div class="panel intro-card">
        <div class="intro-icon"><el-icon><DataLine /></el-icon></div>
        <h4>学院台账参考</h4>
        <p>同步展示学院历年参赛与获奖情况，帮助学生判断投入强度与目标定位。</p>
      </div>
    </div>

    <div v-else ref="resultRef" class="prep-result">
      <div class="plan-banner" :class="{ expired }">
        <div class="plan-banner-main">
          <div class="plan-badges">
            <span class="tag-soft teal">{{ event?.level || plan?.competition?.level }}</span>
            <span class="tag-soft">{{ plan?.competition?.category }}</span>
            <span v-if="plan?.edition?.name" class="tag-soft gold">{{ plan?.edition?.year }} 年 · {{ plan?.edition?.name }}</span>
          </div>
          <h2>{{ plan?.competition?.name || form.competition }}</h2>
          <p>
            <template v-if="expired">
              该届报名已于 {{ fmtDate(plan?.target_date) }} 截止（{{ Math.abs(plan?.days_left || 0) }} 天前），
              以下材料与要求可作为下一届备赛参考。
            </template>
            <template v-else>
              目标日期 {{ fmtDate(plan?.target_date) }}，报名窗口
              {{ fmtDate(plan?.edition?.register_start) }} 至 {{ fmtDate(plan?.edition?.register_end) }}。
            </template>
          </p>
        </div>
        <div class="plan-metrics">
          <div class="plan-metric">
            <strong :class="{ warn: expired }">{{ expired ? '已截止' : plan?.days_left }}</strong>
            <span>{{ expired ? '报名状态' : '剩余天数' }}</span>
          </div>
          <div class="plan-metric">
            <strong>{{ timeline.length }}</strong>
            <span>备赛阶段</span>
          </div>
          <div class="plan-metric">
            <strong>{{ plan?.checklist_total ?? materials.length }}</strong>
            <span>任务与材料</span>
          </div>
          <div class="plan-metric">
            <strong>{{ ledger.registrations ?? 0 }}<small>/{{ ledger.awards ?? 0 }}</small></strong>
            <span>历年参赛 / 获奖</span>
          </div>
        </div>
        <div class="plan-banner-actions">
          <el-button size="small" @click="exportPlan"><el-icon><Download /></el-icon> 导出计划</el-button>
          <el-button size="small" @click="goReview">材料初检</el-button>
          <el-button size="small" type="primary" plain @click="goFinance">经费预算</el-button>
        </div>
      </div>

      <div v-if="plan?.expired || result.structured?.plan_error" class="panel notice-panel">
        <el-icon color="#b07a2e"><WarningFilled /></el-icon>
        <div>
          {{ result.structured?.plan_error || '所查询届次已经截止，未生成倒排时间表。更新下一届通知后重新生成即可。' }}
        </div>
      </div>

      <template v-if="timeline.length">
        <div class="section-label">倒排阶段计划</div>
        <div class="timeline-grid">
          <div v-for="(stage, index) in timeline" :key="stage.stage" class="stage-card">
            <div class="stage-top">
              <span class="stage-index">{{ String(index + 1).padStart(2, '0') }}</span>
              <span class="stage-range">{{ fmtDate(stage.start) }} → {{ fmtDate(stage.end) }}</span>
            </div>
            <h4>{{ stage.stage }}</h4>
            <ul>
              <li v-for="task in stage.tasks" :key="task">{{ task }}</li>
            </ul>
            <div v-if="index < timeline.length - 1" class="stage-connector">
              <el-icon><ArrowRight /></el-icon>
            </div>
          </div>
        </div>
      </template>

      <div class="prep-columns">
        <div class="panel materials-panel">
          <div class="panel-head">
            <h3>材料准备清单</h3>
            <span class="sub">{{ materialDone }} / {{ materials.length }} 已完成</span>
            <div class="right">
              <el-progress
                :percentage="materialProgress"
                :stroke-width="5"
                :show-text="false"
                color="#0f9f93"
                style="width: 86px"
              />
            </div>
          </div>
          <div class="material-list">
            <label v-for="item in materials" :key="item.name" class="material-row" :class="{ done: checked[item.name] }">
              <el-checkbox v-model="checked[item.name]" />
              <div class="material-main">
                <div class="material-name">{{ item.name }}</div>
                <div class="material-advice">{{ item.advice }}</div>
              </div>
            </label>
            <div v-if="!materials.length" class="muted small" style="padding: 20px">
              该届次暂未登记材料清单，请参考原始通知。
            </div>
          </div>
        </div>

        <div class="right-stack">
          <div class="panel tracks-panel">
            <div class="panel-head">
              <h3>赛道与要求</h3>
              <span class="sub">共 {{ tracks.length }} 个赛道</span>
            </div>
            <div class="track-list">
              <div v-for="track in tracks" :key="track.name" class="track-row">
                <div class="track-name">{{ track.name }}</div>
                <div class="track-req">
                  <span v-for="req in track.requirements" :key="req" class="tag-soft">{{ req }}</span>
                </div>
              </div>
              <div v-if="!tracks.length" class="muted small" style="padding: 16px 20px">该届次暂未登记赛道。</div>
            </div>
          </div>

          <div class="panel notes-panel">
            <div class="panel-head">
              <h3>关键提醒</h3>
            </div>
            <div class="notes-list">
              <div v-for="(note, index) in notes" :key="index" class="note-row">
                <span class="note-index">{{ index + 1 }}</span>
                <span>{{ note }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="panel result-panel">
        <ResultView
          :result="result"
          title="计划依据与执行轨迹"
          :show-answer="false"
          :show-tables="false"
          :show-charts="false"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.setup-panel {
  display: flex;
  gap: 28px;
  padding: 22px 24px;
  align-items: flex-end;
  background:
    radial-gradient(420px 200px at 8% 0%, rgba(15, 159, 147, 0.055), transparent 65%),
    var(--surface);
  flex-wrap: wrap;
}

.setup-copy {
  flex: 0 0 260px;
}

.setup-eyebrow {
  font-size: 9.5px;
  letter-spacing: 0.18em;
  color: var(--teal-dark);
  font-weight: 600;
}

.setup-copy h3 {
  font-family: var(--font-display);
  font-size: 18px;
  color: var(--ink);
  margin: 6px 0 5px;
}

.setup-copy p {
  font-size: 10.5px;
  color: var(--muted-2);
  line-height: 1.7;
}

.setup-form {
  flex: 1;
  display: flex;
  gap: 10px;
  align-items: flex-end;
  min-width: 0;
  flex-wrap: wrap;
}

.setup-field {
  width: 136px;
}

.setup-field.grow {
  flex: 1;
  min-width: 220px;
}

.setup-button {
  height: 32px;
  flex-shrink: 0;
}

.prep-intro-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-top: 18px;
}

.intro-card {
  padding: 20px;
}

.intro-icon {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: var(--teal-soft);
  color: var(--teal-dark);
  display: grid;
  place-items: center;
  font-size: 16px;
  margin-bottom: 12px;
}

.intro-card h4 {
  font-size: 13px;
  font-weight: 650;
  color: #304a55;
}

.intro-card p {
  font-size: 11px;
  color: var(--muted);
  line-height: 1.75;
  margin-top: 5px;
}

.prep-result {
  margin-top: 20px;
}

.plan-banner {
  display: flex;
  align-items: center;
  gap: 26px;
  padding: 24px 28px;
  border-radius: 14px;
  background:
    radial-gradient(420px 200px at 100% 0%, rgba(37, 205, 190, 0.2), transparent 70%),
    linear-gradient(126deg, #0c2a3b, #091f2d);
  color: #e9f4f4;
  flex-wrap: wrap;
  position: relative;
  overflow: hidden;
}

.plan-banner.expired {
  background:
    radial-gradient(420px 200px at 100% 0%, rgba(196, 161, 91, 0.18), transparent 70%),
    linear-gradient(126deg, #2d2a22, #1f231f);
}

.plan-banner-main {
  min-width: 260px;
  flex: 1;
}

.plan-badges {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.plan-banner .tag-soft {
  background: rgba(255, 255, 255, 0.07);
  border-color: rgba(255, 255, 255, 0.12);
  color: rgba(226, 243, 241, 0.75);
}

.plan-banner .tag-soft.teal {
  background: rgba(31, 184, 170, 0.15);
  border-color: rgba(60, 203, 189, 0.25);
  color: #75e3d6;
}

.plan-banner .tag-soft.gold {
  background: rgba(196, 161, 91, 0.13);
  border-color: rgba(214, 184, 120, 0.22);
  color: #e0c98f;
}

.plan-banner h2 {
  font-family: var(--font-display);
  font-size: 24px;
  margin: 11px 0 6px;
  color: #f4fbfb;
}

.plan-banner-main p {
  font-size: 11.5px;
  color: rgba(214, 232, 234, 0.58);
  line-height: 1.75;
  max-width: 640px;
}

.plan-metrics {
  display: flex;
  gap: 24px;
  padding: 0 26px;
  border-left: 1px solid rgba(255, 255, 255, 0.09);
  border-right: 1px solid rgba(255, 255, 255, 0.09);
}

.plan-metric {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.plan-metric strong {
  font-family: var(--font-display);
  font-size: 25px;
  line-height: 1.1;
  color: #f1fbfa;
}

.plan-metric strong.warn {
  color: #e2c98f;
  font-size: 19px;
}

.plan-metric strong small {
  font-size: 13px;
  color: rgba(220, 238, 240, 0.5);
}

.plan-metric span {
  font-size: 9.5px;
  color: rgba(214, 232, 234, 0.42);
  letter-spacing: 0.03em;
}

.plan-banner-actions {
  display: flex;
  gap: 7px;
  flex-wrap: wrap;
}

.plan-banner-actions :deep(.el-button) {
  background: rgba(255, 255, 255, 0.07);
  border-color: rgba(255, 255, 255, 0.16);
  color: #e0f0ef;
}

.plan-banner-actions :deep(.el-button--primary) {
  background: rgba(31, 184, 170, 0.22);
  border-color: rgba(60, 203, 189, 0.3);
  color: #88f0e3;
}

.notice-panel {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 14px 18px;
  margin-top: 12px;
  font-size: 12px;
  color: #7c6337;
  background: #fdfaf3;
  border-color: #f0e4c9;
  line-height: 1.7;
}

.timeline-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 20px;
}

.stage-card {
  position: relative;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 11px;
  padding: 14px 14px 12px;
  box-shadow: var(--shadow-sm);
  min-height: 210px;
}

.stage-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin-bottom: 8px;
}

.stage-index {
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 700;
  color: #b9d7d3;
  line-height: 1;
}

.stage-range {
  font-size: 8.5px;
  color: var(--muted-2);
  font-family: monospace;
  white-space: nowrap;
}

.stage-card h4 {
  font-size: 12.5px;
  font-weight: 650;
  color: #2c4752;
  line-height: 1.45;
  min-height: 36px;
}

.stage-card ul {
  margin: 7px 0 0;
  padding-left: 15px;
}

.stage-card li {
  font-size: 10px;
  color: #667a84;
  line-height: 1.7;
  margin-bottom: 4px;
}

.stage-card li::marker {
  color: #9fcac5;
}

.stage-connector {
  position: absolute;
  right: -11px;
  top: 50%;
  z-index: 2;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: #fff;
  border: 1px solid var(--line);
  color: #9fb6bb;
  font-size: 9px;
}

.prep-columns {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(300px, 0.9fr);
  gap: 16px;
  align-items: start;
}

.material-list {
  padding: 4px 0;
}

.material-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 20px;
  border-bottom: 1px solid #f0f3f4;
  cursor: pointer;
}

.material-row:last-child {
  border-bottom: 0;
}

.material-row.done .material-name {
  color: #9aa9b1;
  text-decoration: line-through;
}

.material-row :deep(.el-checkbox) {
  margin-top: 1px;
  height: auto;
}

.material-main {
  min-width: 0;
  flex: 1;
}

.material-name {
  font-size: 12px;
  font-weight: 600;
  color: #35505a;
}

.material-advice {
  font-size: 10.5px;
  color: var(--muted-2);
  margin-top: 2px;
  line-height: 1.6;
}

.right-stack {
  display: grid;
  gap: 16px;
}

.track-list {
  padding: 3px 0;
}

.track-row {
  padding: 10px 20px;
  border-bottom: 1px solid #f1f4f5;
}

.track-row:last-child {
  border-bottom: 0;
}

.track-name {
  font-size: 11.5px;
  font-weight: 600;
  color: #3a535e;
}

.track-req {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
  margin-top: 5px;
}

.notes-list {
  padding: 6px 20px 12px;
}

.note-row {
  display: flex;
  gap: 9px;
  font-size: 10.5px;
  color: #5f727c;
  line-height: 1.75;
  padding: 6px 0;
  border-bottom: 1px dashed #eef2f3;
}

.note-row:last-child {
  border-bottom: 0;
}

.note-index {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  border-radius: 4px;
  background: #f0f5f5;
  color: #7e959c;
  display: grid;
  place-items: center;
  font-size: 8.5px;
  margin-top: 3px;
}

.result-panel {
  margin-top: 16px;
  padding: 22px 24px;
}

@media (max-width: 1280px) {
  .timeline-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .stage-connector {
    display: none;
  }
}

@media (max-width: 1024px) {
  .setup-copy {
    flex-basis: 100%;
  }
  .prep-columns {
    grid-template-columns: 1fr;
  }
  .plan-metrics {
    border: 0;
    padding: 0;
    gap: 20px;
  }
}

@media (max-width: 720px) {
  .timeline-grid {
    grid-template-columns: 1fr;
  }
  .stage-card {
    min-height: 0;
  }
  .stage-card h4 {
    min-height: 0;
  }
  .prep-intro-grid {
    grid-template-columns: 1fr;
  }
  .plan-banner {
    padding: 20px;
    gap: 16px;
  }
  .plan-banner h2 {
    font-size: 20px;
  }
  .plan-banner-actions {
    width: 100%;
  }
  .setup-field {
    width: 100%;
  }
}
</style>
