<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { ensureOptions, store } from '../store'
import { fmtDate, levelType } from '../utils'
import PageHeader from '../components/PageHeader.vue'
import ResultView from '../components/ResultView.vue'
import EmptyState from '../components/EmptyState.vue'

const router = useRouter()
const form = reactive({
  major: '软件工程',
  grade: '2025级',
  tech_tags: ['Python', '数据分析'],
  has_project: true,
  project_title: '校园二手交易平台',
  preferred_level: '不限'
})
const formRef = ref(null)
const loading = ref(false)
const result = ref(null)
const resultRef = ref(null)

const grades = ['2026级', '2025级', '2024级', '2023级', '2022级']
const levels = ['不限', '校级', '省级', '国家级']
const techOptions = ['Python', 'Java', 'C/C++', 'JavaScript', '数据分析', '人工智能', '机器学习', '前端开发', '后端开发', '嵌入式', '数学建模', 'UI 设计', '创新创业']

const recommendations = computed(() => result.value?.structured?.recommend?.recommendations || [])
const totalCandidates = computed(() => result.value?.structured?.recommend?.total_candidates || 0)
const method = computed(() => result.value?.structured?.recommend?.method || '')

const rules = [
  { icon: 'School', title: '专业适配', desc: '专业目录与赛事学科标签交叉匹配' },
  { icon: 'Cpu', title: '技术方向', desc: '技术栈与赛道要求、赛题能力对齐' },
  { icon: 'TrendCharts', title: '年级与难度', desc: '结合年级可投入时间与赛事难度' },
  { icon: 'Briefcase', title: '项目基础', desc: '已有作品可直接转化参赛的程度' }
]

function scorePercent(score) {
  return Math.round(Number(score || 0) * 100)
}

function fillScore(reasons) {
  return (reasons || []).slice(0, 3)
}

