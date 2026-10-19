<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import { store } from '../store'
import { fmtDateTime } from '../utils'
import PageHeader from '../components/PageHeader.vue'
import MarkdownView from '../components/MarkdownView.vue'
import CitationList from '../components/CitationList.vue'
import AgentTrace from '../components/AgentTrace.vue'
import DataTable from '../components/DataTable.vue'
import EChart from '../components/EChart.vue'

const sessions = ref([])
const sessionId = ref(null)
const sessionTitle = ref('新对话')
const messages = ref([])
const question = ref('')
const loading = ref(false)
const loadingSessions = ref(false)
const scrollBox = ref(null)
const showSessions = ref(false)
let askSeq = 0

const suggestions = [
  '2026 年蓝桥杯的报名截止时间和参赛对象是什么？',
  '中国国际大学生创新大赛的参赛材料和组队要求？',
  '全国大学生数学建模竞赛的论文格式要求有哪些？',
  '学院对国家级竞赛的差旅费标准是如何规定的？',
  '学科竞赛获奖后如何折算学生积分与教师工作量？',
  '2027 年有哪些赛事正在报名？'
]

watch(() => store.role, () => {
  newSession()
  loadSessions()
})

async function loadSessions() {
  loadingSessions.value = true
  try {
    const data = await api.qaSessions(40)
    sessions.value = data.items || []
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loadingSessions.value = false
  }
}

function toMessage(raw) {
  if (raw.role === 'user') {
    return { role: 'user', content: raw.content, created_at: raw.created_at }
  }
  const structured = raw.payload || {}
  return {
    role: 'assistant',
    content: raw.content,
    citations: raw.citations || [],
    steps: raw.agent_trace?.steps || [],
    tables: [],
    charts: [],
    structured,
    created_at: raw.created_at,
    result: {
      answer: raw.content,
      citations: raw.citations || [],
      steps: raw.agent_trace?.steps || [],
      structured,
      agent_name: '竞赛知识问答'
    }
  }
}

