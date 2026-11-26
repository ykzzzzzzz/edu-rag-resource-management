import { API_PREFIX, request } from './http'
import type {
  AdminResourceListQuery,
  CourseList,
  CurrentUser,
  LoginRequest,
  MyResourceListQuery,
  Resource,
  ResourceList,
  ResourceListQuery,
  ResourceUpdatePayload,
  ResourceUploadPayload,
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
}
