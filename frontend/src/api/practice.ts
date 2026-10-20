import { request } from './client'
import type { Page } from './chat'
export interface Material { id: string; filename: string; kind: 'course' | 'personal' }
export interface ReferenceDocument { id: string; filename: string; index_revision: number; content_hash: string }
export interface PracticeSettings {
  question_source: 'ai'; topic: string; document_ids: string[]
  count: number; difficulty: 'basic' | 'intermediate' | 'advanced'; generation_requirements: string
  source_conversation_id?: string | null
}
export interface Practice {
  id: string; title?: string; mode: 'chapter' | 'adaptive' | 'review'; question_source: 'bank' | 'ai' | null
  settings: Partial<PracticeSettings> & { knowledge_point_ids?: string[]; reference_documents?: ReferenceDocument[]; topic_from_materials?: boolean }; source_conversation_id: string | null
  status: 'generating' | 'ready' | 'completed' | 'failed'; actual_count: number; effective_count: number
  submitted_count: number; correct_count: number; notice: string | null; error_message: string | null
  created_at: string
}
export interface Result {
  id: string; answer: string; is_correct: boolean; hinted: boolean; category: string
  is_valid: boolean; reference_answer: string; explanation: string; source_type: 'bank' | 'ai'
  source_info: { topic?: string; basis?: string; reference_documents?: ReferenceDocument[]; sources?: { title: string; url: string; author: string; license: string }[]; citations?: { filename: string; text: string; page_number?: number; heading?: string; source_deleted?: boolean }[] }
  wrong_question_id: string | null; created_at: string
}
export interface Item {
  id: string; question_id: string; position: number; type: string; stem: string
  options: { key: string; text: string }[]; source_type: 'bank' | 'ai'; difficulty: string
  knowledge_point_id: string | null; hinted: boolean; hint: string | null; is_valid: boolean
  disabled_reason: string | null; attempt: Result | null; feedback: { reason: string } | null
}
export interface Wrong {
  id: string; question_id: string; knowledge_point_id: string | null; topic?: string; stem: string; source_type: 'bank' | 'ai'
  status: 'pending' | 'consolidated'; correct_days: number; attempt_count: number; error_count: number
  is_valid: boolean; disabled_reason: string | null; updated_at: string
  question?: { options: { key: string; text: string }[]; answer: string; explanation: string; source_info: Result['source_info'] }
  attempts?: Result[]
}
export interface Performance {
  window_days: number; from_time: string; to_time: string
  items: { knowledge_point_id: string; name: string; sample_count: number; accuracy: number | null; status: string; reason: string }[]
}
function write(csrf: string, value: unknown) {
  return { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, body: JSON.stringify(value) }
}
const path = (id: string) => '/practice-sessions/' + encodeURIComponent(id)
export const config = (signal: AbortSignal) => request<{ generation_available: boolean }>('/practice-sessions/config', { signal })
export async function materials(signal: AbortSignal): Promise<Material[]> {
  const items: Material[] = []
  for (let page = 1; ; page++) {
    const result = await request<Page<Material>>('/practice-sessions/materials?page=' + page + '&page_size=100', { signal })
    items.push(...result.items)
    if (!result.items.length || items.length >= result.total) return items
  }
}
export const list = (page: number, signal: AbortSignal) => request<Page<Practice>>('/practice-sessions?page=' + page, { signal })
export const detail = (id: string, signal: AbortSignal) => request<Practice>(path(id), { signal })
export const items = (id: string, signal: AbortSignal) => request<Page<Item>>(path(id) + '/items', { signal })
export const create = (csrf: string, settings: PracticeSettings, key: string, signal: AbortSignal) =>
  request<Practice>('/practice-sessions', { ...write(csrf, { ...settings, client_request_id: key }), signal })
export const submitAll = (csrf: string, id: string, answers: { practice_item_id: string; answer: string }[], key: string, signal: AbortSignal) =>
  request<{ practice: Practice; items: Item[] }>(path(id) + '/submit', { ...write(csrf, { answers, client_request_id: key }), signal })
export const hint = (csrf: string, id: string, signal: AbortSignal) =>
  request<{ hint: string; hinted: boolean }>('/practice-items/' + encodeURIComponent(id) + '/hint', { ...write(csrf, {}), signal })
export const performance = (signal: AbortSignal) => request<Performance>('/learning/performance', { signal })
export const wrongList = (page: number, status: string, search: string, signal: AbortSignal) =>
  request<Page<Wrong>>('/wrong-questions?page=' + page + (status ? '&status=' + status : '') + (search ? '&search=' + encodeURIComponent(search) : ''), { signal })
export const wrongDetail = (id: string, signal: AbortSignal) => request<Wrong>('/wrong-questions/' + encodeURIComponent(id), { signal })
export const review = (csrf: string, ids: string[], key: string, signal: AbortSignal) =>
  request<Practice>('/wrong-questions/review-sessions', { ...write(csrf, { wrong_question_ids: ids, client_request_id: key }), signal })
