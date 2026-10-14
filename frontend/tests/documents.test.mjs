import assert from 'node:assert/strict'
import { before, after, test } from 'node:test'
import { createServer } from 'vite'
import { effectScope, nextTick, ref } from 'vue'

let server, auth, documents
const originalFetch = globalThis.fetch
const config = { max_mib: 20, extensions: ['md', 'pdf', 'txt'], embedding_available: false }
const response = (value, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { 'Content-Type': 'application/json' },
})
const library = (id, readonly = false) => ({ id, kind: readonly ? 'course' : 'personal', name: id, is_readonly: readonly, created_at: '2026-10-14T00:00:00Z' })
const doc = (id, libraryId) => ({
  id, knowledge_base_id: libraryId, knowledge_point_id: null, filename: '笔记.md',
  file_type: 'md', size_bytes: 20, status: 'failed', stage: 'embedding',
  error_code: 'EMBEDDING_NOT_CONFIGURED', error_message: '未接通向量服务',
  retryable: true, source_info: null, created_at: '', updated_at: '',
})
const page = (items) => ({ items, total: items.length, page: 1, page_size: 20 })

before(async () => {
  server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  auth = await server.ssrLoadModule('/src/state/auth.ts')
  documents = await server.ssrLoadModule('/src/state/documents.ts')
})
after(async () => { globalThis.fetch = originalFetch; await server.close() })

async function until(predicate) {
  for (let attempt = 0; attempt < 40; attempt++) {
    if (predicate()) return
    await new Promise(resolve => setImmediate(resolve))
  }
  assert.ok(predicate(), 'state did not settle')
}
function createView(id = 'mine', readonly = false) {
  auth.authState.account = {
    user: { id: 'user', username: 'user', display_name: '用户' },
    default_knowledge_base: library('mine'), csrf_token: 'test-csrf',
  }
  const selected = ref(library(id, readonly))
  const scope = effectScope()
  return { selected, scope, ...scope.run(() => documents.useDocuments(selected)) }
}

test('switching library ignores the previous document list and clears private state', async () => {
  const pending = []
  globalThis.fetch = async (url) => {
    if (url.endsWith('/upload-config')) return response(config)
    return new Promise(resolve => pending.push({ url, resolve }))
  }
  const view = createView()
  try {
    view.selected.value = library('course', true)
    await nextTick()
    pending.find(item => item.url.includes('/course/')).resolve(response(page([doc('course-doc', 'course')])))
    await until(() => view.state.documents[0]?.id === 'course-doc')
    pending.find(item => item.url.includes('/mine/')).resolve(response(page([doc('private-doc', 'mine')])))
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(view.state.documents[0].id, 'course-doc')
  } finally { view.scope.stop() }
  assert.deepEqual(view.state.documents, [])
})

test('an upload failure preserves its message after automatic list refresh', async () => {
  let writes = 0
  globalThis.fetch = async (url, options) => {
    if (options.method === 'POST') {
      writes++
      return response({ code: 'UPLOAD_FAILED', message: '文件保存失败，可重试' }, 503)
    }
    return response(url.endsWith('/upload-config') ? config : page([]))
  }
  const view = createView()
  try {
    await until(() => !view.state.loading)
    const file = new File(['# 测试'], 'notes.md')
    assert.equal(await view.upload(file, ''), false)
    assert.match(view.state.actionError, /保存失败/)
    await view.reload(false)
    assert.match(view.state.actionError, /保存失败/)
    assert.equal(writes, 1)
    assert.equal(view.state.busy, false)
  } finally { view.scope.stop() }
})

test('a late upload acknowledgement cannot add a notice to a different library', async () => {
  let release
  globalThis.fetch = async (url, options) => {
    if (options.method === 'POST') return new Promise(resolve => { release = resolve })
    return response(url.endsWith('/upload-config') ? config : page([]))
  }
  const view = createView()
  try {
    await until(() => !view.state.loading)
    const upload = view.upload(new File(['hello'], 'notes.md'), '')
    view.selected.value = library('course', true)
    await nextTick()
    release(response({ document: doc('old', 'mine'), duplicate: false }))
    assert.equal(await upload, false)
    assert.equal(view.state.notice, '')
    assert.equal(view.state.deletion, null)
    assert.equal(view.state.busy, false)
  } finally { view.scope.stop() }
})

test('readonly libraries do not submit upload or deletion requests', async () => {
  const methods = []
  globalThis.fetch = async (url, options) => {
    methods.push(options.method ?? 'GET')
    return response(url.endsWith('/upload-config') ? config : page([]))
  }
  const view = createView('course', true)
  try {
    await until(() => !view.state.loading)
    assert.equal(await view.upload(new File(['hello'], 'notes.md'), ''), false)
    await view.remove('course-doc')
    assert.ok(methods.every(method => method === 'GET'))
  } finally { view.scope.stop() }
})

test('changing the display name does not reset the current document page', async () => {
  let reads = 0
  globalThis.fetch = async (url) => {
    reads++
    return response(url.endsWith('/upload-config') ? config : page([doc('mine-doc', 'mine')]))
  }
  const view = createView()
  try {
    await until(() => !view.state.loading)
    const before = reads
    view.state.notice = '保留当前操作状态'
    auth.authState.account.user = { ...auth.authState.account.user, display_name: '新名称' }
    await nextTick()
    assert.equal(reads, before)
    assert.equal(view.state.documents[0].id, 'mine-doc')
    assert.equal(view.state.notice, '保留当前操作状态')
  } finally { view.scope.stop() }
})
