import { request } from './client'

export interface DocumentInfo {
  id: string
  knowledge_base_id: string
  knowledge_point_id: string | null
  filename: string
  file_type: 'pdf' | 'txt' | 'md'
  size_bytes: number
  status: 'processing' | 'ready' | 'failed' | 'deleted'
  stage: string
  error_code: string | null
  error_message: string | null
  retryable: boolean
  source_info: { sources?: { title: string; author: string; license: string; url: string }[] } | null
  created_at: string
  updated_at: string
}

export interface UploadConfig {
  max_mib: number
  extensions: string[]
  embedding_available: boolean
}

export interface DocumentPage {
  items: DocumentInfo[]
  page: number
  page_size: number
  total: number
}

export function getUploadConfig(signal: AbortSignal): Promise<UploadConfig> {
  return request('/documents/upload-config', { signal })
}

export function getDocuments(libraryId: string, page: number, signal: AbortSignal): Promise<DocumentPage> {
  return request('/knowledge-bases/' + encodeURIComponent(libraryId) + '/documents?page=' + page + '&page_size=20', { signal })
}

export function getDocument(id: string, signal: AbortSignal): Promise<DocumentInfo> {
  return request('/documents/' + encodeURIComponent(id), { signal })
}

export function uploadDocument(
  libraryId: string, file: File, pointId: string, csrf: string, signal: AbortSignal,
): Promise<{ document: DocumentInfo; duplicate: boolean }> {
  const body = new FormData()
  body.append('file', file)
  if (pointId) body.append('knowledge_point_id', pointId)
  return request('/knowledge-bases/' + encodeURIComponent(libraryId) + '/documents', {
    method: 'POST', headers: { 'X-CSRF-Token': csrf }, body, signal,
  }, 45000)
}

export function processDocument(id: string, csrf: string, signal: AbortSignal): Promise<DocumentInfo> {
  return request('/documents/' + encodeURIComponent(id) + '/process', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: JSON.stringify({ client_request_id: crypto.randomUUID() }), signal,
  })
}

export function deleteDocument(id: string, csrf: string, signal: AbortSignal): Promise<DocumentInfo> {
  return request('/documents/' + encodeURIComponent(id), {
    method: 'DELETE', headers: { 'X-CSRF-Token': csrf }, signal,
  })
}

export function documentFileUrl(id: string, download = false): string {
  return '/api/v1/documents/' + encodeURIComponent(id) + '/file' + (download ? '?download=true' : '')
}
