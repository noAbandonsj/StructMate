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
  if (url.endsWith('/summary')) return Promise.resolve(response({ status: 'empty', content: '', message_count: 0, cutoff_sequence: 0, cutoff_at: null, generated_at: null, has_newer_messages: false }))
  if (url.includes('/config')) return Promise.resolve(response({ generation_available: true }))
  if (url.includes('/messages?')) return Promise.resolve(response(page([message('answer')])))
  if (url.includes('/conversations?')) return Promise.resolve(response(page([conversation('one')])))
  return Promise.resolve(response(conversation(url.split('/').at(-1))))
}

test('new conversations use combined materials and the list only requests active sessions', async () => {
  let created, listUrl
  globalThis.fetch = (url, options) => {
    if (url.includes('/conversations?')) listUrl = url
    if (url.endsWith('/conversations') && options?.method === 'POST') {
      created = JSON.parse(options.body)
      return Promise.resolve(response(conversation('new')))
    }
    return defaultFetch(url)
  }
  const view = scope('')
  try {
    await until(() => !view.state.loading)
    assert.equal(new URL(listUrl, 'http://localhost').searchParams.has('archived'), false)
    const result = await view.create(['chosen-document'], 'chapter')
    assert.equal(result.id, 'new')
    assert.deepEqual(created, { document_ids: ['chosen-document'], chapter_id: 'chapter' })
  } finally { view.effect.stop() }
})

test('archiving keeps the current conversation on failure and removes it from the active list on success', async () => {
  let archived = false, fail = true
  globalThis.fetch = (url, options) => {
    if (options?.method === 'PATCH') {
      if (fail) return Promise.reject(new Error('archive failed'))
      archived = JSON.parse(options.body).archived
      return Promise.resolve(response({ ...conversation('one'), archived }))
    }
    if (url.includes('/conversations?')) return Promise.resolve(response(page(archived ? [] : [conversation('one')])))
    if (url.endsWith('/conversations/one')) return Promise.resolve(response({ ...conversation('one'), archived }))
    if (url.includes('/messages?')) return Promise.resolve(response(page([])))
    return defaultFetch(url)
  }
  const view = scope()
  try {
    await until(() => !view.state.loading && view.state.conversation)
    view.state.draft = '尚未发送的问题'
    assert.equal(await view.update({ archived: true }), undefined)
    assert.equal(view.state.conversation.archived, false)
    assert.equal(view.state.conversations.length, 1)
    assert.match(view.state.error, /连接/)
    fail = false
    view.state.page = 2
    const result = await view.update({ archived: true })
    assert.equal(result.archived, true)
    assert.equal(view.state.conversations.length, 0)
    assert.equal(view.state.page, 1)
    assert.equal(view.state.draft, '尚未发送的问题')
  } finally { view.effect.stop() }
})

test('list actions update another conversation without replacing the current conversation or draft', async () => {
  let other = conversation('two'), releaseDetail, delayDetail = false
  const writes = []
  globalThis.fetch = (url, options) => {
    if (options?.method === 'PATCH') {
      writes.push({ url, body: JSON.parse(options.body) })
      other = { ...other, ...JSON.parse(options.body) }
      return Promise.resolve(response(other))
    }
    if (url.includes('/conversations?')) return Promise.resolve(response(page([conversation('one'), ...other.archived ? [] : [other]])))
    if (url.endsWith('/conversations/one') && delayDetail) return new Promise(resolve => { releaseDetail = resolve })
    if (url.includes('/messages?')) return Promise.resolve(response(page([])))
    return defaultFetch(url)
  }
  const view = scope()
  try {
    await until(() => !view.state.loading && view.state.conversation)
    view.state.draft = '正在编写的追问'
    delayDetail = true
    const rename = view.update({ title: '新的名称' }, 'two')
    await until(() => releaseDetail)
    assert.equal(view.state.conversation.id, 'one')
    releaseDetail(response(conversation('one')))
    assert.equal((await rename).id, 'two')
    assert.equal(view.state.conversations[1].title, '新的名称')
    delayDetail = false
    assert.equal((await view.update({ archived: true }, 'two')).archived, true)
    assert.deepEqual(view.state.conversations.map(item => item.id), ['one'])
    assert.equal(view.selected.value, 'one')
    assert.equal(view.state.conversation.id, 'one')
    assert.equal(view.state.draft, '正在编写的追问')
    assert.ok(writes.every(write => write.url.endsWith('/conversations/two')))
  } finally { view.effect.stop() }
})

