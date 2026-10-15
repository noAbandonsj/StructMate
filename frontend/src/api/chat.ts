import { request } from './client'

export type Scope = 'combined' | 'course' | 'personal'
export type Intent = 'explain' | 'hint' | 'example'
export interface Conversation {
  id: string; title: string; scope: Scope; document_ids: string[]
  knowledge_point_id: string | null; archived: boolean; created_at: string; updated_at: string
}
export interface Citation {
  number: number; document_id: string; chunk_id: string; filename: string
  page_number: number | null; heading: string | null; line_start: number | null
  line_end: number | null; text: string; source_deleted: boolean; knowledge_point_id: string | null
}
export interface Message {
  id: string; conversation_id: string; sequence: number; role: 'user' | 'assistant'
  content: string; status: 'generating' | 'completed' | 'failed' | 'cancelled'
  intent: Intent; reply_to_message_id: string | null; citations: Citation[]
  error_code: string | null; error_message: string | null
}
export interface Page<T> { items: T[]; total: number; page: number; page_size: number }
export interface Config { generation_available: boolean; embedding_available: boolean }
export interface Queued { assistant_message_id: string; user_message_id: string; stream_url: string }
const json = (csrf: string, value: unknown, method = 'POST') => ({
  method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, body: JSON.stringify(value),
})
export const config = (signal: AbortSignal) => request<Config>('/conversations/config', { signal })
export const list = (page: number, archived: boolean, signal: AbortSignal) =>
  request<Page<Conversation>>('/conversations?page=' + page + '&archived=' + archived, { signal })
export const detail = (id: string, signal: AbortSignal) => request<Conversation>('/conversations/' + encodeURIComponent(id), { signal })
export const messages = (id: string, page: number, signal: AbortSignal) =>
  request<Page<Message>>('/conversations/' + encodeURIComponent(id) + '/messages?page=' + page + '&page_size=100', { signal })
export const create = (csrf: string, value: unknown, signal: AbortSignal) =>
  request<Conversation>('/conversations', { ...json(csrf, value), signal })
export const update = (csrf: string, id: string, value: unknown, signal: AbortSignal) =>
  request<Conversation>('/conversations/' + encodeURIComponent(id), { ...json(csrf, value, 'PATCH'), signal })
export const send = (csrf: string, id: string, content: string, intent: Intent, key: string, signal: AbortSignal) =>
  request<Queued>('/conversations/' + encodeURIComponent(id) + '/messages', { ...json(csrf, { content, intent, client_request_id: key }), signal })
export const retry = (csrf: string, id: string, key: string, signal: AbortSignal) =>
  request<Queued>('/messages/' + encodeURIComponent(id) + '/retry', { ...json(csrf, { client_request_id: key }), signal })
export const cancel = (csrf: string, id: string, signal: AbortSignal) =>
  request<Message>('/messages/' + encodeURIComponent(id) + '/cancel', { ...json(csrf, {}), signal })

export function follow(id: string, receive: (type: string, value: any) => void, failed: () => void) {
  const stream = new EventSource('/api/v1/messages/' + encodeURIComponent(id) + '/events')
  for (const type of ['snapshot', 'delta', 'citations', 'completed', 'failed', 'cancelled']) {
    stream.addEventListener(type, (event) => {
      try { receive(type, JSON.parse((event as MessageEvent).data)) } catch { failed(); stream.close() }
      if (['completed', 'failed', 'cancelled'].includes(type)) stream.close()
    })
  }
  stream.onerror = () => { stream.close(); failed() }
  return () => stream.close()
}
