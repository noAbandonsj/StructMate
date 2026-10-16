import assert from 'node:assert/strict'
import { before, after, test } from 'node:test'
import { createServer } from 'vite'
let server, vue, auth, reports, overview
const originalFetch = globalThis.fetch, originalSession = globalThis.sessionStorage
const response = (value, status = 200) => new Response(JSON.stringify(value), { status })
const page = items => ({ items, total: items.length, page: 1, page_size: 20 })
const stats = (count = 0, from = '2026-10-09', to = '2026-10-15') => ({ from_date: from, to_date: to, attempts: { count } })
const report = (id = 'one', snapshot = stats(), key = 'saved-key') => ({ id, client_request_id: key, status: 'completed', snapshot, content: '基于保存时数据' })
function storage() {
  const values = new Map()
  return { get length() { return values.size }, key: i => [...values.keys()][i] ?? null,
    getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
}
before(async () => {
  server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  auth = await server.ssrLoadModule('/src/state/auth.ts')
  reports = await server.ssrLoadModule('/src/state/reports.ts')
  overview = await server.ssrLoadModule('/src/state/overview.ts')
  vue = await import('vue'); globalThis.sessionStorage = storage()
})
after(async () => { globalThis.fetch = originalFetch; globalThis.sessionStorage = originalSession; await server.close() })
async function until(predicate) {
  for (let attempt = 0; attempt < 80; attempt++) { if (predicate()) return; await new Promise(resolve => setImmediate(resolve)) }
  assert.ok(predicate(), 'state did not settle')
}
function defaults(url) {
  if (url.includes('/learning/stats')) return Promise.resolve(response(stats()))
  if (url.includes('/reports?')) return Promise.resolve(response(page([report()])))
  if (url.endsWith('/config')) return Promise.resolve(response({ generation_available: false }))
  if (url.endsWith('/learning/overview')) return Promise.resolve(response({ stats: stats(), recent_conversations: [], recent_practices: [] }))
  return Promise.resolve(response(report(url.split('/').at(-1))))
}
function scope(user, id = '') {
  auth.authState.account = { user: { id: user }, csrf_token: 'test-csrf' }; auth.authState.status = 'ready'
  const selected = vue.ref(id), effect = vue.effectScope()
  return { selected, effect, ...effect.run(() => reports.useReports(selected)) }
}
test('a lost report response keeps date input and reuses the request key across remount', async () => {
  const posted = []
  globalThis.fetch = (url, options) => {
    if (options?.method === 'POST') { posted.push(JSON.parse(options.body)); return Promise.reject(new Error('offline')) }
    return defaults(url)
  }
  const first = scope('retry-owner')
  await until(() => first.state.stats)
  first.state.range = { from_date: '2026-01-01', to_date: '2026-01-07' }
  await first.generate(); assert.ok(first.state.error)
  await first.reload(); assert.ok(first.state.error, 'a read must preserve the mutation error')
  first.effect.stop()
  const second = scope('retry-owner')
  try {
    await until(() => second.state.stats)
    assert.equal(second.state.range.from_date, '2026-01-01')
    await second.generate()
    assert.deepEqual(posted[0], posted[1])
  } finally { second.effect.stop() }
})
test('live statistic refresh never rewrites the selected historical snapshot or range input', async () => {
  let count = 1
  globalThis.fetch = url => url.includes('/learning/stats') ? Promise.resolve(response(stats(count))) : defaults(url)
  const view = scope('history-owner', 'one')
  try {
    await until(() => view.state.report)
    view.state.range.from_date = '2026-01-01'; count = 9
    await view.reload()
    assert.equal(view.state.stats.attempts.count, 9)
    assert.equal(view.state.report.snapshot.attempts.count, 0)
    assert.equal(view.state.range.from_date, '2026-01-01')
  } finally { view.effect.stop() }
})

test('an omitted date boundary is filled with the effective server range after refresh', async () => {
  globalThis.fetch = defaults
  const view = scope('partial-date-owner')
  try {
    await until(() => view.state.stats)
    view.state.range = { from_date: '', to_date: '2026-10-15' }
    await view.reload()
    assert.deepEqual(view.state.range, { from_date: '2026-10-09', to_date: '2026-10-15' })
  } finally { view.effect.stop() }
})
test('switching reports and accounts rejects old responses and clears private results', async () => {
  let release
  globalThis.fetch = url => url.endsWith('/reports/old') ? new Promise(resolve => { release = resolve }) : defaults(url)
  const view = scope('old-owner', 'old')
  try {
    await until(() => release)
    view.selected.value = 'new'; await vue.nextTick(); await until(() => view.state.report?.id === 'new')
    release(response(report('old'))); await new Promise(resolve => setImmediate(resolve))
    assert.equal(view.state.report.id, 'new')
    auth.authState.account = null; await vue.nextTick()
    assert.equal(view.state.report, null); assert.equal(view.state.stats, null)
    assert.deepEqual(view.state.reports, [])
  } finally { view.effect.stop() }
})
test('typing while the initial statistics load is pending keeps the typed dates', async () => {
  let release
  globalThis.fetch = url => url.includes('/learning/stats') ? new Promise(resolve => { release = resolve }) : defaults(url)
  const view = scope('typing-owner')
  try {
    await until(() => release)
    view.state.range = { from_date: '2026-04-01', to_date: '2026-04-20' }
    release(response(stats())); await until(() => view.state.stats)
    assert.equal(view.state.range.from_date, '2026-04-01')
  } finally { view.effect.stop() }
})
test('a saved request confirmed by a report read allows a deliberate new report request', async () => {
  let key, posts = 0
  globalThis.fetch = (url, options) => {
    if (options?.method === 'POST') {
      posts++; const body = JSON.parse(options.body)
      if (!key) { key = body.client_request_id; return Promise.reject(new Error('response lost')) }
      assert.notEqual(body.client_request_id, key)
      return Promise.resolve(response(report('two', stats(), body.client_request_id)))
    }
    if (url.endsWith('/reports/one')) return Promise.resolve(response(report('one', stats(), key)))
    return defaults(url)
  }
  const view = scope('confirmed-owner')
  try {
    await until(() => view.state.stats)
    await view.generate(); view.selected.value = 'one'; await vue.nextTick()
    await until(() => view.state.report)
    assert.equal((await view.generate()).id, 'two'); assert.equal(posts, 2)
  } finally { view.effect.stop() }
})
test('home recent records cannot leak from a previous account', async () => {
  let release
  globalThis.fetch = () => new Promise(resolve => { release = resolve })
  auth.authState.account = { user: { id: 'home-old' } }
  const effect = vue.effectScope(), view = effect.run(() => overview.useOverview())
  try {
    await until(() => release)
    auth.authState.account = null; await vue.nextTick()
    release(response({ stats: stats(10), recent_conversations: [{ id: 'private' }], recent_practices: [] }))
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(view.state.data, null)
  } finally { effect.stop() }
})
