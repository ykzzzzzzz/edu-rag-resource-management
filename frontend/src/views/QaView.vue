<template>
  <div class="page">
    <h2 class="page-title">问答</h2>

    <el-alert class="block" :type="currentMode ? 'info' : 'warning'" show-icon :closable="false" :title="modeText" />

    <el-card class="block" shadow="never">
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="课程范围">
          <el-select
            v-model="courseId"
            class="course-select"
            filterable
            :loading="coursesLoading"
            :disabled="asking"
            :no-data-text="courseError || '暂无课程'"
          >
            <el-option label="全部课程" :value="ALL_COURSES" />
            <el-option v-for="course in courses" :key="course.id" :label="course.name" :value="course.id" />
          </el-select>
          <div v-if="courseError" class="course-error">
            课程列表加载失败，只能在全部课程中提问。
            <el-button link type="primary" size="small" @click="loadCourses">重新加载</el-button>
          </div>
        </el-form-item>

        <el-form-item label="问题">
          <el-input
            v-model="question"
            type="textarea"
            :rows="4"
            resize="vertical"
            placeholder="请输入问题，按 Ctrl+Enter 提交"
            @keydown.ctrl.enter.prevent="submit"
          />
          <div class="input-foot">
            <span class="privacy-hint">{{ PERSONAL_INFO_HINT }}</span>
            <span class="counter" :class="{ 'counter-over': overLimit }">
              {{ trimmedLength }} / {{ QUESTION_MAX_LENGTH }}
            </span>
          </div>
          <div v-if="overLimit" class="field-error">问题不能超过 {{ QUESTION_MAX_LENGTH }} 个字符。</div>
        </el-form-item>

        <el-button type="primary" native-type="submit" :loading="asking" :disabled="!canSubmit">
          {{ asking ? '正在回答…' : '提问' }}
        </el-button>
      </el-form>
    </el-card>

    <el-empty v-if="entries.length === 0" description="还没有提问，回答会显示在这里。本页记录刷新后会清空。" />

    <el-card v-for="entry in entries" :key="entry.id" class="entry" shadow="never">
      <div class="entry-head">
        <div class="entry-question">{{ entry.question }}</div>
        <div class="entry-meta">{{ entry.courseName }} · {{ formatDateTime(entry.askedAt) }}</div>
      </div>

      <el-skeleton v-if="entry.state === 'pending'" :rows="3" animated />

      <div v-else-if="entry.state === 'error' && entry.error" class="entry-error">
        <el-alert type="error" show-icon :closable="false" :title="entry.error.title">
          <div v-if="entry.error.detail">{{ entry.error.detail }}</div>
          <div v-if="entry.error.requestId" class="request-id">请求编号：{{ entry.error.requestId }}</div>
        </el-alert>
        <el-button v-if="entry.error.retryable" class="retry" :disabled="asking" @click="retry(entry)">重试</el-button>
      </div>

      <template v-else-if="entry.answer">
        <el-alert
          v-if="entry.answer.status === 'insufficient_evidence'"
          type="warning"
          show-icon
          :closable="false"
          :title="INSUFFICIENT_EVIDENCE_TEXT"
        >
          <span v-if="entry.answer.answer" class="insufficient-text">{{ entry.answer.answer }}</span>
        </el-alert>
        <AnswerText
          v-else
          :answer="entry.answer.answer"
          :citations="entry.answer.citations"
          @open="(n: number) => openCitation(entry, n)"
        />

        <div v-if="currentMode && entry.answer.mode !== currentMode" class="mode-note">
          该回答生成时的模式：{{ MODE_TEXTS[entry.answer.mode] }}
        </div>

        <div v-if="entry.answer.citations.length > 0" class="citations">
          <div class="citations-title">引用</div>
          <button
            v-for="citation in entry.answer.citations"
            :key="citation.number"
            type="button"
            class="citation-card"
            @click="openCitation(entry, citation.number)"
          >
            <div class="citation-head">
              <span class="citation-number">{{ citation.number }}</span>
              <span class="citation-title">{{ citation.title }}</span>
            </div>
            <div class="citation-meta">{{ citation.course_name }} · {{ formatLocator(citation.locator) }}</div>
            <div class="citation-excerpt">{{ citation.excerpt }}</div>
          </button>
        </div>
      </template>
    </el-card>

    <CitationDrawer
      v-model="drawerVisible"
      :number="drawerNumber"
      :resource-id="drawerResourceId"
      :chunk-id="drawerChunkId"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import type { QaMode } from '../api'
import AnswerText from '../components/AnswerText.vue'
import CitationDrawer from '../components/CitationDrawer.vue'
import { useApiError } from '../composables/useApiError'
import { useCourses } from '../composables/useCourses'
import { session } from '../stores/session'
import {
  INSUFFICIENT_EVIDENCE_TEXT,
  MODE_TEXTS,
  PERSONAL_INFO_HINT,
  QUESTION_MAX_LENGTH,
  QUESTION_MIN_LENGTH,
  countChars,
  describeQaError,
  formatLocator,
} from '../utils/qa'
import type { QaEntry } from '../utils/qa'
import { formatDateTime } from '../utils/resource'

/** el-select 的选项值不能是 null，用哨兵值代表“全部课程”。 */
const ALL_COURSES = '__all__'

const { courses, loading: coursesLoading, error: courseError, loadCourses } = useCourses()
const { handle } = useApiError()

