<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { can, ensureOptions, store } from '../store'
import { fmtDate, fmtMoney, levelType, tagType } from '../utils'
import PageHeader from '../components/PageHeader.vue'
import EmptyState from '../components/EmptyState.vue'

const router = useRouter()

const keyword = ref('')
const levelFilter = ref('')
const activeOnly = ref(true)
const loading = ref(false)
const items = ref([])

const detailOpen = ref(false)
const detailLoading = ref(false)
const detail = ref(null)
const selectedYear = ref(null)

const compDialog = ref(false)
const compSaving = ref(false)
const editingId = ref(null)
const compForm = reactive(blankCompetition())

const editionDialog = ref(false)
const editionSaving = ref(false)
const editionComp = ref(null)
const editionForm = reactive(blankEdition())

const levelOptions = computed(() => store.options?.levels || ['国家级', '省级', '校级'])
const currentEdition = computed(() => detail.value || null)
const detailCompName = computed(() => detail.value?.name || '')
const canWrite = computed(() => can('competitions.write'))
const canUseFinance = computed(() => can('finance.use'))

const stats = computed(() => {
  const list = items.value
  return {
    total: list.length,
    national: list.filter((c) => c.level === '国家级').length,
    provincial: list.filter((c) => c.level === '省级').length,
    running: list.filter((c) => ['进行中', '筹备中'].includes(c.status)).length
  }
})

function blankCompetition() {
  return {
    code: '',
    name: '',
    short_name: '',
    organizer: '',
    co_organizer: '',
    level: '国家级',
    category: '',
    competition_type: '学科竞赛',
    discipline_tags: [],
    official_url: '',
    intro: '',
    target_audience: '',
    is_active: true
  }
}

function blankMilestone() {
  return { name: '', stage: '', start_date: '', end_date: '', note: '' }
}

function blankTrack() {
  return {
    name: '',
    code: '',
    description: '',
    requirementsText: '',
    discipline_tags: [],
    team_size_min: null,
    team_size_max: null,
    fee: null
  }
}

function blankAward() {
  return { award_level: '一等奖', category: '', ratio: '', quantity: '', prize: '', note: '' }
}

function blankEdition() {
  return {
    year: new Date().getFullYear(),
    edition_name: '',
    notice_title: '',
    notice_no: '',
    issued_by: '',
    issued_date: '',
    register_start: '',
    register_end: '',
    competition_period: '',
    eligibility: '',
    team_size_min: 1,
    team_size_max: 3,
    mentor_limit: 2,
    registration_fee: 0,
    fee_note: '',
    required_materials: [],
    material_note: '',
    status: '筹备中',
    source_ref: '',
    milestones: [blankMilestone()],
    tracks: [blankTrack()],
    award_settings: [blankAward()]
  }
}

