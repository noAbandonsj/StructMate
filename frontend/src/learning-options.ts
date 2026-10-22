export const difficultyOptions = [
  { value: 'basic', label: '基础', help: '侧重概念理解与基本操作' },
  { value: 'intermediate', label: '进阶', help: '侧重应用、推演与复杂度分析' },
  { value: 'advanced', label: '挑战', help: '侧重综合分析与条件辨析' },
] as const

export function recentDateRange(days: 7 | 30, now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now)
  const part = (type: string) => parts.find(value => value.type === type)!.value
  const end = `${part('year')}-${part('month')}-${part('day')}`
  const start = new Date(end + 'T00:00:00Z')
  start.setUTCDate(start.getUTCDate() - days + 1)
  return { from_date: start.toISOString().slice(0, 10), to_date: end }
}

export function practiceSourceLabel(source: string | null) {
  return source === 'ai' ? '实时 AI · 参考答案' : source === 'bank' ? '核验题库' : '错题复习'
}
