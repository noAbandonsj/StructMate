import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { createServer } from 'vite'

let server
let auth
let knowledge
let vue
const originalFetch = globalThis.fetch
const library = (id, kind = 'personal') => ({
  id, kind, name: id, is_readonly: kind === 'course', created_at: '2026-10-14T00:00:00Z',
})
const account = (id) => ({
  user: { id, username: id, display_name: id },
  default_knowledge_base: library(id), csrf_token: 'test-' + id,
})
const response = (value, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { 'Content-Type': 'application/json' },
})
const page = (items, total = items.length) => ({ items, total, page: 1, page_size: 100 })

before(async () => {
  server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  auth = await server.ssrLoadModule('/src/state/auth.ts')
  knowledge = await server.ssrLoadModule('/src/state/knowledge.ts')
  vue = await import('vue')
})

after(async () => {
  globalThis.fetch = originalFetch
  await server.close()
})

async function until(predicate) {
  for (let attempt = 0; attempt < 40; attempt++) {
    if (predicate()) return
    await new Promise(resolve => setImmediate(resolve))
  }
  assert.ok(predicate(), 'state did not settle')
}

function createScope(id) {
  auth.authState.account = account(id)
  auth.authState.status = 'ready'
  const scope = vue.effectScope()
  return { scope, ...scope.run(() => knowledge.useKnowledge()) }
}

test('late responses from a previous account cannot overwrite the new account', async () => {
  const pending = []
  globalThis.fetch = (url) => new Promise(resolve => {
    pending.push({ url, user: auth.authState.account?.user.id, resolve })
  })
  const view = createScope('first')
  try {
    assert.equal(pending.length, 2)
    auth.authState.account = account('second')
    await vue.nextTick()
    for (const item of pending.filter(item => item.user === 'second')) {
      item.resolve(response(page(item.url.includes('knowledge-points') ? [] : [library('second')])))
    }
    await until(() => pending.some(item => item.url.endsWith('/second')))
    pending.find(item => item.url.endsWith('/second')).resolve(response(library('second')))
    await until(() => view.state.detail?.id === 'second')
    for (const item of pending.filter(item => item.user === 'first')) {
      item.resolve(response(page(item.url.includes('knowledge-points') ? [] : [library('first')])))
    }
    await new Promise(resolve => setImmediate(resolve))
    assert.deepEqual(view.state.libraries.map(item => item.id), ['second'])
    assert.equal(view.state.detail.id, 'second')
  } finally {
    view.scope.stop()
  }
})

test('changing selection discards a late detail response', async () => {
  const pending = []
  let deferDetails = false
  globalThis.fetch = async (url) => {
    if (url.includes('knowledge-bases?')) return response(page([library('mine'), library('course', 'course')]))
    if (url.includes('knowledge-points?')) return response(page([]))
    if (!deferDetails) return response(library('mine'))
    return new Promise(resolve => pending.push({ url, resolve }))
  }
  const view = createScope('mine')
  try {
    await until(() => view.state.detail?.id === 'mine')
    deferDetails = true
    const oldSelection = view.selectLibrary('course')
    const newSelection = view.selectLibrary('mine')
    pending.find(item => item.url.endsWith('/mine')).resolve(response(library('mine')))
    await newSelection
    pending.find(item => item.url.endsWith('/course')).resolve(response(library('course', 'course')))
    await oldSelection
    assert.equal(view.state.selectedId, 'mine')
    assert.equal(view.state.detail.id, 'mine')
  } finally {
    view.scope.stop()
  }
})

test('an expired session clears account and private library state', async () => {
  globalThis.fetch = async () => response({ code: 'LOGIN_REQUIRED', message: '请登录' }, 401)
  const view = createScope('expired')
  try {
    await until(() => auth.authState.account === null)
    await vue.nextTick()
    assert.equal(view.state.libraries.length, 0)
    assert.equal(view.state.points.length, 0)
    assert.equal(view.state.detail, null)
  } finally {
    view.scope.stop()
  }
})

test('a library connection failure still permits the course catalog to load', async () => {
  globalThis.fetch = async (url) => {
    if (url.includes('knowledge-bases')) throw new TypeError('test network error')
    return response(page([{ id: 'root', name: '线性表', code: 'linear-list', parent_id: null, sort_order: 10 }]))
  }
  const view = createScope('student')
  try {
    await until(() => view.state.pointsStatus === 'ready')
    assert.equal(view.state.librariesStatus, 'error')
    assert.match(view.state.librariesError, /连接/)
    assert.equal(view.state.points[0].name, '线性表')
  } finally {
    view.scope.stop()
  }
})

test('disposing the page clears private values and ignores a late detail response', async () => {
  let resolveDetail
  globalThis.fetch = async (url) => {
    if (url.includes('knowledge-bases?')) return response(page([library('mine')]))
    if (url.includes('knowledge-points?')) return response(page([]))
    return new Promise(resolve => { resolveDetail = resolve })
  }
  const view = createScope('mine')
  await until(() => Boolean(resolveDetail))
  assert.equal(view.state.libraries.length, 1)
  view.scope.stop()
  resolveDetail(response(library('mine')))
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(view.state.libraries.length, 0)
  assert.equal(view.state.selectedId, null)
  assert.equal(view.state.detail, null)
})
