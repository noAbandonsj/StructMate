import assert from 'node:assert/strict'
import { before, after, test } from 'node:test'
import { createServer } from 'vite'
let server, vue, auth, recommendations
const originalFetch = globalThis.fetch
const response = (value, status = 200) => new Response(JSON.stringify(value), { status })
const item = id => ({ id, kind: 'document', document_id: id, chunk_id: id + '-chunk', title: id, reasons: [] })
const result = id => ({ items: [item(id)], basis: '实际权限与元数据匹配' })
before(async () => {
  server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  auth = await server.ssrLoadModule('/src/state/auth.ts')
  recommendations = await server.ssrLoadModule('/src/state/recommendations.ts')
  vue = await import('vue')
})
after(async () => { globalThis.fetch = originalFetch; await server.close() })
async function until(predicate) {
  for (let attempt = 0; attempt < 80; attempt++) { if (predicate()) return; await new Promise(resolve => setImmediate(resolve)) }
  assert.ok(predicate(), 'state did not settle')
}
function defaults(url) {
  if (url.includes('/chapters')) return Promise.resolve(response({ items: [], total: 0 }))
  if (url.includes('/chunks/')) return Promise.resolve(response({ id: 'chunk', text: '真实片段' }))
  return Promise.resolve(response(result('current')))
}
function scope(user, point = '') {
  auth.authState.account = { user: { id: user }, csrf_token: 'test-csrf' }; auth.authState.status = 'ready'
  const context = vue.ref(point), effect = vue.effectScope()
  return { context, effect, ...effect.run(() => recommendations.useRecommendations(context)) }
}
test('changing context rejects a late previous recommendation list', async () => {
  let release
  globalThis.fetch = url => url.includes('chapter_id=old') ? new Promise(resolve => { release = resolve }) : defaults(url)
  const view = scope('context-owner', 'old')
  try {
    await until(() => release)
    view.context.value = 'new'; await vue.nextTick(); await until(() => view.state.items.length)
    release(response(result('old'))); await new Promise(resolve => setImmediate(resolve))
    assert.equal(view.state.items[0].id, 'current'); assert.equal(view.state.point, 'new')
  } finally { view.effect.stop() }
})
test('failure and retry keep the chosen point and difficulty', async () => {
  let fail = false, requested
  globalThis.fetch = url => {
    if (!url.includes('/chapters')) { requested = url; if (fail) return Promise.reject(new Error('offline')) }
    return defaults(url)
  }
  const view = scope('filter-owner')
  try {
    await until(() => view.state.items.length)
    view.state.point = 'tree'; view.state.difficulty = 'advanced'; fail = true
    await view.reload(); assert.ok(view.state.error)
    assert.equal(view.state.point, 'tree'); assert.equal(view.state.difficulty, 'advanced')
    fail = false; await view.reload()
    assert.ok(requested.includes('difficulty=advanced') && requested.includes('chapter_id=tree'))
    assert.equal(view.state.error, '')
  } finally { view.effect.stop() }
})
test('sign out clears private snippets and ignores a late preview response', async () => {
  let release
  globalThis.fetch = url => url.includes('/chunks/') ? new Promise(resolve => { release = resolve }) : defaults(url)
  const view = scope('private-owner')
  try {
    await until(() => view.state.items.length)
    const pending = view.read(view.state.items[0]); await until(() => release)
    auth.authState.account = null; await vue.nextTick()
    release(response({ id: 'private', text: '不能泄露' })); await pending
    assert.equal(view.state.preview, null); assert.deepEqual(view.state.items, [])
  } finally { view.effect.stop() }
})
test('a deleted source fails the fresh permission check without displaying a stored preview', async () => {
  globalThis.fetch = url => url.includes('/chunks/') ? Promise.resolve(response({ code: 'DOCUMENT_DELETED', message: '资料已删除' }, 410)) : defaults(url)
  const view = scope('deleted-owner')
  try {
    await until(() => view.state.items.length)
    await view.read(view.state.items[0])
    assert.equal(view.state.preview, null); assert.equal(view.state.previewError, '资料已删除')
    assert.equal(view.state.previewLoading, false)
  } finally { view.effect.stop() }
})
