export type Role = 'student' | 'teacher' | 'admin'

export type QaMode = 'demo' | 'cloud'

export interface CurrentUser {
  id: string
  username: string
  display_name: string
  role: Role
}

export interface LoginRequest {
  username: string
  password: string
}

export interface SystemMode {
  qa_mode: QaMode
}

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    request_id: string
  }
}

export type ReviewStatus = 'draft' | 'pending' | 'published' | 'rejected' | 'archived'

export type IndexStatus = 'not_indexed' | 'queued' | 'processing' | 'ready' | 'failed'

export interface Course {
  id: string
  name: string
  description: string | null
  created_at: string
}

export interface CourseList {
  items: Course[]
}

/**
 * 资源响应体。index_error 与 review_reason 只对所有者和管理员有值，其他人为 null。
 * 学生看到的 review_status 恒为 published；是否展示内部状态由页面按角色决定。
 */
export interface Resource {
  id: string
  owner_id: string
  owner_name: string
  course_id: string
  course_name: string
  title: string
  description: string | null
  original_filename: string
  mime_type: string
  size_bytes: number
  review_status: ReviewStatus
  index_status: IndexStatus
  index_error: string | null
  review_reason: string | null
  published_at: string | null
  created_at: string
  updated_at: string
}

export interface ResourceList {
  items: Resource[]
  total: number
  page: number
  page_size: number
}

export interface PageQuery {
  page?: number
  page_size?: number
}

/** GET /resources */
export interface ResourceListQuery extends PageQuery {
  q?: string
  course_id?: string
}

/** GET /resources/mine */
export interface MyResourceListQuery extends PageQuery {
  review_status?: ReviewStatus
}

/** GET /admin/resources */
export interface AdminResourceListQuery extends PageQuery {
  review_status?: ReviewStatus
  index_status?: IndexStatus
  course_id?: string
}

export interface ResourceUploadPayload {
  title: string
  course_id: string
  description?: string
  file: File
}

/** PATCH /resources/{id}：description 传 null 表示清空。 */
export interface ResourceUpdatePayload {
  title?: string
  course_id?: string
  description?: string | null
}

export type ReviewAction = 'approve' | 'reject'

export interface ReviewPayload {
  action: ReviewAction
  reason?: string
}

// ---- M4：问答、出处、日志与统计 ----

/** 问答接口正常返回的两种结果。 */
export type QaAnswerStatus = 'answered' | 'insufficient_evidence'

export type CitationLocatorType = 'pdf_page' | 'docx_paragraph' | 'txt_line'

/** 出处位置：PDF 为页码，DOCX 为段落号，TXT 为行号；start 与 end 均为从 1 开始的闭区间。 */
export interface CitationLocator {
  type: CitationLocatorType
  start: number
  end: number
}

export interface QaCitation {
  number: number
  resource_id: string
  chunk_id: string
  title: string
  course_name: string
  locator: CitationLocator
  excerpt: string
}

/** POST /qa/ask：question 去掉首尾空白后 1–500 字符；course_id 为 null 表示全部课程。 */
export interface QaAskRequest {
  question: string
  course_id: string | null
}

export interface QaAnswer {
  status: QaAnswerStatus
  mode: QaMode
  answer: string
  citations: QaCitation[]
}

/** GET /resources/{id}/citations/{chunk_id} */
export interface CitationDetail {
  resource_id: string
  chunk_id: string
  title: string
  course_name: string
  original_filename: string
  locator: CitationLocator
  content: string
}

export interface CourseStat {
  course_id: string
  course_name: string
  published_resources: number
}

export interface DailyQaStat {
  /** YYYY-MM-DD */
  date: string
  total: number
  insufficient_evidence: number
}

export interface AdminStats {
  days: number
  courses: CourseStat[]
  review_status: Record<ReviewStatus, number>
  index_status: Record<IndexStatus, number>
  daily_qa: DailyQaStat[]
  qa_total: number
  insufficient_evidence_total: number
  /** 0–1 的小数。 */
  insufficient_evidence_ratio: number
}

export type QaLogStatus =
  | 'answered'
  | 'insufficient_evidence'
  | 'llm_invalid_output'
  | 'llm_auth_failed'
  | 'llm_quota_exhausted'
  | 'llm_rate_limited'
  | 'llm_unavailable'
  | 'llm_timeout'
  | 'internal_error'

export interface QaLogRetrieved {
  chunk_id: string
  resource_id: string
  rank: number
  similarity: number
}

export interface QaLogTimings {
  retrieval_ms: number | null
  generation_ms: number | null
  total_ms: number | null
}

export interface QaLogItem {
  id: string
  created_at: string
  course_id: string | null
  course_name: string | null
  question: string
  status: QaLogStatus
  answer: string | null
  retrieved: QaLogRetrieved[]
  cited_chunk_ids: string[]
  timings: QaLogTimings
  model_config: Record<string, unknown>
}

export interface QaLogList {
  items: QaLogItem[]
  total: number
  page: number
  page_size: number
}

/** GET /admin/qa-logs：日期为 YYYY-MM-DD。 */
export interface QaLogQuery extends PageQuery {
  status?: QaLogStatus
  course_id?: string
  date_from?: string
  date_to?: string
}

// ---- M6：用户管理与课程管理 ----

/** 管理员视角的用户。后端不返回密码或哈希。 */
export interface AdminUser extends CurrentUser {
  is_active: boolean
  created_at: string
}

/** GET /admin/users 不分页，一次返回全部符合条件的用户。 */
export interface AdminUserList {
  items: AdminUser[]
}

/** GET /admin/users：按角色、启用状态筛选。 */
export interface AdminUserListQuery {
  role?: Role
  is_active?: boolean
}

/** POST /admin/users：username 3–64 位（后端转小写），display_name 1–64，password 8–128。 */
export interface AdminUserCreatePayload {
  username: string
  display_name: string
  password: string
  role: Role
}

/** PATCH /admin/users/{id}：只传要改的字段，不允许显式 null。 */
export interface AdminUserUpdatePayload {
  display_name?: string
  role?: Role
  is_active?: boolean
}

/** POST /admin/users/{id}/reset-password，成功返回 204。 */
export interface ResetPasswordPayload {
  new_password: string
}

/** POST /courses：name 1–100，description 可选且 ≤500。 */
export interface CourseCreatePayload {
  name: string
  description?: string | null
}

/** PATCH /courses/{id}：name 不能为 null，description 传 null 表示清空。 */
export interface CourseUpdatePayload {
  name?: string
  description?: string | null
}
