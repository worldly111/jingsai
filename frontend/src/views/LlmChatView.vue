<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { store } from '../store'
import { fmtDateTime } from '../utils'
import PageHeader from '../components/PageHeader.vue'
import MarkdownView from '../components/MarkdownView.vue'

const MODEL_KEY = 'ci.chatModel'
const router = useRouter()

const catalog = ref(null)
const models = ref([])
const modelId = ref('')
const loadingModels = ref(false)
const loadError = ref('')
const messages = ref([])
const input = ref('')
const sending = ref(false)
const scrollBox = ref(null)
let sendSeq = 0

const suggestions = [
  '用通俗语言解释 Transformer 的注意力机制',
  '帮我润色一段课程项目简介，让表达更简洁',
  '用 Python 实现二分查找，并分析时间复杂度',
  '给我一份为期四周的通用算法学习计划'
]

const selectedModel = computed(
  () => models.value.find((item) => item.id === modelId.value) || null
)
const canSend = computed(
  () => Boolean(input.value.trim()) && !sending.value && Boolean(selectedModel.value?.available)
)
const headerModel = computed(() =>
  selectedModel.value
    ? `${selectedModel.value.provider_label} · ${selectedModel.value.model}`
    : '未选择模型'
)
const placeholder = computed(() =>
  selectedModel.value?.available
    ? '输入通用问题，例如：解释一下快速排序的平均时间复杂度'
    : '暂无可用的模型，请先在模型面板完成配置'
)
const modelPlaceholder = computed(() =>
  catalog.value?.available_count ? '选择模型' : '暂无可用模型'
)
const limits = computed(() => catalog.value?.limits || { max_messages: 20, max_chars: 16000 })

watch(modelId, (value) => {
  if (!value) return
  try {
    localStorage.setItem(MODEL_KEY, value)
  } catch {
    /* localStorage 不可用时不影响使用 */
  }
})

async function loadModels() {
  loadingModels.value = true
  loadError.value = ''
  try {
    const data = await api.llmModels()
    catalog.value = data
    models.value = data.items || []
    let saved = ''
    try {
      saved = localStorage.getItem(MODEL_KEY) || ''
    } catch {
      saved = ''
    }
    const savedModel = models.value.find((item) => item.id === saved && item.available)
    const fallback = models.value.find((item) => item.available) || null
    modelId.value = (savedModel || fallback)?.id || ''
  } catch (error) {
    loadError.value = error.message
  } finally {
    loadingModels.value = false
  }
}

async function refreshModels() {
  await loadModels()
  if (loadError.value) {
    ElMessage.error(loadError.value)
  } else {
    const count = catalog.value?.available_count || 0
    ElMessage.success(count ? `已检测到 ${count} 个可用模型` : '暂未检测到可用模型')
  }
}

async function scrollToBottom() {
  await nextTick()
  if (scrollBox.value) scrollBox.value.scrollTop = scrollBox.value.scrollHeight
}

function trimHistory(history) {
  const maxMessages = Number(limits.value.max_messages) || 20
  const maxChars = Number(limits.value.max_chars) || 16000
  while (history.length > maxMessages) history.shift()
  let chars = history.reduce((sum, item) => sum + item.content.length, 0)
  while (chars > maxChars && history.length > 1) {
    chars -= history[0].content.length
    history.shift()
  }
  return history
}

async function send(text) {
  const content = String(text ?? input.value).trim()
  if (!content || sending.value) return
  const model = selectedModel.value
  if (!model?.available) {
    ElMessage.warning(model?.reason || '请先在左侧选择可用模型')
    return
  }
  const seq = ++sendSeq
  const history = messages.value
    .filter((item) => !item.error)
    .map((item) => ({ role: item.role, content: item.content }))
  history.push({ role: 'user', content })
  trimHistory(history)

  messages.value.push({ role: 'user', content, created_at: new Date().toISOString() })
  input.value = ''
  sending.value = true
  await scrollToBottom()

  try {
    const result = await api.llmChat({ model: model.id, messages: history })
    if (seq !== sendSeq) return
    messages.value.push({
      role: 'assistant',
      content: result.answer,
      provider_label: result.provider_label,
      model: result.model,
      latency_ms: result.latency_ms,
      usage: result.usage || {},
      created_at: new Date().toISOString()
    })
  } catch (error) {
    if (seq !== sendSeq) return
    messages.value.push({
      role: 'assistant',
      content: `本次调用未完成：${error.message}`,
      error: true,
      provider_label: model.provider_label,
      created_at: new Date().toISOString()
    })
  } finally {
    if (seq === sendSeq) {
      sending.value = false
      await scrollToBottom()
    }
  }
}