async function loadCompetitions() {
  loading.value = true
  try {
    const data = await api.competitions({
      keyword: keyword.value,
      level: levelFilter.value,
      active_only: activeOnly.value
    })
    items.value = data.items || []
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

async function openDetail(item, year) {
  detailOpen.value = true
  detailLoading.value = true
  try {
    const data = await api.competition(item.id, year || undefined)
    detail.value = data
    selectedYear.value = data.year || data.editions?.[0]?.year || null
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    detailLoading.value = false
  }
}

async function changeYear(year) {
  if (!detail.value) return
  try {
    detailLoading.value = true
    detail.value = await api.competition(detail.value.id, year)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    detailLoading.value = false
  }
}

function openCreate() {
  Object.assign(compForm, blankCompetition())
  editingId.value = null
  compDialog.value = true
}

function openEdit() {
  if (!detail.value) return
  const source = detail.value
  Object.assign(compForm, {
    code: source.code,
    name: source.name,
    short_name: source.short_name || '',
    organizer: source.organizer || '',
    co_organizer: source.co_organizer || '',
    level: source.level || '国家级',
    category: source.category || '',
    competition_type: source.competition_type || '学科竞赛',
    discipline_tags: [...(source.discipline_tags || [])],
    official_url: source.official_url || '',
    intro: source.intro || '',
    target_audience: source.target_audience || '',
    is_active: source.is_active !== false
  })
  editingId.value = source.id
  compDialog.value = true
}

async function saveCompetition() {
  if (!compForm.code || compForm.code.length < 2) {
    ElMessage.warning('赛事编码至少 2 个字符')
    return
  }
  if (!compForm.name || compForm.name.length < 2) {
    ElMessage.warning('赛事名称至少 2 个字符')
    return
  }
  compSaving.value = true
  try {
    if (editingId.value) {
      await api.updateCompetition(editingId.value, { ...compForm })
      ElMessage.success('赛事信息已更新')
      if (detail.value?.id === editingId.value) await openDetail(detail.value)
    } else {
      const data = await api.createCompetition({ ...compForm })
      ElMessage.success(`赛事「${data.name}」已创建，可继续收录年度信息`)
      await loadCompetitions()
      await ensureOptions(true)
      compDialog.value = false
      openEdition(data.id, data.name)
      return
    }
    compDialog.value = false
    await loadCompetitions()
    await ensureOptions(true)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    compSaving.value = false
  }
}

function openEdition(competitionId, competitionName) {
  const target = items.value.find((c) => c.id === competitionId)
  editionComp.value = { id: competitionId, name: competitionName || target?.name }
  Object.assign(editionForm, blankEdition())
  if (detail.value?.latest_year || target?.latest_year) {
    editionForm.year = (detail.value?.latest_year || target?.latest_year) + 1
  }
  editionForm.registration_fee = target?.registration_fee || 0
  editionDialog.value = true
}

function fillEditionFromDetail() {
  if (!detail.value) return
  const d = detail.value
  editionComp.value = { id: d.id, name: d.name }
  Object.assign(editionForm, blankEdition(), {
    year: d.year || new Date().getFullYear(),
    edition_name: d.edition_name || '',
    notice_title: d.notice_title || '',
    notice_no: d.notice_no || '',
    issued_by: d.issued_by || '',
    issued_date: d.issued_date || '',
    register_start: d.register_start || '',
    register_end: d.register_end || '',
    competition_period: d.competition_period || '',
    eligibility: d.eligibility || '',
    team_size_min: d.team_size_min || 1,
    team_size_max: d.team_size_max || 1,
    mentor_limit: d.mentor_limit || 1,
    registration_fee: d.registration_fee || 0,
    fee_note: d.fee_note || '',
    required_materials: [...(d.required_materials || [])],
    material_note: d.material_note || '',
    status: d.status || '筹备中',
    source_ref: d.source_ref || '',
    milestones: (d.milestones || []).map((m) => ({ ...m })),
    tracks: (d.tracks || []).map((t) => ({
      name: t.name,
      code: t.code || '',
      description: t.description || '',
      requirementsText: (t.requirements || []).join('、'),
      discipline_tags: [...(t.discipline_tags || [])],
      team_size_min: null,
      team_size_max: null,
      fee: t.fee
    })),
    award_settings: (d.award_settings || []).map((a) => ({ ...a }))
  })
  if (!editionForm.milestones.length) editionForm.milestones = [blankMilestone()]
  if (!editionForm.tracks.length) editionForm.tracks = [blankTrack()]
  if (!editionForm.award_settings.length) editionForm.award_settings = [blankAward()]
  editionDialog.value = true
}

async function saveEdition() {
  if (!editionComp.value?.id) return
  if (!editionForm.year) {
    ElMessage.warning('请填写年度')
    return
  }
  editionSaving.value = true
  try {
    const payload = {
      ...editionForm,
      milestones: editionForm.milestones.filter((m) => m.name),
      tracks: editionForm.tracks.filter((t) => t.name).map((t) => ({
        name: t.name,
        code: t.code || '',
        description: t.description || '',
        requirements: String(t.requirementsText || '')
          .split(/[、,，]/)
          .map((x) => x.trim())
          .filter(Boolean),
        team_size_min: t.team_size_min || null,
        team_size_max: t.team_size_max || null,
        fee: t.fee === null || t.fee === '' ? null : Number(t.fee),
        discipline_tags: t.discipline_tags || []
      })),
      award_settings: editionForm.award_settings.filter((a) => a.award_level)
    }
    const data = await api.upsertEdition(editionComp.value.id, payload)
    ElMessage.success(`已保存 ${data.year} 年赛事信息`)
    editionDialog.value = false
    await loadCompetitions()
    if (detailOpen.value && detail.value?.id === editionComp.value.id) {
      await openDetail(detail.value, data.year)
    }
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    editionSaving.value = false
  }
}

function addRow(collection, factory) {
  editionForm[collection].push(factory())
}

function removeRow(collection, index) {
  editionForm[collection].splice(index, 1)
}

function goPrep() {
  router.push({ name: 'prep', query: { competition: detailCompName.value } })
}

function goBudget() {
  router.push({ name: 'finance', query: { competition: detailCompName.value, tab: 'budget' } })
}

onMounted(async () => {
  await ensureOptions()
  await loadCompetitions()
})
</script>

<template>
  <div>
    <PageHeader
      eyebrow="Competitions"
      title="赛事台账"
      description="统一维护赛事基础信息、年度通知、赛道、节点与奖项设置。新增赛事或年度数据后，问答、推荐与备赛计划自动同步，无需改代码。"
    >
      <template #actions>
        <el-button v-if="canWrite" type="primary" @click="openCreate"><el-icon><Plus /></el-icon> 新增赛事</el-button>
      </template>
    </PageHeader>

    <div class="catalog-strip">
      <div class="catalog-stat"><span>收录赛事</span><strong>{{ stats.total }}</strong></div>
      <div class="catalog-stat"><span>国家级</span><strong>{{ stats.national }}</strong></div>
      <div class="catalog-stat"><span>省级</span><strong>{{ stats.provincial }}</strong></div>
      <div class="catalog-stat"><span>进行 / 筹备</span><strong>{{ stats.running }}</strong></div>
      <div class="catalog-filter">
        <el-input
          v-model="keyword"
          placeholder="搜索赛事名称、主办方、简介"
          clearable
          style="width: 240px"
          @keyup.enter="loadCompetitions"
          @clear="loadCompetitions"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="levelFilter" clearable placeholder="全部级别" style="width: 120px" @change="loadCompetitions">
          <el-option v-for="level in levelOptions" :key="level" :label="level" :value="level" />
        </el-select>
        <el-switch v-model="activeOnly" active-text="仅启用" @change="loadCompetitions" />
        <el-button :loading="loading" @click="loadCompetitions"><el-icon><Search /></el-icon> 查询</el-button>
      </div>
    </div>

    <div v-loading="loading" class="competition-grid">
      <div v-for="item in items" :key="item.id" class="competition-card" @click="openDetail(item)">
        <div class="card-top">
          <el-tag size="small" :type="levelType[item.level] || 'info'">{{ item.level }}</el-tag>
          <span v-if="item.category" class="tag-soft">{{ item.category }}</span>
          <span v-if="item.status" class="tag-soft gold">{{ item.status }}</span>
          <span class="card-code mono">{{ item.code }}</span>
        </div>
        <h3>{{ item.name }}</h3>
        <p class="organizer">{{ item.organizer || '主办单位待补充' }}</p>
        <p class="intro">{{ item.intro || '暂无赛事简介' }}</p>
        <div class="card-meta">
          <span><el-icon><Calendar /></el-icon> {{ item.latest_year ? `${item.latest_year} 年` : '未收录年度' }}</span>
          <span><el-icon><User /></el-icon> {{ item.team_size || '—' }}</span>
          <span><el-icon><Wallet /></el-icon> {{ item.registration_fee != null ? `¥${fmtMoney(item.registration_fee)}` : '—' }}</span>
        </div>
        <div class="card-foot">
          <span class="date">{{ item.register_start ? `${fmtDate(item.register_start)} ~ ${fmtDate(item.register_end)}` : '报名窗口待发布' }}</span>
          <div class="card-actions" @click.stop>
            <el-button v-if="canWrite" size="small" text type="primary" @click="openEdition(item.id, item.name)">收录年度</el-button>
            <el-button size="small" text @click="openDetail(item)">详情 →</el-button>
          </div>
        </div>
      </div>
      <EmptyState v-if="!loading && !items.length" title="没有匹配的赛事" description="调整筛选条件，或新增一项赛事并录入年度通知信息。" style="grid-column: 1 / -1" />
    </div>

    <el-drawer v-model="detailOpen" size="760px" :with-header="false">
      <div v-loading="detailLoading" class="detail-wrap">
        <template v-if="detail">
          <div class="detail-hero">
            <div class="detail-tags">
              <el-tag size="small" :type="levelType[detail.level] || 'info'">{{ detail.level }}</el-tag>
              <span v-if="detail.category" class="tag-soft">{{ detail.category }}</span>
              <span v-if="detail.competition_type" class="tag-soft">{{ detail.competition_type }}</span>
            </div>
            <h2>{{ detail.name }}</h2>
            <p class="detail-organizer">{{ detail.organizer }}<span v-if="detail.co_organizer"> · {{ detail.co_organizer }}</span></p>
            <div class="detail-actions">
              <el-select v-if="detail.editions?.length" :model-value="selectedYear" size="small" style="width: 120px" @change="changeYear">
                <el-option v-for="edition in detail.editions" :key="edition.id" :label="`${edition.year} 年`" :value="edition.year" />
              </el-select>
              <el-button v-if="canWrite" size="small" @click="fillEditionFromDetail"><el-icon><Edit /></el-icon> 编辑年度</el-button>
              <el-button v-if="canWrite" size="small" @click="openEdition(detail.id, detail.name)"><el-icon><Plus /></el-icon> 新增年度</el-button>
              <el-button v-if="canWrite" size="small" @click="openEdit"><el-icon><Setting /></el-icon> 编辑赛事</el-button>
            </div>
          </div>

          <div class="detail-grid">
            <div class="detail-main">
              <section class="detail-section">
                <h4>赛事简介</h4>
                <p>{{ detail.intro || '暂无简介' }}</p>
                <p v-if="detail.target_audience" class="muted">面向对象：{{ detail.target_audience }}</p>
                <a v-if="detail.official_url" :href="detail.official_url" target="_blank" rel="noopener" class="official-link">
                  <el-icon><Link /></el-icon> {{ detail.official_url }}
                </a>
                <div v-if="detail.discipline_tags?.length" class="tag-row">
                  <span v-for="tag in detail.discipline_tags" :key="tag" class="tag-soft teal">{{ tag }}</span>
                </div>
              </section>

              <section v-if="detail.year" class="detail-section">
                <div class="section-head">
                  <h4>{{ detail.year }} 年赛事安排</h4>
                  <span class="tag-soft">{{ detail.edition_name || '年度信息' }}</span>
                </div>
                <div class="info-grid">
                  <div><span>通知名称</span><strong>{{ detail.notice_title || '—' }}</strong></div>
                  <div><span>通知编号</span><strong>{{ detail.notice_no || '—' }}</strong></div>
                  <div><span>发文单位</span><strong>{{ detail.issued_by || '—' }}</strong></div>
                  <div><span>发文日期</span><strong>{{ fmtDate(detail.issued_date) }}</strong></div>
                  <div><span>报名时间</span><strong>{{ fmtDate(detail.register_start) }} ~ {{ fmtDate(detail.register_end) }}</strong></div>
                  <div><span>比赛时间</span><strong>{{ detail.competition_period || '—' }}</strong></div>
                  <div><span>队伍规模</span><strong>{{ detail.team_size_min }}-{{ detail.team_size_max }} 人 / 队</strong></div>
                  <div><span>指导教师上限</span><strong>{{ detail.mentor_limit }} 人</strong></div>
                  <div><span>报名费</span><strong>{{ fmtMoney(detail.registration_fee) }} 元</strong></div>
                  <div><span>年度状态</span><strong>{{ detail.status || '—' }}</strong></div>
                </div>
                <p v-if="detail.eligibility" class="detail-note"><strong>参赛资格：</strong>{{ detail.eligibility }}</p>
                <p v-if="detail.fee_note" class="detail-note"><strong>费用说明：</strong>{{ detail.fee_note }}</p>
                <p v-if="detail.material_note" class="detail-note"><strong>材料说明：</strong>{{ detail.material_note }}</p>
                <div v-if="detail.required_materials?.length" class="tag-row" style="margin-top: 8px">
                  <span v-for="mat in detail.required_materials" :key="mat" class="tag-soft">{{ mat }}</span>
                </div>
                <p v-if="detail.source_ref" class="source-note"><el-icon><Document /></el-icon> {{ detail.source_ref }}</p>
              </section>

              <section v-if="detail.milestones?.length" class="detail-section">
                <h4>关键节点</h4>
                <el-timeline>
                  <el-timeline-item
                    v-for="m in detail.milestones"
                    :key="`${m.name}-${m.start_date}`"
                    :timestamp="`${fmtDate(m.start_date)}${m.end_date ? ` ~ ${fmtDate(m.end_date)}` : ''}`"
                    placement="top"
                  >
                    <div class="milestone-title">{{ m.name }} <span v-if="m.stage" class="tag-soft">{{ m.stage }}</span></div>
                    <div v-if="m.note" class="muted small">{{ m.note }}</div>
                  </el-timeline-item>
                </el-timeline>
              </section>

              <section v-if="detail.tracks?.length" class="detail-section">
                <h4>赛道与赛项</h4>
                <div class="track-list">
                  <div v-for="track in detail.tracks" :key="track.name" class="track-row">
                    <div>
                      <strong>{{ track.name }}</strong>
                      <span v-if="track.team_size" class="muted small"> · {{ track.team_size }}</span>
                      <p>{{ track.description }}</p>
                      <div class="tag-row">
                        <span v-for="req in track.requirements || []" :key="req" class="tag-soft">{{ req }}</span>
                      </div>
                    </div>
                    <span v-if="track.fee != null" class="mono track-fee">¥{{ fmtMoney(track.fee) }}</span>
                  </div>
                </div>
              </section>

              <section v-if="detail.award_settings?.length" class="detail-section">
                <h4>奖项设置</h4>
                <el-table :data="detail.award_settings" size="small" border>
                  <el-table-column prop="award_level" label="奖项等级" width="110" />
                  <el-table-column prop="category" label="类别" width="120" />
                  <el-table-column prop="ratio" label="获奖比例" width="110" />
                  <el-table-column prop="quantity" label="数量" width="90" />
                  <el-table-column prop="prize" label="奖励" min-width="140" />
                  <el-table-column prop="note" label="说明" min-width="160" show-overflow-tooltip />
                </el-table>
              </section>
            </div>

            <aside class="detail-aside">
              <div class="aside-card">
                <div class="aside-label">历年台账（近 5 年）</div>
                <div class="aside-ledger">
                  <div><strong>{{ detail.ledger?.registrations ?? 0 }}</strong><span>参赛队次</span></div>
                  <div><strong>{{ detail.ledger?.awards ?? 0 }}</strong><span>获奖项数</span></div>
                </div>
                <div v-for="row in detail.ledger?.by_year || []" :key="row.year" class="ledger-year">
                  <span>{{ row.year }} 年</span>
                  <span class="muted">
                    <template v-for="(count, level) in row" :key="level">
                      <template v-if="level !== 'year'">{{ level }} {{ count }} </template>
                    </template>
                  </span>
                </div>
              </div>
              <div class="aside-card">
                <div class="aside-label">快捷操作</div>
                <el-button size="small" style="width: 100%" @click="goPrep">生成备赛计划</el-button>
                <el-button v-if="canUseFinance" size="small" style="width: 100%; margin: 8px 0 0" @click="goBudget">测算参赛预算</el-button>
                <el-button size="small" style="width: 100%; margin: 8px 0 0" @click="router.push({ name: 'qa', query: { q: detail.name } })">查询赛事政策</el-button>
              </div>
            </aside>
          </div>
        </template>
      </div>
    </el-drawer>

    <el-dialog v-model="compDialog" :title="editingId ? '编辑赛事' : '新增赛事'" width="640px">
      <div class="form-grid">
        <div>
          <label class="field-label">赛事编码<span class="req">*</span></label>
          <el-input v-model="compForm.code" placeholder="如 LANQIAO" :disabled="Boolean(editingId)" />
        </div>
        <div>
          <label class="field-label">赛事简称</label>
          <el-input v-model="compForm.short_name" placeholder="如 蓝桥杯" />
        </div>
        <div class="span-2">
          <label class="field-label">赛事名称<span class="req">*</span></label>
          <el-input v-model="compForm.name" placeholder="赛事全称" />
        </div>
        <div>
          <label class="field-label">级别</label>
          <el-select v-model="compForm.level" style="width: 100%">
            <el-option v-for="level in levelOptions" :key="level" :label="level" :value="level" />
          </el-select>
        </div>
        <div>
          <label class="field-label">类别</label>
          <el-input v-model="compForm.category" placeholder="如 程序设计类" />
        </div>
        <div>
          <label class="field-label">竞赛类型</label>
          <el-input v-model="compForm.competition_type" placeholder="如 学科竞赛" />
        </div>
        <div>
          <label class="field-label">主办单位</label>
          <el-input v-model="compForm.organizer" />
        </div>
        <div class="span-2">
          <label class="field-label">学科标签</label>
          <el-select v-model="compForm.discipline_tags" multiple filterable allow-create default-first-option style="width: 100%" placeholder="输入后回车添加">
            <el-option v-for="tag in compForm.discipline_tags" :key="tag" :label="tag" :value="tag" />
          </el-select>
        </div>
        <div class="span-2">
          <label class="field-label">官网</label>
          <el-input v-model="compForm.official_url" placeholder="https://" />
        </div>
        <div class="span-2">
          <label class="field-label">赛事简介</label>
          <el-input v-model="compForm.intro" type="textarea" :rows="3" />
        </div>
        <div class="span-2">
          <label class="field-label">面向对象</label>
          <el-input v-model="compForm.target_audience" placeholder="如 本科生、研究生" />
        </div>
      </div>
      <template #footer>
        <el-button @click="compDialog = false">取消</el-button>
        <el-button type="primary" :loading="compSaving" @click="saveCompetition">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editionDialog" :title="`${editionComp?.name || ''} · 年度信息`" width="860px" top="6vh">
      <div class="edition-scroll">
        <div class="form-grid">
          <div>
            <label class="field-label">年度<span class="req">*</span></label>
            <el-input-number v-model="editionForm.year" :min="2000" :max="2100" style="width: 100%" />
          </div>
          <div>
            <label class="field-label">届次名称</label>
            <el-input v-model="editionForm.edition_name" placeholder="如 第十七届" />
          </div>
          <div>
            <label class="field-label">年度状态</label>
            <el-select v-model="editionForm.status" style="width: 100%">
              <el-option label="筹备中" value="筹备中" />
              <el-option label="进行中" value="进行中" />
              <el-option label="已完赛" value="已完赛" />
              <el-option label="往届" value="往届" />
            </el-select>
          </div>
          <div>
            <label class="field-label">报名费</label>
            <el-input-number v-model="editionForm.registration_fee" :min="0" :precision="2" :controls="false" style="width: 100%" />
          </div>
          <div class="span-2">
            <label class="field-label">通知标题</label>
            <el-input v-model="editionForm.notice_title" />
          </div>
          <div>
            <label class="field-label">通知编号</label>
            <el-input v-model="editionForm.notice_no" />
          </div>
          <div>
            <label class="field-label">发文单位</label>
            <el-input v-model="editionForm.issued_by" />
          </div>
          <div>
            <label class="field-label">发文日期</label>
            <el-date-picker v-model="editionForm.issued_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
          </div>
          <div>
            <label class="field-label">报名开始</label>
            <el-date-picker v-model="editionForm.register_start" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
          </div>
          <div>
            <label class="field-label">报名截止</label>
            <el-date-picker v-model="editionForm.register_end" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
          </div>
          <div class="span-2">
            <label class="field-label">比赛时间</label>
            <el-input v-model="editionForm.competition_period" placeholder="如 2027 年 3 月—6 月" />
          </div>
          <div>
            <label class="field-label">队伍最少人数</label>
            <el-input-number v-model="editionForm.team_size_min" :min="1" style="width: 100%" />
          </div>
          <div>
            <label class="field-label">队伍最多人数</label>
            <el-input-number v-model="editionForm.team_size_max" :min="1" style="width: 100%" />
          </div>
          <div>
            <label class="field-label">指导教师上限</label>
            <el-input-number v-model="editionForm.mentor_limit" :min="0" style="width: 100%" />
          </div>
          <div>
            <label class="field-label">费用说明</label>
            <el-input v-model="editionForm.fee_note" />
          </div>
          <div class="span-2">
            <label class="field-label">参赛资格</label>
            <el-input v-model="editionForm.eligibility" type="textarea" :rows="2" />
          </div>
          <div class="span-2">
            <label class="field-label">必交材料</label>
            <el-select v-model="editionForm.required_materials" multiple filterable allow-create default-first-option style="width: 100%" placeholder="输入材料名称后回车">
              <el-option v-for="mat in editionForm.required_materials" :key="mat" :label="mat" :value="mat" />
            </el-select>
          </div>
          <div class="span-2">
            <label class="field-label">材料说明</label>
            <el-input v-model="editionForm.material_note" type="textarea" :rows="2" />
          </div>
          <div class="span-2">
            <label class="field-label">信息来源</label>
            <el-input v-model="editionForm.source_ref" placeholder="通知链接或文号，便于引用溯源" />
          </div>
        </div>

        <div class="sub-editor">
          <div class="sub-head">
            <h4>关键节点</h4>
            <el-button size="small" text type="primary" @click="addRow('milestones', blankMilestone)"><el-icon><Plus /></el-icon> 添加节点</el-button>
          </div>
          <div v-for="(m, index) in editionForm.milestones" :key="index" class="sub-row">
            <el-input v-model="m.name" placeholder="节点名称" style="width: 150px" />
            <el-input v-model="m.stage" placeholder="阶段" style="width: 100px" />
            <el-date-picker v-model="m.start_date" type="date" value-format="YYYY-MM-DD" placeholder="开始" style="width: 130px" />
            <el-date-picker v-model="m.end_date" type="date" value-format="YYYY-MM-DD" placeholder="结束" style="width: 130px" />
            <el-input v-model="m.note" placeholder="备注" style="flex: 1" />
            <el-button text type="danger" @click="removeRow('milestones', index)"><el-icon><Delete /></el-icon></el-button>
          </div>
        </div>

        <div class="sub-editor">
          <div class="sub-head">
            <h4>赛道 / 赛项</h4>
            <el-button size="small" text type="primary" @click="addRow('tracks', blankTrack)"><el-icon><Plus /></el-icon> 添加赛道</el-button>
          </div>
          <div v-for="(t, index) in editionForm.tracks" :key="index" class="track-editor">
            <div class="sub-row">
              <el-input v-model="t.name" placeholder="赛道名称" style="flex: 1" />
              <el-input-number v-model="t.fee" :min="0" :precision="2" :controls="false" placeholder="费用" style="width: 100px" />
              <el-button text type="danger" @click="removeRow('tracks', index)"><el-icon><Delete /></el-icon></el-button>
            </div>
            <div class="sub-row">
              <el-input v-model="t.description" placeholder="赛道说明" style="flex: 1" />
              <el-input v-model="t.requirementsText" placeholder="要求（用、分隔）" style="flex: 1" />
            </div>
          </div>
        </div>

        <div class="sub-editor">
          <div class="sub-head">
            <h4>奖项设置</h4>
            <el-button size="small" text type="primary" @click="addRow('award_settings', blankAward)"><el-icon><Plus /></el-icon> 添加奖项</el-button>
          </div>
          <div v-for="(a, index) in editionForm.award_settings" :key="index" class="sub-row">
            <el-input v-model="a.award_level" placeholder="等级" style="width: 110px" />
            <el-input v-model="a.category" placeholder="类别" style="width: 110px" />
            <el-input v-model="a.ratio" placeholder="比例" style="width: 90px" />
            <el-input v-model="a.quantity" placeholder="数量" style="width: 90px" />
            <el-input v-model="a.prize" placeholder="奖励" style="flex: 1" />
            <el-button text type="danger" @click="removeRow('award_settings', index)"><el-icon><Delete /></el-icon></el-button>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="editionDialog = false">取消</el-button>
        <el-button type="primary" :loading="editionSaving" @click="saveEdition">保存年度信息</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.catalog-strip {
  display: flex;
  align-items: center;
  gap: 26px;
  flex-wrap: wrap;
  padding: 14px 20px;
  margin-bottom: 16px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 12px;
}

.catalog-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.catalog-stat span {
  font-size: 10px;
  letter-spacing: 0.12em;
  color: var(--muted-2);
}

.catalog-stat strong {
  font-family: var(--font-serif);
  font-size: 22px;
  line-height: 1;
  color: var(--ink-800);
}

.catalog-filter {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
  flex-wrap: wrap;
}

.competition-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  min-height: 160px;
}

.competition-card {
  padding: 18px 20px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 12px;
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.competition-card:hover {
  transform: translateY(-2px);
  border-color: rgba(15, 159, 147, 0.4);
  box-shadow: 0 14px 32px rgba(10, 32, 45, 0.08);
}

.card-top {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.card-code {
  margin-left: auto;
  font-size: 10px;
  color: var(--muted-2);
}

.competition-card h3 {
  margin: 2px 0 0;
  font-family: var(--font-serif);
  font-size: 18px;
  line-height: 1.4;
  color: var(--ink-900);
}

.organizer {
  margin: 0;
  font-size: 11.5px;
  color: var(--muted);
}

.intro {
  margin: 2px 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-2);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 40px;
}

.card-meta {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 11px;
  color: var(--muted);
}

.card-meta span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.card-foot {
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px dashed var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.card-foot .date {
  font-size: 10.5px;
  color: var(--muted-2);
}

.card-actions {
  display: flex;
  align-items: center;
}

.detail-wrap {
  padding: 26px 28px 40px;
}

.detail-hero {
  padding-bottom: 18px;
  border-bottom: 1px solid var(--line);
}

.detail-tags {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}

.detail-hero h2 {
  font-family: var(--font-serif);
  font-size: 26px;
  margin: 10px 0 4px;
  color: var(--ink-900);
}

.detail-organizer {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
}

.detail-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 14px;
}

.detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 230px;
  gap: 22px;
  margin-top: 20px;
  align-items: start;
}

.detail-main {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.detail-section {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 16px 18px;
}

.detail-section h4 {
  margin: 0 0 10px;
  font-family: var(--font-serif);
  font-size: 15px;
  color: var(--ink-800);
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.section-head h4 {
  margin: 0;
}

.detail-section p {
  margin: 0 0 8px;
  font-size: 12.5px;
  line-height: 1.8;
  color: var(--text-2);
}

.official-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  color: var(--teal-700);
  word-break: break-all;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 18px;
  margin-bottom: 10px;
}

.info-grid div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 7px 0;
  border-bottom: 1px dashed var(--line);
}

.info-grid span {
  font-size: 10px;
  letter-spacing: 0.08em;
  color: var(--muted-2);
}

.info-grid strong {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-1);
}

