<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { fmtMoney, fmtNumber } from '../utils'
import PageHeader from '../components/PageHeader.vue'
import StatCard from '../components/StatCard.vue'
import BudgetPanel from '../components/BudgetPanel.vue'
import LoanPanel from '../components/LoanPanel.vue'
import ReimbursementPanel from '../components/ReimbursementPanel.vue'

const route = useRoute()
const router = useRouter()

const tab = ref('budget')
const summary = ref(null)
const loading = ref(false)
const budgetPanel = ref(null)
const loanPanel = ref(null)
const reimbursementPanel = ref(null)

const presetCompetition = computed(() => String(route.query.competition || ''))

const pendingNote = computed(() => {
  const s = summary.value
  if (!s) return '加载中'
  return `共 ${fmtNumber(s.budgets)} 张 · 待审批 ${fmtNumber(s.budgets_pending)} 张`
})

async function loadSummary() {
  loading.value = true
  try {
    summary.value = await api.financeSummary()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

async function refreshReferences() {
  await Promise.allSettled([
    budgetPanel.value?.refresh?.(),
    loanPanel.value?.refresh?.(),
    reimbursementPanel.value?.refresh?.()
  ])
}

async function handleSaved() {
  await Promise.all([loadSummary(), refreshReferences()])
}

const activePanel = computed(() => ({ budget: budgetPanel.value, loan: loanPanel.value, reimbursement: reimbursementPanel.value }[tab.value]))

function syncTab(value) {
  if (['budget', 'loan', 'reimbursement'].includes(value)) tab.value = value
}

watch(
  () => route.query.tab,
  (value) => syncTab(String(value || '')),
  { immediate: true }
)

watch(tab, (value) => {
  if (String(route.query.tab || '') !== value) {
    router.replace({ query: { ...route.query, tab: value } })
  }
  activePanel.value?.refresh?.()
})

onMounted(loadSummary)
</script>

<template>
  <div>
    <PageHeader
      eyebrow="Finance"
      title="经费辅助"
      description="预算编制、借款办理与报销整理共用一套费用标准与审批规则。金额按标准表计算，每一行都保留计算依据，便于财务复核。"
    >
      <template #actions>
        <el-button @click="router.push('/knowledge?q=经费')"><el-icon><Reading /></el-icon> 查阅制度</el-button>
        <el-button type="primary" :loading="loading" @click="loadSummary"><el-icon><Refresh /></el-icon> 刷新概览</el-button>
      </template>
    </PageHeader>

    <div class="stat-grid" style="margin-bottom: 16px">
      <StatCard
        label="预算总额"
        :value="`¥${fmtMoney(summary?.budget_total)}`"
        :note="pendingNote"
        icon="Wallet"
        tone="ink"
      />
      <StatCard
        label="已批准额度"
        :value="`¥${fmtMoney(summary?.approved_total)}`"
        note="作为借款与报销的上限依据"
        icon="CircleCheck"
      />
      <StatCard
        label="借款累计"
        :value="`¥${fmtMoney(summary?.loan_total)}`"
        :note="`${fmtNumber(summary?.loans)} 笔借款单`"
        icon="CreditCard"
        tone="gold"
      />
      <StatCard
        label="报销累计"
        :value="`¥${fmtMoney(summary?.reimbursement_total)}`"
        :note="`${fmtNumber(summary?.reimbursements)} 张报销单`"
        icon="Tickets"
      />
    </div>

    <div class="policy-strip">
      <span class="strip-icon"><el-icon><InfoFilled /></el-icon></span>
      <div>
        <strong>数据驱动的经费规则</strong>
        <p>费用标准、审批阈值与校验开关来自费用标准表与制度配置；新增赛事或调整标准无需修改代码。金额计算不依赖大模型生成。</p>
      </div>
      <el-button size="small" text type="primary" @click="router.push('/competitions')">查看赛事经费信息</el-button>
    </div>

    <el-tabs v-model="tab" class="finance-tabs">
      <el-tab-pane label="预算申请" name="budget">
        <BudgetPanel ref="budgetPanel" :preset-competition="presetCompetition" @saved="handleSaved" />
      </el-tab-pane>
      <el-tab-pane label="借款办理" name="loan">
        <LoanPanel ref="loanPanel" @saved="handleSaved" />
      </el-tab-pane>
      <el-tab-pane label="报销整理" name="reimbursement">
        <ReimbursementPanel ref="reimbursementPanel" @saved="handleSaved" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.policy-strip {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 18px;
  margin-bottom: 18px;
  border: 1px dashed rgba(15, 159, 147, 0.35);
  border-radius: 10px;
  background: linear-gradient(90deg, rgba(15, 159, 147, 0.06), rgba(15, 159, 147, 0.02));
}

.strip-icon {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--teal-700);
  background: rgba(15, 159, 147, 0.12);
  flex-shrink: 0;
}

.policy-strip strong {
  font-size: 12.5px;
  color: var(--ink-800);
}

.policy-strip p {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: var(--muted);
  line-height: 1.6;
}

.finance-tabs :deep(.el-tabs__header) {
  margin-bottom: 18px;
}

.finance-tabs :deep(.el-tabs__item) {
  font-size: 13px;
  padding: 0 22px;
}
</style>
