import { createRouter, createWebHistory } from 'vue-router'

import HomeView from './views/HomeView.vue'
import AuthView from './views/AuthView.vue'
import NotFoundView from './views/NotFoundView.vue'
import SectionView from './views/SectionView.vue'

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
      component: page.name === 'home' ? HomeView : SectionView,
      meta: { title: page.title, description: page.description, requiresAuth: true },
    })),
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