async function openSession(item) {
  try {
    const data = await api.qaSession(item.id)
    sessionId.value = data.id
    sessionTitle.value = data.title
    messages.value = (data.messages || []).map(toMessage)
    showSessions.value = false
    await scrollToBottom()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

function newSession() {
  askSeq += 1
  loading.value = false
  sessionId.value = null
  sessionTitle.value = '新对话'
  messages.value = []
  question.value = ''
  showSessions.value = false
}

async function deleteSession(item, event) {
  event?.stopPropagation()
  try {
    await ElMessageBox.confirm(`确定删除会话「${item.title}」？`, '删除会话', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
    await api.deleteSession(item.id)
    if (sessionId.value === item.id) newSession()
    await loadSessions()
    ElMessage.success('会话已删除')
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(error.message || '删除失败')
  }
}

async function scrollToBottom() {
  await nextTick()
  if (scrollBox.value) scrollBox.value.scrollTop = scrollBox.value.scrollHeight
}

async function send(text) {
  const content = String(text ?? question.value).trim()
  if (!content || loading.value) return
  const seq = ++askSeq
  question.value = ''
  messages.value.push({ role: 'user', content, created_at: new Date().toISOString() })
  loading.value = true
  await scrollToBottom()
  try {
    const result = await api.qaAsk({
      question: content,
      session_id: sessionId.value,
      user_role: store.role
    })
    if (seq !== askSeq) return
    sessionId.value = result.session_id
    if (sessionTitle.value === '新对话') sessionTitle.value = content.slice(0, 30)
    messages.value.push({
      role: 'assistant',
      content: result.answer,
      citations: result.citations || [],
      steps: result.steps || [],
      tables: result.tables || [],
      charts: result.charts || [],
      structured: result.structured || {},
      created_at: new Date().toISOString(),
      result
    })
    await loadSessions()
  } catch (error) {
    if (seq !== askSeq) return
    messages.value.push({
      role: 'assistant',
      content: `抱歉，本次检索失败：${error.message}`,
      error: true,
      citations: [],
      steps: [],
      tables: [],
      charts: []
    })
  } finally {
    if (seq === askSeq) {
      loading.value = false
      await scrollToBottom()
    }
  }
}

function onKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    send()
  }
}

async function exportMessage(message) {
  try {
    await api.exportAgent(
      { title: '竞赛知识问答', answer: message.content, tables: message.tables || [] },
      'docx'
    )
  } catch (error) {
    ElMessage.error(error.message)
  }
}

function eventTags(structured) {
  const comp = structured?.competition
  if (!comp) return []
  const tags = [`赛事级别：${comp.level || '—'}`]
  if (comp.register_start || comp.register_end) tags.push(`报名：${comp.register_start || '—'} 至 ${comp.register_end || '—'}`)
  if (comp.latest_year) tags.push(`最新年度：${comp.latest_year}`)
  return tags
}

onMounted(loadSessions)
</script>

<template>
  <div>
    <PageHeader
      eyebrow="Knowledge QA"
      title="竞赛知识问答"
      description="覆盖赛事通知、参赛规程、报名条件与学院管理制度；回答优先采用结构化赛事台账，并逐条给出原始文件出处。"
    >
      <template #actions>
        <el-button @click="newSession"><el-icon><Plus /></el-icon> 新建对话</el-button>
        <el-button type="primary" plain @click="showSessions = !showSessions" class="mobile-history">
          <el-icon><Clock /></el-icon> 历史会话
        </el-button>
      </template>
    </PageHeader>

    <div class="qa-layout" :class="{ 'show-sessions': showSessions }">
      <aside class="session-panel">
        <div class="session-head">
          <div>
            <h3>会话记录</h3>
            <span>{{ sessions.length }} 个对话</span>
          </div>
          <el-button text circle size="small" @click="newSession"><el-icon><EditPen /></el-icon></el-button>
        </div>
        <div v-loading="loadingSessions" class="session-list">
          <div
            v-for="item in sessions"
            :key="item.id"
            class="session-item"
            :class="{ active: item.id === sessionId }"
            @click="openSession(item)"
          >
            <div class="session-title">{{ item.title }}</div>
            <div class="session-last">{{ item.last_message || '暂无消息' }}</div>
            <div class="session-meta">
              <span>{{ item.user_role }} · {{ fmtDateTime(item.created_at) }}</span>
              <el-icon class="session-delete" @click="deleteSession(item, $event)"><Delete /></el-icon>
            </div>
          </div>
          <div v-if="!sessions.length && !loadingSessions" class="session-empty">
            暂无历史会话，提出第一个问题即可开始。
          </div>
        </div>
        <div class="session-foot">
          <el-icon><Lock /></el-icon>
          问答日志将写入质检台账，用于持续改进检索质量
        </div>
      </aside>

      <section class="chat-panel">
        <div class="chat-head">
          <div class="chat-avatar"><el-icon><ChatDotRound /></el-icon></div>
          <div>
            <div class="chat-title">{{ sessionTitle }}</div>
            <div class="chat-sub">
              知识库增强检索 · 结构化台账校准
              <span class="tag-soft teal" style="margin-left: 6px">RAG</span>
            </div>
          </div>
          <div class="chat-head-right">
            <span class="tag-soft">{{ store.role }}</span>
            <el-button text size="small" @click="newSession"><el-icon><RefreshLeft /></el-icon> 清空</el-button>
          </div>
        </div>

        <div ref="scrollBox" class="chat-scroll">
          <div v-if="!messages.length" class="chat-welcome">
            <div class="welcome-mark">
              <el-icon><ChatLineRound /></el-icon>
            </div>
            <h2>关于学科竞赛，<br />从一份原始文件开始回答。</h2>
            <p>
              我会先检索结构化赛事台账与知识库原文，再组织答案。每个结论都可以展开查看出处，
              大模型不可用时自动切换为离线规则通道。
            </p>
            <div class="suggestion-grid">
              <button v-for="item in suggestions" :key="item" class="suggestion" @click="send(item)">
                <el-icon><ArrowUpRight /></el-icon>
                <span>{{ item }}</span>
              </button>
            </div>
          </div>

          <div v-for="(message, index) in messages" :key="index" class="message" :class="message.role">
            <template v-if="message.role === 'user'">
              <div class="user-bubble">{{ message.content }}</div>
              <div class="user-avatar">{{ store.role === '学生' ? '学' : store.role === '教师' ? '师' : '管' }}</div>
            </template>

            <template v-else>
              <div class="bot-avatar"><el-icon><MagicStick /></el-icon></div>
              <div class="bot-body">
                <div class="bot-name">
                  竞智助手
                  <span class="tag-soft teal" v-if="!message.error">已核验出处</span>
                </div>
                <div v-if="message.error" class="bot-error">{{ message.content }}</div>
                <template v-else>
                  <div v-if="eventTags(message.structured).length" class="event-strip">
                    <span class="event-name">{{ message.structured?.competition?.name }}</span>
                    <span v-for="tag in eventTags(message.structured)" :key="tag">{{ tag }}</span>
                  </div>
                  <div class="bot-answer">
                    <MarkdownView :content="message.content" />
                  </div>
                  <div v-if="message.charts?.length" class="chat-extra">
                    <EChart :option="message.charts[0].option" :height="300" />
                  </div>
                  <div v-for="(table, tIndex) in message.tables || []" :key="tIndex" class="chat-extra">
                    <DataTable :table="table" :max-height="320" />
                  </div>
                  <CitationList v-if="message.citations?.length" :citations="message.citations" style="margin-top: 12px" />
                  <AgentTrace v-if="message.steps?.length" :steps="message.steps" style="margin-top: 10px" />
                  <div class="bot-actions">
                    <el-button text size="small" @click="exportMessage(message)">
                      <el-icon><Download /></el-icon> 导出 Word
                    </el-button>
                    <span class="bot-time">{{ fmtDateTime(message.created_at) }}</span>
                  </div>
                </template>
              </div>
            </template>
          </div>

          <div v-if="loading" class="message assistant">
            <div class="bot-avatar"><el-icon><MagicStick /></el-icon></div>
            <div class="bot-body">
              <div class="typing"><span /><span /><span /></div>
              <div class="typing-text">正在检索知识库并核对台账…</div>
            </div>
          </div>
        </div>

        <div class="composer">
          <div class="composer-box">
            <el-input
              v-model="question"
              type="textarea"
              :rows="2"
              resize="none"
              maxlength="4000"
              placeholder="例如：2026 年蓝桥杯报名截止时间是什么时候？需要提交哪些材料？"
              @keydown="onKeydown"
            />
            <div class="composer-bar">
              <span class="composer-hint">Enter 发送 · Shift + Enter 换行</span>
              <el-button type="primary" :loading="loading" :disabled="!question.trim()" @click="send()">
                <el-icon v-if="!loading"><Promotion /></el-icon>
                {{ loading ? '检索中' : '发送提问' }}
              </el-button>
            </div>
          </div>
          <div class="composer-tip">
            <el-icon><Warning /></el-icon>
            重要政策与时间节点请以引用原文为准；如需最新信息，请先在知识库更新当年通知。
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.mobile-history {
  display: none;
}

.qa-layout {
  display: grid;
  grid-template-columns: 252px minmax(0, 1fr);
  gap: 18px;
  height: calc(100vh - 205px);
  min-height: 620px;
  position: relative;
}

.session-panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.session-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 16px 12px;
  border-bottom: 1px solid var(--line);
}

