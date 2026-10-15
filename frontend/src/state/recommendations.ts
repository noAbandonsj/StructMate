import { onScopeDispose, reactive, watch, type Ref } from 'vue'
import * as api from '../api/recommendations'
import { getPoints, type KnowledgePoint } from '../api/knowledge'
import { ApiError } from '../api/client'
import { authState, restoreAccount } from './auth'
export function useRecommendations(context: Ref<string>) {
  const state = reactive({ items: [] as api.Recommendation[], points: [] as KnowledgePoint[],
    point: '', difficulty: 'basic', basis: '', loading: false, error: '',
    preview: null as { item: api.Recommendation; chunk: api.Chunk } | null, previewLoading: false, previewError: '',
  })
  let epoch = 0, readVersion = 0, previewVersion = 0, disposed = false
  let reader = new AbortController(), previewReader = new AbortController()
  const valid = (stamp: number, user: string | undefined) => !disposed && stamp === epoch && user === authState.account?.user.id
  function closePreview() { previewVersion++; previewReader.abort(); state.preview = null; state.previewError = ''; state.previewLoading = false }
  async function fail(error: unknown, preview = false) {
    if (error instanceof ApiError && error.status === 401) await restoreAccount(true)
    else if (preview) state.previewError = error instanceof Error ? error.message : '原文暂不可用，请刷新推荐。'
    else state.error = error instanceof Error ? error.message : '推荐暂不可用，请重试。'
  }
  async function reload() {
    const user = authState.account?.user.id, stamp = epoch, version = ++readVersion
    reader.abort(); reader = new AbortController(); closePreview()
    if (!user) return
    const signal = reader.signal, current = () => valid(stamp, user) && version === readVersion
    state.loading = true; state.error = ''; state.items = []
    try {
      const [result, points] = await Promise.all([api.list(state.point, state.difficulty, signal), getPoints(signal)])
      if (current()) { state.items = result.items; state.basis = result.basis; state.points = points }
    } catch (error) { if (current() && !signal.aborted) await fail(error) }
    finally { if (current()) state.loading = false }
  }
  async function read(item: api.Recommendation) {
    if (!item.document_id || !item.chunk_id) return
    closePreview(); const version = previewVersion, stamp = epoch, user = authState.account?.user.id
    previewReader = new AbortController(); const signal = previewReader.signal
    state.previewLoading = true
    const current = () => valid(stamp, user) && version === previewVersion
    try {
      const chunk = await api.chunk(item.document_id, item.chunk_id, signal)
      if (current()) state.preview = { item, chunk }
    } catch (error) { if (current() && !signal.aborted) await fail(error, true) }
    finally { if (current()) state.previewLoading = false }
  }
  watch([() => authState.account?.user.id, context], () => {
    epoch++; readVersion++; reader.abort(); closePreview()
    state.items = []; state.points = []; state.error = ''; state.basis = ''; state.loading = false
    state.point = context.value; state.difficulty = 'basic'
    if (authState.account) void reload()
  }, { immediate: true })
  onScopeDispose(() => { disposed = true; epoch++; reader.abort(); closePreview(); state.items = []; state.points = [] })
  return { state, reload, read, closePreview }
}
