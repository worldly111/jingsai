<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import MarkdownView from './MarkdownView.vue'
import CitationList from './CitationList.vue'
import CheckList from './CheckList.vue'
import AgentTrace from './AgentTrace.vue'
import DataTable from './DataTable.vue'
import EChart from './EChart.vue'

const props = defineProps({
  result: { type: Object, default: null },
  title: { type: String, default: '' },
  showTables: { type: Boolean, default: true },
  showCharts: { type: Boolean, default: true },
  showCitations: { type: Boolean, default: true },
  showTrace: { type: Boolean, default: true },
  showChecks: { type: Boolean, default: true },
  showExport: { type: Boolean, default: true },
  showAnswer: { type: Boolean, default: true },
  showSuggestions: { type: Boolean, default: true }
})

const exporting = ref(false)
const copying = ref(false)

const answer = computed(() => props.result?.answer || '')
const sections = computed(() => props.result?.sections || [])
const tables = computed(() => props.result?.tables || [])
const charts = computed(() => props.result?.charts || [])
const citations = computed(() => props.result?.citations || [])
const checks = computed(() => props.result?.checks || [])
const suggestions = computed(() => props.result?.suggestions || [])
const steps = computed(() => props.result?.steps || [])
const displayTitle = computed(() => props.title || props.result?.agent_name || '智能体结果')

const modeText = computed(() => {
  if (!props.result) return ''
  return props.result.llm_used ? `${props.result.llm_provider || '大模型'} 生成` : '离线规则引擎'
})

const qaTags = computed(() => {
  const u = props.result?.structured?.understanding
  if (!u) return []
  return [u.intent, u.competition, u.year ? `${u.year} 年` : ''].filter(Boolean)
})

const dataSource = computed(() => {
  const s = props.result?.structured || {}
  return s.overview?.data_source || s.plan?.ledger?.data_source || ''
})

async function exportAgent(format) {
  try {
    exporting.value = true
    await api.exportAgent(
      { title: displayTitle.value, answer: answer.value, tables: tables.value },
      format
    )
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    exporting.value = false
  }
}

async function copyAnswer() {
  try {
    copying.value = true
    await navigator.clipboard.writeText(answer.value)
    ElMessage.success('已复制回答内容')
  } catch {
    ElMessage.error('复制失败，请手动选择文本')
  } finally {
    copying.value = false
  }
}
</script>

<template>
  <div v-if="result" class="result-shell">
    <div class="result-head">
      <div>
        <div class="result-title">
          <el-icon color="#0f9f93"><MagicStick /></el-icon>
          {{ displayTitle }}
        </div>
        <div class="result-meta">
          <span class="tag-soft teal"><el-icon><Cpu /></el-icon>{{ modeText }}</span>
          <span v-if="result.duration_ms !== undefined" class="tag-soft">{{ result.duration_ms }} ms</span>
          <span v-if="citations.length" class="tag-soft"><el-icon><Document /></el-icon>{{ citations.length }} 条引用</span>
          <span v-if="steps.length" class="tag-soft">{{ steps.length }} 个节点</span>
          <span v-for="tag in qaTags" :key="tag" class="tag-soft gold">{{ tag }}</span>
          <span v-if="result.run_id" class="tag-soft mono">{{ result.run_id }}</span>
        </div>
      </div>
      <div class="result-actions">
        <slot name="actions" />
        <el-button v-if="showExport" size="small" :loading="copying" @click="copyAnswer">
          <el-icon><CopyDocument /></el-icon> 复制
        </el-button>
        <el-button v-if="showExport" size="small" :loading="exporting" @click="exportAgent('docx')">
          <el-icon><Document /></el-icon> Word
        </el-button>
        <el-button v-if="showExport" size="small" :loading="exporting" @click="exportAgent('md')">Markdown</el-button>
      </div>
    </div>

    <el-alert
      v-if="result.error"
      type="error"
      :closable="false"
      show-icon
      :title="`工作流执行异常：${result.error}`"
      style="margin-bottom: 16px"
    />

    <div v-if="showAnswer && (answer || sections.length)" class="result-section">
      <div class="result-section-title">回答与结论</div>
      <div class="answer-card">
        <MarkdownView v-if="answer" :content="answer" />
        <template v-else>
          <div v-for="(section, index) in sections" :key="index">
            <MarkdownView :content="section.content || ''" />
          </div>
        </template>
      </div>
    </div>

    <div v-if="showChecks && checks.length" class="result-section">
      <div class="result-section-title">校验结果</div>
      <CheckList :checks="checks" />
    </div>

    <div v-if="showCharts && charts.length" class="result-section">
      <div class="result-section-title">可视化分析</div>
      <div class="result-charts">
        <div v-for="(chart, index) in charts" :key="index" class="chart-card">
          <div class="chart-card-head">
            <h4>{{ chart.title || '图表' }}</h4>
            <span class="tag-soft" style="margin-left: auto">{{ chart.kind || chart.type || 'chart' }}</span>
          </div>
          <div class="chart-card-body">
            <EChart :option="chart.option" :height="340" />
          </div>
        </div>
      </div>
    </div>

    <div v-if="showTables && tables.length" class="result-section">
      <div class="result-section-title">结构化结果</div>
      <div class="result-tables">
        <DataTable v-for="(table, index) in tables" :key="index" :table="table" />
      </div>
    </div>

    <div v-if="showSuggestions && suggestions.length" class="result-section">
      <div class="result-section-title">下一步建议</div>
      <div class="suggestion-list">
        <div v-for="(item, index) in suggestions" :key="index" class="suggestion-item">
          <span class="tag-soft teal">{{ index + 1 }}</span>
          <span>{{ item }}</span>
        </div>
      </div>
    </div>

    <div v-if="showCitations && citations.length" class="result-section">
      <div class="result-section-title">原文依据与溯源</div>
      <CitationList :citations="citations" />
    </div>

    <div v-if="showTrace && steps.length" class="result-section">
      <div class="result-section-title">执行过程</div>
      <AgentTrace :steps="steps" />
    </div>

    <div class="result-foot">
      <el-icon><Lock /></el-icon>
      <span>重要政策与数据以结构化台账、原始文件为准，大模型仅参与表达与归纳。</span>
      <span v-if="dataSource">数据来源：{{ dataSource }}</span>
      <span style="margin-left: auto">Run {{ result.run_id || '—' }}</span>
    </div>
  </div>
</template>

<style scoped>
.suggestion-list {
  display: grid;
  gap: 8px;
}

.suggestion-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 12.5px;
  color: #4b616c;
  line-height: 1.75;
  padding: 9px 12px;
  background: #fbfcfc;
  border: 1px solid var(--line);
  border-radius: 8px;
}

.suggestion-item .tag-soft {
  flex-shrink: 0;
  min-width: 22px;
  justify-content: center;
  padding: 1px 5px;
}
</style>