.detail-note {
  padding: 8px 10px;
  background: #fafcfb;
  border-radius: 6px;
  font-size: 11.5px !important;
  line-height: 1.75 !important;
}

.source-note {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 10px !important;
  font-size: 10.5px !important;
  color: var(--muted-2) !important;
}

.milestone-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--text-1);
}

.track-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.track-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fcfdfd;
}

.track-row strong {
  font-size: 12px;
  color: var(--ink-800);
}

.track-row p {
  margin: 4px 0 0;
  font-size: 11.5px;
}

.track-fee {
  font-size: 12px;
  color: var(--gold-700);
  flex-shrink: 0;
}

.detail-aside {
  position: sticky;
  top: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.aside-card {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 14px;
}

.aside-label {
  font-size: 10px;
  letter-spacing: 0.14em;
  color: var(--muted-2);
  margin-bottom: 10px;
}

.aside-ledger {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-bottom: 8px;
}

.aside-ledger div {
  padding: 8px;
  background: #f7faf9;
  border-radius: 7px;
  display: flex;
  flex-direction: column;
}

.aside-ledger strong {
  font-family: var(--font-serif);
  font-size: 22px;
  color: var(--teal-700);
}

.aside-ledger span {
  font-size: 10px;
  color: var(--muted-2);
}

.ledger-year {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 0;
  border-top: 1px dashed var(--line);
  font-size: 10.5px;
}

.sub-editor {
  margin-top: 18px;
  padding-top: 12px;
  border-top: 1px dashed var(--line);
}

.sub-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.sub-head h4 {
  margin: 0;
  font-size: 12.5px;
  color: var(--ink-800);
}

.sub-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.track-editor {
  padding: 8px;
  border: 1px solid var(--line);
  border-radius: 8px;
  margin-bottom: 8px;
  background: #fcfdfd;
}

.edition-scroll {
  max-height: 62vh;
  overflow-y: auto;
  padding-right: 8px;
}

@media (max-width: 1200px) {
  .competition-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 860px) {
  .competition-grid {
    grid-template-columns: 1fr;
  }
  .detail-grid {
    grid-template-columns: 1fr;
  }
  .catalog-filter {
    width: 100%;
    margin-left: 0;
  }
}
</style>