function clearChat() {
  sendSeq += 1
  sending.value = false
  messages.value = []
  input.value = ''
}

function onKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    send()
  }
}

async function copyAnswer(message) {
  try {
    await navigator.clipboard.writeText(message.content)
    ElMessage.success('回答已复制')
  } catch {
    ElMessage.error('复制失败，请手动选择文本')
  }
}

onMounted(loadModels)
</script>

<template>
  <div>
    <PageHeader
      eyebrow="General Chat"
      title="通用模型问答"
      description="面向所有使用者的通用大模型对话。可自主切换已配置的模型，回答不检索本系统知识库与台账；涉及竞赛政策与业务数据时，请使用竞赛知识问答或对应业务页面核验。"
    >
      <template #actions>
        <el-button :disabled="!messages.length" @click="clearChat">
          <el-icon><Delete /></el-icon> 清空对话
        </el-button>
        <el-button type="primary" plain @click="router.push('/qa')">
          <el-icon><Collection /></el-icon> 竞赛知识问答
        </el-button>
      </template>
    </PageHeader>

    <div class="scope-banner">
      <el-icon><Warning /></el-icon>
      <div>
        <strong>通用对话不等于业务结论。</strong>
        本页不读取台账、不生成引用；报名时间、费用标准、获奖统计等事实请以
        <router-link to="/qa">竞赛知识问答</router-link>
        或对应业务页面为准。
      </div>
    </div>

    <div class="llm-layout">
      <aside class="model-panel">
        <div class="panel-head">
          <div>
            <h3>选择模型</h3>
            <span>{{ catalog?.available_count || 0 }} 个可用 / {{ models.length }} 个已登记</span>
          </div>
          <el-button
            text
            circle
            size="small"
            :loading="loadingModels"
            title="重新检测模型状态"
            @click="refreshModels"
          >
            <el-icon v-if="!loadingModels"><Refresh /></el-icon>
          </el-button>
        </div>

        <div v-loading="loadingModels" class="model-select-wrap">
          <el-select
            v-model="modelId"
            class="model-select"
            :placeholder="modelPlaceholder"
            :disabled="!models.length"
          >
            <el-option
              v-for="item in models"
              :key="item.id"
              :value="item.id"
              :label="`${item.provider_label} · ${item.model}`"
              :disabled="!item.available"
            >
              <div class="model-option">
                <div class="model-option-main">
                  <span class="model-option-label">{{ item.provider_label }}</span>
                  <span class="model-option-id">{{ item.model }}</span>
                </div>
                <span class="model-state" :class="{ ok: item.available }">
                  {{ item.available ? '可用' : '未配置' }}
                </span>
              </div>
            </el-option>
          </el-select>
          <div v-if="loadError" class="load-error">{{ loadError }}</div>
        </div>

        <div
          v-if="selectedModel"
          class="model-card"
          :class="{ muted: !selectedModel.available }"
        >
          <div class="model-card-head">
            <strong>{{ selectedModel.provider_label }}</strong>
            <span class="tag-soft" :class="selectedModel.available ? 'teal' : 'gold'">
              {{ selectedModel.available ? '可用' : '未配置' }}
            </span>
          </div>
          <div class="model-card-id">{{ selectedModel.model }}</div>
          <p>{{ selectedModel.description }}</p>
          <div v-if="!selectedModel.available" class="model-reason">
            <el-icon><Warning /></el-icon>
            {{ selectedModel.reason }}
          </div>
        </div>

        <div v-if="catalog && !catalog.available_count" class="setup-box">
          <div class="setup-title">尚未配置可用模型</div>
          <p>{{ catalog.setup_hint }}</p>
          <div class="env-list">
            <code>DEEPSEEK_API_KEY</code>
            <code>QWEN_API_KEY</code>
            <code>DOUBAO_API_KEY</code>
          </div>
          <p class="setup-note">
            本地或自建端点：设置 <code>LLM_PROVIDER=openai_compatible</code>、
            <code>LLM_BASE_URL</code>、<code>LLM_MODEL</code>。密钥只保存在后端，不会发送到浏览器。
          </p>
        </div>

        <div class="panel-divider" />

        <div class="scope-list">
          <div class="scope-title"><el-icon><CircleCheck /></el-icon> 适合</div>
          <ul>
            <li>通用知识、概念解释与学习规划</li>
            <li>文字润色、摘要与翻译</li>
            <li>代码示例、报错解释与思路讨论</li>
          </ul>
          <div class="scope-title caution"><el-icon><Warning /></el-icon> 不作为依据</div>
          <ul>
            <li>本校竞赛报名时间、材料与资格</li>
            <li>费用标准、预算与审批状态</li>
            <li>获奖统计、排名与工作量认定</li>
          </ul>
        </div>

        <div class="panel-foot">
          <span>对话仅保留在当前页面，刷新后清空</span>
          <span>{{ limits.max_messages }} 条 / {{ limits.max_chars }} 字符上限</span>
        </div>
      </aside>

      <section class="chat-panel">
        <div class="chat-head">
          <div class="chat-avatar"><el-icon><Cpu /></el-icon></div>
          <div class="chat-head-text">
            <div class="chat-title">通用模型对话</div>
            <div class="chat-sub">
              {{ headerModel }}
              <span class="tag-soft" style="margin-left: 6px">通用</span>
            </div>
          </div>
          <div class="chat-head-right">
            <span class="model-status" :class="{ ok: selectedModel?.available }">
              <span class="dot" />
              {{ selectedModel?.available ? '就绪' : '未就绪' }}
            </span>
          </div>
        </div>

        <div ref="scrollBox" class="chat-scroll">
          <div v-if="!messages.length" class="chat-welcome">
            <div class="welcome-mark"><el-icon><Cpu /></el-icon></div>
            <h2>通用问题，<br />交给所选模型。</h2>
            <p>
              这是一个直接调用大模型的通用对话窗口，不会读取本系统台账，也不会生成引用。
              需要可追溯的竞赛答案时，请使用竞赛知识问答。
            </p>
            <div class="suggestion-grid">
              <button
                v-for="item in suggestions"
                :key="item"
                class="suggestion"
                :disabled="!selectedModel?.available"
                @click="send(item)"
              >
                <el-icon><ArrowUpRight /></el-icon>
                <span>{{ item }}</span>
              </button>
            </div>
          </div>

          <div
            v-for="(message, index) in messages"
            :key="index"
            class="message"
            :class="message.role"
          >
            <template v-if="message.role === 'user'">
              <div class="user-bubble">{{ message.content }}</div>
              <div class="user-avatar">
                {{ store.role === '学生' ? '学' : store.role === '教师' ? '师' : '管' }}
              </div>
            </template>

            <template v-else>
              <div class="bot-avatar" :class="{ error: message.error }">
                <el-icon><Cpu /></el-icon>
              </div>
              <div class="bot-body">
                <div class="bot-name">
                  {{ message.provider_label || '大模型' }}
                  <span v-if="message.model" class="model-chip">{{ message.model }}</span>
                  <span v-if="message.error" class="tag-soft warn">调用失败</span>
                </div>
                <div v-if="message.error" class="bot-error">{{ message.content }}</div>
                <div v-else class="bot-answer">
                  <MarkdownView :content="message.content" />
                </div>
                <div class="bot-actions">
                  <el-button v-if="!message.error" text size="small" @click="copyAnswer(message)">
                    <el-icon><CopyDocument /></el-icon> 复制
                  </el-button>
                  <span class="bot-meta">
                    <span v-if="message.latency_ms">{{ message.latency_ms }} ms</span>
                    <span v-if="message.usage?.total_tokens">
                      {{ message.usage.total_tokens }} tokens
                    </span>
                    <span>{{ fmtDateTime(message.created_at) }}</span>
                  </span>
                </div>
              </div>
            </template>
          </div>

          <div v-if="sending" class="message assistant">
            <div class="bot-avatar"><el-icon><Cpu /></el-icon></div>
            <div class="bot-body">
              <div class="typing"><span /><span /><span /></div>
              <div class="typing-text">正在调用 {{ selectedModel?.provider_label || '大模型' }}…</div>
            </div>
          </div>
        </div>

        <div class="composer">
          <div class="composer-box">
            <el-input
              v-model="input"
              type="textarea"
              :rows="2"
              resize="none"
              maxlength="4000"
              :placeholder="placeholder"
              @keydown="onKeydown"
            />
            <div class="composer-bar">
              <span class="composer-hint">Enter 发送 · Shift + Enter 换行</span>
              <el-button type="primary" :loading="sending" :disabled="!canSend" @click="send()">
                <el-icon v-if="!sending"><Promotion /></el-icon>
                {{ sending ? '生成中' : '发送' }}
              </el-button>
            </div>
          </div>
          <div class="composer-tip">
            <el-icon><CircleInfo /></el-icon>
            {{ catalog?.disclaimer || '本页回答由大模型直接生成，不检索知识库与台账，不作为业务事实依据。' }}
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.scope-banner {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 11px 15px;
  margin-bottom: 14px;
  border: 1px solid #eadfc8;
  border-radius: 10px;
  background: linear-gradient(120deg, #fdfaf2, #fcfdfb);
  color: #6f603f;
  font-size: 11.5px;
  line-height: 1.7;
}

.scope-banner > .el-icon {
  margin-top: 2px;
  color: #b58536;
  flex-shrink: 0;
}

.scope-banner strong {
  color: #5d4a26;
  margin-right: 4px;
}

.scope-banner a {
  color: var(--teal-dark);
  font-weight: 600;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.llm-layout {
  display: grid;
  grid-template-columns: 286px minmax(0, 1fr);
  gap: 18px;
  height: calc(100vh - 258px);
  min-height: 600px;
}

.model-panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow-y: auto;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 16px 11px;
}

.panel-head h3 {
  font-size: 13px;
  font-weight: 650;
  color: var(--ink);
}

.panel-head span {
  font-size: 10px;
  color: var(--muted-2);
}

.model-select-wrap {
  padding: 0 16px;
}

.model-select {
  width: 100%;
}

.model-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
}