.session-head h3 {
  font-size: 13px;
  font-weight: 650;
  color: var(--ink);
}

.session-head span {
  font-size: 10px;
  color: var(--muted-2);
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
  min-height: 0;
}

.session-item {
  padding: 10px 10px 9px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 2px;
  border: 1px solid transparent;
  transition: background 0.14s ease;
}

.session-item:hover {
  background: #f7faf9;
}

.session-item.active {
  background: #eff8f6;
  border-color: #d3ebe7;
}

.session-title {
  font-size: 12px;
  font-weight: 600;
  color: #344b56;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-last {
  font-size: 10.5px;
  color: var(--muted-2);
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
  font-size: 9.5px;
  color: #9aa9b1;
}

.session-delete {
  opacity: 0;
  font-size: 11px;
  transition: opacity 0.15s;
}

.session-item:hover .session-delete {
  opacity: 1;
  color: #b56a65;
}

.session-empty {
  padding: 28px 14px;
  font-size: 11px;
  color: var(--muted-2);
  line-height: 1.7;
  text-align: center;
}

.session-foot {
  padding: 11px 14px;
  border-top: 1px solid var(--line);
  font-size: 9.5px;
  color: var(--muted-2);
  line-height: 1.6;
  display: flex;
  gap: 6px;
  align-items: flex-start;
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
  background: linear-gradient(140deg, #0d9488, #0f6472);
  color: #e7fffb;
  display: grid;
  place-items: center;
  font-size: 15px;
}

.chat-title {
  font-size: 13px;
  font-weight: 650;
  color: var(--ink);
  max-width: 520px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chat-sub {
  font-size: 10px;
  color: var(--muted-2);
  display: flex;
  align-items: center;
}

.chat-head-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 6px;
}

.chat-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 24px 26px 10px;
  min-height: 0;
  background:
    radial-gradient(600px 300px at 100% 0%, rgba(15, 159, 147, 0.035), transparent 60%),
    #fdfefe;
}

.chat-welcome {
  max-width: 720px;
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
  background: linear-gradient(145deg, #0f8f84, #0b5866);
  color: #eafffc;
  font-size: 22px;
  box-shadow: 0 12px 28px rgba(13, 148, 136, 0.22);
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

.suggestion:hover {
  border-color: #b9dfda;
  background: #f8fcfb;
  color: var(--teal-dark);
  transform: translateY(-1px);
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
  background: var(--teal-soft);
  border: 1px solid #cdeae6;
  color: var(--teal-dark);
  display: grid;
  place-items: center;
  font-size: 13px;
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
}

.event-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 7px 13px;
  padding: 8px 12px;
  margin-bottom: 8px;
  background: #f4faf9;
  border: 1px solid #def0ed;
  border-radius: 8px;
  font-size: 10.5px;
  color: #55716f;
}

.event-name {
  font-weight: 650;
  color: #1c645e;
}

.chat-extra {
  margin-top: 12px;
}

.bot-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}

.bot-time {
  margin-left: auto;
  font-size: 9.5px;
  color: #a3b0b6;
}

.typing {
  display: flex;
  gap: 4px;
  padding: 13px 16px;
  background: #f3f8f7;
  border-radius: 4px 12px 12px 12px;
  width: 58px;
}

.typing span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #67b6ac;
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
  align-items: center;
  gap: 5px;
  margin-top: 7px;
  font-size: 9.5px;
  color: #a1adb3;
}

@media (max-width: 1024px) {
  .qa-layout {
    grid-template-columns: 1fr;
    height: calc(100vh - 185px);
  }
  .session-panel {
    display: none;
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 270px;
    z-index: 5;
    box-shadow: var(--shadow-lg);
  }
  .qa-layout.show-sessions .session-panel {
    display: flex;
  }
  .mobile-history {
    display: inline-flex;
  }
}

@media (max-width: 720px) {
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
}
</style>
