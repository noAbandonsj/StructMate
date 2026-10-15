import { computed, onScopeDispose, reactive, watch, type Ref } from 'vue'
import * as api from '../api/chat'
import { ApiError } from '../api/client'
import { authState, restoreAccount } from './auth'
import { readDraft, saveDraft } from './chat-drafts'

export function useChat(selected: Ref<string>) {
  const state = reactive({
    conversations: [] as api.Conversation[], total: 0, page: 1, archived: false,
    conversation: null as api.Conversation | null, messages: [] as api.Message[],
    config: null as api.Config | null, loading: false, busy: false, error: '', streamError: '',
    draft: '', intent: 'explain' as api.Intent, historyPage: 1,
  })
  let epoch = 0, readVersion = 0, disposed = false
  let reader = new AbortController(), writer = new AbortController()
  let closeStream: (() => void) | null = null
  let streamVersion = 0
  let pending: { content: string; intent: api.Intent; key: string } | null = null
  let restoringDraft = false
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
    const current = () => valid(version, user, id) && readStamp === readVersion
    reader.abort(); reader = new AbortController()
    const signal = reader.signal
    state.loading = true; state.error = ''
    try {
      const [conversations, config, conversation] = await Promise.all([
        api.list(state.page, state.archived, signal), api.config(signal),
        id ? api.detail(id, signal) : Promise.resolve(null),
      ])
      if (!current()) return
      state.conversations = conversations.items; state.total = conversations.total
      state.config = config; state.conversation = conversation
      if (id) await loadHistory(signal, version, user, id, readStamp)
    } catch (error) { if (current() && !signal.aborted) await failure(error) }
    finally { if (current()) state.loading = false }
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
  async function create(scope: api.Scope, documentIds: string[] = [], pointId?: string) {
    return mutate((csrf, signal) => api.create(csrf, { scope, document_ids: documentIds, knowledge_point_id: pointId || null }, signal))
  }
  async function send() {
    const content = state.draft.trim(), version = epoch, user = authState.account?.user.id, id = selected.value
    if (!content || !id || active.value || state.conversation?.archived) return
    if (!pending || pending.content !== content || pending.intent !== state.intent)
      pending = { content, intent: state.intent, key: crypto.randomUUID() }
    const request = pending
    const result = await mutate((csrf, signal) => api.send(csrf, id, content, request.intent, request.key, signal))
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
  async function update(values: Partial<api.Conversation>) {
    const id = selected.value
    const result = await mutate((csrf, signal) => api.update(csrf, id, values, signal))
    if (result) { state.conversation = result; await reload() }
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
  return { state, active, reload, create, send, retry, cancel, update, older, reconnect: () => { if (active.value) follow(active.value.id) } }
}
