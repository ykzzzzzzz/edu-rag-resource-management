import type { Role } from '../api/types'

export interface NavItem {
  path: string
  title: string
  roles: Role[]
}

export const ROLE_LABELS: Record<Role, string> = {
  student: '学生',
  teacher: '教师',
  admin: '管理员',
}

const ALL_ROLES: Role[] = ['student', 'teacher', 'admin']

/** 侧边菜单与路由共用的单一配置。 */
export const NAV_ITEMS: NavItem[] = [
  { path: '/resources', title: '资源浏览', roles: ALL_ROLES },
  { path: '/qa', title: '问答', roles: ALL_ROLES },
  { path: '/my-resources', title: '我的资源', roles: ['teacher'] },
  { path: '/admin/users', title: '用户管理', roles: ['admin'] },
  { path: '/admin/courses', title: '课程管理', roles: ['admin'] },
  { path: '/admin/reviews', title: '审核管理', roles: ['admin'] },
  { path: '/admin/stats', title: '统计', roles: ['admin'] },
  { path: '/admin/qa-logs', title: '问答日志', roles: ['admin'] },
]