.model-option-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.35;
}

.model-option-label {
  font-size: 12px;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.model-option-id {
  font-size: 9.5px;
  color: var(--muted-2);
  font-family: 'SFMono-Regular', Consolas, monospace;
}

.model-state {
  font-size: 9.5px;
  color: #a58a57;
  background: #fbf6ea;
  border-radius: 4px;
  padding: 1px 6px;
  flex-shrink: 0;
}

.model-state.ok {
  color: var(--teal-dark);
  background: var(--teal-soft);
}

.load-error {
  margin-top: 8px;
  font-size: 10.5px;
  color: var(--danger);
  line-height: 1.6;
}

.model-card {
  margin: 13px 16px 0;
  padding: 12px 13px;
  border: 1px solid #d7ebe7;
  border-radius: 9px;
  background: linear-gradient(145deg, #f7fcfb, #fbfdfd);
}

.model-card.muted {
  border-color: #eadfc8;
  background: #fdfaf3;
}

.model-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.model-card-head strong {
  font-size: 12px;
  color: var(--ink);
}

.model-card-id {
  margin-top: 5px;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 10px;
  color: var(--teal-dark);
  word-break: break-all;
}

.model-card p {
  margin-top: 7px;
  font-size: 10.5px;
  line-height: 1.7;
  color: var(--muted);
}

.model-reason {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #e8dcc3;
  font-size: 10px;
  line-height: 1.6;
  color: #9a7432;
}

.setup-box {
  margin: 13px 16px 0;
  padding: 12px 13px;
  border: 1px solid #e3e9ec;
  border-radius: 9px;
  background: #f8fafb;
}

.setup-title {
  font-size: 11.5px;
  font-weight: 650;
  color: #5c707a;
}

.setup-box p {
  margin-top: 7px;
  font-size: 10.5px;
  line-height: 1.7;
  color: var(--muted);
}

.setup-note code,
.setup-box p code {
  font-size: 9.5px;
  background: #eef3f4;
  padding: 1px 4px;
  border-radius: 3px;
  color: #3f5b66;
}

.env-list {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 8px;
}

.env-list code {
  font-size: 9.5px;
  padding: 2px 6px;
  border-radius: 4px;
  background: #eef3f4;
  color: #3f5b66;
}

.panel-divider {
  height: 1px;
  margin: 15px 16px 0;
  background: var(--line);
}

.scope-list {
  padding: 13px 16px 0;
}

.scope-title {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 10.5px;
  font-weight: 650;
  color: var(--teal-dark);
}

.scope-title.caution {
  margin-top: 13px;
  color: #9a7432;
}

.scope-list ul {
  margin: 5px 0 0;
  padding-left: 17px;
}

.scope-list li {
  font-size: 10px;
  line-height: 1.85;
  color: var(--muted);
}

.panel-foot {
  margin-top: auto;
  padding: 13px 16px 15px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 9px;
  color: #a3b0b6;
}

.chat-panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.chat-head {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 13px 18px;
  border-bottom: 1px solid var(--line);
  background: #fcfdfd;
  flex-shrink: 0;
}

.chat-avatar {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  background: linear-gradient(140deg, #1d6f86, #0c3b50);
  color: #e7faff;
  display: grid;
  place-items: center;
  font-size: 15px;
}

.chat-head-text {
  min-width: 0;
}

.chat-title {
  font-size: 13px;
  font-weight: 650;
  color: var(--ink);
}

.chat-sub {
  font-size: 10px;
  color: var(--muted-2);
  display: flex;
  align-items: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chat-head-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 6px;
}

.model-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 9px;
  border-radius: 20px;
  border: 1px solid var(--line);
  background: #fff;
  font-size: 10px;
  color: var(--muted);
  white-space: nowrap;
}

.model-status .dot {
  background: #c7a45e;
  box-shadow: 0 0 0 3px rgba(199, 164, 94, 0.13);
}

.model-status.ok .dot {
  background: #37a97c;
  box-shadow: 0 0 0 3px rgba(55, 169, 124, 0.13);
}

.chat-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 24px 26px 10px;
  min-height: 0;
  background:
    radial-gradient(600px 300px at 100% 0%, rgba(30, 111, 134, 0.04), transparent 60%),
    #fdfefe;
}

.chat-welcome {
  max-width: 700px;
  margin: 18px auto 30px;
  text-align: center;
}

.welcome-mark {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  margin: 0 auto 16px;
  background: linear-gradient(145deg, #1d6f86, #0b3a4f);
  color: #e9fbff;
  font-size: 22px;
  box-shadow: 0 12px 28px rgba(22, 94, 116, 0.22);
}

.chat-welcome h2 {
  font-family: var(--font-display);
  font-size: 25px;
  line-height: 1.5;
  color: var(--ink);
  letter-spacing: 0.02em;
}

.chat-welcome p {
  max-width: 540px;
  margin: 10px auto 0;
  font-size: 12px;
  line-height: 1.8;
  color: var(--muted);
}

.suggestion-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 24px;
  text-align: left;
}

.suggestion {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: #fff;
  color: #4d626c;
  font-size: 11.5px;
  line-height: 1.6;
  cursor: pointer;
  font-family: inherit;
  transition: all 0.15s ease;
}

.suggestion:hover:not(:disabled) {
  border-color: #b9dfda;
  background: #f8fcfb;
  color: var(--teal-dark);
  transform: translateY(-1px);
}

.suggestion:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.suggestion .el-icon {
  flex-shrink: 0;
  margin-top: 2px;
  color: #92aaa9;
}

.message {
  display: flex;
  gap: 10px;
  margin-bottom: 22px;
  max-width: 900px;
}

.message.user {
  justify-content: flex-end;
  margin-left: auto;
}

.user-bubble {
  max-width: 74%;
  padding: 10px 15px;
  border-radius: 12px 3px 12px 12px;
  background: linear-gradient(135deg, #123f52, #0d2f40);
  color: #e9f5f5;
  font-size: 12.5px;
  line-height: 1.75;
  white-space: pre-wrap;
  box-shadow: 0 5px 16px rgba(10, 43, 56, 0.12);
}

.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  flex-shrink: 0;
  background: #e9f1f2;
  color: #5a727e;
  display: grid;
  place-items: center;
  font-size: 11px;
  font-weight: 650;
  font-family: var(--font-display);
}

.bot-avatar {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  flex-shrink: 0;
  background: #e8f3f7;
  border: 1px solid #cfe4ec;
  color: #17617a;
  display: grid;
  place-items: center;
  font-size: 13px;
}

.bot-avatar.error {
  background: #fdf3f2;
  border-color: #efd9d6;
  color: #a35a52;
}

.bot-body {
  min-width: 0;
  flex: 1;
}

.bot-name {
  font-size: 11px;
  font-weight: 650;
  color: #4c636e;
  margin-bottom: 7px;
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}

.model-chip {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 9px;
  font-weight: 400;
  color: #71858e;
  background: #f1f5f6;
  border-radius: 4px;
  padding: 1px 5px;
}

.bot-answer {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 4px 12px 12px 12px;
  padding: 15px 18px;
  box-shadow: 0 2px 8px rgba(15, 40, 50, 0.025);
}

.bot-error {
  background: #fdf6f5;
  border: 1px solid #f0d9d6;
  color: #9e4c47;
  border-radius: 10px;
  padding: 12px 15px;
  font-size: 12px;
  line-height: 1.7;
}

.bot-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}

