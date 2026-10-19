<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import { can, ensureOptions, store } from '../store'
import { fmtDateTime, fmtMoney, tagType } from '../utils'
import CheckList from './CheckList.vue'
import DataTable from './DataTable.vue'
import EmptyState from './EmptyState.vue'

const emit = defineEmits(['saved'])
const canApprove = computed(() => can('finance.approve'))

const CATEGORIES = ['交通费', '住宿费', '报名费', '伙食补助', '市内交通', '材料费', '其他']

function blankItem() {
  return {
    category: '交通费',
    item_name: '',
    amount: null,
    expense_date: '',
    invoice_no: '',
    has_invoice: true,
    payee: ''
  }
}

const form = reactive({
  budget_doc_no: '',
  loan_doc_no: '',
  claimant_name: '',
  college: '计算与智能技术学院',
  competition_name: '',
  reimburse_date: new Date().toISOString().slice(0, 10),
  event_end_date: '',
  purpose: '',
  fund_source: '学科竞赛专项经费',
  achieved: false,
  attachments: {
    event_notice: true,
    trip_approval: true,
    pasted_sheet: true,
    achievement_proof: true
  },
  remark: '',
  items: [blankItem(), blankItem()]
})

const budgets = ref([])
const loans = ref([])
const list = ref([])
const loadingList = ref(false)
const planning = ref(false)
const saving = ref(false)
const plan = ref(null)
const busyId = ref(0)

const selectedBudget = computed(() => budgets.value.find((b) => b.doc_no === form.budget_doc_no))
const availableLoans = computed(() => {
  const pool = loans.value.filter((l) => l.status !== '已冲销')
  if (!form.budget_doc_no || !selectedBudget.value?.competition_name) return pool
  return pool.filter((l) => l.competition_name === selectedBudget.value.competition_name)
})
const totalAmount = computed(() =>
  form.items.reduce((sum, item) => sum + (Number(item.amount) || 0), 0)
)

const contentRows = computed(() =>
  Object.entries(plan.value?.content || {}).map(([key, value]) => ({ key, value }))
)

const contentTable = computed(() => ({
  title: '报销单要素',
  columns: [
    { key: 'key', label: '项目', width: 160 },
    { key: 'value', label: '内容', width: 340 }
  ],
  rows: contentRows.value
}))

const itemTable = computed(() => ({
  title: '支出明细',
  columns: [
    { key: 'category', label: '类别', width: 90 },
    { key: 'item_name', label: '费用名称', width: 180 },
    { key: 'amount', label: '金额（元）', width: 110 },
    { key: 'expense_date', label: '发生日期', width: 110 },
    { key: 'invoice_no', label: '发票号码', width: 180 },
    { key: 'has_invoice', label: '票据', width: 80 },
    { key: 'payee', label: '收款方', width: 140 },
    { key: 'calc_basis', label: '核对说明', width: 220 }
  ],
  rows: plan.value?.items || []
}))

function buildPayload() {
  return {
    budget_doc_no: form.budget_doc_no || undefined,
    loan_doc_no: form.loan_doc_no || undefined,
    competition_name: form.competition_name || undefined,
    claimant_name: form.claimant_name,
    college: form.college,
    reimburse_date: form.reimburse_date || undefined,
    event_end_date: form.event_end_date || undefined,
    purpose: form.purpose || undefined,
    fund_source: form.fund_source,
    achieved: form.achieved,
    attachments: { ...form.attachments },
    attachment_count: form.items.filter((i) => Number(i.amount) > 0).length,
    remark: form.remark,
    items: form.items
      .filter((i) => i.item_name && Number(i.amount) > 0)
      .map((i) => ({
        category: i.category,
        item_name: i.item_name,
        amount: Number(i.amount),
        expense_date: i.expense_date || undefined,
        invoice_no: i.invoice_no,
        has_invoice: i.has_invoice,
        payee: i.payee
      }))
  }
}

function onBudgetChange() {
  if (!selectedBudget.value) return
  form.competition_name = selectedBudget.value.competition_name || form.competition_name
  form.claimant_name = form.claimant_name || selectedBudget.value.applicant_name || ''
  if (!form.purpose) form.purpose = `参加${selectedBudget.value.competition_name || '学科竞赛'}经费报销`
}

