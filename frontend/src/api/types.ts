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
