import { request } from './http'
import type { CurrentUser, LoginRequest, SystemMode } from './types'

export { ApiError } from './http'
export type * from './types'

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
}
