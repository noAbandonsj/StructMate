import { onScopeDispose, reactive, watch } from 'vue'

import * as api from '../api/knowledge'
import { ApiError } from '../api/client'
import { authState, restoreAccount } from './auth'

type Status = 'loading' | 'ready' | 'error'
const message = (error: unknown) => error instanceof Error ? error.message : '加载失败，请重试。'
const expired = (error: unknown) => error instanceof ApiError && error.status === 401

export function useKnowledge() {
  const state = reactive<{
    libraries: api.LibraryInfo[]
    chapters: api.Chapter[]
    librariesStatus: Status
    chaptersStatus: Status
    librariesError: string
    chaptersError: string
    selectedId: string | null
    detail: api.LibraryInfo | null
    detailStatus: Status
    detailError: string
  }>({
    libraries: [], chapters: [], librariesStatus: 'loading', chaptersStatus: 'loading',
    librariesError: '', chaptersError: '', selectedId: null, detail: null,
    detailStatus: 'ready', detailError: '',
  })
  let revision = 0
  let detailRevision = 0
  let listController: AbortController | null = null
  let detailController: AbortController | null = null

  async function selectLibrary(id: string) {
    if (!state.libraries.some(library => library.id === id)) return
    const userId = authState.account?.user.id
    const startedAt = ++detailRevision
    detailController?.abort()
    const controller = new AbortController()
    detailController = controller
    state.selectedId = id
    state.detail = null
    state.detailStatus = 'loading'
    state.detailError = ''
    try {
      const detail = await api.getLibrary(id, controller.signal)
      if (startedAt !== detailRevision || userId !== authState.account?.user.id) return
      state.detail = detail
      state.detailStatus = 'ready'
    } catch (error) {
      if (startedAt !== detailRevision || userId !== authState.account?.user.id) return
      if (expired(error)) await restoreAccount(true)
      else {
        state.detailStatus = 'error'
        state.detailError = message(error)
      }
    }
  }

  async function reload() {
    const userId = authState.account?.user.id
    if (!userId) return
    const startedAt = ++revision
    listController?.abort()
    detailController?.abort()
    detailRevision++
    const controller = new AbortController()
    listController = controller
    state.librariesStatus = state.chaptersStatus = 'loading'
    state.librariesError = state.chaptersError = ''
    state.detail = null
    const [libraries, chapters] = await Promise.allSettled([
      api.getLibraries(controller.signal), api.getChapters(controller.signal),
    ])
    if (startedAt !== revision || userId !== authState.account?.user.id) return
    if ([libraries, chapters].some(result => result.status === 'rejected' && expired(result.reason))) {
      await restoreAccount(true)
      return
    }
    if (libraries.status === 'fulfilled') {
      state.libraries = libraries.value
      state.librariesStatus = 'ready'
    } else {
      state.librariesStatus = 'error'
      state.librariesError = message(libraries.reason)
    }
    if (chapters.status === 'fulfilled') {
      state.chapters = chapters.value
      state.chaptersStatus = 'ready'
    } else {
      state.chaptersStatus = 'error'
      state.chaptersError = message(chapters.reason)
    }
    if (libraries.status === 'fulfilled') {
      const selected = state.libraries.find(library => library.id === state.selectedId)
        ?? state.libraries.find(library => library.id === authState.account?.default_knowledge_base.id)
        ?? state.libraries[0]
      state.selectedId = selected?.id ?? null
      if (selected) await selectLibrary(selected.id)
    }
  }

  watch(() => authState.account?.user.id, () => {
    revision++
    detailRevision++
    listController?.abort()
    detailController?.abort()
    state.libraries = []
    state.chapters = []
    state.selectedId = null
    state.detail = null
    state.detailError = ''
    state.detailStatus = 'ready'
    void reload()
  }, { immediate: true })

  onScopeDispose(() => {
    revision++
    detailRevision++
    listController?.abort()
    detailController?.abort()
    state.libraries = []
    state.chapters = []
    state.selectedId = null
    state.detail = null
  })

  return { state, reload, selectLibrary }
}
