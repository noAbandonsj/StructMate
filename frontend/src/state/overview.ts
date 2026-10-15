import { onScopeDispose, reactive, watch } from 'vue'
import { overview, type Overview } from '../api/reports'
import { ApiError } from '../api/client'
import { authState, restoreAccount } from './auth'
export function useOverview() {
  const state = reactive({ data: null as Overview | null, loading: false, error: '' })
  let version = 0, disposed = false, reader = new AbortController()
  async function reload() {
    reader.abort(); reader = new AbortController()
    const stamp = ++version, user = authState.account?.user.id, signal = reader.signal
    if (!user) return
    state.loading = true; state.error = ''
    const current = () => !disposed && stamp === version && user === authState.account?.user.id
    try {
      const data = await overview(signal)
      if (current()) state.data = data
    } catch (error) {
      if (!current() || signal.aborted) return
      if (error instanceof ApiError && error.status === 401) await restoreAccount(true)
      else state.error = error instanceof Error ? error.message : '读取失败，请重试。'
    } finally { if (current()) state.loading = false }
  }
  watch(() => authState.account?.user.id, () => {
    version++; reader.abort(); state.data = null; state.error = ''; state.loading = false
    if (authState.account) void reload()
  }, { immediate: true })
  onScopeDispose(() => { disposed = true; version++; reader.abort(); state.data = null })
  return { state, reload }
}
