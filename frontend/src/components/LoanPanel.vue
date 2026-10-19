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

const form = reactive({
  budget_doc_no: '',
  borrower_name: '',
  teacher_no: '',
  amount: null,
  purpose: '',
  payee: '',
  expected_repay_date: '',
  fund_source: '学科竞赛专项经费',
  remark: ''
})

const budgets = ref([])
const loans = ref([])
const loadingBudgets = ref(false)
const loadingList = ref(false)
const planning = ref(false)
const saving = ref(false)
const plan = ref(null)
const busyId = ref(0)

const selectedBudget = computed(() => budgets.value.find((b) => b.doc_no === form.budget_doc_no))
const approvedCount = computed(() => budgets.value.filter((b) => b.status === '已批准').length)
const canApprove = computed(() => can('finance.approve'))

const contentRows = computed(() =>
  Object.entries(plan.value?.content || {}).map(([key, value]) => ({ key, value }))
)

const contentTable = computed(() => ({
  title: '借款单要素',
  columns: [
    { key: 'key', label: '项目', width: 160 },
    { key: 'value', label: '内容', width: 340 }
  ],
  rows: contentRows.value
}))

function defaultRepayDate() {
  const d = new Date()
  d.setDate(d.getDate() + 60)
  return d.toISOString().slice(0, 10)
}

function buildPayload() {
  const payload = {
    budget_doc_no: form.budget_doc_no || undefined,
    borrower: { name: form.borrower_name, teacher_no: form.teacher_no },
    purpose: form.purpose || undefined,
    payee: form.payee || undefined,
    expected_repay_date: form.expected_repay_date || undefined,
    fund_source: form.fund_source,
    remark: form.remark
  }
  if (form.amount !== null && form.amount !== '') payload.amount = Number(form.amount)
  return payload
}

function onBudgetChange() {
  if (!selectedBudget.value) return
  if (form.amount === null || form.amount === '') {
    form.amount = selectedBudget.value.approved_amount ?? selectedBudget.value.total_amount ?? null
  }
  if (!form.purpose) {
    form.purpose = `参加${selectedBudget.value.competition_name || '学科竞赛'}相关费用支出`
  }
}

async function loadBudgets() {
  loadingBudgets.value = true
  try {
    const data = await api.budgets()
    budgets.value = data.items || []
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loadingBudgets.value = false
  }
}

async function loadLoans() {
  loadingList.value = true
  try {
    const data = await api.loans()
    loans.value = data.items || []
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loadingList.value = false
  }
}

async function runPlan() {
  if (!form.budget_doc_no) {
    ElMessage.warning('请选择已批准的预算单作为借款依据')
    return
  }
  if (!form.borrower_name) {
    ElMessage.warning('请填写借款人姓名')
    return
  }
  planning.value = true
  plan.value = null
  try {
    plan.value = await api.planLoan(buildPayload())
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    planning.value = false
  }
}

