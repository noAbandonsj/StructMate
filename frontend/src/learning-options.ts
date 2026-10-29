export const difficultyOptions = [
  { value: 'basic', label: '基础' },
  { value: 'intermediate', label: '进阶' },
  { value: 'advanced', label: '挑战' },
] as const

export function recentDateRange(days: 7 | 30, now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now)
  const part = (type: string) => parts.find(value => value.type === type)!.value
  const end = `${part('year')}-${part('month')}-${part('day')}`
  const start = new Date(end + 'T00:00:00Z')
  start.setUTCDate(start.getUTCDate() - days + 1)
  return { from_date: start.toISOString().slice(0, 10), to_date: end }
}
