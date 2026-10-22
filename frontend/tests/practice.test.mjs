import assert from 'node:assert/strict'
import { before, after, test } from 'node:test'
import { createServer } from 'vite'
let server, vue, auth, practice, wrong
const originalFetch = globalThis.fetch, originalSession = globalThis.sessionStorage, originalLocal = globalThis.localStorage
const response = (value, status = 200) => new Response(JSON.stringify(value), { status })
const page = items => ({ items, total: items.length, page: 1, page_size: 20 })
const session = id => ({ id, mode: 'chapter', question_source: 'bank', status: 'ready', settings: {}, actual_count: 1, effective_count: 1, submitted_count: 0 })
const item = id => ({ id, question_id: id, options: [{ key: 'A', text: '选项 A' }, { key: 'B', text: '选项 B' }], attempt: null, is_valid: true, hinted: false, hint: null })
const account = id => ({ user: { id }, csrf_token: 'test-' + id })
function storage() {
  const values = new Map()
  return { get length() { return values.size }, key: index => [...values.keys()][index] ?? null,
    getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
}
before(async () => {
  server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  auth = await server.ssrLoadModule('/src/state/auth.ts')
  practice = await server.ssrLoadModule('/src/state/practice.ts')
  wrong = await server.ssrLoadModule('/src/state/wrong.ts')
  vue = await import('vue')
  globalThis.sessionStorage = storage(); globalThis.localStorage = storage()
})
after(async () => { globalThis.fetch = originalFetch; globalThis.sessionStorage = originalSession; globalThis.localStorage = originalLocal; await server.close() })
async function until(predicate) {
  for (let attempt = 0; attempt < 60; attempt++) { if (predicate()) return; await new Promise(resolve => setImmediate(resolve)) }
  assert.ok(predicate(), 'state did not settle')
}
function defaults(url) {
  if (url.includes('/practice-sessions/materials?')) return Promise.resolve(response(page([])))
  if (url.includes('/knowledge-points')) return Promise.resolve(response(page([])))
  if (url.includes('/learning/performance')) return Promise.resolve(response({ items: [], window_days: 30 }))
  if (url.endsWith('/config')) return Promise.resolve(response({ generation_available: false }))
  if (url.includes('/practice-sessions?')) return Promise.resolve(response(page([session('one')])))
  if (url.endsWith('/items')) return Promise.resolve(response(page([item('question')])))
  if (url.includes('/wrong-questions?')) return Promise.resolve(response(page([])))
  return Promise.resolve(response(session(url.split('/').at(-1))))
}
function scope(user = 'student', id = 'one', wrongModule = false) {
  auth.authState.account = account(user); auth.authState.status = 'ready'
  const selected = vue.ref(id), effect = vue.effectScope()
  return { effect, selected, ...effect.run(() => (wrongModule ? wrong.useWrong(selected) : practice.usePractice(selected))) }
}
test('a failed group submission preserves the selected option and request key across remount', async () => {
  const posted = []
  globalThis.fetch = (url, options) => {
    if (url.endsWith('/submit')) { posted.push(JSON.parse(options.body)); return Promise.reject(new Error('offline')) }
    return defaults(url)
  }
  const view = scope('failed-submit')
  try {
    await until(() => view.state.items.length)
    view.state.choices.question = 'A'
    await view.submitAll(); await view.submitAll()
    assert.equal(view.state.choices.question, 'A')
    assert.equal(posted[0].client_request_id, posted[1].client_request_id)
    assert.ok(view.state.error)
    await view.reload()
    assert.ok(view.state.error, 'a background refresh must not erase the submission error')
  } finally { view.effect.stop() }
  const restored = scope('failed-submit')
  try {
    await until(() => restored.state.items.length)
    assert.equal(restored.state.choices.question, 'A')
    await restored.submitAll()
    assert.equal(posted[0].client_request_id, posted[2].client_request_id)
    assert.deepEqual(posted[0].answers, [{ practice_item_id: 'question', answer: 'A' }])
  } finally { restored.effect.stop() }
})
test('legacy bank preferences create AI exercises while preserving existing practice history', async () => {
  const posted = []
  globalThis.localStorage.setItem('capstone.practice.preferences.mode-owner', JSON.stringify({
    question_source: 'bank', mode: 'adaptive', count: 8, difficulty: 'intermediate', knowledge_point_ids: ['tree'],
  }))
  globalThis.fetch = (url, options) => {
    if (url.endsWith('/practice-sessions') && options?.method === 'POST') {
      posted.push(JSON.parse(options.body))
      return Promise.resolve(response({ ...session('new-ai'), question_source: 'ai' }))
    }
    return defaults(url)
  }
  const view = scope('mode-owner')
  try {
    await until(() => view.state.practice)
    assert.equal(view.state.form.question_source, 'ai')
    assert.equal(view.state.form.mode, undefined)
    assert.equal(view.state.form.count, 8)
    assert.equal(view.state.form.difficulty, 'intermediate')
    assert.equal(view.state.form.knowledge_point_ids, undefined)
    view.state.form.topic = '二叉树遍历'
    view.state.form.generation_requirements = '概念与复杂度'
    assert.equal(view.state.practice.question_source, 'bank')
    await view.create()
    assert.equal(posted[0].question_source, 'ai')
    assert.equal(posted[0].generation_requirements, '概念与复杂度')
    assert.equal(posted[0].mode, undefined)
    assert.equal(posted[0].topic, '二叉树遍历')
    assert.deepEqual(posted[0].document_ids, [])
    assert.equal(posted[0].count, 8)
    assert.equal(view.state.practice.question_source, 'bank')
  } finally { view.effect.stop() }
  const restored = scope('mode-owner')
  try { assert.equal(restored.state.form.question_source, 'ai') } finally { restored.effect.stop() }
})
test('an unsubmitted choice survives remount and is cleared on sign out', async () => {
  globalThis.fetch = defaults
  const first = scope('draft-owner')
  await until(() => first.state.items.length)
  first.state.choices.question = 'B'; first.effect.stop()
  const restored = scope('draft-owner')
  try {
    await until(() => restored.state.items.length)
    assert.equal(restored.state.choices.question, 'B')
    globalThis.fetch = () => Promise.resolve(new Response(null, { status: 204 }))
    await auth.signOut(); await vue.nextTick()
    assert.deepEqual(restored.state.choices, {})
    assert.equal(globalThis.sessionStorage.getItem('capstone.practice.draft-owner.one'), null)
  } finally { restored.effect.stop() }
})

test('a lost creation response keeps the topic, selected materials and request key', async () => {
  const posted = []
  globalThis.fetch = (url, options) => {
    if (url.endsWith('/practice-sessions') && options?.method === 'POST') {
      posted.push(JSON.parse(options.body)); return Promise.reject(new Error('offline'))
    }
    return defaults(url)
  }
  const view = scope('topic-retry-owner', '')
  try {
    await until(() => view.state.ready)
    view.state.form.topic = '  循环队列判空  '
    view.state.form.document_ids = ['my-notes']
    await view.create(); await view.create()
    assert.equal(posted[0].topic, '循环队列判空')
    assert.deepEqual(posted[0].document_ids, ['my-notes'])
    assert.equal(posted[0].client_request_id, posted[1].client_request_id)
    assert.ok(view.state.error)
    assert.equal(JSON.parse(globalThis.localStorage.getItem('capstone.practice.preferences.topic-retry-owner')).topic, '')
    view.state.form.topic = '二叉树遍历'
    await view.create()
    assert.notEqual(posted[0].client_request_id, posted[2].client_request_id)
  } finally { view.effect.stop() }
  const restored = scope('topic-retry-owner', '')
  try {
    assert.equal(restored.state.form.topic, '二叉树遍历')
    assert.deepEqual(restored.state.form.document_ids, ['my-notes'])
  } finally { restored.effect.stop() }
})

test('material choices from an old account cannot enter the new account', async () => {
  const pending = []
  globalThis.fetch = url => url.includes('/practice-sessions/materials?')
    ? new Promise(resolve => pending.push(resolve)) : defaults(url)
  const view = scope('materials-first', '')
  try {
    await until(() => pending.length === 1)
    auth.authState.account = account('materials-second'); await vue.nextTick()
    await until(() => pending.length === 2)
    pending[1](response(page([{ id: 'second-file', filename: '当前账号资料', kind: 'personal' }])))
    await until(() => view.state.ready)
    pending[0](response(page([{ id: 'private-file', filename: '旧账号私人资料', kind: 'personal' }])))
    await new Promise(resolve => setImmediate(resolve))
    assert.deepEqual(view.state.materials.map(value => value.id), ['second-file'])
  } finally { view.effect.stop() }
})
test('changing accounts rejects an old practice detail response', async () => {
  const pending = []
  globalThis.fetch = url => url.endsWith('/practice-sessions/one')
    ? new Promise(resolve => pending.push({ user: auth.authState.account.user.id, resolve })) : defaults(url)
  const view = scope('first')
  try {
    await until(() => pending.length === 1)
    auth.authState.account = account('second'); await vue.nextTick()
    await until(() => pending.length === 2)
    pending[1].resolve(response({ ...session('one'), notice: '新账号' }))
    await until(() => view.state.practice)
    pending[0].resolve(response({ ...session('one'), notice: '私有旧内容' }))
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(view.state.practice.notice, '新账号')
  } finally { view.effect.stop() }
})
test('a hint response applies to the current item after a list refresh', async () => {
  let completeHint
  globalThis.fetch = url => url.endsWith('/hint')
    ? new Promise(resolve => { completeHint = resolve }) : defaults(url)
  const view = scope('hint-owner')
  try {
    await until(() => view.state.items.length)
    const original = view.state.items[0]
    const operation = view.hint(original)
    await view.reload()
    completeHint(response({ hint: '先比较定义', hinted: true }))
    await operation
    assert.equal(view.state.items[0].hinted, true)
    assert.equal(view.state.items[0].hint, '先比较定义')
  } finally { view.effect.stop() }
})
test('late wrong-question details cannot replace the selected question', async () => {
  const pending = []
  globalThis.fetch = url => /\/wrong-questions\/(one|two)$/.test(url)
    ? new Promise(resolve => pending.push({ id: url.split('/').at(-1), resolve })) : defaults(url)
  const view = scope('wrong-owner', 'one', true)
  try {
    await until(() => pending.length === 1)
    view.selected.value = 'two'; await vue.nextTick()
    await until(() => pending.length === 2)
    pending[1].resolve(response({ id: 'two', stem: '当前题目' }))
    await until(() => view.state.detail?.id === 'two')
    pending[0].resolve(response({ id: 'one', stem: '旧题' }))
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(view.state.detail.id, 'two')
  } finally { view.effect.stop() }
})

test('finishing generation cannot leave ready metadata paired with an earlier empty item list', async () => {
  let published = false, finish
  globalThis.fetch = url => {
    if (url.endsWith('/practice-sessions/one')) return new Promise(resolve => {
      finish = () => { published = true; resolve(response(session('one'))) }
    })
    if (url.endsWith('/items')) return Promise.resolve(response(page(published ? [item('published-question')] : [])))
    return defaults(url)
  }
  const view = scope('generation-owner')
  try {
    await until(() => finish)
    finish()
    await until(() => !view.state.loading && view.state.practice)
    assert.equal(view.state.practice.status, 'ready')
    assert.equal(view.state.items.length, 1)
    assert.equal(view.state.items[0].id, 'published-question')
  } finally { view.effect.stop() }
})

test('failed refresh keeps existing practice data and exposes the read failure separately', async () => {
  globalThis.fetch = defaults
  const view = scope('refresh-failure-owner')
  try {
    await until(() => view.state.ready)
    globalThis.fetch = async () => { throw new Error('offline') }
    await view.reload()
    assert.ok(view.state.readError)
    assert.equal(view.state.history.length, 1)
    assert.equal(view.state.items[0].id, 'question')
    assert.equal(view.state.practice.id, 'one')
    globalThis.fetch = defaults
    await view.reload()
    assert.equal(view.state.readError, '')
  } finally { view.effect.stop() }
})


test('only a completed set of choices is sent in one request and all results appear together', async () => {
  const questions = [item('first-question'), item('second-question')]
  const completed = questions.map((value, index) => ({ ...value, attempt: {
    id: 'result-' + index, answer: index ? 'B' : 'A', is_correct: true, is_valid: true,
  } }))
  const posted = []
  let submitted = false
  const metadata = () => ({ ...session('one'), effective_count: 2, actual_count: 2,
    status: submitted ? 'completed' : 'ready', submitted_count: submitted ? 2 : 0 })
  globalThis.fetch = (url, options) => {
    if (url.endsWith('/submit')) {
      posted.push(JSON.parse(options.body)); submitted = true
      return Promise.resolve(response({ practice: metadata(), items: completed }))
    }
    if (url.endsWith('/practice-sessions/one')) return Promise.resolve(response(metadata()))
    if (url.endsWith('/practice-sessions/one/items')) return Promise.resolve(response(page(submitted ? completed : questions)))
    return defaults(url)
  }
  const view = scope('submit-all-owner')
  try {
    await until(() => view.state.ready)
    view.state.choices['first-question'] = 'A'
    await view.submitAll()
    assert.equal(posted.length, 0)
    assert.ok(view.state.items.every(value => !value.attempt))
    view.state.choices['second-question'] = 'invalid-option'
    await view.submitAll()
    assert.equal(posted.length, 0, 'an invalid restored choice must still count as unanswered')
    view.state.choices['second-question'] = 'B'
    await view.submitAll()
    assert.equal(posted.length, 1)
    assert.equal(posted[0].answers.length, 2)
    assert.equal(view.state.practice.status, 'completed')
    assert.ok(view.state.items.every(value => value.attempt))
    assert.deepEqual(view.state.choices, {})
    assert.equal(globalThis.sessionStorage.getItem('capstone.practice.submit-all-owner.submit.one'), null)
  } finally { view.effect.stop() }
})