async function save(status) {
  if (!form.budget_doc_no || !form.borrower_name) {
    ElMessage.warning('请先选择预算单并填写借款人')
    return
  }
  saving.value = true
  try {
    const data = await api.createLoan({ payload: buildPayload(), status })
    ElMessage.success(`已保存借款单 ${data.doc_no}（${data.status}）`)
    plan.value = {
      content: data.generated_content || plan.value?.content || {},
      amount: data.amount,
      checks: data.checks || plan.value?.checks || [],
      budget: plan.value?.budget,
      generated_text: plan.value?.generated_text || ''
    }
    await loadLoans()
    emit('saved')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}

async function changeStatus(row, status) {
  const label = {
    待审批: '提交审批',
    已借出: '办理借出',
    已冲销: '办理冲销'
  }[status] || status
  try {
    await ElMessageBox.confirm(`确认对借款单 ${row.doc_no} 执行「${label}」？`, '借款状态流转', {
      confirmButtonText: '确认',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  busyId.value = row.id
  try {
    await api.loanStatus(row.id, { status })
    ElMessage.success('借款状态已更新')
    await loadLoans()
    emit('saved')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    busyId.value = 0
  }
}

async function download(row, format) {
  try {
    await api.loanDoc(row.id, format)
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function refreshReferences() {
  await Promise.all([loadBudgets(), loadLoans()])
}

defineExpose({ refresh: refreshReferences })

onMounted(async () => {
  await ensureOptions()
  form.expected_repay_date = defaultRepayDate()
  if (store.options?.teachers?.length) form.borrower_name = store.options.teachers[0]
  await refreshReferences()
})
</script>

<template>
  <div>
    <div class="finance-workbench">
      <div class="form-card">
        <div class="form-card-head">
          <h3>借款单要素</h3>
          <p>借款须以已批准的预算为前提，系统自动校验额度、前账与单笔上限。</p>
        </div>
        <div class="form-card-body">
          <div class="form-grid">
            <div class="span-2">
              <label class="field-label">依据预算单<span class="req">*</span></label>
              <el-select
                v-model="form.budget_doc_no"
                filterable
                placeholder="选择已批准预算"
                style="width: 100%"
                :loading="loadingBudgets"
                @change="onBudgetChange"
              >
                <el-option v-for="budget in budgets" :key="budget.id" :label="`${budget.doc_no} · ${budget.competition_name || budget.title}`" :value="budget.doc_no">
                  <span>{{ budget.doc_no }} · {{ budget.competition_name || budget.title }}</span>
                  <span style="float: right; color: #96a6ae; font-size: 10px">{{ budget.status }} · ¥{{ fmtMoney(budget.approved_amount ?? budget.total_amount) }}</span>
                </el-option>
              </el-select>
              <div class="field-hint">可选 {{ approvedCount }} 张已批准预算；未批准预算将无法通过校验</div>
            </div>
            <div>
              <label class="field-label">借款人<span class="req">*</span></label>
              <el-select v-model="form.borrower_name" filterable allow-create placeholder="借款人" style="width: 100%">
                <el-option v-for="name in store.options?.teachers || []" :key="name" :label="name" :value="name" />
              </el-select>
            </div>
            <div>
              <label class="field-label">工号</label>
              <el-input v-model="form.teacher_no" placeholder="如 T2008" />
            </div>
            <div>
              <label class="field-label">借款金额（元）</label>
              <el-input-number v-model="form.amount" :min="0" :precision="2" :controls="false" style="width: 100%" placeholder="默认取批准金额" />
            </div>
            <div>
              <label class="field-label">预计冲销日期</label>
              <el-date-picker v-model="form.expected_repay_date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" style="width: 100%" />
            </div>
            <div class="span-2">
              <label class="field-label">借款用途</label>
              <el-input v-model="form.purpose" placeholder="参加××竞赛相关费用支出" />
            </div>
            <div class="span-2">
              <label class="field-label">收款单位</label>
              <el-input v-model="form.payee" placeholder="按赛事通知指定收款单位" />
            </div>
            <div class="span-2">
              <label class="field-label">经费来源</label>
              <el-input v-model="form.fund_source" />
            </div>
            <div class="span-2">
              <label class="field-label">备注</label>
              <el-input v-model="form.remark" type="textarea" :rows="2" placeholder="选填" />
            </div>
          </div>
          <div class="form-actions">
            <el-button type="primary" :loading="planning" @click="runPlan"><el-icon><MagicStick /></el-icon> 生成借款单</el-button>
            <el-button :loading="saving" :disabled="!plan" @click="save('待审批')">保存为待审批</el-button>
            <el-button :loading="saving" :disabled="!plan" plain @click="save('草稿')">保存草稿</el-button>
          </div>
        </div>
      </div>

      <div class="finance-result">
        <template v-if="plan">
          <div class="amount-banner">
            <div>
              <div class="amount-label">借款金额</div>
              <div class="amount-value">¥ {{ fmtMoney(plan.amount) }}</div>
              <div class="amount-upper">{{ plan.content?.['借款金额（大写）'] || '' }}</div>
            </div>
            <div class="amount-side">
              <span class="tag-soft gold">{{ plan.content?.['单据编号'] || '待保存' }}</span>
              <span v-if="plan.budget?.doc_no" class="tag-soft">{{ plan.budget.doc_no }}</span>
            </div>
          </div>

          <div v-if="plan.budget" class="budget-brief">
            <span class="brief-label">预算依据</span>
            <span>{{ plan.budget.competition_name || '—' }}</span>
            <span class="muted">批准金额 ¥{{ fmtMoney(plan.budget.amount) }}</span>
            <span v-if="plan.budget.destination" class="muted">· {{ plan.budget.destination }}</span>
          </div>

          <DataTable :table="contentTable" :max-height="380" />

          <div class="result-section">
            <div class="result-section-title">借款校验</div>
            <CheckList :checks="plan.checks || []" />
          </div>

          <details class="doc-preview-box">
            <summary>查看借款单文本</summary>
            <pre class="doc-preview">{{ plan.generated_text }}</pre>
          </details>
        </template>
        <EmptyState
          v-else
          title="选择预算单生成借款单"
          description="系统自动带出赛事、地点与批准额度，并校验前账未清、单笔上限和预算余额。"
        />
      </div>
    </div>

    <div class="panel list-panel">
      <div class="panel-head">
        <h3>借款单列表</h3>
        <span class="sub">共 {{ loans.length }} 张</span>
        <div class="right">
          <el-button size="small" text :loading="loadingList" @click="loadLoans"><el-icon><Refresh /></el-icon> 刷新</el-button>
        </div>
      </div>
      <el-table :data="loans" size="small" v-loading="loadingList" style="width: 100%">
        <el-table-column prop="doc_no" label="单据编号" min-width="150" />
        <el-table-column prop="borrower_name" label="借款人" width="100" />
        <el-table-column prop="competition_name" label="赛事" min-width="150" show-overflow-tooltip />
        <el-table-column label="借款金额" width="120" align="right">
          <template #default="{ row }"><span class="mono">¥{{ fmtMoney(row.amount) }}</span></template>
        </el-table-column>
        <el-table-column prop="expected_repay_date" label="预计冲销" width="110" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }"><el-tag size="small" :type="tagType(row.status)">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="创建时间" width="140">
          <template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === '草稿'" size="small" text type="primary" :loading="busyId === row.id" @click="changeStatus(row, '待审批')">提交</el-button>
            <el-button v-if="canApprove && row.status === '待审批'" size="small" text type="success" :loading="busyId === row.id" @click="changeStatus(row, '已借出')">办理借出</el-button>
            <el-button v-if="canApprove && row.status === '已借出'" size="small" text type="warning" :loading="busyId === row.id" @click="changeStatus(row, '已冲销')">冲销</el-button>
            <el-button size="small" text @click="download(row, 'docx')">Word</el-button>
            <el-button size="small" text @click="download(row, 'xlsx')">Excel</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div style="padding: 30px 0; color: var(--muted-2); font-size: 12px">暂无借款单</div>
        </template>
      </el-table>
    </div>
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

.budget-brief {
  display: flex;
  align-items: center;
  gap: 10px;
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
