import { ApiError } from '../api/http'
import type { CitationLocator, QaAnswer, QaLogStatus } from '../api/types'

export const QUESTION_MIN_LENGTH = 1
export const QUESTION_MAX_LENGTH = 500

export const MODE_TEXTS = {
  demo: '资料摘录演示：直接摘录资料原文，不调用外部模型',
  cloud: '云端生成：问题和检索到的资料片段会发送给云端模型服务',
} as const

export const PERSONAL_INFO_HINT = '请勿在提问中填写姓名、学号、电话等个人信息'
export const INSUFFICIENT_EVIDENCE_TEXT = '已发布资料中未找到足够依据'
export const CITATION_UNAVAILABLE_TEXT = '该出处已不可用（资料可能已下架）'

/** 按 Unicode 码点计数，与后端的字符数口径一致（emoji 等不会被算成两个字符）。 */
export function countChars(text: string): number {
  return Array.from(text).length
}

/** 出处位置：PDF 为页，DOCX 为段，TXT 为行；起止相同时只显示一个数字。 */
export function formatLocator(locator: CitationLocator): string {
  const unit = { pdf_page: '页', docx_paragraph: '段', txt_line: '行' }[locator.type]
  const range = locator.end > locator.start ? `${locator.start}–${locator.end}` : `${locator.start}`
  return unit ? `第 ${range} ${unit}` : `${locator.start}–${locator.end}`
}

// ---- 回答中的引用标记 ----

export type AnswerSegment =
  | { kind: 'text'; text: string }
  | { kind: 'cite'; text: string; number: number }

// 只识别半角方括号包裹的 1–999 整数，不允许前导 0、空格或逗号分隔。
const CITE_MARK = /\[([1-9]\d{0,2})\]/g

/**
 * 把回答拆成文本片段和引用标记。只有编号出现在 citations 中的 `[n]` 才成为标记，
 * 其余（如不存在的编号、`[1,2]`、全角括号）保持为普通文本。结果只用于文本插值，不生成 HTML。
 */
export function parseAnswer(answer: string, knownNumbers: ReadonlySet<number>): AnswerSegment[] {
  const segments: AnswerSegment[] = []
  let last = 0
  for (const match of answer.matchAll(CITE_MARK)) {
    const number = Number(match[1])
    if (!knownNumbers.has(number)) continue
    const start = match.index
    if (start > last) segments.push({ kind: 'text', text: answer.slice(last, start) })
    segments.push({ kind: 'cite', text: match[0], number })
    last = start + match[0].length
  }
  if (last < answer.length) segments.push({ kind: 'text', text: answer.slice(last) })
  return segments
}

// ---- 提问错误 ----

export interface QaErrorInfo {
  status: number
  code: string
  /** 面向用户的中文说明。 */
  title: string
  /** 后端返回的 message（与 title 不同时才有值）。 */
  detail: string
  requestId: string | null
  /** 重试是否可能有意义；参数错误、无权限时不提供。 */
  retryable: boolean
}

const CODE_TITLES: Record<string, string> = {
  network_error: '无法连接服务器，请确认后端已启动。',
  retrieval_warming_up: '检索模型正在加载，请稍后重试。',
  qa_rate_limited: '提问过于频繁，请稍后再试。',
  llm_invalid_output: '云端模型返回的内容无法使用，请重试或换一种问法。',
  llm_auth_failed: '云端模型服务认证失败，请联系管理员检查配置。',
  llm_quota_exhausted: '云端模型服务额度已用尽，请联系管理员。',
  llm_rate_limited: '云端模型服务当前请求过多，请稍后重试。',
  llm_unavailable: '云端模型服务暂不可用，请稍后重试。',
  llm_timeout: '云端模型响应超时，请稍后重试。',
}

const STATUS_TITLES: Record<number, string> = {
  401: '登录已失效，请重新登录。',
  403: '无权限提问。',
  422: `问题不合法，请输入 ${QUESTION_MIN_LENGTH}–${QUESTION_MAX_LENGTH} 个字符的问题。`,
  429: '提问过于频繁，请稍后再试。',
  502: '云端模型返回的内容无法使用，请稍后重试。',
  503: '问答服务暂时不可用，请稍后重试。',
  504: '云端模型响应超时，请稍后重试。',
}

export function describeQaError(error: unknown): QaErrorInfo {
  if (error instanceof ApiError) {
    const title = CODE_TITLES[error.code] ?? STATUS_TITLES[error.status] ?? '提问失败，请稍后重试。'
    return {
      status: error.status,
      code: error.code,
      title,
      detail: error.message && error.message !== title ? error.message : '',
      requestId: error.requestId,
      retryable: ![401, 403, 422].includes(error.status),
    }
  }
  return { status: -1, code: '', title: '提问失败，请稍后重试。', detail: '', requestId: null, retryable: true }
}

// ---- 问答日志 ----

export const QA_LOG_STATUS_LABELS: Record<QaLogStatus, string> = {
  answered: '已回答',
  insufficient_evidence: '证据不足',
  llm_invalid_output: '模型输出不合法',
  llm_auth_failed: '模型认证失败',
  llm_quota_exhausted: '模型额度用尽',
  llm_rate_limited: '模型限流',
  llm_unavailable: '模型不可用',
  llm_timeout: '模型超时',
  internal_error: '内部错误',
}

export type LogTagType = 'success' | 'warning' | 'danger' | 'info'

export const QA_LOG_STATUS_TAG_TYPES: Record<QaLogStatus, LogTagType> = {
  answered: 'success',
  insufficient_evidence: 'warning',
  llm_invalid_output: 'danger',
  llm_auth_failed: 'danger',
  llm_quota_exhausted: 'danger',
  llm_rate_limited: 'danger',
  llm_unavailable: 'danger',
  llm_timeout: 'danger',
  internal_error: 'danger',
}

export const QA_LOG_STATUS_OPTIONS = (Object.keys(QA_LOG_STATUS_LABELS) as QaLogStatus[]).map((value) => ({
  value,
  label: QA_LOG_STATUS_LABELS[value],
}))

export function formatMs(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value)} ms` : '-'
}

/** 模型配置的值统一转成文本：标量直接转字符串，对象和数组用 JSON。 */
export function formatConfigValue(value: unknown): string {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

// ---- 问答页的会话内记录 ----

/** 本页会话内的一条问答记录，只保存在内存里，刷新页面后清空。 */
export interface QaEntry {
  id: number
  question: string
  courseId: string | null
  courseName: string
  askedAt: string
  state: 'pending' | 'done' | 'error'
  answer: QaAnswer | null
  error: QaErrorInfo | null
}