.bot-meta {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 9.5px;
  color: #a3b0b6;
}

.typing {
  display: flex;
  gap: 4px;
  padding: 13px 16px;
  background: #f1f7f9;
  border-radius: 4px 12px 12px 12px;
  width: 58px;
}

.typing span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #6b9db0;
  animation: bounce 1.2s infinite;
}

.typing span:nth-child(2) {
  animation-delay: 0.15s;
}
.typing span:nth-child(3) {
  animation-delay: 0.3s;
}

.typing-text {
  font-size: 10px;
  color: var(--muted-2);
  margin-top: 6px;
}

@keyframes bounce {
  0%,
  60%,
  100% {
    transform: translateY(0);
    opacity: 0.5;
  }
  30% {
    transform: translateY(-3px);
    opacity: 1;
  }
}

.composer {
  border-top: 1px solid var(--line);
  padding: 12px 18px 13px;
  background: #fff;
  flex-shrink: 0;
}

.composer-box {
  border: 1px solid #dce6e9;
  border-radius: 10px;
  padding: 8px 10px 7px;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  background: #fdfefe;
}

.composer-box:focus-within {
  border-color: #9dd8d1;
  box-shadow: 0 0 0 3px rgba(15, 159, 147, 0.07);
}

.composer-box :deep(.el-textarea__inner) {
  box-shadow: none !important;
  background: transparent;
  padding: 2px 4px;
  font-size: 12.5px;
  line-height: 1.7;
}

