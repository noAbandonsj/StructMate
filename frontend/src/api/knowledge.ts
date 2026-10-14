import { request } from './client'

export interface LibraryInfo {
  id: string
  kind: 'personal' | 'course'
  name: string
  is_readonly: boolean
  created_at: string
}

export interface KnowledgePoint {
  id: string
  code: string
  name: string
  parent_id: string | null
  sort_order: number
}

interface Page<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}

async function allItems<T>(path: string, signal: AbortSignal): Promise<T[]> {
  const items: T[] = []
  for (let page = 1; ; page++) {
    const result = await request<Page<T>>(path + '?page=' + page + '&page_size=100', { signal })
    items.push(...result.items)
    if (items.length >= result.total || result.items.length === 0) return items
  }
}

export function getLibraries(signal: AbortSignal): Promise<LibraryInfo[]> {
  return allItems('/knowledge-bases', signal)
}

export function getPoints(signal: AbortSignal): Promise<KnowledgePoint[]> {
  return allItems('/knowledge-points', signal)
}

export function getLibrary(id: string, signal: AbortSignal): Promise<LibraryInfo> {
  return request('/knowledge-bases/' + encodeURIComponent(id), { signal })
}
