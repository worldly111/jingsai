<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { ensureOptions, store } from '../store'
import PageHeader from '../components/PageHeader.vue'
import ResultView from '../components/ResultView.vue'
import CheckList from '../components/CheckList.vue'

const route = useRoute()
const router = useRouter()
const form = reactive({
  material_type: 'application_form',
  competition_name: '',
  text: ''
})
const loading = ref(false)
const uploading = ref(false)
const fileName = ref('')
const result = ref(null)
const resultRef = ref(null)
const fileInput = ref(null)

const materialTypes = [
  { value: 'application_form', label: '项目申报书 / 参赛报名表' },
  { value: 'technical_doc', label: '作品说明书 / 设计文档 / 论文' },
  { value: 'defense_ppt', label: '答辩演示文稿' }
]

const sampleText = `项目名称：智农云——面向设施农业的轻量级病害识别系统
一、项目背景与意义
设施农业病虫害识别高度依赖农技人员经验，基层服务半径大、响应慢。现有通用视觉模型在低算力边缘设备上推理延迟高，且缺少针对本地作物的小样本数据。本项目面向县域合作社，构建可在边缘端运行的轻量级病害识别与预警系统，降低巡检成本，提升处置时效。
二、目标与内容
总体目标：形成一套可复制的设施农业病害识别方案。具体内容包括：（1）构建本地作物病害图像数据集；（2）设计轻量化识别模型；（3）开发移动端巡检应用；（4）在两家合作社开展试点验证。
三、技术方案与路线
采用知识蒸馏与结构化剪枝压缩视觉模型，结合田间图像增强与主动学习降低标注成本；边缘端使用量化推理，移动端通过离线包运行。系统包含图像采集、识别、预警、台账四个模块，数据经统一接口汇入合作社管理后台。
四、创新点与特色
与通用模型相比，本方案在保持识别精度的同时将模型体积压缩到 12MB，可在低端安卓设备离线运行；通过主动学习闭环持续吸收本地样本，解决小样本泛化问题。
五、团队分工
团队共 5 人：两名同学负责数据采集与标注，两名负责模型训练与压缩，一名负责移动端开发；指导教师提供农学知识与试点协调。
六、实施计划与进度安排
2026 年 11 月完成数据采集，12 月完成模型基线，2027 年 2 月完成边缘部署，3 月进入合作社试点。
七、预期成果
形成软件著作权 1 项、试点报告 1 份，识别准确率目标不低于 92%，单次识别延迟低于 300ms。`

const wordCount = computed(() => form.text.trim().length)
const review = computed(() => result.value?.structured?.review)
const sections = computed(() => review.value?.sections || [])
const requiredSections = computed(() => sections.value.filter((s) => s.required))
const foundRequired = computed(() => requiredSections.value.filter((s) => s.found).length)
const questions = computed(() => [...new Set(review.value?.questions || [])])
const score = computed(() => Number(review.value?.score || 0))
const errorCount = computed(() => (result.value?.checks || []).filter((c) => c.level === 'error').length)
const warnCount = computed(() => (result.value?.checks || []).filter((c) => c.level === 'warning').length)

const scoreColor = computed(() => {
  if (score.value >= 80) return '#0f9f93'
  if (score.value >= 60) return '#c49a4d'
  return '#c05a54'
})

const scoreLabel = computed(() => {
  if (score.value >= 85) return '具备竞争力'
  if (score.value >= 70) return '基本成型'
  if (score.value >= 50) return '仍需补强'
  return '待系统完善'
})

function fillSample() {
  form.text = sampleText
  form.material_type = 'application_form'
  fileName.value = ''
}

function triggerUpload() {
  fileInput.value?.click()
}

async function onFileSelected(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    const data = await api.reviewExtract(fd)
    form.text = data.text || ''
    fileName.value = data.file_name || file.name
    ElMessage.success(`已解析 ${file.name}，共 ${data.char_count} 字`)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    uploading.value = false
  }
}

