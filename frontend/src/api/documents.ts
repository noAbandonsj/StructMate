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

export function getDocuments(libraryId: string, page: number, signal: AbortSignal, management = false, filters = { search: '', status: '' }): Promise<DocumentPage> {
  const path = management ? '/admin/course/documents' : '/knowledge-bases/' + encodeURIComponent(libraryId) + '/documents'
  const query = new URLSearchParams({ page: String(page), page_size: '20' })
  if (management && filters.search) query.set('search', filters.search)
  if (management && filters.status) query.set('status', filters.status)
  return request(path + '?' + query, { signal })
}

export function getDocument(id: string, signal: AbortSignal, management = false): Promise<DocumentInfo> {
  return request(documentPath(id, management), { signal })
}

function documentPath(id: string, management = false) {
  return (management ? '/admin/course/documents/' : '/documents/') + encodeURIComponent(id)
}

export interface Attribution { author: string; source: string; license: string }

export function uploadDocument(
  libraryId: string, file: File, pointId: string, csrf: string, signal: AbortSignal,
  management = false, attribution?: Attribution,
): Promise<{ document: DocumentInfo; duplicate: boolean }> {
  const body = new FormData()
  body.append('file', file)
  if (pointId) body.append('knowledge_point_id', pointId)
  if (management && attribution) {
    body.append('author', attribution.author)
    body.append('source', attribution.source)
    body.append('license', attribution.license)
  }
  return request(management ? '/admin/course/documents' : '/knowledge-bases/' + encodeURIComponent(libraryId) + '/documents', {
    method: 'POST', headers: { 'X-CSRF-Token': csrf }, body, signal,
  }, 45000)
}

export function processDocument(id: string, csrf: string, signal: AbortSignal, management = false): Promise<DocumentInfo> {
  return request(documentPath(id, management) + '/process', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: JSON.stringify({ client_request_id: crypto.randomUUID() }), signal,
  })
}

export function deleteDocument(id: string, csrf: string, signal: AbortSignal, management = false): Promise<DocumentInfo> {
  return request(documentPath(id, management), {
    method: 'DELETE', headers: { 'X-CSRF-Token': csrf }, signal,
  })
}

export function documentFileUrl(id: string, download = false, management = false): string {
  return '/api/v1' + documentPath(id, management) + '/file' + (download ? '?download=true' : '')
}

export interface ParsedChunk {
  id: string; text: string; page_number: number | null; heading: string | null; line_start: number | null; line_end: number | null
}
export interface MaintenanceEvent { action: 'upload' | 'process' | 'delete'; actor: string; created_at: string }
export function getCourseHistory(id: string, signal: AbortSignal): Promise<MaintenanceEvent[]> {
  return request(documentPath(id, true) + '/history', { signal })
}
export function getCourseChunks(id: string, page: number, signal: AbortSignal): Promise<{ items: ParsedChunk[]; total: number }> {
  return request(documentPath(id, true) + '/chunks?page=' + page + '&page_size=20', { signal })
}
