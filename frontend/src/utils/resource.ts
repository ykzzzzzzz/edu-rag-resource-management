import type { CurrentUser, IndexStatus, Resource, ReviewStatus } from '../api/types'

export const REVIEW_STATUS_LABELS: Record<ReviewStatus, string> = {
  draft: '草稿',
  pending: '待审核',
  published: '已发布',
  rejected: '已驳回',
  archived: '已下架',
}

export const INDEX_STATUS_LABELS: Record<IndexStatus, string> = {
  not_indexed: '未索引',
  queued: '排队中',
  processing: '处理中',
  ready: '可用于问答',
  failed: '失败',
}

export const REVIEW_STATUS_OPTIONS = (Object.keys(REVIEW_STATUS_LABELS) as ReviewStatus[]).map((value) => ({
  value,
  label: REVIEW_STATUS_LABELS[value],
}))

export const INDEX_STATUS_OPTIONS = (Object.keys(INDEX_STATUS_LABELS) as IndexStatus[]).map((value) => ({
  value,
  label: INDEX_STATUS_LABELS[value],
}))

/** 上传限制。前端只做预检，最终以服务端返回为准。 */
export const ALLOWED_EXTENSIONS = ['.pdf', '.docx', '.txt']
export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024
export const TITLE_MAX_LENGTH = 200
export const DESCRIPTION_MAX_LENGTH = 2000
export const REASON_MAX_LENGTH = 500

/** 人类可读的文件大小。 */
export function formatSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '-'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[unit]}`
}

const dateTimeFormat = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '-' : dateTimeFormat.format(date)
}

/** 预检待上传文件，返回错误文本；通过时返回 null。 */
export function validateUploadFile(file: File): string | null {
  const name = file.name.toLowerCase()
  if (!ALLOWED_EXTENSIONS.some((ext) => name.endsWith(ext))) {
    return '仅支持 .pdf、.docx、.txt 文件'
  }
  if (file.size === 0) {
    return '文件为空'
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return `文件不能超过 ${MAX_UPLOAD_BYTES / 1024 / 1024} MiB`
  }
  return null
}

/** 管理员或资源所有者才能看到审核与索引等内部状态。 */
export function canSeeInternalStatus(user: CurrentUser | null, resource: Resource): boolean {
  return user !== null && (user.role === 'admin' || resource.owner_id === user.id)
}

/**
 * 是否显示下载入口。与服务端可见性规则一致：已发布资源所有登录角色可下载；
 * 其他状态（草稿、待审核、已驳回、已下架）仅所有者教师和管理员可下载原件。
 * 服务端仍会再次校验，不可见时返回 404。
 */
export function canDownload(user: CurrentUser | null, resource: Resource): boolean {
  return resource.review_status === 'published' || canSeeInternalStatus(user, resource)
}