.composer-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 5px;
  padding: 0 2px;
}

.composer-hint {
  font-size: 9.5px;
  color: #a6b2b8;
}

.composer-tip {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  margin-top: 7px;
  font-size: 9.5px;
  line-height: 1.6;
  color: #a1adb3;
}

.composer-tip .el-icon {
  margin-top: 1px;
  flex-shrink: 0;
}

:deep(.tag-soft.warn) {
  background: #fdf3f2;
  border-color: #efd9d6;
  color: #a35a52;
}

@media (max-width: 1024px) {
  .llm-layout {
    grid-template-columns: 1fr;
    height: auto;
  }
  .model-panel {
    max-height: none;
    overflow: visible;
  }
  .chat-panel {
    height: calc(100vh - 360px);
    min-height: 520px;
  }
}

@media (max-width: 720px) {
  .scope-banner {
    padding: 10px 12px;
  }
  .suggestion-grid {
    grid-template-columns: 1fr;
  }
  .chat-scroll {
    padding: 16px 14px 8px;
  }
  .chat-head {
    padding: 11px 14px;
  }
  .chat-head-right .tag-soft {
    display: none;
  }
  .composer {
    padding: 10px 12px;
  }
  .bot-answer {
    padding: 13px;
  }
  .user-bubble {
    max-width: 86%;
  }
  .bot-meta span:nth-child(2) {
    display: none;
  }
}
</style>
