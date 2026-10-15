import { createRouter, createWebHistory } from 'vue-router'

import HomeView from './views/HomeView.vue'
import AuthView from './views/AuthView.vue'
import NotFoundView from './views/NotFoundView.vue'
import SectionView from './views/SectionView.vue'
import KnowledgeView from './views/KnowledgeView.vue'
import ChatView from './views/ChatView.vue'
import PracticeView from './views/PracticeView.vue'
import WrongView from './views/WrongView.vue'
import ReportsView from './views/ReportsView.vue'

import { navigation, safeReturnPath } from './navigation'
import { authState, restoreAccount } from './state/auth'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: AuthView,
      meta: { title: '登录', authPage: true },
    },
    {
      path: '/register',
      name: 'register',
      component: AuthView,
      meta: { title: '注册', authPage: true },
    },
    ...navigation.map((page) => ({
      path: page.path,
      name: page.name,
      component: page.name === 'home' ? HomeView : page.name === 'knowledge' ? KnowledgeView : page.name === 'chat' ? ChatView : page.name === 'practice' ? PracticeView : page.name === 'wrong' ? WrongView : page.name === 'reports' ? ReportsView : SectionView,
      meta: { title: page.title, description: page.description, requiresAuth: true },
    })),
    { path: '/chat/:id', component: ChatView, meta: { title: '学习对话', requiresAuth: true } },
    { path: '/practice/:id', component: PracticeView, meta: { title: '练习中心', requiresAuth: true } },
    { path: '/wrong/:id', component: WrongView, meta: { title: '错题本', requiresAuth: true } },
    { path: '/reports/:id', component: ReportsView, meta: { title: '学习报告', requiresAuth: true } },
    {
      path: '/:pathMatch(.*)*',
      component: NotFoundView,
      meta: { title: '页面未找到' },
    },
  ],
})

router.beforeEach(async (to) => {
  await restoreAccount()
  if (authState.status === 'error') return true
  if (to.meta.requiresAuth && !authState.account) {
    return { name: 'login', query: { redirect: safeReturnPath(to.fullPath) } }
  }
  if (to.meta.authPage && authState.account) return safeReturnPath(to.query.redirect)
  return true
})