async function submit() {
  loading.value = true
  result.value = null
  try {
    const question = `我是${form.major}专业${form.grade}学生${
      form.tech_tags.length ? `，技术方向为${form.tech_tags.join('、')}` : ''
    }${form.has_project ? `，已完成项目「${form.project_title || '课程项目'}」` : '，暂无完整项目基础'}，希望参加${
      form.preferred_level === '不限' ? '适合我当前阶段的' : form.preferred_level
    }竞赛，请推荐适合我的赛事。`
    const data = await api.runAgent('recommend', {
      question,
      profile: {
        major: form.major,
        grade: form.grade,
        tech_tags: form.tech_tags,
        has_project: form.has_project,
        project_title: form.project_title,
        preferred_level: form.preferred_level === '不限' ? '' : form.preferred_level
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

function goPrep(item) {
  router.push({ name: 'prep', query: { competition: item.name } })
}

function goCompetition(item) {
  router.push({ name: 'competitions', query: { open: item.competition_id } })
}

onMounted(ensureOptions)
</script>

<template>
  <div>
    <PageHeader
      eyebrow="Competition Match"
      title="竞赛推荐"
      description="综合专业、年级、技术方向与项目基础，从在库赛事中给出可解释的匹配结果，并直接衔接备赛计划。"
    >
      <template #actions>
        <el-button @click="router.push('/competitions')"><el-icon><TrophyBase /></el-icon> 浏览赛事库</el-button>
      </template>
    </PageHeader>

    <div class="recommend-layout">
      <div class="form-card">
        <div class="form-card-head">
          <h3>学生画像</h3>
          <p>画像越具体，可解释的匹配依据越充分。</p>
        </div>
        <div class="form-card-body">
          <div class="form-grid">
            <div class="span-2">
              <label class="field-label">专业<span class="req">*</span></label>
              <el-select v-model="form.major" filterable allow-create style="width: 100%" placeholder="选择或输入专业">
                <el-option v-for="m in store.options?.majors || []" :key="m" :label="m" :value="m" />
              </el-select>
            </div>
            <div>
              <label class="field-label">年级<span class="req">*</span></label>
              <el-select v-model="form.grade" style="width: 100%">
                <el-option v-for="g in grades" :key="g" :label="g" :value="g" />
              </el-select>
            </div>
            <div>
              <label class="field-label">意向级别</label>
              <el-select v-model="form.preferred_level" style="width: 100%">
                <el-option v-for="l in levels" :key="l" :label="l" :value="l" />
              </el-select>
            </div>
            <div class="span-2">
              <label class="field-label">技术方向</label>
              <el-select
                v-model="form.tech_tags"
                multiple
                filterable
                allow-create
                collapse-tags
                collapse-tags-tooltip
                style="width: 100%"
                placeholder="选择或输入技术方向"
              >
                <el-option v-for="tag in techOptions" :key="tag" :label="tag" :value="tag" />
              </el-select>
            </div>
            <div class="span-2">
              <div class="project-toggle">
                <div>
                  <label class="field-label" style="margin: 0">是否已有项目基础</label>
                  <div class="field-hint">已有作品可显著提升创新类赛事匹配度</div>
                </div>
                <el-switch v-model="form.has_project" />
              </div>
            </div>
            <div v-if="form.has_project" class="span-2">
              <label class="field-label">项目名称</label>
              <el-input v-model="form.project_title" maxlength="80" placeholder="例如：校园二手交易平台" />
            </div>
          </div>
          <div class="form-actions">
            <el-button type="primary" :loading="loading" style="flex: 1" @click="submit">
              <el-icon v-if="!loading"><Compass /></el-icon>
              {{ loading ? '匹配中' : '生成推荐结果' }}
            </el-button>
          </div>
          <div class="form-note">
            <el-icon><Lock /></el-icon>
            匹配依据来自赛事台账与可配置权重，不依赖大模型自由发挥。
          </div>
        </div>
      </div>

      <div ref="resultRef" class="recommend-result">
        <template v-if="!result">
          <div class="panel intro-panel">
            <div class="intro-head">
              <span class="tag-soft teal">Explainable Matching</span>
              <h2>推荐结果如何产生？</h2>
              <p>
                系统先读取赛事库中的学科标签、难度、报名时间与学院历年台账，再按角色画像计算适配度；
                每条推荐都会给出可核对的理由，而非只有一句结论。
              </p>
            </div>
            <div class="rule-grid">
              <div v-for="rule in rules" :key="rule.title" class="rule-item">
                <div class="rule-icon"><el-icon><component :is="rule.icon" /></el-icon></div>
                <div>
                  <div class="rule-title">{{ rule.title }}</div>
                  <div class="rule-desc">{{ rule.desc }}</div>
                </div>
              </div>
            </div>
            <div class="intro-foot">
              <span>在库赛事 <strong>{{ store.options?.competitions?.length || '—' }}</strong> 项</span>
              <span>覆盖年度 <strong>{{ store.options?.years?.join(' / ') || '—' }}</strong></span>
              <span>台账队伍 <strong>{{ store.health?.competitions ? '80+' : '—' }}</strong></span>
            </div>
          </div>
        </template>

        <template v-else>
          <div class="match-summary">
            <div>
              <span class="tag-soft teal">匹配完成</span>
              <h2>从 {{ totalCandidates }} 个在库赛事中，为你选出 {{ recommendations.length }} 个优先目标</h2>
              <p>{{ method }}</p>
            </div>
            <div class="match-actions">
              <el-button @click="submit" :loading="loading"><el-icon><Refresh /></el-icon> 重新匹配</el-button>
            </div>
          </div>

          <div v-if="recommendations.length" class="match-list">
            <div
              v-for="(item, index) in recommendations"
              :key="item.competition_id"
              class="match-card"
              :class="{ top: index === 0 }"
            >
              <div class="match-rank">{{ String(index + 1).padStart(2, '0') }}</div>
              <div class="match-main">
                <div class="match-title-row">
                  <div>
                    <div class="match-title">
                      {{ item.name }}
                      <span v-if="index === 0" class="best-tag">最佳匹配</span>
                    </div>
                    <div class="match-sub">
                      <el-tag size="small" :type="levelType[item.level] || 'info'" effect="light">{{ item.level }}</el-tag>
                      <span class="tag-soft">{{ item.category }}</span>
                      <span class="tag-soft">难度 {{ item.difficulty }}</span>
                      <span class="tag-soft">{{ item.team_size }}</span>
                    </div>
                  </div>
                  <div class="score-ring" :style="{ '--score': `${scorePercent(item.score)}%` }">
                    <div class="score-inner">
                      <strong>{{ scorePercent(item.score) }}</strong>
                      <span>适配度</span>
                    </div>
                  </div>
                </div>

                <div class="match-reasons">
                  <span v-for="reason in fillScore(item.reasons)" :key="reason" class="reason-chip">
                    <el-icon><Check /></el-icon>{{ reason }}
                  </span>
                </div>
                <div v-if="item.fit_reason" class="fit-callout">{{ item.fit_reason }}</div>

                <div class="match-meta">
                  <div>
                    <span>报名截止</span>
                    <strong>{{ fmtDate(item.register_end) }}</strong>
                  </div>
                  <div>
                    <span>报名费</span>
                    <strong>{{ item.registration_fee ? `¥${item.registration_fee}` : '免费' }}</strong>
                  </div>
                  <div>
                    <span>历年参赛 / 获奖</span>
                    <strong>{{ item.college_ledger?.registrations ?? 0 }} / {{ item.college_ledger?.awards ?? 0 }}</strong>
                  </div>
                  <div>
                    <span>建议年级</span>
                    <strong>{{ item.recommended_grade || '不限' }}</strong>
                  </div>
                </div>

                <div class="match-foot">
                  <span class="deadline-note">
                    <el-icon><Calendar /></el-icon>
                    报名截止 {{ fmtDate(item.register_end) }}，请预留校内选拔与材料准备时间
                  </span>
                  <div class="match-buttons">
                    <el-button size="small" @click="goCompetition(item)">赛事详情</el-button>
                    <el-button size="small" type="primary" plain @click="goPrep(item)">生成备赛计划</el-button>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <EmptyState v-else title="暂未匹配到合适赛事" description="请补充专业、技术方向或调整意向级别后重试。" />

          <div class="panel result-panel">
            <ResultView
              :result="result"
              title="推荐过程与依据"
              :show-answer="false"
              :show-tables="false"
              :show-charts="false"
            />
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.recommend-layout {
  display: grid;
  grid-template-columns: 350px minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}

.form-card {
  position: sticky;
  top: 92px;
}

.project-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 11px 13px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fbfcfc;
}

.form-note {
  display: flex;
  gap: 6px;
  align-items: flex-start;
  margin-top: 12px;
  font-size: 10px;
  color: var(--muted-2);
  line-height: 1.6;
}

.intro-panel {
  padding: 30px 32px;
  background:
    radial-gradient(420px 260px at 100% 0%, rgba(15, 159, 147, 0.06), transparent 65%),
    var(--surface);
}

.intro-head h2 {
  font-family: var(--font-display);
  font-size: 23px;
  color: var(--ink);
  margin: 12px 0 8px;
}

.intro-head p {
  font-size: 12.5px;
  color: var(--muted);
  line-height: 1.85;
  max-width: 680px;
}

.rule-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 24px;
}

.rule-item {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  padding: 13px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: #fdfefe;
}

.rule-icon {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: var(--teal-soft);
  color: var(--teal-dark);
  display: grid;
  place-items: center;
  font-size: 14px;
  flex-shrink: 0;
}

.rule-title {
  font-size: 12px;
  font-weight: 650;
  color: #35515a;
}

.rule-desc {
  font-size: 10.5px;
  color: var(--muted-2);
  margin-top: 2px;
  line-height: 1.6;
}

.intro-foot {
  display: flex;
  gap: 28px;
  flex-wrap: wrap;
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px dashed var(--line);
  font-size: 10.5px;
  color: var(--muted-2);
}

.intro-foot strong {
  color: var(--ink-2);
  font-size: 12px;
  margin-left: 3px;
}

.match-summary {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.match-summary h2 {
  font-family: var(--font-display);
  font-size: 20px;
  color: var(--ink);
  margin: 9px 0 4px;
}

.match-summary p {
  font-size: 10.5px;
  color: var(--muted-2);
  max-width: 700px;
  line-height: 1.6;
}

.match-list {
  display: grid;
  gap: 12px;
}

.match-card {
  display: flex;
  gap: 16px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 13px;
  padding: 20px 22px 16px;
  box-shadow: var(--shadow-sm);
  position: relative;
  overflow: hidden;
}

.match-card.top {
  border-color: #d9c79b;
  background:
    radial-gradient(300px 140px at 100% 0%, rgba(196, 161, 91, 0.11), transparent 70%),
    var(--surface);
}

.match-rank {
  font-family: var(--font-display);
  font-size: 20px;
  color: #c2d0d4;
  font-weight: 700;
  line-height: 1;
  padding-top: 3px;
  width: 27px;
  flex-shrink: 0;
}

.match-card.top .match-rank {
  color: #b49048;
}

.match-main {
  min-width: 0;
  flex: 1;
}

.match-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.match-title {
  font-size: 15px;
  font-weight: 650;
  color: var(--ink);
  line-height: 1.45;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.best-tag {
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: #8a6a2b;
  background: #faf2df;
  border: 1px solid #ead9b2;
  border-radius: 4px;
  padding: 1px 6px;
}

.match-sub {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 7px;
}

.score-ring {
  width: 58px;
  height: 58px;
  border-radius: 50%;
  flex-shrink: 0;
  background: conic-gradient(var(--teal) var(--score), #e8eff0 0);
  display: grid;
  place-items: center;
  position: relative;
}

.score-ring::before {
  content: '';
  position: absolute;
  inset: 4px;
  background: #fff;
  border-radius: 50%;
}

.score-inner {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  line-height: 1.1;
}

.score-inner strong {
  font-family: var(--font-display);
  font-size: 17px;
  color: var(--ink);
  font-weight: 700;
}

.score-inner span {
  font-size: 8px;
  color: var(--muted-2);
  margin-top: 2px;
}

.match-reasons {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;
}

.reason-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  color: #4b6a66;
  background: #f3f9f8;
  border: 1px solid #e0eeec;
  border-radius: 5px;
  padding: 2px 7px;
}

.reason-chip .el-icon {
  font-size: 10px;
  color: #4fa79c;
}

.fit-callout {
  margin-top: 9px;
  font-size: 11px;
  color: #5b6e77;
  background: #fbfcfc;
  border-left: 2px solid #d8e5e3;
  padding: 6px 10px;
  border-radius: 0 5px 5px 0;
  line-height: 1.7;
}

.match-meta {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-top: 13px;
  padding: 11px 0;
  border-top: 1px dashed var(--line);
  border-bottom: 1px dashed var(--line);
}

.match-meta div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.match-meta span {
  font-size: 9.5px;
  color: var(--muted-2);
}

.match-meta strong {
  font-size: 12px;
  color: #2e4652;
  font-weight: 600;
}

.match-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 11px;
  flex-wrap: wrap;
}

.deadline-note {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 10px;
  color: var(--muted-2);
}

.match-buttons {
  display: flex;
  gap: 7px;
  margin-left: auto;
}

.result-panel {
  margin-top: 16px;
  padding: 22px 24px;
}

@media (max-width: 1200px) {
  .recommend-layout {
    grid-template-columns: 1fr;
  }
  .form-card {
    position: static;
  }
}

@media (max-width: 720px) {
  .intro-panel {
    padding: 22px;
  }
  .rule-grid {
    grid-template-columns: 1fr;
  }
  .match-card {
    padding: 16px;
    gap: 10px;
  }
  .match-meta {
    grid-template-columns: repeat(2, 1fr);
  }
  .score-ring {
    width: 50px;
    height: 50px;
  }
  .match-foot {
    align-items: flex-start;
    flex-direction: column;
  }
  .match-buttons {
    margin-left: 0;
    width: 100%;
  }
}
</style>
