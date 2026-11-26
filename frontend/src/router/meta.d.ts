import type { Role } from '../api/types'

declare module 'vue-router' {
  interface RouteMeta {
    /** 页面标题，同时用于浏览器标签页与占位页。 */
    title?: string
    /** 允许访问的角色；缺省表示任何已登录用户可访问。 */
    roles?: Role[]
    /** 不需要登录的页面，例如登录页。 */
    public?: boolean
  }
}