function onLoanChange() {
  const loan = loans.value.find((l) => l.doc_no === form.loan_doc_no)
  if (loan) {
    form.claimant_name = form.claimant_name || loan.borrower_name || ''
    form.competition_name = form.competition_name || loan.competition_name || ''
  }
}

async function loadBudgets() {
  const data = await api.budgets()
  budgets.value = data.items || []
}

async function loadLoans() {
  const data = await api.loans()
  loans.value = data.items || []
}

async function loadList() {
  loadingList.value = true
  try {
    const data = await api.reimbursements()
    list.value = data.items || []
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loadingList.value = false
  }
}

async function runPlan() {
  const payload = buildPayload()
  if (!payload.items.length) {
    ElMessage.warning('请至少录入一条金额大于 0 的支出明细')
    return
  }
  if (!form.claimant_name) {
    ElMessage.warning('请填写报销人')
    return
  }
  planning.value = true
  plan.value = null
  try {
    plan.value = await api.planReimbursement(payload)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    planning.value = false
  }
}

async function save(status) {
  const payload = buildPayload()
  if (!payload.items.length || !form.claimant_name) {
    ElMessage.warning('请填写报销人并录入支出明细')
    return
  }
  saving.value = true
  try {
    const data = await api.createReimbursement({ payload, status })
    ElMessage.success(`已保存报销单 ${data.doc_no}（${data.status}）`)
    await loadList()
    emit('saved')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}

async function changeStatus(row, status) {
  const label = { 待审核: '提交审核', 已通过: '审核通过', 已驳回: '驳回' }[status] || status
  try {
    await ElMessageBox.confirm(`确认对报销单 ${row.doc_no} 执行「${label}」？`, '报销状态流转', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      type: status === '已驳回' ? 'warning' : 'info'
    })
  } catch {
    return
  }
  busyId.value = row.id
  try {
    const data = await api.reimbursementStatus(row.id, { status })
    ElMessage.success(data.closed_loan_doc_no ? `报销已通过，借款单 ${data.closed_loan_doc_no} 已自动冲销` : '报销状态已更新')
    await loadList()
    emit('saved')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    busyId.value = 0
  }
}

async function download(row, format) {
  try {
    await api.reimbursementDoc(row.id, format)
  } catch (error) {
    ElMessage.error(error.message)
  }
}

function addItem() {
  form.items.push(blankItem())
}

function removeItem(index) {
  form.items.splice(index, 1)
}

async function refreshReferences() {
  try {
    await Promise.all([loadBudgets(), loadLoans()])
  } catch (error) {
    ElMessage.error(error.message)
  }
  await loadList()
}

defineExpose({ refresh: refreshReferences })

onMounted(async () => {
  await ensureOptions()
  if (store.options?.teachers?.length) form.claimant_name = store.options.teachers[0]
  await refreshReferences()
})
</script>

