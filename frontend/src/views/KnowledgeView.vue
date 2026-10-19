<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import { can, ensureHealth, ensureOptions, store } from '../store'
import { fmtDateTime, fmtNumber, tagType } from '../utils'
import PageHeader from '../components/PageHeader.vue'
import StatCard from '../components/StatCard.vue'
import EmptyState from '../components/EmptyState.vue'

const route = useRoute()

const stats = ref(null)
const documents = ref([])
const total = ref(0)
const loading = ref(false)
const filters = reactive({ keyword: '', doc_type: '', year: null })
const yearOptions = computed(() => (store.options?.years || []).slice().sort((a, b) => b - a))
const canWrite = computed(() => can('knowledge.write'))

const searching = ref(false)
const searchQuery = ref('')
const searchResults = ref([])
const searchDone = ref(false)

const uploadOpen = ref(false)
const uploading = ref(false)
const fileList = ref([])
const selectedFile = ref(null)
const uploadForm = reactive({
  doc_type: '通知公告',
  year: null,
  competition_id: null,
  issuing_body: '',
  doc_no: '',
  source_url: '',
  tags: ''
})

const detailOpen = ref(false)
const detailLoading = ref(false)
const detail = ref(null)

const reindexing = ref(false)
const busyId = ref(0)

const supported = computed(() => stats.value?.supported_formats || ['.pdf', '.docx', '.xlsx', '.txt', '.md', '.csv'])
const typeStats = computed(() => stats.value?.by_type || [])
const totalChunks = computed(() => stats.value?.chunks || 0)

