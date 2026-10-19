export const navigation = [
  { path: '/', name: 'home', title: '学习首页', description: '从课程资料、答疑和练习开始学习。' },
  { path: '/knowledge', name: 'knowledge', title: '我的知识库', description: '使用课程资料，上传并管理自己的学习资料。' },
  { path: '/chat', name: 'chat', title: '学习对话', description: '用自然语言提问，结合真实资料理解数据结构。' },
  { path: '/practice', name: 'practice', title: '练习中心', description: '切换题库出题和实时 AI 出题，按知识点进行练习。' },
  { path: '/wrong', name: 'wrong', title: '错题本', description: '保留错误与复习记录，逐步巩固知识。' },
  { path: '/reports', name: 'reports', title: '学习报告', description: '查看学习统计、总结和推荐资料。' },
] as const

export function safeReturnPath(value: unknown): string {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return '/'
  const path = value.split(/[?#]/, 1)[0]
  if (path === '/admin/course') return value
  if (path && /^\/(chat|practice|wrong|reports)\/[0-9a-f-]{36}$/.test(path)) return value
  return navigation.some((page) => page.path === path) ? value : '/'
}
