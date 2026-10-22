import { onScopeDispose, reactive, watch, type Ref } from 'vue'

import * as api from '../api/documents'
import type { LibraryInfo } from '../api/knowledge'
import { ApiError } from '../api/client'
import { authState, restoreAccount } from './auth'

export function useDocuments(library: Ref<LibraryInfo>, management = false) {
  const state = reactive<{
    documents: api.DocumentInfo[]
    config: api.UploadConfig | null
    total: number
    page: number
    loading: boolean
    busy: boolean
    error: string
    actionError: string
    notice: string
    deletion: api.DocumentInfo | null
    filters: { search: string; status: string; chapterId: string }
  }>({
    documents: [], config: null, total: 0, page: 1, loading: false, busy: false,
    error: '', actionError: '', notice: '', deletion: null,
    filters: { search: '', status: '', chapterId: '' },
  })
  let epoch = 0
  let readVersion = 0
  let reader: AbortController | null = null
  let writer: AbortController | null = null
  let timer: ReturnType<typeof setTimeout> | null = null
  let disposed = false

  function valid(start: number, userId: string | undefined, libraryId: string) {
    return !disposed && start === epoch && userId === authState.account?.user.id && libraryId === library.value.id
  }
  function stopTimer() {
    if (timer) clearTimeout(timer)
    timer = null
  }
  function pollLater() {
    stopTimer()
    if (!disposed && authState.account) timer = setTimeout(() => void reload(false), 2000)
  }
  async function fail(error: unknown, mutation = false) {
    if (error instanceof ApiError && (error.status === 401 || (management && error.status === 403))) await restoreAccount(true)
    else {
      const message = error instanceof Error ? error.message : '操作失败，请重试。'
      if (mutation) state.actionError = message
      else state.error = message
    }
  }

  async function reload(showLoading = true) {
    const userId = authState.account?.user.id
    if (!userId || disposed) return
    const libraryId = library.value.id
    const startedAt = epoch
    const version = ++readVersion
    reader?.abort()
    const controller = new AbortController()
    reader = controller
    stopTimer()
    if (showLoading) state.loading = true
    state.error = ''
    try {
      const [documents, config] = await Promise.all([
        api.getDocuments(libraryId, state.page, controller.signal, management, state.filters), api.getUploadConfig(controller.signal),
      ])
      if (!valid(startedAt, userId, libraryId) || version !== readVersion) return
      if (state.page > 1 && !documents.items.length) {
        state.page--
        await reload(showLoading)
        return
      }
      state.documents = documents.items
      state.total = documents.total
      state.config = config
      if (state.deletion) {
        const deleted = await api.getDocument(state.deletion.id, controller.signal, management)
        if (!valid(startedAt, userId, libraryId) || version !== readVersion) return
        state.deletion = deleted
        if (deleted.stage === 'complete') {
          state.deletion = null
          state.notice = '原文件与向量已清理，历史学习记录仍保留。'
        }
      }
    } catch (error) {
      if (valid(startedAt, userId, libraryId) && version === readVersion) await fail(error)
    } finally {
      if (valid(startedAt, userId, libraryId) && version === readVersion) {
        state.loading = false
        pollLater()
      }
    }
  }

  async function mutate<T>(action: (csrf: string, signal: AbortSignal) => Promise<T>): Promise<T | undefined> {
    const account = authState.account
    if (!account || disposed || state.busy || (management ? account.user.role !== 'admin' : library.value.is_readonly)) return
    const libraryId = library.value.id
    const startedAt = epoch
    const controller = new AbortController()
    writer = controller
    state.busy = true
    state.actionError = state.notice = ''
    try {
      const result = await action(account.csrf_token, controller.signal)
      if (!valid(startedAt, account.user.id, libraryId)) return
      return result
    } catch (error) {
      if (valid(startedAt, account.user.id, libraryId)) await fail(error, true)
    } finally {
      if (valid(startedAt, account.user.id, libraryId)) state.busy = false
    }
  }

  async function upload(file: File, chapterId: string, attribution?: api.Attribution) {
    const libraryId = library.value.id
    const userId = authState.account?.user.id
    const startedAt = epoch
    const result = await mutate((csrf, signal) => api.uploadDocument(libraryId, file, chapterId, csrf, signal, management, attribution))
    if (!valid(startedAt, userId, libraryId)) return false
    if (result) {
      state.notice = result.duplicate ? '同内容资料已存在，可以查看已有文件。' : '文件已保存，请查看处理状态；就绪后可用于学习。'
      state.page = 1
      if (management) state.filters = { ...state.filters, search: '', status: '' }
      await reload(false)
      return true
    }
    return false
  }
  async function process(id: string) {
    const startedAt = epoch
    const userId = authState.account?.user.id
    const libraryId = library.value.id
    const result = await mutate((csrf, signal) => api.processDocument(id, csrf, signal, management))
    if (!valid(startedAt, userId, libraryId)) return
    if (result) {
      state.notice = '已重新提交处理。'
      await reload(false)
    }
  }
  async function remove(id: string) {
    const startedAt = epoch
    const userId = authState.account?.user.id
    const libraryId = library.value.id
    const result = await mutate((csrf, signal) => api.deleteDocument(id, csrf, signal, management))
    if (!valid(startedAt, userId, libraryId)) return
    if (result) {
      state.deletion = result
      state.notice = '资料已停止检索，正在清理原文件与向量。'
      await reload(false)
    }
  }
  async function setPage(page: number) {
    if (page < 1 || page > Math.max(1, Math.ceil(state.total / 20))) return
    state.page = page
    await reload()
  }

  function reset() {
    epoch++
    readVersion++
    reader?.abort()
    writer?.abort()
    stopTimer()
    state.documents = []
    state.config = state.deletion = null
    state.total = 0
    state.page = 1
    state.error = state.actionError = state.notice = ''
    state.busy = state.loading = false
  }
  watch([() => authState.account?.user.id, () => library.value.id], () => {
    reset()
    if (authState.account) void reload()
  }, { immediate: true })
  onScopeDispose(() => { disposed = true; reset() })
  async function setFilters(search: string, status: string, chapterId = state.filters.chapterId) {
    state.filters = { search: search.trim(), status, chapterId }
    state.page = 1
    await reload()
  }
  return { state, reload, upload, process, remove, setPage, setFilters }
}