async function submit() {
  if (form.text.trim().length < 20) {
    ElMessage.warning('请粘贴或上传待检查的材料正文（至少 20 字）')
    return
  }
  loading.value = true
  result.value = null
  try {
    const data = await api.runAgent('review', {
      question: `请检查这份${materialTypes.find((t) => t.value === form.material_type)?.label || '项目材料'}`,
      payload: {
        material_type: form.material_type,
        competition_name: form.competition_name,
        text: form.text
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

function sectionStatus(section) {
  if (!section.found) return { label: section.required ? '缺失' : '未包含', type: section.required ? 'danger' : 'info' }
  if (section.length < section.min_length) return { label: '篇幅不足', type: 'warning' }
  return { label: '已覆盖', type: 'success' }
}

function goPrep() {
  router.push({ name: 'prep', query: { competition: form.competition_name } })
}

onMounted(async () => {
  await ensureOptions()
  const comp = String(route.query.competition || '')
  if (comp) form.competition_name = comp
})
</script>

<template>
  <div>
    <PageHeader
      eyebrow="Material Review"
      title="项目指导辅助"
      description="依据可配置的评审量表，对申报书、作品说明和答辩材料做结构完整性、要素覆盖与规范性初检，并生成预答辩问题。"
    >
      <template #actions>
        <el-button @click="router.push('/prep')"><el-icon><Calendar /></el-icon> 回到备赛计划</el-button>
      </template>
    </PageHeader>

    <div class="review-layout">
      <div class="form-card review-form">
        <div class="form-card-head">
          <h3>待检查材料</h3>
          <p>支持直接粘贴文本，或上传 PDF / Word / Markdown 文件。</p>
        </div>
        <div class="form-card-body">
          <div class="form-grid">
            <div>
              <label class="field-label">材料类型<span class="req">*</span></label>
              <el-select v-model="form.material_type" style="width: 100%">
                <el-option v-for="type in materialTypes" :key="type.value" :label="type.label" :value="type.value" />
              </el-select>
            </div>
            <div>
              <label class="field-label">目标赛事</label>
              <el-select
                v-model="form.competition_name"
                filterable
                clearable
                allow-create
                placeholder="可选"
                style="width: 100%"
              >
                <el-option
                  v-for="comp in store.options?.competitions || []"
                  :key="comp.id"
                  :label="comp.name"
                  :value="comp.name"
                />
              </el-select>
            </div>
          </div>

          <div class="editor-label">
            <label class="field-label" style="margin: 0">材料正文<span class="req">*</span></label>
            <span class="editor-count">{{ wordCount }} 字</span>
          </div>
          <el-input
            v-model="form.text"
            type="textarea"
            :rows="17"
            resize="vertical"
            placeholder="粘贴项目申报书、作品说明书或答辩稿正文…"
          />
          <div class="editor-toolbar">
            <input ref="fileInput" type="file" accept=".pdf,.docx,.doc,.txt,.md,.markdown" hidden @change="onFileSelected" />
            <el-button size="small" :loading="uploading" @click="triggerUpload">
              <el-icon><Upload /></el-icon> 上传文件解析
            </el-button>
            <el-button size="small" text @click="fillSample"><el-icon><DocumentAdd /></el-icon> 填入示例</el-button>
            <span v-if="fileName" class="file-chip"><el-icon><Paperclip /></el-icon>{{ fileName }}</span>
            <span v-else class="hint">支持 PDF / Word / TXT / Markdown，单文件不超过 50MB</span>
          </div>

          <div class="form-actions">
            <el-button type="primary" style="flex: 1" :loading="loading" @click="submit">
              <el-icon v-if="!loading"><DocumentChecked /></el-icon>
              {{ loading ? '正在初检' : '开始材料初检' }}
            </el-button>
          </div>
          <div class="form-note">
            <el-icon><Lock /></el-icon>
            初检结果用于发现问题，不替代指导教师复核；评分量表位于 data/rules/review_rubrics.yaml。
          </div>
        </div>
      </div>

      <div ref="resultRef" class="review-result">
        <template v-if="!result">
          <div class="panel preview-panel">
            <div class="preview-icon"><el-icon><DocumentChecked /></el-icon></div>
            <h2>让问题在提交之前被发现</h2>
            <p>
              初检会核对章节是否齐全、篇幅是否支撑评审、创新与可行性等要素是否出现，
              并针对缺失项生成评委可能追问的问题。
            </p>
            <div class="preview-checklist">
              <div><el-icon><Check /></el-icon> 章节完整性：必需 / 建议章节逐项核对</div>
              <div><el-icon><Check /></el-icon> 要素覆盖：创新性、可行性、量化指标、推广价值</div>
              <div><el-icon><Check /></el-icon> 规范性：占位符、匿名要求、学校信息暴露</div>
              <div><el-icon><Check /></el-icon> 预答辩：按缺失项生成针对性问题</div>
            </div>
            <div class="preview-note">当前为规则初检通道，可在项目中接入大模型获得更细致的表达建议。</div>
          </div>
        </template>

        <template v-else>
          <div class="score-banner panel">
            <div class="score-ring-lg" :style="{ '--score': `${score}%`, '--ring': scoreColor }">
              <div class="score-inner-lg">
                <strong>{{ score.toFixed(1) }}</strong>
                <span>/ 100</span>
              </div>
            </div>
            <div class="score-main">
              <div class="score-head">
                <span class="tag-soft teal">{{ review?.material_label }}</span>
                <span class="score-label" :style="{ color: scoreColor }">{{ scoreLabel }}</span>
              </div>
              <h2>材料初检完成</h2>
              <div class="score-meta">
                <span>正文 {{ review?.word_count ?? wordCount }} 字</span>
                <span>必需章节 {{ foundRequired }} / {{ requiredSections.length }}</span>
                <span class="error-text">{{ errorCount }} 项严重问题</span>
                <span class="warn-text">{{ warnCount }} 项待改进</span>
              </div>
            </div>
            <div class="score-actions">
              <el-button size="small" @click="goPrep">配套备赛计划</el-button>
            </div>
          </div>

          <div class="panel">
            <div class="panel-head">
              <h3>章节完整性</h3>
              <span class="sub">{{ sections.length }} 个检查项</span>
            </div>
            <div class="section-check-list">
              <div v-for="section in sections" :key="section.key" class="section-check-row">
                <div class="section-status" :class="sectionStatus(section).type">
                  <el-icon>
                    <CircleCheckFilled v-if="sectionStatus(section).type === 'success'" />
                    <WarningFilled v-else-if="sectionStatus(section).type === 'warning'" />
                    <CircleCloseFilled v-else />
                  </el-icon>
                </div>
                <div class="section-main">
                  <div class="section-name">
                    {{ section.name }}
                    <span v-if="section.required" class="required-dot">必需</span>
                  </div>
                  <div class="section-detail">
                    {{ section.found ? `已识别约 ${section.length} 字` : '未识别到对应章节' }}
                    · 建议不少于 {{ section.min_length }} 字
                  </div>
                  <div v-if="!section.found || section.length < section.min_length" class="section-advice">
                    {{ section.advice }}
                  </div>
                </div>
                <el-tag size="small" :type="sectionStatus(section).type" effect="plain">
                  {{ sectionStatus(section).label }}
                </el-tag>
              </div>
            </div>
          </div>

          <div class="panel checks-panel">
            <div class="panel-head">
              <h3>问题与修改建议</h3>
              <span class="sub">按严重程度排序</span>
            </div>
            <div style="padding: 16px 20px">
              <CheckList :checks="result.checks" />
            </div>
          </div>

          <div v-if="questions.length" class="panel questions-panel">
            <div class="panel-head">
              <h3>预答辩问题</h3>
              <span class="sub">依据缺失要素自动生成</span>
            </div>
            <div class="question-list">
              <div v-for="(question, index) in questions" :key="question" class="question-row">
                <span class="question-index">Q{{ index + 1 }}</span>
                <span>{{ question }}</span>
              </div>
            </div>
          </div>

          <div v-if="review?.highlights?.length" class="panel highlight-panel">
            <div class="panel-head"><h3>材料亮点</h3></div>
            <div class="highlight-list">
              <div v-for="item in review.highlights" :key="item" class="highlight-row">
                <el-icon color="#2f8f67"><StarFilled /></el-icon>
                <span>{{ item }}</span>
              </div>
            </div>
          </div>

          <div class="panel result-panel">
            <ResultView
              :result="result"
              title="完整初检报告"
              :show-tables="false"
              :show-checks="false"
              :show-suggestions="false"
              :show-charts="false"
            />
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.review-layout {
  display: grid;
  grid-template-columns: minmax(380px, 0.9fr) minmax(0, 1.1fr);
  gap: 20px;
  align-items: start;
}

.review-form {
  position: sticky;
  top: 92px;
}

.editor-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 15px 0 6px;
}

.editor-count {
  font-size: 10px;
  color: var(--muted-2);
  font-family: monospace;
}

.review-form :deep(.el-textarea__inner) {
  font-size: 12px;
  line-height: 1.8;
  color: #364c57;
  background: #fdfefe;
}

.editor-toolbar {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 8px;
  flex-wrap: wrap;
  min-height: 28px;
}

.editor-toolbar .hint {
  font-size: 9.5px;
  color: var(--muted-2);
}

.file-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 9.5px;
  color: var(--teal-dark);
  background: var(--teal-soft);
  border: 1px solid #cfebe7;
  border-radius: 4px;
  padding: 2px 7px;
  max-width: 210px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.form-note {
  display: flex;
  gap: 6px;
  align-items: flex-start;
  margin-top: 11px;
  font-size: 9.5px;
  color: var(--muted-2);
  line-height: 1.6;
}

.preview-panel {
  padding: 34px 32px;
  background:
    radial-gradient(420px 260px at 100% 0%, rgba(15, 159, 147, 0.07), transparent 65%),
    var(--surface);
}

.preview-icon {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  background: linear-gradient(145deg, #0f8f84, #0c5e68);
  color: #e8fffb;
  display: grid;
  place-items: center;
  font-size: 22px;
  margin-bottom: 17px;
  box-shadow: 0 10px 26px rgba(13, 148, 136, 0.2);
}

.preview-panel h2 {
  font-family: var(--font-display);
  font-size: 24px;
  color: var(--ink);
}

.preview-panel > p {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.85;
  max-width: 560px;
  margin-top: 9px;
}

.preview-checklist {
  margin-top: 24px;
  display: grid;
  gap: 10px;
}

.preview-checklist div {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 11.5px;
  color: #48616b;
  padding: 10px 13px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fdfefe;
}

.preview-checklist .el-icon {
  color: var(--teal-dark);
  flex-shrink: 0;
}

.preview-note {
  margin-top: 22px;
  padding-top: 14px;
  border-top: 1px dashed var(--line);
  font-size: 10px;
  color: var(--muted-2);
}

.review-result {
  display: grid;
  gap: 14px;
  min-width: 0;
}

.score-banner {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 20px 24px;
  background:
    radial-gradient(360px 180px at 100% 0%, rgba(15, 159, 147, 0.055), transparent 70%),
    var(--surface);
}

.score-ring-lg {
  width: 86px;
  height: 86px;
  border-radius: 50%;
  flex-shrink: 0;
  background: conic-gradient(var(--ring) var(--score), #edf2f3 0);
  display: grid;
  place-items: center;
  position: relative;
}

.score-ring-lg::before {
  content: '';
  position: absolute;
  inset: 6px;
  background: #fff;
  border-radius: 50%;
}

.score-inner-lg {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  line-height: 1.15;
}

.score-inner-lg strong {
  font-family: var(--font-display);
  font-size: 24px;
  font-weight: 700;
  color: var(--ink);
}

.score-inner-lg span {
  font-size: 9px;
  color: var(--muted-2);
}

.score-main {
  min-width: 0;
  flex: 1;
}

.score-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.score-label {
  font-size: 10px;
  font-weight: 650;
  letter-spacing: 0.04em;
}

.score-main h2 {
  font-family: var(--font-display);
  font-size: 20px;
  color: var(--ink);
  margin: 7px 0 5px;
}

.score-meta {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 10.5px;
  color: var(--muted-2);
}

.error-text {
  color: #b8544e;
}
.warn-text {
  color: #a9782f;
}

.section-check-list {
  padding: 4px 0;
}

.section-check-row {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  padding: 11px 20px;
  border-bottom: 1px solid #f0f3f4;
}

.section-check-row:last-child {
  border-bottom: 0;
}

.section-status {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  flex-shrink: 0;
  display: grid;
  place-items: center;
  margin-top: 1px;
  font-size: 13px;
}

.section-status.success {
  color: #2f8f67;
  background: #eff8f3;
}
.section-status.warning {
  color: #b07a2e;
  background: #fcf7ed;
}
.section-status.danger {
  color: #bf5751;
  background: #fcf2f1;
}
.section-status.info {
  color: #8497a0;
  background: #f3f6f7;
}

.section-main {
  min-width: 0;
  flex: 1;
}

.section-name {
  font-size: 12px;
  font-weight: 600;
  color: #35505a;
  display: flex;
  align-items: center;
  gap: 7px;
}

.required-dot {
  font-size: 8.5px;
  color: #a47134;
  background: #faf3e4;
  border-radius: 3px;
  padding: 0 4px;
  line-height: 1.5;
}

.section-detail {
  font-size: 10.5px;
  color: var(--muted-2);
  margin-top: 2px;
}

.section-advice {
  font-size: 10.5px;
  color: #7a6a4c;
  background: #fdfbf6;
  border-left: 2px solid #e7d7b5;
  padding: 4px 8px;
  margin-top: 5px;
  border-radius: 0 4px 4px 0;
  line-height: 1.6;
}

.question-list {
  padding: 4px 0;
}

.question-row {
  display: flex;
  gap: 11px;
  align-items: flex-start;
  padding: 11px 20px;
  border-bottom: 1px dashed #edf2f3;
  font-size: 11.5px;
  color: #4b616b;
  line-height: 1.75;
}

.question-row:last-child {
  border-bottom: 0;
}

.question-index {
  flex-shrink: 0;
  font-family: var(--font-display);
  font-size: 11px;
  font-weight: 700;
  color: var(--teal-dark);
  background: var(--teal-soft);
  border-radius: 4px;
  padding: 1px 6px;
  margin-top: 1px;
}

.highlight-list {
  padding: 10px 20px 14px;
}

.highlight-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  font-size: 11.5px;
  color: #4b616b;
  padding: 5px 0;
}

.result-panel {
  padding: 22px 24px;
}

@media (max-width: 1200px) {
  .review-layout {
    grid-template-columns: 1fr;
  }
  .review-form {
    position: static;
  }
}

@media (max-width: 720px) {
  .score-banner {
    padding: 16px;
    gap: 14px;
    flex-wrap: wrap;
  }
  .score-ring-lg {
    width: 70px;
    height: 70px;
  }
  .score-inner-lg strong {
    font-size: 20px;
  }
}
</style>
