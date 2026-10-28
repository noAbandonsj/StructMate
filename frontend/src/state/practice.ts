import { onScopeDispose, reactive, watch, type Ref } from 'vue'
import * as api from '../api/practice'
import { getChapters, type Chapter } from '../api/knowledge'
import { isValidAnswer, practiceProgress } from '../practice-answers'
import { ApiError } from '../api/client'
import { authState, restoreAccount } from './auth'
import { readDraft, saveDraft } from './learning-drafts'

const defaults = (): api.PracticeSettings => ({
  chapter_id: '', document_ids: [], count: 5,
  difficulty: 'basic', generation_requirements: '',
})
export function usePractice(selected: Ref<string>) {
  const state = reactive({
    form: defaults(), history: [] as api.Practice[], total: 0, page: 1,
    practice: null as api.Practice | null, items: [] as api.Item[], choices: {} as Record<string, string>,
    materials: [] as api.Material[], chapters: [] as Chapter[],
    generationAvailable: false, ready: false, loading: false, busy: false, error: '', readError: '',
  })
  let epoch = 0, readVersion = 0, disposed = false, restoring = false
  let reader = new AbortController(), writer = new AbortController()
  let timer: ReturnType<typeof setTimeout> | null = null
  let pendingCreate: { signature: string; key: string } | null = null
  let pendingSubmit: { signature: string; key: string } | null = null
  const valid = (version: number, user: string | undefined, id: string) =>
    !disposed && version === epoch && user === authState.account?.user.id && id === selected.value
  function stopTimer() { if (timer) clearTimeout(timer); timer = null }
  async function fail(error: unknown) {
    if (error instanceof ApiError && error.status === 401) await restoreAccount(true)
    else state.error = error instanceof Error ? error.message : '操作失败，请重试。'
  }
  function save() {
    if (restoring || disposed) return
    const user = authState.account?.user.id
    if (!user) return
    saveDraft(user, 'form', state.form.generation_requirements, 'practice')
    saveDraft(user, selected.value, JSON.stringify(state.choices), 'practice')
    try { localStorage.setItem('capstone.practice.preferences.' + user, JSON.stringify({ ...state.form, generation_requirements: '', source_conversation_id: null })) } catch { /* Optional preferences. */ }
  }
  async function readContext(signal: AbortSignal) {
    const [history, materials, config, chapters] = await Promise.all([
      api.list(state.page, signal), api.materials(signal), api.config(signal), getChapters(signal),
    ])
    return { history, materials, config, chapters }
  }
  async function reload(background = false) {
    const version = epoch, user = authState.account?.user.id, id = selected.value, readStamp = ++readVersion
    const current = () => valid(version, user, id) && readStamp === readVersion
    if (!user || disposed) return
    reader.abort(); reader = new AbortController(); stopTimer()
    const signal = reader.signal
    if (!background) state.loading = true
    try {
      const [practice, context] = await Promise.all([
        id ? api.detail(id, signal) : Promise.resolve(null),
        background ? Promise.resolve(null) : readContext(signal),
      ])
      // Read items after terminal metadata: generation publishes them atomically.
      // Parallel reads could otherwise pair ready metadata with an earlier empty list.
      const terminal = id && practice?.status !== 'generating'
      const [items, history] = await Promise.all([
        terminal ? api.items(id, signal) : Promise.resolve(null),
        background && terminal ? api.list(state.page, signal) : Promise.resolve(null),
      ])
      if (!current()) return
      if (context) {
        state.history = context.history.items; state.total = context.history.total
        state.materials = context.materials; state.chapters = context.chapters
        state.generationAvailable = context.config.generation_available
        if (!state.form.chapter_id) {
          const material = context.materials.find(item => state.form.document_ids.includes(item.id))
          if (material?.chapter_id) state.form.chapter_id = material.chapter_id
        }
      }
      if (history) { state.history = history.items; state.total = history.total }
      state.practice = practice; state.items = items?.items ?? []
      state.ready = true; state.readError = ''
      for (const item of state.items) {
        if (item.attempt || !item.is_valid || !isValidAnswer(item, state.choices[item.id])) delete state.choices[item.id]
      }
      if (state.practice?.status === 'completed') {
        pendingSubmit = null
        saveDraft(user, 'submit.' + id, '', 'practice')
      }
    } catch (error) {
      if (current() && !signal.aborted) {
        if (error instanceof ApiError && error.status === 401) await restoreAccount(true)
        else state.readError = error instanceof Error ? error.message : '练习读取失败，请重试。'
      }
    }
    finally {
      if (current()) {
        if (!background) state.loading = false
        if (state.practice?.status === 'generating') timer = setTimeout(() => void reload(true), 1500)
      }
    }
  }
  async function mutate<T>(action: (csrf: string, signal: AbortSignal) => Promise<T>) {
    const account = authState.account, version = epoch, id = selected.value
    if (!account || state.busy || disposed) return
    writer = new AbortController(); state.busy = true; state.error = ''
    try {
      const result = await action(account.csrf_token, writer.signal)
      if (valid(version, account.user.id, id)) return result
    } catch (error) { if (valid(version, account.user.id, id)) await fail(error) }
    finally { if (valid(version, account.user.id, id)) state.busy = false }
  }
  async function create(sourceConversationId?: string) {
    if (!state.ready || state.loading || state.readError) return
    if (!state.chapters.some(chapter => chapter.id === state.form.chapter_id)) {
      state.error = '请选择练习章节。'; return
    }
    if (state.form.document_ids.some(id => !state.materials.some(material => material.id === id && (!material.chapter_id || material.chapter_id === state.form.chapter_id)))) {
      state.error = '参考资料已不可用或属于其他章节，请重新选择。'; return
    }
    const settings = { ...state.form, generation_requirements: state.form.generation_requirements.trim(), source_conversation_id: sourceConversationId || null }
    const signature = JSON.stringify(settings)
    if (!pendingCreate || pendingCreate.signature !== signature) pendingCreate = { signature, key: crypto.randomUUID() }
    const result = await mutate((csrf, signal) => api.create(csrf, settings, pendingCreate!.key, signal))
    if (result) pendingCreate = null
    return result
  }
  async function submitAll() {
    const version = epoch, user = authState.account?.user.id, id = selected.value
    if (!user || !id || state.loading || !state.ready || state.readError) return
    const { answers, canSubmit } = practiceProgress(state.items, state.choices)
    if (!canSubmit) {
      state.error = '请完成本组全部有效题目后统一提交。'; return
    }
    const signature = JSON.stringify(answers)
    if (!pendingSubmit || pendingSubmit.signature !== signature) pendingSubmit = { signature, key: crypto.randomUUID() }
    saveDraft(user, 'submit.' + id, JSON.stringify(pendingSubmit), 'practice')
    const result = await mutate((csrf, signal) => api.submitAll(csrf, id, answers, pendingSubmit!.key, signal))
    if (!result || !valid(version, user, id)) return
    state.practice = result.practice; state.items = result.items
    for (const item of result.items) if (item.attempt) delete state.choices[item.id]
    pendingSubmit = null; saveDraft(user, 'submit.' + id, '', 'practice')
    await reload()
  }
  async function hint(item: api.Item) {
    const result = await mutate((csrf, signal) => api.hint(csrf, item.id, signal))
    const current = state.items.find(value => value.id === item.id)
    if (result && current) { current.hinted = true; current.hint = result.hint }
  }
  function restore() {
    restoring = true
    epoch++; readVersion++; reader.abort(); writer.abort(); stopTimer()
    state.form = defaults(); state.practice = null; state.items = []; state.history = []; state.choices = {}; state.ready = false
    state.error = state.readError = ''; state.total = 0; state.page = 1; state.busy = state.loading = false; state.materials = []; state.chapters = []; state.generationAvailable = false
    pendingCreate = null; pendingSubmit = null
    const user = authState.account?.user.id
    if (user) {
      try {
        const value = JSON.parse(localStorage.getItem('capstone.practice.preferences.' + user) || '{}')
        if (['basic', 'intermediate', 'advanced'].includes(value.difficulty)) state.form.difficulty = value.difficulty
        if (Number.isInteger(value.count) && value.count >= 1 && value.count <= 20) state.form.count = value.count
        if (typeof value.chapter_id === 'string') state.form.chapter_id = value.chapter_id
        if (Array.isArray(value.document_ids)) state.form.document_ids = value.document_ids.filter((value: unknown) => typeof value === 'string').slice(0, 5)
      } catch { /* Use validated defaults. */ }
      try {
        const pending = JSON.parse(readDraft(user, 'submit.' + selected.value, 'practice') || 'null')
        if (pending && typeof pending.signature === 'string' && typeof pending.key === 'string') pendingSubmit = pending
      } catch { pendingSubmit = null }
      state.form.generation_requirements = readDraft(user, 'form', 'practice').slice(0, 1000)
      try {
        const choices = JSON.parse(readDraft(user, selected.value, 'practice') || '{}')
        if (choices && typeof choices === 'object' && !Array.isArray(choices)) state.choices = choices
      } catch { state.choices = {} }
      void reload()
    }
    restoring = false
  }
  watch([() => authState.account?.user.id, selected], restore, { immediate: true })
  watch([() => state.form, () => state.choices], save, { deep: true, flush: 'sync' })
  onScopeDispose(() => { disposed = true; restoring = true; epoch++; reader.abort(); writer.abort(); stopTimer(); state.items = []; state.history = []; state.choices = {} })
  return { state, reload, create, submitAll, hint }
}
