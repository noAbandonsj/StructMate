import { computed, onScopeDispose, reactive, watch, type Ref } from 'vue'
import * as api from '../api/chat'
import { ApiError } from '../api/client'
import { authState, restoreAccount } from './auth'
import { readDraft, saveDraft } from './learning-drafts'

export function useChat(selected: Ref<string>) {
  const state = reactive({
    conversations: [] as api.Conversation[], total: 0, page: 1,
    conversation: null as api.Conversation | null, messages: [] as api.Message[],
    config: null as api.Config | null, loading: false, busy: false, error: '', streamError: '',
    draft: '', historyPage: 1,
    summary: null as api.Summary | null, summaryError: '', summaryLoading: false,
  })
  let epoch = 0, readVersion = 0, disposed = false
  let reader = new AbortController(), writer = new AbortController()
  let closeStream: (() => void) | null = null
  let streamVersion = 0
  let pending: { content: string; key: string } | null = null
  let restoringDraft = false
  let summaryVersion = 0, summaryReader = new AbortController()
  let summaryTimer: ReturnType<typeof setTimeout> | null = null
  let pendingSummaryKey: string | null = null
  const retryKeys = new Map<string, string>()
  const active = computed(() => state.messages.find(message => message.status === 'generating'))
  const valid = (version: number, user: string | undefined, id: string) =>
    !disposed && version === epoch && authState.account?.user.id === user && selected.value === id
  async function failure(error: unknown) {
    if (error instanceof ApiError && error.status === 401) await restoreAccount(true)
    else state.error = error instanceof Error ? error.message : '操作失败，请重试。'
  }
  function follow(messageId: string) {
    closeStream?.()
    const streamStartedAt = ++streamVersion
    state.streamError = ''
    const version = epoch, user = authState.account?.user.id, id = selected.value
    closeStream = api.follow(messageId, (type, value) => {
      if (!valid(version, user, id) || streamStartedAt !== streamVersion) return
      if (value.code === 'LOGIN_REQUIRED') { void restoreAccount(true); return }
      const index = state.messages.findIndex(message => message.id === messageId)
      if (index < 0) return
      if (type === 'delta') state.messages[index]!.content += value.text
      else if (type === 'citations') state.messages[index]!.citations = value
      else state.messages[index] = value
    }, () => { if (valid(version, user, id) && streamStartedAt === streamVersion) state.streamError = '连接已断开，已生成内容保留。重新连接不会重复提问。' })
  }
  async function loadHistory(signal: AbortSignal, version: number, user: string | undefined, id: string, readStamp: number) {
    let result = await api.messages(id, 1, signal)
    if (result.total > 100) result = await api.messages(id, Math.ceil(result.total / 100), signal)
    if (!valid(version, user, id) || readStamp !== readVersion) return
    state.messages = result.items
    state.historyPage = result.page
    const generating = result.items.find(message => message.status === 'generating')
    if (generating) follow(generating.id)
  }
  async function reload() {
    const version = epoch, user = authState.account?.user.id, id = selected.value
    const readStamp = ++readVersion
    const summaryStamp = ++summaryVersion
    summaryReader.abort(); stopSummaryTimer(); state.summaryLoading = false
    const current = () => valid(version, user, id) && readStamp === readVersion
    reader.abort(); reader = new AbortController()
    const signal = reader.signal
    state.loading = true; state.error = ''
    try {
      const [conversations, config, conversation, summary] = await Promise.all([
        api.list(state.page, signal), api.config(signal),
        id ? api.detail(id, signal) : Promise.resolve(null),
        id ? api.summary(id, signal) : Promise.resolve(null),
      ])
      if (!current()) return
      state.conversations = conversations.items; state.total = conversations.total
      state.config = config; state.conversation = conversation
      if (summaryStamp === summaryVersion) acceptSummary(summary)
      if (id) await loadHistory(signal, version, user, id, readStamp)
    } catch (error) { if (current() && !signal.aborted) await failure(error) }
    finally { if (current()) state.loading = false }
  }
  function stopSummaryTimer() { if (summaryTimer) clearTimeout(summaryTimer); summaryTimer = null }
  function acceptSummary(summary: api.Summary | null) {
    if (pendingSummaryKey && summary?.client_request_id === pendingSummaryKey) pendingSummaryKey = null
    state.summary = summary; state.summaryError = ''
    stopSummaryTimer()
    if (summary?.status === 'generating') summaryTimer = setTimeout(() => void refreshSummary(), 1500)
  }
  async function refreshSummary() {
    const version = epoch, user = authState.account?.user.id, id = selected.value, stamp = ++summaryVersion
    if (!user || !id || disposed) return
    summaryReader.abort(); summaryReader = new AbortController(); stopSummaryTimer()
    const signal = summaryReader.signal
    state.summaryLoading = true; state.summaryError = ''
    try {
      const summary = await api.summary(id, signal)
      if (valid(version, user, id) && stamp === summaryVersion) acceptSummary(summary)
    } catch (error) {
      if (valid(version, user, id) && stamp === summaryVersion && !signal.aborted) {
        if (error instanceof ApiError && error.status === 401) await restoreAccount(true)
        else state.summaryError = error instanceof Error ? error.message : '总结读取失败，请刷新。'
      }
    } finally { if (valid(version, user, id) && stamp === summaryVersion) state.summaryLoading = false }
  }
  async function generateSummary() {
    if (!selected.value || state.summary?.status === 'generating') return
    const version = epoch, user = authState.account?.user.id, id = selected.value
    summaryVersion++; summaryReader.abort(); stopSummaryTimer(); state.summaryLoading = false
    pendingSummaryKey ??= crypto.randomUUID()
    const key = pendingSummaryKey
    const result = await mutate((csrf, signal) => api.generateSummary(csrf, id, key, signal))
    if (result && valid(version, user, id)) { pendingSummaryKey = null; acceptSummary(result) }
  }
  async function mutate<T>(action: (csrf: string, signal: AbortSignal) => Promise<T>): Promise<T | undefined> {
    const account = authState.account, version = epoch, id = selected.value
    if (!account || state.busy || disposed) return
    writer = new AbortController(); state.busy = true; state.error = ''
    try {
      const result = await action(account.csrf_token, writer.signal)
      if (valid(version, account.user.id, id)) return result
    } catch (error) { if (valid(version, account.user.id, id)) await failure(error) }
    finally { if (valid(version, account.user.id, id)) state.busy = false }
  }
  async function create(documentIds: string[] = [], chapterId?: string) {
    return mutate((csrf, signal) => api.create(csrf, { document_ids: documentIds, chapter_id: chapterId || null }, signal))
  }
  async function send() {
    const content = state.draft.trim(), version = epoch, user = authState.account?.user.id, id = selected.value
    if (!content || !id || active.value || state.conversation?.archived) return
    if (!pending || pending.content !== content)
      pending = { content, key: crypto.randomUUID() }
    const request = pending
    const result = await mutate((csrf, signal) => api.send(csrf, id, content, request.key, signal))
    if (!result || !valid(version, user, id)) return
    pending = null
    if (state.draft.trim() === content) state.draft = ''
    await reload()
  }
  async function retry(messageId: string) {
    const version = epoch, user = authState.account?.user.id, id = selected.value
    if (active.value) return
    const key = retryKeys.get(messageId) ?? crypto.randomUUID()
    retryKeys.set(messageId, key)
    const result = await mutate((csrf, signal) => api.retry(csrf, messageId, key, signal))
    if (!result || !valid(version, user, id)) return
    retryKeys.delete(messageId)
    await reload()
  }
  async function cancel() {
    const message = active.value
    if (!message) return
    const result = await mutate((csrf, signal) => api.cancel(csrf, message.id, signal))
    if (result) {
      const index = state.messages.findIndex(item => item.id === result.id)
      if (index >= 0) state.messages[index] = result
      closeStream?.()
    }
  }
  async function update(values: api.ConversationPatch, identifier = selected.value) {
    const id = selected.value, version = epoch, user = authState.account?.user.id
    const result = await mutate((csrf, signal) => api.update(csrf, identifier, values, signal))
    if (result) {
      if (identifier === id) state.conversation = result
      if (values.archived !== undefined) state.page = 1
      await reload()
      if (valid(version, user, id)) return result
    }
  }
  async function older() {
    if (state.historyPage <= 1 || state.loading) return
    const version = epoch, user = authState.account?.user.id, id = selected.value
    const readStamp = readVersion
    const current = () => valid(version, user, id) && readStamp === readVersion
    state.loading = true
    try {
      const result = await api.messages(id, state.historyPage - 1, reader.signal)
      if (current()) { state.messages = [...result.items, ...state.messages]; state.historyPage = result.page }
    } catch (error) { if (current()) await failure(error) }
    finally { if (current()) state.loading = false }
  }
  function reset() {
    restoringDraft = true
    summaryVersion++; summaryReader.abort(); stopSummaryTimer(); pendingSummaryKey = null
    state.summary = null; state.summaryError = ''; state.summaryLoading = false
    streamVersion++
    epoch++; readVersion++; reader.abort(); writer.abort(); closeStream?.(); closeStream = null
    state.conversations = []; state.messages = []; state.conversation = state.config = null
    state.total = 0; state.error = state.streamError = ''; state.busy = state.loading = false
    pending = null; retryKeys.clear()
    state.draft = ''
  }
  watch([() => authState.account?.user.id, selected], () => {
    reset()
    const user = authState.account?.user.id
    if (user) { state.draft = readDraft(user, selected.value); void reload() }
    restoringDraft = false
  }, { immediate: true })
  watch(() => state.draft, value => {
    const user = authState.account?.user.id
    if (user && !restoringDraft) saveDraft(user, selected.value, value)
  }, { flush: 'sync' })
  onScopeDispose(() => { disposed = true; reset() })
  return { state, active, reload, create, send, retry, cancel, update, older, refreshSummary, generateSummary, reconnect: () => { if (active.value) follow(active.value.id) } }
}