<template>
  <div>
    <div class="finance-workbench">
      <div class="form-card">
        <div class="form-card-head">
          <h3>报销整理参数</h3>
          <p>逐项录入实际支出与票据，系统检查缺票、超标、超预算、时限与附件完整性。</p>
        </div>
        <div class="form-card-body">
          <div class="form-grid">
            <div class="span-2">
              <label class="field-label">关联预算单</label>
              <el-select v-model="form.budget_doc_no" filterable clearable placeholder="选择预算单" style="width: 100%" @change="onBudgetChange">
                <el-option v-for="budget in budgets" :key="budget.id" :label="`${budget.doc_no} · ${budget.competition_name || budget.title}`" :value="budget.doc_no" />
              </el-select>
            </div>
            <div class="span-2">
              <label class="field-label">冲销借款单</label>
              <el-select v-model="form.loan_doc_no" filterable clearable placeholder="如有借款请选择" style="width: 100%" @change="onLoanChange">
                <el-option v-for="loan in availableLoans" :key="loan.id" :label="`${loan.doc_no} · ${loan.borrower_name} · ¥${fmtMoney(loan.amount)}`" :value="loan.doc_no" />
              </el-select>
            </div>
            <div>
              <label class="field-label">报销人<span class="req">*</span></label>
              <el-select v-model="form.claimant_name" filterable allow-create placeholder="报销人" style="width: 100%">
                <el-option v-for="name in store.options?.teachers || []" :key="name" :label="name" :value="name" />
              </el-select>
            </div>
            <div>
              <label class="field-label">所在单位</label>
              <el-input v-model="form.college" />
            </div>
            <div>
              <label class="field-label">报销日期</label>
              <el-date-picker v-model="form.reimburse_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
            </div>
            <div>
              <label class="field-label">竞赛结束日期</label>
              <el-date-picker v-model="form.event_end_date" type="date" value-format="YYYY-MM-DD" placeholder="用于时限校验" style="width: 100%" />
            </div>
            <div class="span-2">
              <label class="field-label">事由</label>
              <el-input v-model="form.purpose" placeholder="参加××竞赛经费报销" />
            </div>
            <div class="span-2">
              <label class="field-label">附件与证明材料</label>
              <div class="attach-row">
                <el-checkbox v-model="form.attachments.event_notice">参赛通知</el-checkbox>
                <el-checkbox v-model="form.attachments.trip_approval">出差审批表</el-checkbox>
                <el-checkbox v-model="form.attachments.pasted_sheet">票据粘贴单</el-checkbox>
                <el-checkbox v-model="form.attachments.achievement_proof" :disabled="!form.achieved">成绩证明</el-checkbox>
                <el-switch v-model="form.achieved" active-text="已获奖" inactive-text="未获奖" size="small" />
              </div>
            </div>
          </div>

          <div class="items-head">
            <span>支出明细</span>
            <div>
              <span class="muted small">合计 ¥{{ fmtMoney(totalAmount) }}</span>
              <el-button size="small" text type="primary" style="margin-left: 8px" @click="addItem"><el-icon><Plus /></el-icon> 添加明细</el-button>
            </div>
          </div>
          <div v-for="(item, index) in form.items" :key="index" class="reimb-item">
            <div class="reimb-item-head">
              <span class="item-index">{{ index + 1 }}</span>
              <el-select v-model="item.category" filterable allow-create size="small" style="width: 104px">
                <el-option v-for="cat in CATEGORIES" :key="cat" :label="cat" :value="cat" />
              </el-select>
              <el-input v-model="item.item_name" size="small" placeholder="费用名称" style="flex: 1" />
              <el-input-number v-model="item.amount" :min="0" :precision="2" :controls="false" size="small" placeholder="金额" style="width: 108px" />
              <el-button text type="danger" size="small" @click="removeItem(index)"><el-icon><Delete /></el-icon></el-button>
            </div>
            <div class="reimb-item-sub">
              <el-date-picker v-model="item.expense_date" type="date" value-format="YYYY-MM-DD" size="small" placeholder="发生日期" style="width: 130px" />
              <el-input v-model="item.invoice_no" size="small" placeholder="发票号码" style="width: 170px" />
              <el-checkbox v-model="item.has_invoice" size="small">有发票</el-checkbox>
              <el-input v-model="item.payee" size="small" placeholder="收款方" style="flex: 1" />
            </div>
          </div>

          <div class="form-actions">
            <el-button type="primary" :loading="planning" @click="runPlan"><el-icon><MagicStick /></el-icon> 检查报销单</el-button>
            <el-button :loading="saving" :disabled="!plan" @click="save('待审核')">保存并提交审核</el-button>
            <el-button :loading="saving" :disabled="!plan" plain @click="save('草稿')">保存草稿</el-button>
          </div>
        </div>
      </div>

      <div class="finance-result">
        <template v-if="plan">
          <div class="amount-banner">
            <div>
              <div class="amount-label">报销合计</div>
              <div class="amount-value">¥ {{ fmtMoney(plan.total) }}</div>
              <div class="amount-upper">{{ plan.total_upper || '' }}</div>
            </div>
            <div class="amount-side">
              <div class="score-ring" :class="{ low: plan.completeness_score < 70 }">
                <strong>{{ Math.round(plan.completeness_score) }}</strong>
                <span>完整度</span>
              </div>
            </div>
          </div>

          <div v-if="plan.budget || plan.loan" class="budget-brief">
            <span v-if="plan.budget" class="brief-item">
              <span class="brief-label">预算</span>{{ plan.budget.doc_no }} · 批准 ¥{{ fmtMoney(plan.budget.amount) }}
            </span>
            <span v-if="plan.loan" class="brief-item">
              <span class="brief-label">借款</span>{{ plan.loan.doc_no }} · ¥{{ fmtMoney(plan.loan.amount) }}
            </span>
            <span v-if="plan.loan" class="brief-item">
              <span class="brief-label">应退/补</span>¥{{ fmtMoney(plan.loan.amount - plan.total) }}
            </span>
          </div>

          <DataTable :table="itemTable" :max-height="340" />

          <div class="result-section">
            <div class="result-section-title">票据与合规校验</div>
            <CheckList :checks="plan.checks || []" />
          </div>

          <DataTable :table="contentTable" :max-height="320" />

          <details class="doc-preview-box">
            <summary>查看报销单文本</summary>
            <pre class="doc-preview">{{ plan.generated_text }}</pre>
          </details>
        </template>
        <EmptyState
          v-else
          title="录入明细后检查报销单"
          description="系统逐项核对发票、日期、费用标准、预算余额与报销时限，并给出材料完整性评分。"
        />
      </div>
    </div>

    <div class="panel list-panel">
      <div class="panel-head">
        <h3>报销单列表</h3>
        <span class="sub">共 {{ list.length }} 张</span>
        <div class="right">
          <el-button size="small" text :loading="loadingList" @click="loadList"><el-icon><Refresh /></el-icon> 刷新</el-button>
        </div>
      </div>
      <el-table :data="list" size="small" v-loading="loadingList" style="width: 100%">
        <el-table-column prop="doc_no" label="单据编号" min-width="150" />
        <el-table-column prop="claimant_name" label="报销人" width="100" />
        <el-table-column prop="competition_name" label="赛事" min-width="150" show-overflow-tooltip />
        <el-table-column label="报销金额" width="120" align="right">
          <template #default="{ row }"><span class="mono">¥{{ fmtMoney(row.total_amount) }}</span></template>
        </el-table-column>
        <el-table-column label="完整度" width="90" align="center">
          <template #default="{ row }">
            <span class="mono" :style="{ color: (row.completeness_score || 0) < 70 ? '#bf4a3f' : '#178a75' }">
              {{ row.completeness_score ?? '—' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }"><el-tag size="small" :type="tagType(row.status)">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="创建时间" width="140">
          <template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === '草稿'" size="small" text type="primary" :loading="busyId === row.id" @click="changeStatus(row, '待审核')">提交</el-button>
            <el-button v-if="canApprove && row.status === '待审核'" size="small" text type="success" :loading="busyId === row.id" @click="changeStatus(row, '已通过')">通过</el-button>
            <el-button v-if="canApprove && row.status === '待审核'" size="small" text type="danger" :loading="busyId === row.id" @click="changeStatus(row, '已驳回')">驳回</el-button>
            <el-button size="small" text @click="download(row, 'docx')">Word</el-button>
            <el-button size="small" text @click="download(row, 'xlsx')">Excel</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div style="padding: 30px 0; color: var(--muted-2); font-size: 12px">暂无报销单</div>
        </template>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.finance-workbench {
  display: grid;
  grid-template-columns: 460px minmax(0, 1fr);
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

.score-ring {
  width: 76px;
  height: 76px;
  border-radius: 50%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border: 3px solid #37b8a8;
  background: rgba(255, 255, 255, 0.06);
}

.score-ring.low {
  border-color: #df8b55;
}

.score-ring strong {
  font-family: var(--font-serif);
  font-size: 24px;
  line-height: 1;
}

.score-ring span {
  font-size: 9px;
  letter-spacing: 0.12em;
  color: #9fc3c8;
  margin-top: 3px;
}

.budget-brief {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  padding: 10px 14px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 10px;
  font-size: 12px;
}

.brief-label {
  font-size: 10px;
  letter-spacing: 0.14em;
  color: var(--muted-2);
  margin-right: 4px;
}

.attach-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 14px;
}

.items-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 16px 0 8px;
  padding-top: 12px;
  border-top: 1px dashed var(--line);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-1);
}

.reimb-item {
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  margin-bottom: 8px;
  background: #fcfdfd;
}

.reimb-item-head,
.reimb-item-sub {
  display: flex;
  align-items: center;
  gap: 6px;
}

.reimb-item-sub {
  margin-top: 6px;
  padding-left: 24px;
}

.item-index {
  width: 18px;
  font-size: 11px;
  color: var(--muted-2);
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
