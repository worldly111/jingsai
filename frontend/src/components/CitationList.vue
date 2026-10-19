<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

const props = defineProps({
  citations: { type: Array, default: () => [] },
  title: { type: String, default: '原文依据' }
})

const open = ref(true)
const downloading = ref(null)

async function downloadSource(item) {
  if (!item.document_id) return
  try {
    downloading.value = item.chunk_id
    await api.knowledgeFile(item.document_id, item.title || '原始文件')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    downloading.value = null
  }
}
</script>

<template>
  <div v-if="props.citations.length" class="citation-box">
    <div class="citation-head" @click="open = !open">
      <el-icon color="#2f8f82"><Document /></el-icon>
      <span class="title">{{ title }}</span>
      <span class="count">{{ props.citations.length }} 处</span>
      <span class="hint">{{ open ? '收起' : '展开查看原始出处' }}</span>
      <el-icon :style="{ transition: 'transform .2s', transform: open ? 'rotate(180deg)' : 'none' }">
        <ArrowDown />
      </el-icon>
    </div>
    <div v-show="open" class="citation-list">
      <div v-for="item in props.citations" :key="`${item.document_id}-${item.chunk_id}`" class="citation-item">
        <div class="citation-index">{{ item.index }}</div>
        <div class="citation-main">
          <div class="citation-title">
            <span>{{ item.title }}</span>
            <span v-if="item.doc_type" class="tag-soft">{{ item.doc_type }}</span>
            <span v-if="item.year" class="tag-soft">{{ item.year }} 年</span>
            <span v-if="item.competition_name" class="tag-soft teal">{{ item.competition_name }}</span>
          </div>
          <div class="citation-meta">
            <span v-if="item.issuing_body">{{ item.issuing_body }}</span>
            <span v-if="item.doc_no">{{ item.doc_no }}</span>
            <span v-if="item.location">{{ item.location }}</span>
          </div>
          <div v-if="item.snippet" class="citation-snippet">{{ item.snippet }}</div>
          <div style="display: flex; gap: 14px; margin-top: 6px; align-items: center">
            <a v-if="item.source_url" class="source-link" :href="item.source_url" target="_blank" rel="noreferrer">
              <el-icon><Link /></el-icon> 官方来源
            </a>
            <button
              v-if="item.document_id"
              class="source-link"
              style="background: none; border: 0; padding: 0; cursor: pointer"
              :disabled="downloading === item.chunk_id"
              @click="downloadSource(item)"
            >
              <el-icon><Download /></el-icon>
              {{ downloading === item.chunk_id ? '下载中…' : '下载原始文件' }}
            </button>
          </div>
        </div>
        <div v-if="item.score" class="citation-score">相关度 {{ Number(item.score).toFixed(3) }}</div>
      </div>
    </div>
  </div>
</template>