const courseId = ref(ALL_COURSES)
const question = ref('')
const asking = ref(false)
// 只保存在内存里，刷新页面后清空；新记录插在最前。
const entries = ref<QaEntry[]>([])
let nextId = 1
/** 最近一次响应里的模式；session 里的模式尚未取到时作为顶部提示的依据。 */
const lastMode = ref<QaMode | null>(null)

const trimmedLength = computed(() => countChars(question.value.trim()))
const overLimit = computed(() => trimmedLength.value > QUESTION_MAX_LENGTH)
const canSubmit = computed(() => !asking.value && trimmedLength.value >= QUESTION_MIN_LENGTH && !overLimit.value)

const currentMode = computed<QaMode | null>(() => session.qaMode.value ?? lastMode.value)
const modeText = computed(() =>
  currentMode.value === null ? '当前问答模式未知，请稍后刷新页面。' : MODE_TEXTS[currentMode.value],
)

function courseNameOf(id: string | null): string {
  if (id === null) return '全部课程'
  return courses.value.find((c) => c.id === id)?.name ?? '指定课程'
}

async function ask(entry: QaEntry): Promise<void> {
  asking.value = true
  entry.state = 'pending'
  entry.error = null
  try {
    const result = await api.ask({ question: entry.question, course_id: entry.courseId })
    entry.answer = result
    entry.state = 'done'
    lastMode.value = result.mode
  } catch (e) {
    // 401 时清会话并跳转登录页；其余错误作为一条记录显示在历史里。
    await handle(e, '提问失败，请稍后重试。')
    entry.answer = null
    entry.error = describeQaError(e)
    entry.state = 'error'
  } finally {
    asking.value = false
  }
}

async function submit(): Promise<void> {
  if (!canSubmit.value) return
  const scope = courseId.value === ALL_COURSES ? null : courseId.value
  const entry = reactive<QaEntry>({
    id: nextId++,
    question: question.value.trim(),
    courseId: scope,
    courseName: courseNameOf(scope),
    askedAt: new Date().toISOString(),
    state: 'pending',
    answer: null,
    error: null,
  })
  entries.value.unshift(entry)
  // 提交后立即清空输入框；失败时记录里有“重试”，不会丢问题。
  question.value = ''
  await ask(entry)
}

function retry(entry: QaEntry): void {
  if (asking.value) return
  void ask(entry)
}

// ---- 引用抽屉 ----
const drawerVisible = ref(false)
const drawerNumber = ref<number | null>(null)
const drawerResourceId = ref('')
const drawerChunkId = ref('')

function openCitation(entry: QaEntry, number: number): void {
  const citation = entry.answer?.citations.find((c) => c.number === number)
  if (!citation) return
  drawerNumber.value = citation.number
  drawerResourceId.value = citation.resource_id
  drawerChunkId.value = citation.chunk_id
  drawerVisible.value = true
}

onMounted(() => {
  void loadCourses()
})
</script>

<style scoped>
.page {
  min-width: 0;
  max-width: 900px;
}

.page-title {
  margin: 0 0 16px;
  font-size: 20px;
}

.block {
  margin-bottom: 16px;
}

.course-select {
  width: 280px;
  max-width: 100%;
}

.course-error {
  width: 100%;
  margin-top: 4px;
  font-size: 13px;
  color: var(--el-color-danger);
}

.input-foot {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  margin-top: 4px;
  font-size: 13px;
  line-height: 1.5;
}

.privacy-hint {
  color: var(--el-color-warning-dark-2);
}

.counter {
  flex: none;
  color: var(--text-secondary);
}

.counter-over,
.field-error {
  color: var(--el-color-danger);
}

.field-error {
  width: 100%;
  font-size: 13px;
}

.entry {
  margin-bottom: 16px;
}

.entry-head {
  margin-bottom: 12px;
}

.entry-question {
  font-size: 16px;
  font-weight: 600;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.entry-meta {
  margin-top: 2px;
  font-size: 13px;
  color: var(--text-secondary);
}

.entry-error {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}

.entry-error :deep(.el-alert) {
  flex: 1 1 280px;
  width: auto;
}

.request-id {
  margin-top: 4px;
  font-size: 12px;
  opacity: 0.8;
}

.retry {
  flex: none;
}

.insufficient-text {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.mode-note {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}

.citations {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 16px;
}

.citations-title {
  font-size: 13px;
  color: var(--text-secondary);
}

.citation-card {
  display: block;
  width: 100%;
  padding: 10px 12px;
  box-sizing: border-box;
  border: 1px solid var(--el-border-color-light);
  border-radius: 6px;
  background: var(--el-fill-color-blank);
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.citation-card:hover,
.citation-card:focus-visible {
  border-color: var(--el-color-primary);
}

.citation-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.citation-number {
  flex: none;
  min-width: 20px;
  height: 20px;
  padding: 0 4px;
  box-sizing: border-box;
  border-radius: 10px;
  background: var(--el-color-primary);
  color: #fff;
  font-size: 12px;
  line-height: 20px;
  text-align: center;
}

.citation-title {
  font-weight: 600;
  overflow-wrap: anywhere;
}

.citation-meta {
  margin-top: 2px;
  font-size: 13px;
  color: var(--text-secondary);
}

.citation-excerpt {
  margin-top: 6px;
  font-size: 14px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
