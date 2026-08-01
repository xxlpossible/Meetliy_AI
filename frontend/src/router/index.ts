// ============================================================
// Vue Router 配置 — 路由定义 + 鉴权守卫
// ============================================================

import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: '登录', requiresAuth: false },
  },
  {
    path: '/',
    redirect: '/dashboard',
  },
  {
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('@/views/DashboardView.vue'),
    meta: { title: '会议工作空间', requiresAuth: true },
  },
  {
    path: '/meeting/room/:meetingId',
    name: 'meeting-room',
    component: () => import('@/views/MeetingRoomView.vue'),
    meta: { title: '实时会议', requiresAuth: true },
  },
  {
    path: '/meeting/detail/:meetingId',
    name: 'meeting-detail',
    component: () => import('@/views/MeetingDetailView.vue'),
    meta: { title: '会议纪要', requiresAuth: true },
  },
  {
    path: '/knowledge',
    name: 'knowledge',
    component: () => import('@/views/KnowledgeView.vue'),
    meta: { title: '知识库', requiresAuth: true },
  },
  {
    path: '/profile',
    name: 'profile',
    component: () => import('@/views/ProfileView.vue'),
    meta: { title: '个人中心', requiresAuth: true },
  },
  {
    path: '/chat',
    name: 'chat',
    component: () => import('@/views/ChatView.vue'),
    meta: { title: 'AI 对话', requiresAuth: true },
  },
  {
    path: '/chat/session/:sessionId',
    name: 'chat-session',
    component: () => import('@/views/ChatView.vue'),
    meta: { title: 'AI 对话', requiresAuth: true },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { title: '页面不存在', requiresAuth: false },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  },
})

// ---- 全局前置守卫：鉴权 ----
router.beforeEach((to, _from, next) => {
  const auth = useAuthStore()

  // 设置页面标题
  document.title = `${to.meta.title || 'Meetily'} — Meetily`

  if (to.meta.requiresAuth && !auth.isLoggedIn) {
    next({ name: 'login', query: { redirect: to.fullPath } })
  } else if (to.name === 'login' && auth.isLoggedIn) {
    next({ name: 'dashboard' })
  } else {
    next()
  }
})

export default router
