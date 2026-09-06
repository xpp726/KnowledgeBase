import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue'), meta: { public: true } },
    { path: '/', name: 'chat', component: () => import('../views/ChatView.vue') },
    { path: '/documents', name: 'documents', component: () => import('../views/DocumentsView.vue') },
    { path: '/logs', name: 'logs', component: () => import('../views/LogsView.vue') },
    { path: '/stats', name: 'stats', component: () => import('../views/StatsView.vue') },
    { path: '/settings', name: 'settings', component: () => import('../views/SettingsView.vue'), meta: { requireAdmin: true } },
    { path: '/users', name: 'users', component: () => import('../views/UsersView.vue'), meta: { requireAdmin: true } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

// 全局守卫：未登录跳登录页；admin 页面非 admin 跳首页
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.init()

  if (to.meta.public) {
    // 已登录用户访问登录页，跳首页
    if (auth.token && to.name === 'login') {
      return '/'
    }
    return true
  }

  if (!auth.token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  if (to.meta.requireAdmin && !auth.isAdmin()) {
    return '/'
  }

  return true
})

export default router
