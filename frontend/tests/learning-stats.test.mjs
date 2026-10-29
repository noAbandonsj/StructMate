import assert from 'node:assert/strict'
import { before, after, test } from 'node:test'
import { createServer } from 'vite'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'

let server, LearningStats, PracticeQuestionCard
before(async () => {
  server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  LearningStats = (await server.ssrLoadModule('/src/components/LearningStats.vue')).default
  PracticeQuestionCard = (await server.ssrLoadModule('/src/components/PracticeQuestionCard.vue')).default
})
after(async () => { await server.close() })

const measure = (count, correct) => ({ count, correct_count: correct, accuracy: count ? correct / count : null })
function stats() {
  return {
    from_date: '2026-10-29', to_date: '2026-10-29',
    attempts: measure(4, 3), categories: { first: measure(3, 2), repeat: measure(1, 1), review: measure(0, 0) },
    hinted_attempt_count: 1, chapters: [{ chapter_id: 'one', name: '线性表', attempts: measure(4, 3), first: measure(3, 2), evidence: 'insufficient' }],
    learning: { asked_questions: 0, completed_answers: 0 }, wrong_questions: { new_in_range: 1, current_pending: 1 }, basis: '首次作答包含使用提示的首次作答。',
  }
}
const render = (component, props) => renderToString(createSSRApp({ render: () => h(component, props) }))

test('statistics render one first-attempt category', async () => {
  const html = await render(LearningStats, { stats: stats() })
  assert.match(html, /首次作答正确率/)
  assert.match(html, /66\.7%/)
  assert.doesNotMatch(html, /首次独立|首次提示作答/)
  assert.match(html, /重复练习/)
  assert.match(html, /错题复习/)
})

test('an empty chapter displays zero first attempts and an unevaluated accuracy', async () => {
  const snapshot = stats()
  snapshot.chapters[0].first = measure(0, 0)
  const html = await render(LearningStats, { stats: snapshot })
  assert.match(html, /<td>0<\/td>/)
  assert.match(html, /未评估/)
  assert.match(html, /证据不足（少于 5 道）/)
  assert.doesNotMatch(html, /旧报告|未记录/)
})

test('a hinted first answer has the same category label and retains its hint marker', async () => {
  const item = {
    id: 'one', position: 1, type: 'true_false', stem: '测试题', is_valid: true,
    options: [{ key: 'true', text: '正确' }, { key: 'false', text: '错误' }],
    attempt: { category: 'first', hinted: true, is_valid: true, is_correct: true, answer: 'true', reference_answer: 'true', explanation: '解析', source_info: { citations: [] } },
  }
  const html = await render(PracticeQuestionCard, { item, busy: false })
  assert.match(html, /首次作答 · 使用了提示/)
  assert.doesNotMatch(html, /首次独立|首次提示作答/)
})
