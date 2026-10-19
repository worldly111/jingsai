<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import { can, ensureOptions, store } from '../store'
import { fmtDateTime, fmtMoney, tagType } from '../utils'
import CheckList from './CheckList.vue'
import DataTable from './DataTable.vue'
import EmptyState from './EmptyState.vue'

const props = defineProps({
  presetCompetition: { type: String, default: '' }
})
const emit = defineEmits(['saved'])

const form = reactive({
  competition_name: '',
  competition_level: '国家级',
  year: null,
  team_name: '',
  destination: '',
  trip_days: 3,
  student_count: 5,
  teacher_count: 1,
  mentor_trip: true,
  registration_fee: null,
  registration_fee_unit: '元/人',
  transport_mode: '高铁/动车二等座',
  transport_unit_price: null,
  applicant: '',
  remark: '',
  custom_items: []
})

const planning = ref(false)
const saving = ref(false)
const plan = ref(null)
const feeHint = ref('')
const list = ref([])
const listLoading = ref(false)
const detail = ref(null)
const detailOpen = ref(false)
const detailLoading = ref(false)
const statusBusy = ref(0)

const yearOptions = computed(() => (store.options?.years || []).slice().sort((a, b) => b - a))
const approvedBudgets = computed(() => list.value.filter((b) => b.status === '已批准'))
const canApprove = computed(() => can('finance.approve'))

const itemTable = computed(() => ({
  title: '预算明细',
  columns: [
    { key: 'category', label: '类别', width: 90 },
    { key: 'item_name', label: '项目', width: 200 },
    { key: 'unit', label: '单位', width: 100 },
    { key: 'quantity', label: '数量', width: 70 },
    { key: 'unit_price', label: '单价（元）', width: 100 },
    { key: 'amount', label: '金额（元）', width: 110 },
    { key: 'calc_basis', label: '计算依据', width: 300 },
    { key: 'standard_code', label: '标准编号', width: 100 }
  ],
  rows: plan.value?.items || []
}))

const detailItems = computed(() => ({
  title: '预算明细',
  columns: itemTable.value.columns,
  rows: detail.value?.items || []
}))

function buildPayload() {
  const payload = {
    competition_name: form.competition_name,
    competition_level: form.competition_level,
    year: form.year || undefined,
    team_name: form.team_name,
    destination: form.destination,
    trip_days: Number(form.trip_days) || 0,
    student_count: Number(form.student_count) || 0,
    teacher_count: Number(form.teacher_count) || 0,
    mentor_trip: form.mentor_trip,
    transport_mode: form.transport_mode,
    registration_fee_unit: form.registration_fee_unit,
    remark: form.remark
  }
  if (form.registration_fee !== null && form.registration_fee !== '') {
    if (form.registration_fee_unit === '元/人') payload.registration_fee_per_person = Number(form.registration_fee)
    else payload.registration_fee_per_team = Number(form.registration_fee)
  }
  if (form.transport_unit_price !== null && form.transport_unit_price !== '') {
    payload.transport_unit_price = Number(form.transport_unit_price)
  }
  payload.items = form.custom_items
    .filter((i) => i.item_name && Number(i.unit_price || 0) > 0)
    .map((i) => ({
      category: i.category || '其他',
      item_name: i.item_name,
      quantity: Number(i.quantity) || 1,
      unit: i.unit || '项',
      unit_price: Number(i.unit_price) || 0
    }))
  return payload
}

async function onCompetitionChange(name) {
  const comp = store.options?.competitions?.find((c) => c.name === name)
  feeHint.value = ''
  if (!comp) return
  form.competition_level = comp.level || form.competition_level
  try {
    const data = await api.competition(comp.id)
    if (data?.year && !form.year) form.year = data.year
    if (data?.registration_fee) {
      feeHint.value = `赛事台账登记报名费 ${fmtMoney(data.registration_fee)} 元${data.fee_note ? `（${data.fee_note}）` : ''}，请确认计费口径。`
    }
  } catch {
    /* 台账详情不可用时保留手工录入 */
  }
}

