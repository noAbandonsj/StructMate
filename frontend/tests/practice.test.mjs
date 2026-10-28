import assert from 'node:assert/strict'
import { before, after, test } from 'node:test'
import { createServer } from 'vite'
let server, vue, auth, practice, wrong
const originalFetch = globalThis.fetch, originalSession = globalThis.sessionStorage, originalLocal = globalThis.localStorage
const response = (value, status = 200) => new Response(JSON.stringify(value), { status })
const page = items => ({ items, total: items.length, page: 1, page_size: 20 })
const session = id => ({ id, mode: 'chapter', status: 'ready', settings: {}, actual_count: 1, effective_count: 1, submitted_count: 0 })
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
  if (url.includes('/practice-sessions/materials?')) return Promise.resolve(response(page([{ id: 'my-notes', filename: '队列笔记', chapter_id: 'stack', kind: 'personal' }])))
  if (url.includes('/chapters')) return Promise.resolve(response(page([{ id: 'stack', code: 'stack-queue', name: '栈与队列' }, { id: 'tree', code: 'tree', name: '树与二叉树' }])))
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
test('chapter selection and material ownership are checked before creating exercises', async () => {
  let posts = 0
  globalThis.fetch = (url, options) => {
    if (options?.method === 'POST') posts++
    return defaults(url)
  }
  const view = scope('chapter-guard')
  try {
    await until(() => view.state.ready)
    await view.create()
    assert.match(view.state.error, /章节/)
    view.state.form.chapter_id = 'tree'
    view.state.form.document_ids = ['my-notes']
    await view.create()
    assert.match(view.state.error, /其他章节/)
    assert.equal(posts, 0)
  } finally { view.effect.stop() }
})

test('creation sends current chapter settings while preserving the displayed session', async () => {
  const posted = []
  globalThis.localStorage.setItem('capstone.practice.preferences.mode-owner', JSON.stringify({
    count: 8, difficulty: 'intermediate',
  }))
  globalThis.fetch = (url, options) => {
    if (url.endsWith('/practice-sessions') && options?.method === 'POST') {
      posted.push(JSON.parse(options.body))
      return Promise.resolve(response({ ...session('new-ai') }))
    }
    return defaults(url)
  }
  const view = scope('mode-owner')
  try {
    await until(() => view.state.practice)
    assert.equal(view.state.form.question_source, undefined)
    assert.equal(view.state.form.mode, undefined)
    assert.equal(view.state.form.count, 8)
    assert.equal(view.state.form.difficulty, 'intermediate')
    assert.equal(view.state.form.chapter_ids, undefined)
    view.state.form.chapter_id = 'tree'
    view.state.form.generation_requirements = '概念与复杂度'
    assert.equal(view.state.practice.id, 'one')
    await view.create()
    assert.equal(posted[0].question_source, undefined)
    assert.equal(posted[0].generation_requirements, '概念与复杂度')
    assert.equal(posted[0].mode, undefined)
    assert.equal(posted[0].chapter_id, 'tree')
    assert.equal(posted[0].topic, undefined)
    assert.deepEqual(posted[0].document_ids, [])
    assert.equal(posted[0].count, 8)
    assert.equal(view.state.practice.id, 'one')
  } finally { view.effect.stop() }
  const restored = scope('mode-owner')
  try { assert.equal(restored.state.form.question_source, undefined) } finally { restored.effect.stop() }
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

test('a lost creation response keeps the chapter, requirements, materials and request key', async () => {
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
    view.state.form.chapter_id = 'stack'
    view.state.form.generation_requirements = '  循环队列判空  '
    view.state.form.document_ids = ['my-notes']
    await view.create(); await view.create()
    assert.equal(posted[0].generation_requirements, '循环队列判空')
    assert.equal(posted[0].chapter_id, 'stack')
    assert.deepEqual(posted[0].document_ids, ['my-notes'])
    assert.equal(posted[0].client_request_id, posted[1].client_request_id)
    assert.ok(view.state.error)
    assert.equal(JSON.parse(globalThis.localStorage.getItem('capstone.practice.preferences.topic-retry-owner')).generation_requirements, '')
    view.state.form.generation_requirements = '队列应用'
    await view.create()
    assert.notEqual(posted[0].client_request_id, posted[2].client_request_id)
  } finally { view.effect.stop() }
  const restored = scope('topic-retry-owner', '')
  try {
    assert.equal(restored.state.form.generation_requirements, '队列应用')
    assert.equal(restored.state.form.chapter_id, 'stack')
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

test('generation polling stays quiet and only refreshes questions and history when finished', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const requests = [], pending = [], loading = []
  let initial = true
  globalThis.fetch = url => {
    requests.push(url)
    if (url.endsWith('/practice-sessions/one')) {
      if (initial) { initial = false; return Promise.resolve(response({ ...session('one'), status: 'generating' })) }
      return new Promise(resolve => pending.push(resolve))
    }
    return defaults(url)
  }
  const view = scope('quiet-poll-owner')
  const stop = vue.watch(() => view.state.loading, value => loading.push(value), { flush: 'sync' })
  try {
    await until(() => view.state.ready && !view.state.loading)
    const materials = view.state.materials, chapters = view.state.chapters
    requests.length = 0; loading.length = 0
    for (let poll = 0; poll < 2; poll++) {
      t.mock.timers.tick(1500)
      await until(() => pending.length === poll + 1)
      assert.equal(view.state.loading, false, 'a pending status request must not switch the form into loading')
      assert.equal(view.state.practice.status, 'generating')
      pending[poll](response({ ...session('one'), status: 'generating' }))
      await new Promise(resolve => setImmediate(resolve))
    }
    assert.deepEqual(requests, Array(2).fill('/api/v1/practice-sessions/one'))
    assert.equal(view.state.materials, materials)
    assert.equal(view.state.chapters, chapters)
    assert.deepEqual(loading, [])
    t.mock.timers.tick(1500)
    await until(() => pending.length === 3)
    assert.equal(view.state.items.length, 0)
    pending[2](response(session('one')))
    await until(() => view.state.practice.status === 'ready')
    assert.equal(view.state.items[0].id, 'question')
    assert.ok(requests.some(url => url.endsWith('/items')))
    assert.ok(requests.some(url => url.includes('/practice-sessions?')))
    assert.deepEqual(loading, [])
    const finishedCount = requests.length
    t.mock.timers.tick(1500)
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(requests.length, finishedCount, 'terminal sessions must stop polling')
  } finally { stop(); view.effect.stop() }
})

test('a polling error retains generation state and stays visible until a successful retry', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const pending = []
  let initial = true
  globalThis.fetch = url => {
    if (url.endsWith('/practice-sessions/one')) {
      if (initial) { initial = false; return Promise.resolve(response({ ...session('one'), status: 'generating' })) }
      return new Promise((resolve, reject) => pending.push({ resolve, reject }))
    }
    return defaults(url)
  }
  const view = scope('poll-error-owner')
  try {
    await until(() => view.state.ready && !view.state.loading)
    t.mock.timers.tick(1500)
    await until(() => pending.length === 1)
    pending[0].reject(new Error('offline'))
    await until(() => view.state.readError)
    const message = view.state.readError
    t.mock.timers.tick(1500)
    await until(() => pending.length === 2)
    assert.equal(view.state.readError, message)
    assert.equal(view.state.loading, false)
    assert.equal(view.state.practice.status, 'generating')
    pending[1].resolve(response({ ...session('one'), status: 'failed', error_message: '生成失败，请重试。' }))
    await until(() => view.state.practice.status === 'failed')
    assert.equal(view.state.readError, '')
    assert.equal(view.state.loading, false)
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
