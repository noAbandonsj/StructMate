import { request } from './client'
import type { Page } from './chat'
import type { Practice } from './practice'

export type Category = 'first_independent' | 'first_hinted' | 'repeat' | 'review'
export interface Measure { count: number; correct_count: number; accuracy: number | null }
export interface Stats {
  from_date: string; to_date: string; time_zone: string; as_of: string
  attempts: Measure; categories: Record<Category, Measure>; sources: Record<'bank' | 'ai', Measure>
  hinted_attempt_count: number
  knowledge_points: { knowledge_point_id: string; name: string; attempts: Measure; independent: Measure; evidence: string }[]
  learning: { asked_questions: number; completed_answers: number; active_days: number; conversation_count: number }
  wrong_questions: { new_in_range: number; current_pending: number }; basis: string
}
export interface Report {
  id: string; client_request_id: string; from_date: string; to_date: string; cutoff_at: string; created_at: string
  generated_at: string | null; status: 'generating' | 'completed' | 'failed'; snapshot: Stats
  content: string; error_code: string | null; error_message: string | null
}
export interface Overview {
  stats: Stats; recent_conversations: { id: string; title: string; updated_at: string }[]
  recent_practices: Practice[]
}
export interface Range { from_date: string; to_date: string }
function parameters(range: Range) {
  const result = new URLSearchParams()
  if (range.from_date) result.set('from_date', range.from_date)
  if (range.to_date) result.set('to_date', range.to_date)
  return result.toString()
}
export const stats = (range: Range, signal: AbortSignal) => request<Stats>('/learning/stats?' + parameters(range), { signal })
export const overview = (signal: AbortSignal) => request<Overview>('/learning/overview', { signal })
export const list = (page: number, signal: AbortSignal) => request<Page<Report>>('/reports?page=' + page, { signal })
export const detail = (id: string, signal: AbortSignal) => request<Report>('/reports/' + encodeURIComponent(id), { signal })
export const create = (csrf: string, range: Range, key: string, signal: AbortSignal) => request<Report>('/reports', {
  method: 'POST', signal, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
  body: JSON.stringify({ from_date: range.from_date || null, to_date: range.to_date || null, client_request_id: key }),
})
export const exportUrl = (id: string) => '/api/v1/reports/' + encodeURIComponent(id) + '/export'
