import { createRouter, createWebHistory } from 'vue-router'

import HomeView from './views/HomeView.vue'
import NotFoundView from './views/NotFoundView.vue'
import SectionView from './views/SectionView.vue'

export const navigation = [
  { path: '/', name: 'home', title: '学习首页', description: '从课程资料、答疑和练习开始学习。' },
  { path: '/knowledge', name: 'knowledge', title: '我的知识库', description: '使用课程资料，上传并管理自己的学习资料。' },
  { path: '/chat', name: 'chat', title: '学习对话', description: '用自然语言提问，结合真实资料理解数据结构。' },
  { path: '/practice', name: 'practice', title: '练习中心', description: '切换题库出题和实时 AI 出题，按知识点进行练习。' },
  { path: '/wrong', name: 'wrong', title: '错题本', description: '保留错误与复习记录，逐步巩固知识。' },
  { path: '/reports', name: 'reports', title: '学习报告', description: '查看学习统计、总结和推荐资料。' },
] as const

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    ...navigation.map((page) => ({
      path: page.path,
      name: page.name,
      component: page.name === 'home' ? HomeView : SectionView,
      meta: { title: page.title, description: page.description },
    })),
    {
      path: '/:pathMatch(.*)*',
      component: NotFoundView,
      meta: { title: '页面未找到' },
    },
  ],
})
