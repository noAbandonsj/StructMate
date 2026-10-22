import { request } from './client'
import type { Page } from './client'
export interface Material { id: string; filename: string; kind: 'course' | 'personal'; chapter_id: string | null }
export interface ReferenceDocument { id: string; filename: string; index_revision: number; content_hash: string }
export interface PracticeSettings {
  chapter_id: string; document_ids: string[]
  count: number; difficulty: 'basic' | 'intermediate' | 'advanced'; generation_requirements: string
  source_conversation_id?: string | null
}
export interface Practice {
  id: string; title?: string; chapter_id?: string | null; chapter_name?: string | null; mode: 'chapter' | 'review'
  settings: Partial<PracticeSettings> & { reference_documents?: ReferenceDocument[] }; source_conversation_id: string | null
  status: 'generating' | 'ready' | 'completed' | 'failed'; actual_count: number; effective_count: number
  submitted_count: number; correct_count: number; notice: string | null; error_message: string | null
  created_at: string
}
export interface Result {
  id: string; answer: string; is_correct: boolean; hinted: boolean; category: string
  is_valid: boolean; reference_answer: string; explanation: string
  source_info: { basis?: string; reference_documents?: ReferenceDocument[]; citations?: { filename: string; text: string; page_number?: number; heading?: string; source_deleted?: boolean }[] }
  wrong_question_id: string | null; created_at: string
}
export interface Item {
  id: string; question_id: string; position: number; type: string; stem: string
  options: { key: string; text: string }[]; difficulty: string
  chapter_id: string | null; hinted: boolean; hint: string | null; is_valid: boolean
  disabled_reason: string | null; attempt: Result | null
}
export interface Wrong {
  id: string; question_id: string; chapter_id: string | null; chapter_name: string; stem: string
  status: 'pending' | 'consolidated'; correct_days: number; attempt_count: number; error_count: number
  is_valid: boolean; disabled_reason: string | null; updated_at: string
  question?: { options: { key: string; text: string }[]; answer: string; explanation: string; source_info: Result['source_info'] }
  attempts?: Result[]
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
export const wrongList = (page: number, status: string, search: string, signal: AbortSignal, chapter = '') =>
  request<Page<Wrong>>('/wrong-questions?page=' + page + (status ? '&status=' + status : '') + (search ? '&search=' + encodeURIComponent(search) : '') + (chapter ? '&chapter_id=' + encodeURIComponent(chapter) : ''), { signal })
export const wrongDetail = (id: string, signal: AbortSignal) => request<Wrong>('/wrong-questions/' + encodeURIComponent(id), { signal })
export const review = (csrf: string, ids: string[], key: string, signal: AbortSignal) =>
  request<Practice>('/wrong-questions/review-sessions', { ...write(csrf, { wrong_question_ids: ids, client_request_id: key }), signal })