test('chat sends with only generation configured and no material readiness contract', async () => {
  let writes = 0, configUrl = ''
  globalThis.fetch = (url, options) => {
    if (options?.method === 'POST') {
      writes++
      return Promise.resolve(response({ assistant_message_id: 'answer', user_message_id: 'question' }))
    }
    if (url.includes('/config')) {
      configUrl = url
      return Promise.resolve(response({ generation_available: true }))
    }
    if (url.includes('/messages?')) return Promise.resolve(response(page([])))
    return defaultFetch(url)
  }
  const view = scope('empty-course')
  try {
    await until(() => view.state.config && !view.state.loading)
    view.state.draft = '请解释栈'
    await view.send()
    assert.equal(configUrl, '/api/v1/conversations/config')
    assert.equal(writes, 1)
    assert.equal(view.state.draft, '')
    assert.equal(view.state.error, '')
  } finally { view.effect.stop() }
})

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
    view.state.draft = '请用例子解释栈和队列的区别'
    await view.send(); await view.send()
    assert.equal(view.state.draft, '请用例子解释栈和队列的区别')
    assert.ok(view.state.error)
    assert.equal(submitted.length, 2)
    assert.equal(submitted[0].content, '请用例子解释栈和队列的区别')
    assert.equal(submitted[0].intent, undefined)
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

test('summary network retries reuse the request key and keep the question draft', async () => {
  const submitted = []
  let completed = false
  const info = () => ({ status: completed ? 'completed' : 'generating', content: completed ? '本次总结' : '', message_count: completed ? 2 : 0, cutoff_sequence: completed ? 2 : 0, has_newer_messages: false })
  globalThis.fetch = (url, options) => {
    if (url.endsWith('/summary') && options.method === 'POST') {
      submitted.push(JSON.parse(options.body))
      if (submitted.length === 1) return Promise.reject(new Error('network failed'))
      return Promise.resolve(response(info()))
    }
    return defaultFetch(url)
  }
  const view = scope('one', 'summary-owner')
  try {
    await until(() => !view.state.loading && view.state.conversation)
    view.state.draft = '未提交的追问'
    await view.generateSummary(); await view.generateSummary()
    assert.equal(submitted.length, 2)
    assert.equal(submitted[0].client_request_id, submitted[1].client_request_id)
    assert.equal(view.state.draft, '未提交的追问')
    completed = true
    globalThis.fetch = (url, options) => url.endsWith('/summary') ? Promise.resolve(response(info())) : defaultFetch(url, options)
    await view.refreshSummary()
    assert.equal(view.state.summary.content, '本次总结')
    assert.equal(view.state.summaryLoading, false)
  } finally { view.effect.stop() }
})

test('a late summary response cannot replace a different conversation summary', async () => {
  globalThis.fetch = defaultFetch
  const view = scope('one', 'summary-switch')
  try {
    await until(() => !view.state.loading && view.state.conversation)
    let finishOld
    globalThis.fetch = (url) => {
      if (url.endsWith('/one/summary')) return new Promise(resolve => { finishOld = resolve })
      if (url.endsWith('/two/summary')) return Promise.resolve(response({ status: 'completed', content: '新会话总结' }))
      return defaultFetch(url)
    }
    const old = view.refreshSummary()
    view.selected.value = 'two'
    await vue.nextTick()
    await until(() => view.state.summary?.content === '新会话总结')
    finishOld(response({ status: 'completed', content: '旧会话私有内容' }))
    await old
    assert.equal(view.state.summary.content, '新会话总结')
    assert.equal(view.state.summaryLoading, false)
  } finally { view.effect.stop() }
})

test('a restored summary acknowledges a lost POST response before starting another summary', async () => {
  const submitted = []
  let saved = null
  globalThis.fetch = (url, options) => {
    if (url.endsWith('/summary') && options.method === 'POST') {
      const value = JSON.parse(options.body); submitted.push(value)
      saved = { status: 'completed', content: '已保存在服务器的总结', client_request_id: value.client_request_id }
      if (submitted.length === 1) return Promise.reject(new Error('response lost'))
      return Promise.resolve(response(saved))
    }
    if (url.endsWith('/summary') && saved) return Promise.resolve(response(saved))
    return defaultFetch(url)
  }
  const view = scope('one', 'summary-restored')
  try {
    await until(() => !view.state.loading && view.state.conversation)
    await view.generateSummary()
    await view.refreshSummary()
    assert.equal(view.state.summary.content, '已保存在服务器的总结')
    await view.generateSummary()
    assert.equal(submitted.length, 2)
    assert.notEqual(submitted[0].client_request_id, submitted[1].client_request_id)
  } finally { view.effect.stop() }
})
