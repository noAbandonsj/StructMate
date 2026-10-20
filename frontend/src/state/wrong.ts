import { onScopeDispose, reactive, watch, type Ref } from 'vue'
import * as api from '../api/practice'
import { ApiError } from '../api/client'
import { authState, restoreAccount } from './auth'
export function useWrong(selected: Ref<string>) {
  const state = reactive({
    items: [] as api.Wrong[], detail: null as api.Wrong | null,
    checked: [] as string[], page: 1, total: 0, status: 'pending', search: '', loading: false, busy: false, error: '',
  })
  let epoch = 0, readVersion = 0, disposed = false
  let reader = new AbortController(), writer = new AbortController()
  let pending: { signature: string; key: string } | null = null
  const valid = (version: number, user: string | undefined, id: string) =>
    !disposed && version === epoch && user === authState.account?.user.id && id === selected.value
  async function fail(error: unknown) {
    if (error instanceof ApiError && error.status === 401) await restoreAccount(true)
    else state.error = error instanceof Error ? error.message : '操作失败，请重试。'
  }
  async function reload() {
    const version = epoch, user = authState.account?.user.id, id = selected.value, readStamp = ++readVersion
    const current = () => valid(version, user, id) && readStamp === readVersion
    if (!user) return
    reader.abort(); reader = new AbortController()
    state.loading = true; state.error = ''
    try {
      const [result, detail] = await Promise.all([
        api.wrongList(state.page, state.status, state.search, reader.signal),
        id ? api.wrongDetail(id, reader.signal) : Promise.resolve(null),
      ])
      if (!current()) return
      state.items = result.items; state.total = result.total; state.detail = detail
      state.checked = state.checked.filter(value => result.items.some(item => item.id === value))
    } catch (error) { if (current() && !reader.signal.aborted) await fail(error) }
    finally { if (current()) state.loading = false }
  }
  async function review(ids: string[]) {
    const account = authState.account, version = epoch, id = selected.value
    if (!account || state.busy || !ids.length) return
    const signature = [...ids].sort().join(',')
    if (!pending || pending.signature !== signature) pending = { signature, key: crypto.randomUUID() }
    writer = new AbortController(); state.busy = true; state.error = ''
    try {
      const result = await api.review(account.csrf_token, ids, pending.key, writer.signal)
      if (valid(version, account.user.id, id)) { pending = null; return result }
    } catch (error) { if (valid(version, account.user.id, id)) await fail(error) }
    finally { if (valid(version, account.user.id, id)) state.busy = false }
  }
  watch([() => authState.account?.user.id, selected], () => {
    epoch++; reader.abort(); writer.abort()
    state.items = []; state.detail = null; state.checked = []
    state.search = ''; state.page = 1
    state.total = 0; state.error = ''; state.loading = state.busy = false; pending = null
    if (authState.account) void reload()
  }, { immediate: true })
  onScopeDispose(() => { disposed = true; epoch++; reader.abort(); writer.abort(); state.items = []; state.detail = null; state.checked = [] })
  return { state, reload, review }
}
