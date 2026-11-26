import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import AppLayout from '../layouts/AppLayout.vue'
import { NAV_ITEMS } from '../config/navigation'
import { session } from '../stores/session'
import HomeView from '../views/HomeView.vue'
import LoginView from '../views/LoginView.vue'
import PlaceholderView from '../views/PlaceholderView.vue'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: LoginView,
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: AppLayout,
    children: [
      { path: '', name: 'home', component: HomeView, meta: { title: '首页' } },
      ...NAV_ITEMS.map<RouteRecordRaw>((item) => ({
        path: item.path.slice(1),
        name: `nav:${item.path}`,
        component: PlaceholderView,
        meta: { title: item.title, roles: item.roles },
      })),
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

/** 只允许站内路径作为登录后的跳转目标，且不回到登录页。 */
function safeRedirect(value: unknown): string | null {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) {
    return null
  }
  if (value.startsWith('/login')) {
    return null
  }
  return value
}

router.beforeEach(async (to) => {
  if (!session.restored.value) {
    await session.restore()
  }
  const user = session.user.value

  if (to.meta.public) {
    if (user && to.name === 'login') {
      return safeRedirect(to.query.redirect) ?? '/'
    }
    return true
  }

  if (!user) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  const roles = to.meta.roles
  if (roles && !roles.includes(user.role)) {
    return { path: '/' }
  }
  return true
})

router.afterEach((to) => {
  const title = to.meta.title
  document.title = title ? `${title} - 教育资源管理系统` : '教育资源管理系统'
})
