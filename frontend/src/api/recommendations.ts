import { request } from './client'
export interface Recommendation {
  id: string; kind: 'document' | 'external'; title: string; description: string; url: string
  chapter_id: string | null; difficulty: string | null; language: string; reasons: string[]
  source_info: { author?: string; license?: string; checked_on?: string } | null
  document_id?: string; chunk_id?: string; heading?: string | null; page_number?: number | null
  line_start?: number | null; line_end?: number | null
}
export interface Chunk { id: string; text: string; heading: string | null; page_number: number | null; line_start: number | null; line_end: number | null }
export const list = (point: string, difficulty: string, signal: AbortSignal) =>
  request<{ items: Recommendation[]; basis: string }>('/recommendations?difficulty=' + encodeURIComponent(difficulty) + (point ? '&chapter_id=' + encodeURIComponent(point) : ''), { signal })
export const chunk = (document: string, id: string, signal: AbortSignal) =>
  request<Chunk>('/documents/' + encodeURIComponent(document) + '/chunks/' + encodeURIComponent(id), { signal })