async function runPlan() {
  if (!form.competition_name) {
    ElMessage.warning('请先选择赛事')
    return
  }
  planning.value = true
  plan.value = null
  try {
    plan.value = await api.planBudget(buildPayload())
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    planning.value = false
  }
}

async function save(status) {
  if (!form.competition_name) {
    ElMessage.warning('请先选择赛事')
    return
  }
  if (!form.applicant) {
    ElMessage.warning('请填写申请人姓名，便于单据流转')
    return
  }
  saving.value = true
  try {
    const data = await api.createBudget({
      payload: buildPayload(),
      applicant: { name: form.applicant },
      status
    })
    ElMessage.success(`已保存预算单 ${data.doc_no}（${data.status}）`)
    plan.value = {
      items: data.items,
      total: data.total_amount,
      checks: data.checks || plan.value?.checks || [],
      approval: plan.value?.approval,
      summary: plan.value?.summary,
      standards_used: plan.value?.standards_used || []
    }
    await loadList()
    emit('saved')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}

async function loadList() {
  listLoading.value = true
  try {
    const data = await api.budgets()
    list.value = data.items || []
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    listLoading.value = false
  }
}

async function openDetail(row) {
  detailOpen.value = true
  detailLoading.value = true
  try {
    detail.value = await api.budget(row.id)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    detailLoading.value = false
  }
}

async function changeStatus(row, status) {
  const messages = {
    待审批: `确认提交预算单 ${row.doc_no} 进入审批？`,
    已批准: `确认批准预算单 ${row.doc_no}，批准金额 ${fmtMoney(row.total_amount)} 元？`,
    已驳回: `确认驳回预算单 ${row.doc_no}？`
  }
  try {
    await ElMessageBox.confirm(messages[status], '预算状态流转', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      type: status === '已驳回' ? 'warning' : 'info'
    })
  } catch {
    return
  }
  statusBusy.value = row.id
  try {
    await api.budgetStatus(row.id, {
      status,
      approved_amount: status === '已批准' ? row.total_amount : null,
      reviewer: status === '已批准' ? '学院经费负责人' : '',
      note: status === '已驳回' ? '请补充预算明细与依据后重新提交' : ''
    })
    ElMessage.success('状态已更新')
    await loadList()
    emit('saved')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    statusBusy.value = 0
  }
}

async function download(row, format) {
  try {
    await api.budgetDoc(row.id, format)
  } catch (error) {
    ElMessage.error(error.message)
  }
}

function addItem() {
  form.custom_items.push({ category: '其他', item_name: '', quantity: 1, unit: '项', unit_price: 0 })
}

function removeItem(index) {
  form.custom_items.splice(index, 1)
}

watch(
  () => props.presetCompetition,
  (value) => {
    if (value && value !== form.competition_name) {
      form.competition_name = value
      onCompetitionChange(value)
    }
  },
  { immediate: true }
)

watch(
  () => form.competition_name,
  (value) => {
    if (value) onCompetitionChange(value)
  }
)

defineExpose({ refresh: loadList })

onMounted(async () => {
  await ensureOptions()
  await loadList()
})
</script>

