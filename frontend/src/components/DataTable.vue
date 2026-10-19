<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { displayValue } from '../utils'

const props = defineProps({
  table: { type: Object, required: true },
  maxHeight: { type: [Number, String], default: 460 }
})

const exporting = ref(false)
const columns = () => props.table?.columns || []
const rows = () => props.table?.rows || []

async function exportTable(format) {
  try {
    exporting.value = true
    await api.exportTable(
      { title: props.table?.title || '数据表', columns: columns(), rows: rows() },
      format
    )
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <div class="table-card">
    <div class="table-card-head">
      <h4>{{ table.title || '数据表' }}</h4>
      <span class="rows">{{ rows().length }} 行</span>
      <div class="right">
        <el-button size="small" text :loading="exporting" @click="exportTable('xlsx')">
          <el-icon><Download /></el-icon> Excel
        </el-button>
        <el-button size="small" text :loading="exporting" @click="exportTable('csv')">CSV</el-button>
      </div>
    </div>
    <el-table :data="rows()" size="small" stripe :max-height="maxHeight" style="width: 100%">
      <el-table-column
        v-for="col in columns()"
        :key="col.key"
        :prop="col.key"
        :label="col.label || col.key"
        :min-width="col.width || 100"
        show-overflow-tooltip
      >
        <template #default="{ row }">
          <span :class="{ 'mono': col.key === 'run_id' || col.key === 'doc_no' }">{{ displayValue(row[col.key]) }}</span>
        </template>
      </el-table-column>
      <template #empty>
        <div style="padding: 26px 0; color: var(--muted-2); font-size: 12px">暂无数据</div>
      </template>
    </el-table>
  </div>
</template>
