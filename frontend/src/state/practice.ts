import { onScopeDispose, reactive, watch, type Ref } from 'vue'
import * as api from '../api/practice'
import { getPoints, type KnowledgePoint } from '../api/knowledge'
import { ApiError } from '../api/client'
import { authState, restoreAccount } from './auth'
import { readDraft, saveDraft } from './learning-drafts'

const defaults = (): api.PracticeSettings => ({
  question_source: 'bank', mode: 'chapter', knowledge_point_ids: [], count: 5,
  difficulty: 'basic', generation_requirements: '',
})
export function usePractice(selected: Ref<string>) {
  const state = reactive({
    form: defaults(), history: [] as api.Practice[], total: 0, page: 1,
    practice: null as api.Practice | null, items: [] as api.Item[], choices: {} as Record<string, string>,
    points: [] as KnowledgePoint[], analysis: null as api.Performance | null,
    generationAvailable: false, loading: false, busy: false, error: '', readError: '',
  })
  let epoch = 0, readVersion = 0, disposed = false, restoring = false
  let reader = new AbortController(), writer = new AbortController()
  let timer: ReturnType<typeof setTimeout> | null = null
  let pendingCreate: { signature: string; key: string } | null = null
  const answerKeys = new Map<string, { answer: string; key: string }>()
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
  async function reload() {
    const version = epoch, user = authState.account?.user.id, id = selected.value, readStamp = ++readVersion
    const current = () => valid(version, user, id) && readStamp === readVersion
    if (!user || disposed) return
    reader.abort(); reader = new AbortController(); stopTimer()
    const signal = reader.signal
    state.loading = true
    state.readError = ''
    try {
      const [history, points, config, analysis, practice] = await Promise.all([
        api.list(state.page, signal), getPoints(signal), api.config(signal), api.performance(signal),
        id ? api.detail(id, signal) : Promise.resolve(null),
      ])
      // Read items after terminal metadata: generation publishes them atomically.
      // Parallel reads could otherwise pair ready metadata with an earlier empty list.
      const items = id && practice?.status !== 'generating' ? await api.items(id, signal) : null
      if (!current()) return
      state.history = history.items; state.total = history.total; state.points = points
      state.generationAvailable = config.generation_available; state.analysis = analysis
      state.practice = practice; state.items = items?.items ?? []
      for (const item of state.items) {
        if (item.attempt || !item.is_valid || !item.options.some(option => option.key === state.choices[item.id])) delete state.choices[item.id]
      }
    } catch (error) {
      if (current() && !signal.aborted) {
        if (error instanceof ApiError && error.status === 401) await restoreAccount(true)
        else state.readError = error instanceof Error ? error.message : '练习读取失败，请重试。'
      }
    }
    finally {
      if (current()) {
        state.loading = false
        if (state.practice?.status === 'generating') timer = setTimeout(() => void reload(), 1500)
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
    const settings = { ...state.form, generation_requirements: state.form.question_source === 'ai' ? state.form.generation_requirements : '', source_conversation_id: sourceConversationId || null }
    const signature = JSON.stringify(settings)
    if (!pendingCreate || pendingCreate.signature !== signature) pendingCreate = { signature, key: crypto.randomUUID() }
    const result = await mutate((csrf, signal) => api.create(csrf, settings, pendingCreate!.key, signal))
    if (result) pendingCreate = null
    return result
  }
  async function submit(item: api.Item) {
    const answer = state.choices[item.id], version = epoch, user = authState.account?.user.id, id = selected.value
    if (!answer || item.attempt || !item.is_valid) return
    let pending = answerKeys.get(item.id)
    if (!pending || pending.answer !== answer) { pending = { answer, key: crypto.randomUUID() }; answerKeys.set(item.id, pending) }
    const result = await mutate((csrf, signal) => api.submit(csrf, item.id, answer, pending!.key, signal))
    if (!result || !valid(version, user, id)) return
    item.attempt = result; delete state.choices[item.id]; answerKeys.delete(item.id)
    await reload()
  }
  async function hint(item: api.Item) {
    const result = await mutate((csrf, signal) => api.hint(csrf, item.id, signal))
    const current = state.items.find(value => value.id === item.id)
    if (result && current) { current.hinted = true; current.hint = result.hint }
  }
  async function feedback(item: api.Item, reason: string) {
    const result = await mutate((csrf, signal) => api.feedback(csrf, item.id, reason, signal))
    const current = state.items.find(value => value.id === item.id)
    if (result && current) current.feedback = result
  }
  function restore() {
    restoring = true
    epoch++; readVersion++; reader.abort(); writer.abort(); stopTimer()
    state.form = defaults(); state.practice = null; state.items = []; state.history = []; state.choices = {}
    state.error = state.readError = ''; state.total = 0; state.page = 1; state.busy = state.loading = false; state.points = []; state.analysis = null; state.generationAvailable = false
    pendingCreate = null; answerKeys.clear()
    const user = authState.account?.user.id
    if (user) {
      try {
        const value = JSON.parse(localStorage.getItem('capstone.practice.preferences.' + user) || '{}')
        if (['bank', 'ai'].includes(value.question_source)) state.form.question_source = value.question_source
        if (['chapter', 'adaptive'].includes(value.mode)) state.form.mode = value.mode
        if (['basic', 'intermediate', 'advanced'].includes(value.difficulty)) state.form.difficulty = value.difficulty
        if (Number.isInteger(value.count) && value.count >= 1 && value.count <= 20) state.form.count = value.count
        if (Array.isArray(value.knowledge_point_ids)) state.form.knowledge_point_ids = value.knowledge_point_ids.filter((value: unknown) => typeof value === 'string')
      } catch { /* Use validated defaults. */ }
      state.form.generation_requirements = readDraft(user, 'form', 'practice')
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
  return { state, reload, create, submit, hint, feedback }
}