<template>
  <div>
    <div class="finance-workbench">
      <div class="form-card">
        <div class="form-card-head">
          <h3>预算测算参数</h3>
          <p>根据费用标准表与差旅规则自动生成明细，每行都标注计算依据与标准编号。</p>
        </div>
        <div class="form-card-body">
          <div class="form-grid">
            <div class="span-2">
              <label class="field-label">赛事<span class="req">*</span></label>
              <el-select
                v-model="form.competition_name"
                filterable
                allow-create
                placeholder="选择或输入赛事名称"
                style="width: 100%"
              >
                <el-option v-for="comp in store.options?.competitions || []" :key="comp.id" :label="comp.name" :value="comp.name">
                  <span>{{ comp.name }}</span>
                  <span style="float: right; color: #96a6ae; font-size: 10px">{{ comp.level }}</span>
                </el-option>
              </el-select>
              <div v-if="feeHint" class="field-hint">{{ feeHint }}</div>
            </div>
            <div>
              <label class="field-label">赛事级别</label>
              <el-select v-model="form.competition_level" style="width: 100%">
                <el-option v-for="level in store.options?.levels || ['国家级', '省级', '校级']" :key="level" :label="level" :value="level" />
              </el-select>
            </div>
            <div>
              <label class="field-label">年度</label>
              <el-select v-model="form.year" clearable placeholder="年度" style="width: 100%">
                <el-option v-for="year in yearOptions" :key="year" :label="`${year} 年`" :value="year" />
              </el-select>
            </div>
            <div class="span-2">
              <label class="field-label">参赛队伍 / 项目</label>
              <el-input v-model="form.team_name" placeholder="如：智农云团队" />
            </div>
            <div>
              <label class="field-label">参赛地点</label>
              <el-input v-model="form.destination" placeholder="如：杭州" />
            </div>
            <div>
              <label class="field-label">行程天数</label>
              <el-input-number v-model="form.trip_days" :min="0" :max="30" style="width: 100%" />
            </div>
            <div>
              <label class="field-label">参赛学生数</label>
              <el-input-number v-model="form.student_count" :min="0" :max="60" style="width: 100%" />
            </div>
            <div>
              <label class="field-label">指导教师数</label>
              <el-input-number v-model="form.teacher_count" :min="0" :max="10" style="width: 100%" />
            </div>
            <div class="span-2">
              <label class="field-label">指导教师随队</label>
              <el-switch v-model="form.mentor_trip" active-text="随队" inactive-text="不随队" />
              <span class="field-hint" style="margin-left: 10px">随队教师的交通与住宿计入差旅预算</span>
            </div>
            <div>
              <label class="field-label">报名费</label>
              <el-input-number v-model="form.registration_fee" :min="0" :precision="2" :controls="false" placeholder="留空按标准" style="width: 100%" />
            </div>
            <div>
              <label class="field-label">计费口径</label>
              <el-select v-model="form.registration_fee_unit" style="width: 100%">
                <el-option label="元/人" value="元/人" />
                <el-option label="元/队" value="元/队" />
              </el-select>
            </div>
            <div class="span-2">
              <label class="field-label">交通方式</label>
              <el-input v-model="form.transport_mode" placeholder="高铁/动车二等座" />
            </div>
            <div class="span-2">
              <label class="field-label">往返票价（元/人）</label>
              <el-input-number v-model="form.transport_unit_price" :min="0" :precision="2" :controls="false" placeholder="留空按标准上限估算" style="width: 100%" />
            </div>
            <div class="span-2">
              <label class="field-label">申请人</label>
              <el-select v-model="form.applicant" filterable allow-create clearable placeholder="选择指导教师" style="width: 100%">
                <el-option v-for="name in store.options?.teachers || []" :key="name" :label="name" :value="name" />
              </el-select>
            </div>
            <div class="span-2">
              <label class="field-label">预算说明</label>
              <el-input v-model="form.remark" type="textarea" :rows="2" placeholder="如：多学院组团参赛、超标原因说明等" />
            </div>
          </div>

          <div class="custom-items">
            <div class="custom-items-head">
              <span>其他费用项（可选）</span>
              <el-button size="small" text type="primary" @click="addItem"><el-icon><Plus /></el-icon> 添加</el-button>
            </div>
            <div v-for="(item, index) in form.custom_items" :key="index" class="custom-item-row">
              <el-input v-model="item.category" placeholder="类别" style="width: 110px" />
              <el-input v-model="item.item_name" placeholder="费用名称" style="flex: 1" />
              <el-input-number v-model="item.quantity" :min="1" :controls="false" placeholder="数量" style="width: 74px" />
              <el-input v-model="item.unit" placeholder="单位" style="width: 68px" />
              <el-input-number v-model="item.unit_price" :min="0" :precision="2" :controls="false" placeholder="单价" style="width: 100px" />
              <el-button text type="danger" @click="removeItem(index)"><el-icon><Delete /></el-icon></el-button>
            </div>
          </div>

          <div class="form-actions">
            <el-button type="primary" :loading="planning" @click="runPlan">
              <el-icon><MagicStick /></el-icon> 测算预算
            </el-button>
            <el-button :loading="saving" :disabled="!plan" @click="save('待审批')">保存为待审批</el-button>
            <el-button :loading="saving" :disabled="!plan" plain @click="save('草稿')">保存草稿</el-button>
          </div>
        </div>
      </div>

      <div class="finance-result">
        <template v-if="plan">
          <div class="amount-banner">
            <div>
              <div class="amount-label">预算合计</div>
              <div class="amount-value">¥ {{ fmtMoney(plan.total) }}</div>
              <div class="amount-upper">{{ plan.total_upper || '' }}</div>
            </div>
            <div class="amount-side">
              <span class="tag-soft gold">{{ plan.approval?.level || '待测算' }}</span>
              <span class="tag-soft">{{ plan.items?.length || 0 }} 项明细</span>
            </div>
          </div>

          <div v-if="plan.approval?.steps?.length" class="approval-route">
            <span class="route-label">审批路径</span>
            <template v-for="(step, index) in plan.approval.steps" :key="step">
              <span class="route-step">{{ step }}</span>
              <span v-if="index < plan.approval.steps.length - 1" class="route-arrow">→</span>
            </template>
          </div>

          <DataTable :table="itemTable" :max-height="360" />

          <div class="result-section">
            <div class="result-section-title">合规校验</div>
            <CheckList :checks="plan.checks || []" />
          </div>

          <div v-if="plan.standards_used?.length" class="standards-row">
            <span class="muted">已引用费用标准：</span>
            <span v-for="code in plan.standards_used" :key="code" class="tag-soft mono">{{ code }}</span>
          </div>

          <details class="doc-preview-box">
            <summary>查看预算申请文本</summary>
            <pre class="doc-preview">{{ plan.generated_text }}</pre>
          </details>
        </template>
        <EmptyState
          v-else
          title="填写参数后测算预算"
          description="系统按费用标准表自动列示报名费、交通、住宿与补助，逐行给出计算依据，并提示审批路径与超标风险。"
        />
      </div>
    </div>

    <div class="panel list-panel">
      <div class="panel-head">
        <h3>预算单列表</h3>
        <span class="sub">共 {{ list.length }} 张</span>
        <div class="right">
          <el-button size="small" text :loading="listLoading" @click="loadList"><el-icon><Refresh /></el-icon> 刷新</el-button>
        </div>
      </div>
      <el-table :data="list" size="small" v-loading="listLoading" style="width: 100%">
        <el-table-column prop="doc_no" label="单据编号" min-width="150">
          <template #default="{ row }">
            <el-link type="primary" :underline="false" @click="openDetail(row)">{{ row.doc_no }}</el-link>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="预算名称" min-width="200" show-overflow-tooltip />
        <el-table-column prop="competition_name" label="赛事" min-width="150" show-overflow-tooltip />
        <el-table-column prop="year" label="年度" width="70" />
        <el-table-column label="预算金额" width="120" align="right">
          <template #default="{ row }"><span class="mono">¥{{ fmtMoney(row.total_amount) }}</span></template>
        </el-table-column>
        <el-table-column label="已批准" width="120" align="right">
          <template #default="{ row }">{{ row.approved_amount === null ? '—' : `¥${fmtMoney(row.approved_amount)}` }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }"><el-tag size="small" :type="tagType(row.status)">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="创建时间" width="140">
          <template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === '草稿'" size="small" text type="primary" :loading="statusBusy === row.id" @click="changeStatus(row, '待审批')">提交</el-button>
            <el-button v-if="canApprove && row.status === '待审批'" size="small" text type="success" :loading="statusBusy === row.id" @click="changeStatus(row, '已批准')">批准</el-button>
            <el-button v-if="canApprove && row.status === '待审批'" size="small" text type="danger" :loading="statusBusy === row.id" @click="changeStatus(row, '已驳回')">驳回</el-button>
            <el-button size="small" text @click="download(row, 'docx')">Word</el-button>
            <el-button size="small" text @click="download(row, 'xlsx')">Excel</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div style="padding: 30px 0; color: var(--muted-2); font-size: 12px">暂无预算单，测算后保存即可进入审批流转</div>
        </template>
      </el-table>
    </div>

    <el-drawer v-model="detailOpen" title="预算单详情" size="620px">
      <div v-loading="detailLoading">
        <template v-if="detail">
          <div class="amount-banner" style="margin-bottom: 16px">
            <div>
              <div class="amount-label">{{ detail.doc_no }}</div>
              <div class="amount-value" style="font-size: 24px">¥ {{ fmtMoney(detail.total_amount) }}</div>
              <div class="amount-upper">{{ detail.competition_name }} · {{ detail.year }} 年</div>
            </div>
            <div class="amount-side"><el-tag :type="tagType(detail.status)">{{ detail.status }}</el-tag></div>
          </div>
          <el-descriptions :column="2" size="small" border>
            <el-descriptions-item label="申请人">{{ detail.applicant_name || '—' }}</el-descriptions-item>
            <el-descriptions-item label="参赛队伍">{{ detail.team_name || '—' }}</el-descriptions-item>
            <el-descriptions-item label="参赛地点">{{ detail.destination || '—' }}</el-descriptions-item>
            <el-descriptions-item label="行程天数">{{ detail.trip_days }} 天</el-descriptions-item>
            <el-descriptions-item label="学生 / 教师">{{ detail.student_count }} / {{ detail.teacher_count }}</el-descriptions-item>
            <el-descriptions-item label="审批人">{{ detail.reviewer || '—' }}</el-descriptions-item>
          </el-descriptions>
          <DataTable :table="detailItems" :max-height="360" style="margin-top: 16px" />
          <div class="result-section">
            <div class="result-section-title">申请文本</div>
            <pre class="doc-preview">{{ detail.generated_text }}</pre>
          </div>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.finance-workbench {
  display: grid;
  grid-template-columns: 420px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.finance-workbench .form-card {
  position: sticky;
  top: 82px;
}

.finance-result {
  min-height: 300px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.amount-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 24px;
  border-radius: 12px;
  color: #f2fbf9;
  background:
    radial-gradient(circle at 85% 10%, rgba(17, 168, 156, 0.4), transparent 55%),
    linear-gradient(120deg, #0b2130, #103a45);
  border: 1px solid rgba(15, 159, 147, 0.4);
}

.amount-label {
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: #8fc8c1;
}

.amount-value {
  font-family: var(--font-serif);
  font-size: 34px;
  line-height: 1.2;
  margin: 4px 0 2px;
}

.amount-upper {
  font-size: 11.5px;
  color: #9fc3c8;
}

.amount-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
}

.approval-route {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 14px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 10px;
  font-size: 12px;
  color: var(--text-1);
}

.route-label {
  font-size: 10px;
  letter-spacing: 0.14em;
  color: var(--muted-2);
}

.route-step {
  padding: 3px 10px;
  border-radius: 20px;
  background: var(--teal-50);
  color: var(--teal-700);
}

.route-arrow {
  color: var(--muted-2);
}

.standards-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 11.5px;
}

.custom-items {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px dashed var(--line);
}

.custom-items-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-1);
  margin-bottom: 8px;
}

.custom-item-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.doc-preview-box {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
  padding: 12px 16px;
}

.doc-preview-box summary {
  cursor: pointer;
  font-size: 12px;
  color: var(--teal-700);
  font-weight: 600;
}

.doc-preview {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-sans);
  font-size: 12.5px;
  line-height: 1.9;
  color: var(--text-1);
  margin: 12px 0 0;
  max-height: 420px;
  overflow: auto;
}

.result-section {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 16px;
}

.list-panel {
  margin-top: 18px;
  padding: 0;
  overflow: hidden;
}

.list-panel .panel-head {
  margin: 0;
  padding: 14px 18px;
}

@media (max-width: 1200px) {
  .finance-workbench {
    grid-template-columns: 1fr;
  }
  .finance-workbench .form-card {
    position: static;
  }
}
</style>
