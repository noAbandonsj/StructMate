import { onScopeDispose, reactive, watch, type Ref } from 'vue'
import * as api from '../api/reports'
import { config } from '../api/practice'
import { ApiError } from '../api/client'
import { authState, restoreAccount } from './auth'
import { readDraft, saveDraft } from './learning-drafts'

export function useReports(selected: Ref<string>) {
  const state = reactive({
    range: { from_date: '', to_date: '' }, stats: null as api.Stats | null,
    reports: [] as api.Report[], report: null as api.Report | null, page: 1, total: 0,
    loading: false, busy: false, readError: '', error: '', generationAvailable: false,
  })
  let epoch = 0, readVersion = 0, disposed = false
  let reader = new AbortController(), writer = new AbortController()
  let timer: ReturnType<typeof setTimeout> | undefined
  let pending: { signature: string; key: string } | null = null
  const signature = () => JSON.stringify(state.range)
  const valid = (version: number, user: string | undefined, id: string) =>
    !disposed && epoch === version && user === authState.account?.user.id && id === selected.value
  function persist() {
    const user = authState.account?.user.id
    if (user) saveDraft(user, 'range', JSON.stringify({ range: state.range, pending }), 'reports')
  }
  async function fail(error: unknown, read = false) {
    if (error instanceof ApiError && error.status === 401) await restoreAccount(true)
    else if (read) state.readError = error instanceof Error ? error.message : '读取失败，请重试。'
    else state.error = error instanceof Error ? error.message : '保存失败，请重试。'
  }
  async function reload() {
    const user = authState.account?.user.id, id = selected.value, version = epoch, stamp = ++readVersion
    if (!user) return
    reader.abort(); reader = new AbortController(); clearTimeout(timer)
    const signal = reader.signal, rangeSignature = signature()
    const current = () => valid(version, user, id) && stamp === readVersion
    state.loading = true; state.readError = ''
    try {
      const [stats, reports, report, configuration] = await Promise.all([
        api.stats({ ...state.range }, signal), api.list(state.page, signal),
        id ? api.detail(id, signal) : Promise.resolve(null), config(signal),
      ])
      if (!current()) return
      state.stats = stats; state.reports = reports.items; state.total = reports.total
      state.report = report; state.generationAvailable = configuration.generation_available
      if (signature() === rangeSignature && !state.range.from_date && !state.range.to_date) {
        state.range = { from_date: stats.from_date, to_date: stats.to_date }
      }
      if (report && pending?.key === report.client_request_id) { pending = null; persist() }
      if (report?.status === 'generating') timer = setTimeout(() => void reload(), 1500)
    } catch (error) { if (current() && !signal.aborted) await fail(error, true) }
    finally { if (current()) state.loading = false }
  }
  async function generate() {
    const account = authState.account, version = epoch, id = selected.value
    if (!account || state.busy) return
    const value = signature()
    if (!pending || pending.signature !== value) pending = { signature: value, key: crypto.randomUUID() }
    persist(); writer = new AbortController(); state.busy = true; state.error = ''
    try {
      const result = await api.create(account.csrf_token, { ...state.range }, pending.key, writer.signal)
      if (valid(version, account.user.id, id)) { pending = null; persist(); return result }
    } catch (error) { if (valid(version, account.user.id, id)) await fail(error) }
    finally { if (valid(version, account.user.id, id)) state.busy = false }
  }
  watch(() => state.range, persist, { deep: true, flush: 'sync' })
  watch(() => authState.account?.user.id, user => {
    epoch++; reader.abort(); writer.abort(); clearTimeout(timer); readVersion++
    state.stats = null; state.reports = []; state.report = null; state.total = 0; state.page = 1
    state.error = state.readError = ''; state.busy = state.loading = false; state.generationAvailable = false
    pending = null
    let range: api.Range = { from_date: '', to_date: '' }
    if (user) {
      try {
        const saved = JSON.parse(readDraft(user, 'range', 'reports') || '{}')
        if (typeof saved.range?.from_date === 'string' && typeof saved.range?.to_date === 'string') range = saved.range
        if (typeof saved.pending?.signature === 'string' && typeof saved.pending?.key === 'string') pending = saved.pending
      } catch { /* Invalid local draft: start with the default seven-day range. */ }
    }
    state.range = range
    if (user) void reload()
  }, { immediate: true })
  watch(selected, () => {
    epoch++; readVersion++; reader.abort(); writer.abort(); clearTimeout(timer)
    state.report = null; state.error = state.readError = ''; state.loading = state.busy = false
    if (authState.account) void reload()
  })
  onScopeDispose(() => { disposed = true; epoch++; reader.abort(); writer.abort(); clearTimeout(timer); state.report = null; state.stats = null; state.reports = [] })
  return { state, reload, generate }
}