function fmtSize(bytes) {
  const n = Number(bytes || 0)
  if (!n) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

async function loadStats() {
  try {
    stats.value = await api.knowledgeStats()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function loadDocuments() {
  loading.value = true
  try {
    const data = await api.knowledgeDocuments({
      keyword: filters.keyword,
      doc_type: filters.doc_type,
      year: filters.year || undefined
    })
    documents.value = data.items || []
    total.value = data.total || 0
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

async function refreshAll() {
  await Promise.all([loadStats(), loadDocuments()])
}

function resetFilters() {
  filters.keyword = ''
  filters.doc_type = ''
  filters.year = null
  loadDocuments()
}

async function search() {
  if (!searchQuery.value.trim()) {
    searchResults.value = []
    searchDone.value = false
    return
  }
  searching.value = true
  searchDone.value = false
  try {
    const data = await api.knowledgeSearch(searchQuery.value.trim(), 8)
    searchResults.value = data.items || []
    searchDone.value = true
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    searching.value = false
  }
}

function openUpload() {
  uploadForm.doc_type = '通知公告'
  uploadForm.year = null
  uploadForm.competition_id = null
  uploadForm.issuing_body = ''
  uploadForm.doc_no = ''
  uploadForm.source_url = ''
  uploadForm.tags = ''
  fileList.value = []
  selectedFile.value = null
  uploadOpen.value = true
}

function onFileChange(uploadFile) {
  selectedFile.value = uploadFile.raw
  fileList.value = [uploadFile]
}

function onFileRemove() {
  selectedFile.value = null
  fileList.value = []
}

async function submitUpload() {
  if (!selectedFile.value) {
    ElMessage.warning('请选择要上传的文件')
    return
  }
  const form = new FormData()
  form.append('file', selectedFile.value)
  if (uploadForm.doc_type) form.append('doc_type', uploadForm.doc_type)
  if (uploadForm.year) form.append('year', String(uploadForm.year))
  if (uploadForm.competition_id) form.append('competition_id', String(uploadForm.competition_id))
  if (uploadForm.issuing_body) form.append('issuing_body', uploadForm.issuing_body)
  if (uploadForm.doc_no) form.append('doc_no', uploadForm.doc_no)
  if (uploadForm.source_url) form.append('source_url', uploadForm.source_url)
  if (uploadForm.tags) form.append('tags', uploadForm.tags)

  uploading.value = true
  try {
    const data = await api.knowledgeUpload(form)
    if (data.ok) {
      ElMessage.success(`「${data.title}」已入库，生成 ${data.chunks} 个知识片段`)
      uploadOpen.value = false
      await refreshAll()
      await ensureHealth(true)
    } else {
      ElMessage.error(data.message || '文档入库失败')
    }
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    uploading.value = false
  }
}

async function openDetail(row) {
  detailOpen.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await api.knowledgeDocument(row.id)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    detailLoading.value = false
  }
}

async function download(row, name) {
  const id = row.document_id || row.id
  try {
    await api.knowledgeFile(id, name || row.file_name || row.title || '原始文件')
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function reindexOne(row) {
  busyId.value = row.id
  try {
    const data = await api.knowledgeReindexOne(row.id)
    if (data.ok) ElMessage.success(`「${data.title}」已重建索引，共 ${data.chunks} 个片段`)
    else ElMessage.error(data.message || '重建失败')
    await refreshAll()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    busyId.value = 0
  }
}

async function reindexAll() {
  try {
    await ElMessageBox.confirm('将扫描知识库目录，对新增与变更文件重新解析入库。该操作可能需要一些时间。', '同步知识库目录', {
      confirmButtonText: '开始同步',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  reindexing.value = true
  try {
    const data = await api.knowledgeReindex()
    ElMessage.success(`同步完成：处理 ${data.total} 个文件，成功 ${data.succeeded} 个，跳过 ${data.skipped} 个`)
    await refreshAll()
    await ensureHealth(true)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    reindexing.value = false
  }
}

async function removeDoc(row) {
  try {
    await ElMessageBox.confirm(`确认删除知识文档「${row.title}」及其全部片段？原始文件保留在服务器目录。`, '删除文档', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning'
    })
  } catch {
    return
  }
  busyId.value = row.id
  try {
    await api.knowledgeDelete(row.id)
    ElMessage.success('文档已从知识库删除')
    await refreshAll()
    await ensureHealth(true)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    busyId.value = 0
  }
}

onMounted(async () => {
  await ensureOptions()
  await refreshAll()
  const q = String(route.query.q || '')
  if (q) {
    searchQuery.value = q
    search()
  }
})
</script>

<template>
  <div>
    <PageHeader
      eyebrow="RAG Library"
      title="知识库"
      description="竞赛通知、规程、制度与获奖名单统一解析入库，问答引用可回溯到原文件与具体章节。支持 PDF、Word、Excel、纯文本，新增文件无需改代码。"
    >
      <template #actions>
        <el-tag v-if="!canWrite" type="info" effect="plain">只读权限</el-tag>
        <template v-if="canWrite">
          <el-button :loading="reindexing" @click="reindexAll"><el-icon><Refresh /></el-icon> 同步目录</el-button>
          <el-button type="primary" @click="openUpload"><el-icon><UploadFilled /></el-icon> 上传文档</el-button>
        </template>
      </template>
    </PageHeader>

    <div class="stat-grid" style="margin-bottom: 16px">
      <StatCard label="知识文档" :value="fmtNumber(stats?.documents)" :note="`已入库文档 ${fmtNumber(total)} 份`" icon="Files" tone="ink" />
      <StatCard label="知识片段" :value="fmtNumber(totalChunks)" note="支持向量与 BM25 混合检索" icon="Grid" />
      <StatCard
        label="向量索引"
        :value="stats?.has_vector ? '就绪' : '未建立'"
        :note="`${stats?.vector_dim || 0} 维 · ${stats?.bm25_ready ? 'BM25 就绪' : '关键词索引未就绪'}`"
        icon="Connection"
        tone="gold"
      />
      <StatCard label="入库异常" :value="fmtNumber(stats?.failed)" note="失败文档可在列表中重试" icon="Warning" />
    </div>

    <div class="panel search-panel">
      <div class="search-head">
        <div>
          <div class="section-label">知识检索测试</div>
          <p class="muted small">直接验证混合检索效果，返回结果带原文位置与下载入口，不调用大模型。</p>
        </div>
        <div class="search-box">
          <el-input v-model="searchQuery" placeholder="如：蓝桥杯 报名截止时间 参赛对象" clearable style="width: 420px" @keyup.enter="search">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-button type="primary" :loading="searching" @click="search">检索</el-button>
        </div>
      </div>

      <div v-if="searchResults.length" class="search-results">
        <div v-for="item in searchResults" :key="item.chunk_id" class="search-item">
          <div class="search-item-head">
            <span class="search-index">{{ item.index }}</span>
            <div>
              <div class="search-title">{{ item.title }}</div>
              <div class="search-meta">
                <span v-if="item.doc_type" class="tag-soft">{{ item.doc_type }}</span>
                <span v-if="item.doc_no" class="mono">{{ item.doc_no }}</span>
                <span v-if="item.location">{{ item.location }}</span>
                <span v-if="item.issuing_body">{{ item.issuing_body }}</span>
              </div>
            </div>
            <div class="search-scores">
              <el-tooltip content="综合得分（向量 + 关键词融合）" placement="top">
                <span class="score-pill">{{ Number(item.score || 0).toFixed(3) }}</span>
              </el-tooltip>
              <el-button size="small" text @click="download(item)"><el-icon><Download /></el-icon></el-button>
            </div>
          </div>
          <p class="search-snippet">{{ item.content?.slice(0, 280) }}{{ item.content?.length > 280 ? '…' : '' }}</p>
        </div>
      </div>
      <EmptyState v-else-if="searchDone" title="未检索到相关片段" description="尝试更换关键词，或先上传对应的赛事通知文件。" />
    </div>

    <div class="type-strip">
      <span class="type-label">文档类型分布</span>
      <span v-for="item in typeStats" :key="item.doc_type" class="type-chip">
        {{ item.doc_type }}<strong>{{ item.count }}</strong>
      </span>
      <span class="type-formats">支持格式：{{ supported.join(' / ') }}</span>
    </div>

    <div class="panel docs-panel">
      <div class="panel-head">
        <h3>文档目录</h3>
        <span class="sub">共 {{ total }} 份</span>
        <div class="right">
          <el-input v-model="filters.keyword" clearable placeholder="搜索标题" size="small" style="width: 180px" @keyup.enter="loadDocuments" @clear="loadDocuments" />
          <el-select v-model="filters.doc_type" clearable placeholder="文档类型" size="small" style="width: 130px" @change="loadDocuments">
            <el-option v-for="type in store.options?.doc_types || []" :key="type" :label="type" :value="type" />
          </el-select>
          <el-select v-model="filters.year" clearable placeholder="年度" size="small" style="width: 110px" @change="loadDocuments">
            <el-option v-for="year in yearOptions" :key="year" :label="`${year} 年`" :value="year" />
          </el-select>
          <el-button size="small" :loading="loading" @click="loadDocuments">查询</el-button>
          <el-button size="small" text @click="resetFilters">重置</el-button>
        </div>
      </div>

      <el-table :data="documents" size="small" v-loading="loading" style="width: 100%">
        <el-table-column label="文档" min-width="260">
          <template #default="{ row }">
            <div class="doc-cell">
              <span class="doc-icon"><el-icon><Document /></el-icon></span>
              <div>
                <el-link :underline="false" type="primary" @click="openDetail(row)">{{ row.title }}</el-link>
                <div class="doc-sub">
                  <span v-if="row.doc_type" class="tag-soft">{{ row.doc_type }}</span>
                  <span v-if="row.year">{{ row.year }} 年</span>
                  <span v-if="row.doc_no" class="mono">{{ row.doc_no }}</span>
                </div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="competition_name" label="关联赛事" min-width="150" show-overflow-tooltip />
        <el-table-column prop="issuing_body" label="发文单位" min-width="140" show-overflow-tooltip />
        <el-table-column label="规模" width="130">
          <template #default="{ row }">
            <div class="cell-stack">
              <span>{{ row.chunk_count }} 片段 · {{ fmtNumber(row.char_count) }} 字</span>
              <span class="muted small">{{ fmtSize(row.file_size) }} · {{ row.file_name?.split('.').pop()?.toUpperCase() }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }"><el-tag size="small" :type="tagType(row.status)">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="入库时间" width="140">
          <template #default="{ row }">{{ fmtDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="250" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="openDetail(row)">详情</el-button>
            <el-button size="small" text @click="download(row)">原文</el-button>
            <el-button v-if="canWrite" size="small" text :loading="busyId === row.id" @click="reindexOne(row)">重建</el-button>
            <el-button v-if="canWrite" size="small" text type="danger" :loading="busyId === row.id" @click="removeDoc(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <EmptyState title="知识库暂无文档" description="上传竞赛通知、规程或制度文件，或点击「同步目录」扫描知识库文件夹。" />
        </template>
      </el-table>
    </div>

    <el-dialog v-model="uploadOpen" title="上传知识文档" width="660px">
      <el-upload
        v-model:file-list="fileList"
        drag
        :auto-upload="false"
        :limit="1"
        :on-change="onFileChange"
        :on-remove="onFileRemove"
        :accept="supported.join(',')"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">将文件拖到此处，或<em>点击选择</em></div>
        <template #tip>
          <div class="el-upload__tip">支持 {{ supported.join(' / ') }}，单个文件不超过 50MB。文件名建议包含年度与赛事，如「2026-蓝桥杯-报名通知.pdf」。</div>
        </template>
      </el-upload>

      <div class="form-grid" style="margin-top: 16px">
        <div>
          <label class="field-label">文档类型</label>
          <el-select v-model="uploadForm.doc_type" style="width: 100%">
            <el-option v-for="type in store.options?.doc_types || []" :key="type" :label="type" :value="type" />
          </el-select>
        </div>
        <div>
          <label class="field-label">年度</label>
          <el-select v-model="uploadForm.year" clearable placeholder="年度" style="width: 100%">
            <el-option v-for="year in yearOptions" :key="year" :label="`${year} 年`" :value="year" />
          </el-select>
        </div>
        <div class="span-2">
          <label class="field-label">关联赛事</label>
          <el-select v-model="uploadForm.competition_id" clearable filterable placeholder="可选" style="width: 100%">
            <el-option v-for="comp in store.options?.competitions || []" :key="comp.id" :label="comp.name" :value="comp.id" />
          </el-select>
        </div>
        <div>
          <label class="field-label">发文单位</label>
          <el-input v-model="uploadForm.issuing_body" placeholder="如 教育部高等教育司" />
        </div>
        <div>
          <label class="field-label">文号</label>
          <el-input v-model="uploadForm.doc_no" placeholder="如 教高函〔2026〕1号" />
        </div>
        <div class="span-2">
          <label class="field-label">原文链接</label>
          <el-input v-model="uploadForm.source_url" placeholder="https://" />
        </div>
        <div class="span-2">
          <label class="field-label">标签</label>
          <el-input v-model="uploadForm.tags" placeholder="多个标签用英文逗号分隔，如 报名,省赛" />
        </div>
      </div>
      <template #footer>
        <el-button @click="uploadOpen = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="submitUpload">解析并入库</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="detailOpen" size="720px" :title="detail?.document?.title || '文档详情'">
      <div v-loading="detailLoading">
        <template v-if="detail">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="文档类型">{{ detail.document.doc_type || '—' }}</el-descriptions-item>
            <el-descriptions-item label="年度">{{ detail.document.year || '—' }}</el-descriptions-item>
            <el-descriptions-item label="关联赛事">{{ detail.document.competition_name || '—' }}</el-descriptions-item>
            <el-descriptions-item label="发文单位">{{ detail.document.issuing_body || '—' }}</el-descriptions-item>
            <el-descriptions-item label="文号">{{ detail.document.doc_no || '—' }}</el-descriptions-item>
            <el-descriptions-item label="生效日期">{{ detail.document.effective_date || '—' }}</el-descriptions-item>
            <el-descriptions-item label="文件名">{{ detail.document.file_name }}</el-descriptions-item>
            <el-descriptions-item label="规模">{{ detail.document.chunk_count }} 片段 / {{ fmtNumber(detail.document.char_count) }} 字</el-descriptions-item>
            <el-descriptions-item label="状态">{{ detail.document.status }}</el-descriptions-item>
            <el-descriptions-item label="来源">
              <el-link v-if="detail.document.source_url" :href="detail.document.source_url" target="_blank" type="primary">原文链接</el-link>
              <span v-else>本地上传</span>
            </el-descriptions-item>
          </el-descriptions>
          <div style="margin: 12px 0" class="tag-row">
            <span v-for="tag in detail.document.tags || []" :key="tag" class="tag-soft">{{ tag }}</span>
            <el-button size="small" text type="primary" @click="download(detail.document)"><el-icon><Download /></el-icon> 下载原文</el-button>
          </div>
          <p v-if="detail.document.error_msg" class="error-text">{{ detail.document.error_msg }}</p>

          <div class="result-section-title">知识片段（{{ detail.chunks?.length || 0 }}）</div>
          <el-collapse>
            <el-collapse-item v-for="chunk in detail.chunks" :key="chunk.id" :name="chunk.id">
              <template #title>
                <div class="chunk-title">
                  <span class="tag-soft">#{{ chunk.chunk_index + 1 }}</span>
                  <span>{{ chunk.section || '正文片段' }}</span>
                  <span v-if="chunk.page_no" class="muted small">第 {{ chunk.page_no }} 页</span>
                  <span v-if="chunk.row_ref" class="muted small">{{ chunk.row_ref }}</span>
                  <span class="chunk-vector" :class="{ ok: chunk.has_vector }">{{ chunk.has_vector ? '向量' : '关键词' }}</span>
                </div>
              </template>
              <pre class="chunk-content">{{ chunk.content }}</pre>
            </el-collapse-item>
          </el-collapse>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.search-panel {
  padding: 18px 20px;
  margin-bottom: 14px;
}

.search-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}

.search-head p {
  margin: 4px 0 0;
}

.search-box {
  display: flex;
  gap: 8px;
}

.search-results {
  margin-top: 14px;
  border-top: 1px dashed var(--line);
  padding-top: 8px;
}

.search-item {
  padding: 12px 0;
  border-bottom: 1px dashed var(--line);
}

.search-item:last-child {
  border-bottom: 0;
}

.search-item-head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.search-index {
  width: 22px;
  height: 22px;
  border-radius: 6px;
  background: var(--teal-50);
  color: var(--teal-700);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  flex-shrink: 0;
}

.search-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-800);
}

.search-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 3px;
  font-size: 10.5px;
  color: var(--muted-2);
}

.search-scores {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 4px;
}

.score-pill {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 2px 7px;
  border-radius: 20px;
  background: rgba(196, 146, 50, 0.12);
  color: #9a6b1d;
}

.search-snippet {
  margin: 8px 0 0 32px;
  font-size: 11.5px;
  line-height: 1.8;
  color: var(--text-2);
}

.type-strip {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 14px;
  padding: 9px 14px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: #fff;
}

.type-label {
  font-size: 10px;
  letter-spacing: 0.12em;
  color: var(--muted-2);
}

.type-chip {
  font-size: 10.5px;
  padding: 3px 9px;
  border-radius: 20px;
  background: #f5f9f8;
  color: var(--text-2);
}

.type-chip strong {
  margin-left: 5px;
  color: var(--teal-700);
  font-family: var(--font-mono);
}

.type-formats {
  margin-left: auto;
  font-size: 10px;
  color: var(--muted-2);
}

.docs-panel {
  padding: 0;
  overflow: hidden;
}

.docs-panel .panel-head {
  margin: 0;
  padding: 14px 18px;
}

.docs-panel .right {
  display: flex;
  align-items: center;
  gap: 6px;
}

.doc-cell {
  display: flex;
  align-items: flex-start;
  gap: 9px;
}

.doc-icon {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  background: rgba(15, 159, 147, 0.1);
  color: var(--teal-700);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.doc-sub {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
  margin-top: 2px;
  font-size: 10px;
  color: var(--muted-2);
}

.cell-stack {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 11px;
  color: var(--text-2);
}

.tag-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.chunk-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-1);
}

.chunk-vector {
  margin-left: auto;
  font-size: 9.5px;
  padding: 1px 7px;
  border-radius: 20px;
  background: #f2f4f5;
  color: var(--muted-2);
  font-weight: 400;
}

.chunk-vector.ok {
  background: rgba(15, 159, 147, 0.1);
  color: var(--teal-700);
}

.chunk-content {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-sans);
  font-size: 11.5px;
  line-height: 1.85;
  color: var(--text-2);
  background: #fbfcfc;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
  margin: 0;
  max-height: 340px;
  overflow: auto;
}

.error-text {
  color: #bf4a3f;
  font-size: 11.5px;
}

@media (max-width: 1000px) {
  .search-box {
    width: 100%;
  }
  .search-box .el-input {
    flex: 1;
    width: auto !important;
  }
  .type-formats {
    margin-left: 0;
  }
}
</style>
