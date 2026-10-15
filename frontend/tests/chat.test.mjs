import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { createServer } from 'vite'

let server, auth, chat, vue
const originalFetch = globalThis.fetch, originalEvents = globalThis.EventSource, originalStorage = globalThis.sessionStorage
const streams = []
class TestStream {
  listeners = new Map()
  closed = false
  constructor(url) { this.url = url; streams.push(this) }
  addEventListener(name, handler) { this.listeners.set(name, handler) }
  close() { this.closed = true }
  emit(name, value) { this.listeners.get(name)?.({ data: JSON.stringify(value) }) }
}
const response = (data, status = 200) => new Response(JSON.stringify(data), { status })
const account = id => ({ user: { id, display_name: id }, csrf_token: 'test-' + id })
const conversation = id => ({ id, title: id, scope: 'combined', document_ids: [], archived: false })
const page = items => ({ items, page: 1, page_size: 100, total: items.length })
const message = (id, content = '', status = 'generating') => ({ id, content, status, role: 'assistant', citations: [], conversation_id: 'one' })
async function until(predicate) {
  for (let i = 0; i < 60; i++) { if (predicate()) return; await new Promise(resolve => setImmediate(resolve)) }
  assert.ok(predicate(), 'state did not settle')
}
before(async () => {
  server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  auth = await server.ssrLoadModule('/src/state/auth.ts')
  chat = await server.ssrLoadModule('/src/state/chat.ts')
  vue = await import('vue')
  globalThis.EventSource = TestStream
  const values = new Map()
  globalThis.sessionStorage = {
    get length() { return values.size },
    key: index => [...values.keys()][index] ?? null,
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  }
})
after(async () => {
  globalThis.fetch = originalFetch; globalThis.EventSource = originalEvents; globalThis.sessionStorage = originalStorage
  await server.close()
})
function scope(id = 'one', user = 'student') {
  auth.authState.account = account(user); auth.authState.status = 'ready'
  const selected = vue.ref(id), effect = vue.effectScope()
  return { selected, effect, ...effect.run(() => chat.useChat(selected)) }
}
function defaultFetch(url) {
  if (url.includes('/config')) return Promise.resolve(response({ generation_available: true, embedding_available: true }))
  if (url.includes('/messages?')) return Promise.resolve(response(page([message('answer')])))
  if (url.includes('/conversations?')) return Promise.resolve(response(page([conversation('one')])))
  return Promise.resolve(response(conversation(url.split('/').at(-1))))
}
test('restored generating answers connect without submitting another question', async () => {
  let writes = 0
  globalThis.fetch = (url, options) => { if (options.method === 'POST') writes++; return defaultFetch(url) }
  const view = scope()
  try {
    await until(() => view.active.value?.id === 'answer')
    const stream = streams.at(-1)
    stream.emit('snapshot', message('answer', '已生成'))
    stream.emit('delta', { text: '内容' })
    assert.equal(view.state.messages[0].content, '已生成内容')
    stream.emit('completed', message('answer', '已生成内容', 'completed'))
    assert.equal(view.active.value, undefined)
    assert.equal(writes, 0)
  } finally { view.effect.stop() }
})
test('switching conversations closes the previous stream and rejects late tokens', async () => {
  globalThis.fetch = defaultFetch
  const view = scope()
  try {
    await until(() => view.active.value)
    const old = streams.at(-1)
    view.selected.value = 'two'
    await vue.nextTick()
    await until(() => view.state.conversation?.id === 'two' && !view.state.loading)
    assert.equal(old.closed, true)
    old.emit('delta', { text: '旧用户内容' })
    assert.equal(view.state.messages[0].content, '')
  } finally { view.effect.stop() }
})
test('a timed out send retains draft and reuses its request key', async () => {
  const submitted = []
  globalThis.fetch = (url, options) => {
    if (options.method === 'POST') {
      submitted.push(JSON.parse(options.body))
      return Promise.reject(new Error('network interruption'))
    }
    if (url.includes('/messages?')) return Promise.resolve(response(page([])))
    return defaultFetch(url)
  }
  const view = scope()
  try {
    await until(() => !view.state.loading && view.state.conversation)
    view.state.draft = '我的问题'
    await view.send(); await view.send()
    assert.equal(view.state.draft, '我的问题')
    assert.ok(view.state.error)
    assert.equal(submitted.length, 2)
    assert.equal(submitted[0].client_request_id, submitted[1].client_request_id)
  } finally { view.effect.stop() }
})
test('an unfinished draft survives remount and is isolated by account', async () => {
  globalThis.fetch = defaultFetch
  const first = scope('one', 'draft-owner')
  first.state.draft = '还没提交的追问'
  first.effect.stop()
  const restored = scope('one', 'draft-owner')
  try { assert.equal(restored.state.draft, '还没提交的追问') } finally { restored.effect.stop() }
  const other = scope('one', 'another-user')
  try { assert.equal(other.state.draft, '') } finally { other.effect.stop() }
})
test('changing accounts clears private messages and ignores a delayed history response', async () => {
  const pending = []
  globalThis.fetch = url => {
    if (url.includes('/messages?')) return new Promise(resolve => pending.push({ user: auth.authState.account.user.id, resolve }))
    return defaultFetch(url)
  }
  const view = scope('one', 'first-user')
  try {
    await until(() => pending.length === 1)
    auth.authState.account = account('second-user')
    await vue.nextTick()
    await until(() => pending.length === 2)
    pending[1].resolve(response(page([message('new-answer', '新账户')])))
    await until(() => view.state.messages.length > 0)
    pending[0].resolve(response(page([message('old-answer', '私人内容')])))
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(view.state.messages[0].id, 'new-answer')
  } finally { view.effect.stop() }
})

test('signing out clears saved drafts for the outgoing account', async () => {
  globalThis.fetch = defaultFetch
  const view = scope('one', 'logout-owner')
  view.state.draft = '退出时应清除'
  globalThis.fetch = () => Promise.resolve(new Response(null, { status: 204 }))
  await auth.signOut()
  await vue.nextTick()
  assert.equal(globalThis.sessionStorage.getItem('capstone.chat.logout-owner.one'), null)
  assert.equal(view.state.draft, '')
  view.effect.stop()
})

test('an earlier refresh cannot overwrite a newer result in the same conversation', async () => {
  globalThis.fetch = defaultFetch
  const view = scope()
  try {
    await until(() => !view.state.loading && view.state.conversation)
    let resolveOld, reads = 0
    globalThis.fetch = url => {
      if (url.endsWith('/conversations/one')) {
        reads++
        if (reads === 1) return new Promise(resolve => { resolveOld = resolve })
        return Promise.resolve(response({ ...conversation('one'), title: '最新名称' }))
      }
      return defaultFetch(url)
    }
    const old = view.reload()
    await view.reload()
    resolveOld(response({ ...conversation('one'), title: '旧名称' }))
    await old
    assert.equal(view.state.conversation.title, '最新名称')
  } finally { view.effect.stop() }
})
