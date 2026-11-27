import { API_PREFIX, request } from './http'
import type {
  AdminResourceListQuery,
  AdminStats,
  AdminUser,
  AdminUserCreatePayload,
  AdminUserList,
  AdminUserListQuery,
  AdminUserUpdatePayload,
  CitationDetail,
  Course,
  CourseCreatePayload,
  CourseList,
  CourseUpdatePayload,
  CurrentUser,
  LoginRequest,
  MyResourceListQuery,
  QaAnswer,
  QaAskRequest,
  QaLogList,
  QaLogQuery,
  Resource,
  ResourceList,
  ResourceListQuery,
  ResourceUpdatePayload,
  ResourceUploadPayload,
  ResetPasswordPayload,
  ReviewPayload,
  SystemMode,
} from './types'

export { ApiError } from './http'
export type * from './types'

/** 拼接查询串，跳过 undefined、null 和空字符串。 */
function withQuery(path: string, query?: object): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== '') {
      params.set(key, String(value))
    }
  }
  const text = params.toString()
  return text ? `${path}?${text}` : path
}

/** 资源原件下载地址。同源直接用 <a href>，会话 Cookie 自动携带。 */
export function resourceDownloadUrl(id: string): string {
  return `${API_PREFIX}/resources/${encodeURIComponent(id)}/download`
}

export const api = {
  /** 登录成功后服务端设置 HttpOnly 会话 Cookie。 */
  login(payload: LoginRequest): Promise<CurrentUser> {
    return request<CurrentUser>('POST', '/auth/login', payload)
  },
  /** 撤销会话并清除 Cookie，返回 204。 */
  logout(): Promise<void> {
    return request<void>('POST', '/auth/logout')
  },
  /** 未登录时服务端返回 401。 */
  me(): Promise<CurrentUser> {
    return request<CurrentUser>('GET', '/auth/me')
  },
  systemMode(): Promise<SystemMode> {
    return request<SystemMode>('GET', '/system/mode')
  },

  /** 课程列表（所有登录角色），按名称排序，不分页。 */
  listCourses(): Promise<CourseList> {
    return request<CourseList>('GET', '/courses')
  },
  /** 新建课程（仅管理员），成功返回 201；名称重复返回 409 course_name_taken。 */
  createCourse(payload: CourseCreatePayload): Promise<Course> {
    return request<Course>('POST', '/courses', payload)
  },
  /** 修改课程名称或描述（仅管理员）；description 传 null 清空。 */
  updateCourse(id: string, payload: CourseUpdatePayload): Promise<Course> {
    return request<Course>('PATCH', `/courses/${encodeURIComponent(id)}`, payload)
  },

  /** 用户列表（仅管理员），可按 role、is_active 筛选；后端不分页。 */
  listUsers(query?: AdminUserListQuery): Promise<AdminUserList> {
    return request<AdminUserList>('GET', withQuery('/admin/users', query))
  },
  /** 新建账号（仅管理员），成功返回 201；用户名重复返回 409 username_taken。 */
  createUser(payload: AdminUserCreatePayload): Promise<AdminUser> {
    return request<AdminUser>('POST', '/admin/users', payload)
  },
  /** 修改显示名、角色、启用状态（仅管理员）；停用会撤销该用户全部会话。 */
  updateUser(id: string, payload: AdminUserUpdatePayload): Promise<AdminUser> {
    return request<AdminUser>('PATCH', `/admin/users/${encodeURIComponent(id)}`, payload)
  },
  /** 重置密码并撤销该用户全部会话，成功返回 204。 */
  resetUserPassword(id: string, payload: ResetPasswordPayload): Promise<void> {
    return request<void>('POST', `/admin/users/${encodeURIComponent(id)}/reset-password`, payload)
  },

  /** 已发布资源列表。 */
  listResources(query?: ResourceListQuery): Promise<ResourceList> {
    return request<ResourceList>('GET', withQuery('/resources', query))
  },
  /** 教师本人资源（仅教师）。 */
  listMyResources(query?: MyResourceListQuery): Promise<ResourceList> {
    return request<ResourceList>('GET', withQuery('/resources/mine', query))
  },
  /** 管理员资源列表（仅管理员）。 */
  listAdminResources(query?: AdminResourceListQuery): Promise<ResourceList> {
    return request<ResourceList>('GET', withQuery('/admin/resources', query))
  },
  getResource(id: string): Promise<Resource> {
    return request<Resource>('GET', `/resources/${encodeURIComponent(id)}`)
  },
  /** multipart 上传为草稿，成功返回 201。 */
  uploadResource(payload: ResourceUploadPayload): Promise<Resource> {
    const form = new FormData()
    form.append('title', payload.title)
    form.append('course_id', payload.course_id)
    if (payload.description) {
      form.append('description', payload.description)
    }
    form.append('file', payload.file)
    return request<Resource>('POST', '/resources', form)
  },
  /** 修改本人草稿的元数据。 */
  updateResource(id: string, payload: ResourceUpdatePayload): Promise<Resource> {
    return request<Resource>('PATCH', `/resources/${encodeURIComponent(id)}`, payload)
  },
  /** 草稿提交审核。 */
  submitResource(id: string): Promise<Resource> {
    return request<Resource>('POST', `/resources/${encodeURIComponent(id)}/submit`)
  },
  /** 被驳回的资源退回草稿。 */
  reviseResource(id: string): Promise<Resource> {
    return request<Resource>('POST', `/resources/${encodeURIComponent(id)}/revise`)
  },
  /** 管理员通过或驳回待审核资源；驳回必须带 reason。 */
  reviewResource(id: string, payload: ReviewPayload): Promise<Resource> {
    return request<Resource>('POST', `/admin/resources/${encodeURIComponent(id)}/review`, payload)
  },
  archiveResource(id: string): Promise<Resource> {
    return request<Resource>('POST', `/admin/resources/${encodeURIComponent(id)}/archive`)
  },
  /** 已发布且索引失败的资源重新排队，成功返回 202。 */
  retryResourceIndex(id: string): Promise<Resource> {
    return request<Resource>('POST', `/admin/resources/${encodeURIComponent(id)}/index/retry`)
  },

  /** 提问（所有登录角色）。无依据时 200 + insufficient_evidence，模型故障走 5xx 错误体。 */
  ask(payload: QaAskRequest): Promise<QaAnswer> {
    return request<QaAnswer>('POST', '/qa/ask', payload)
  },
  /** 重新请求某个引用片段；资源已下架、未就绪或片段不属于该资源时返回 404。 */
  getCitation(resourceId: string, chunkId: string): Promise<CitationDetail> {
    return request<CitationDetail>(
      'GET',
      `/resources/${encodeURIComponent(resourceId)}/citations/${encodeURIComponent(chunkId)}`,
    )
  },
  /** 统计数据（仅管理员），days 为 1–180。 */
  getAdminStats(days?: number): Promise<AdminStats> {
    return request<AdminStats>('GET', withQuery('/admin/stats', { days }))
  },
  /** 匿名问答日志（仅管理员）。 */
  listQaLogs(query?: QaLogQuery): Promise<QaLogList> {
    return request<QaLogList>('GET', withQuery('/admin/qa-logs', query))
  },
}
