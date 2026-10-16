<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { usePractice } from '../state/practice'
import { difficultyOptions } from '../learning-options'
import MarkdownContent from '../components/MarkdownContent'
const route = useRoute(), router = useRouter()
const selected = computed(() => typeof route.params.id === 'string' ? route.params.id : '')
const { state, reload, create, submit, hint, feedback } = usePractice(selected)
const reasons = reactive<Record<string, string>>({})
const pointSearch = ref('')
const pointGroups = computed(() => {
  const query = pointSearch.value.trim().toLowerCase()
  return state.points.filter(point => !point.parent_id).sort((a, b) => a.sort_order - b.sort_order).map(root => ({ root,
    points: state.points.filter(point => (point.parent_id === root.id || point.id === root.id) && (root.name.toLowerCase().includes(query) || point.name.toLowerCase().includes(query))).sort((a, b) => a.sort_order - b.sort_order),
  })).filter(group => group.points.length)
})
const selectedDifficulty = computed(() => difficultyOptions.find(option => option.value === state.form.difficulty))
const startReason = computed(() => {
  if (state.busy) return '正在提交，请稍候。'
  if (state.loading) return '正在读取练习设置。'
  if (state.readError || !state.ready) return '练习设置暂未就绪，请刷新重试。'
  if (state.practice?.status === 'generating') return '当前题组正在生成并复核，请等待完成后再开始新练习。'
  if (state.form.question_source === 'ai' && !state.generationAvailable) return '生成模型暂不可用，可切换为核验题库。'
  if (!Number.isInteger(state.form.count) || state.form.count < 1 || state.form.count > 20) return '题量须为 1 至 20 的整数。'
  return ''
})
function jumpTo(id: string) {
  const element = document.getElementById('question-' + id)
  element?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  element?.focus({ preventScroll: true })
}
function nextQuestion(position: number) {
  const next = state.items.find(item => item.position > position && !item.attempt && item.is_valid) ?? state.items.find(item => !item.attempt && item.is_valid)
  if (next) jumpTo(next.id)
}
const sourceLabel = (source: string | null) => source === 'ai' ? '实时 AI · 参考答案' : source === 'bank' ? '核验题库' : '错题复习'
function time(value: string) { return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) }
function safeLink(value: string) { try { return ['https:', 'http:'].includes(new URL(value).protocol) ? value : '#' } catch { return '#' } }
watch(() => route.query.point, value => { if (typeof value === 'string') state.form.knowledge_point_ids = [value] }, { immediate: true })
async function start() {
  if (startReason.value) return
  const source = typeof route.query.conversation === 'string' ? route.query.conversation : state.practice?.source_conversation_id ?? undefined
  const practice = await create(source)
  if (practice) await router.push('/practice/' + practice.id)
}
function retryGeneration() {
  if (!state.practice || state.practice.mode === 'review') return
  const old = state.practice.settings
  state.form = { ...state.form, ...old, question_source: state.practice.question_source ?? 'bank' }
  void start()
}
</script>
<template>
  <section>
    <div class="section-heading"><h1>练习中心</h1><button class="text-button" :disabled="state.loading" @click="reload()">刷新练习</button></div>
    <p class="intro-copy">切换出题方式会保留设置，只影响下一组练习。题库答案已核验，AI 题按生成时保存的参考答案反馈。</p>
    <p v-if="state.readError" class="form-error" role="alert">暂时无法更新练习与设置，已有内容已保留。{{ state.readError }} <button @click="reload()" :disabled="state.loading">重试读取</button></p>
    <p v-if="state.error" class="form-error" role="alert">{{ state.error }}</p>
    <div class="practice-layout">
      <aside class="practice-settings">
        <form @submit.prevent="start">
          <fieldset :disabled="state.busy">
            <legend>开始新练习</legend>
            <fieldset class="choice-field"><legend>出题方式</legend><div class="segmented-control"><label><input type="radio" v-model="state.form.question_source" value="bank"><span>核验题库</span></label><label><input type="radio" v-model="state.form.question_source" value="ai"><span>实时 AI</span></label></div></fieldset>
            <label>练习策略<select v-model="state.form.mode"><option value="chapter">按知识点</option><option value="adaptive">推荐练习</option></select></label>
            <fieldset class="choice-field"><legend>难度</legend><div class="segmented-control"><label v-for="option in difficultyOptions" :key="option.value"><input type="radio" v-model="state.form.difficulty" :value="option.value"><span>{{ option.label }}</span></label></div><p class="field-help">{{ selectedDifficulty?.help }}，实际难度以具体题目为准。</p></fieldset>
            <fieldset class="choice-field"><legend>题量</legend><div class="count-options"><button v-for="count in [5, 10, 20]" :key="count" type="button" :aria-pressed="state.form.count === count" @click="state.form.count = count">{{ count }} 题</button><label class="custom-count">自定义<input type="number" v-model.number="state.form.count" min="1" max="20" required aria-label="自定义题量"></label></div></fieldset>
            <details class="point-picker"><summary>{{ state.form.knowledge_point_ids.length ? `已选 ${state.form.knowledge_point_ids.length} 个知识点` : '全部知识点' }} · 更改范围</summary><label class="check-row"><input type="checkbox" :checked="!state.form.knowledge_point_ids.length" @change="state.form.knowledge_point_ids = []">全部知识点</label><input type="search" v-model="pointSearch" placeholder="搜索知识点" aria-label="搜索知识点"><div class="point-list"><fieldset v-for="group in pointGroups" :key="group.root.id"><legend>{{ group.root.name }}</legend><label v-for="point in group.points" :key="point.id" class="check-row"><input type="checkbox" v-model="state.form.knowledge_point_ids" :value="point.id">{{ point.name }}</label></fieldset><p v-if="!pointGroups.length" class="field-help">{{ state.loading ? '正在读取知识点…' : state.readError ? '暂时无法读取知识点，请重试。' : '没有匹配的知识点。' }}</p></div><button type="button" class="text-button" :disabled="!state.form.knowledge_point_ids.length" @click="state.form.knowledge_point_ids = []">清空选择，使用全部知识点</button></details>
            <details v-if="state.form.question_source === 'ai'"><summary>额外出题要求（选填）</summary><label>出题要求<textarea v-model="state.form.generation_requirements" maxlength="1000" rows="3" placeholder="例如：侧重概念辨析与复杂度分析"></textarea></label></details>
            <p v-if="startReason" id="practice-start-reason" class="field-help" role="status">{{ startReason }}</p>
            <button class="primary-button" :disabled="!!startReason" :aria-describedby="startReason ? 'practice-start-reason' : undefined">{{ state.busy ? '正在提交…' : state.practice?.status === 'generating' ? '正在生成并复核…' : '开始新练习' }}</button>
          </fieldset>
        </form>
        <details class="performance-panel"><summary>推荐依据：最近 30 天</summary><p class="field-help">只计算不同新题的首次独立作答。提示作答、重复练习和复习分开统计。包含题库与 AI 题，AI 按保存的参考答案计分，停用题排除。</p>
          <p v-for="item in state.analysis?.items" :key="item.knowledge_point_id">{{ item.name }}：{{ item.sample_count }} 道，{{ item.accuracy === null ? '未评估' : (item.accuracy * 100).toFixed(0) + '%' }}<span class="field-help"> · {{ item.reason }}</span></p>
        </details>
        <h2 class="history-heading">已有练习</h2><p v-if="state.loading && !state.history.length" class="field-help">正在读取已有练习…</p><p v-else-if="state.readError && !state.history.length" class="field-help">暂时无法读取已有练习，请重试。</p><p v-else-if="!state.history.length" class="field-help">开始一组练习后会保存在这里。</p>
        <RouterLink v-for="practice in state.history" :key="practice.id" :to="'/practice/' + practice.id" class="conversation-link" :class="{ selected: selected === practice.id }">{{ sourceLabel(practice.question_source) }} · {{ practice.actual_count }} 题<span class="field-help">{{ time(practice.created_at) }}</span></RouterLink>
        <div v-if="state.total > 20" class="document-pagination"><button :disabled="state.page <= 1 || state.loading" @click="state.page--; reload()">上一页</button><span>{{ state.page }}</span><button :disabled="state.page * 20 >= state.total || state.loading" @click="state.page++; reload()">下一页</button></div>
      </aside>
      <div class="practice-main">
        <p v-if="!state.practice" class="notice">{{ state.loading ? '正在读取练习…' : state.readError ? '练习尚未读取成功，重试后可继续学习。' : selected ? '暂未取得这组练习，请刷新重试。' : '选择出题方式、难度和题量，开始一组练习。' }}</p>
        <template v-else>
          <div class="section-heading"><h2>{{ sourceLabel(state.practice.question_source) }}</h2><RouterLink v-if="state.practice.source_conversation_id" :to="'/chat/' + state.practice.source_conversation_id">返回原会话</RouterLink></div>
          <p v-if="state.practice.status === 'generating'" class="notice" role="status">正在生成并复核题目，通常需要一些时间。可离开页面，回来后自动恢复状态；无需重复创建。</p>
          <div v-if="state.practice.status === 'failed'" class="form-error" role="alert">{{ state.practice.error_message }} <button @click="retryGeneration" :disabled="state.busy">按原设置重试</button></div>
          <p v-if="state.practice.notice" class="notice">{{ state.practice.notice }}</p>
          <p v-if="state.practice.actual_count" class="practice-progress">已提交 {{ state.practice.submitted_count }} / {{ state.practice.effective_count }} 道有效题，答对 {{ state.practice.correct_count }} 道。{{ state.practice.status === 'completed' ? '本组已完成。' : '' }}</p>
          <nav v-if="state.items.length" class="question-nav" aria-label="题号导航"><button v-for="item in state.items" :key="item.id" :class="{ answered: !!item.attempt, incorrect: item.attempt?.is_valid && !item.attempt.is_correct }" :aria-label="`第 ${item.position} 题，${!item.is_valid ? '已停用' : item.attempt ? item.attempt.is_correct ? '已答对' : '已答错' : '未作答'}`" @click="jumpTo(item.id)">{{ item.position }}</button></nav>
          <article v-for="item in state.items" :key="item.id" :id="'question-' + item.id" class="question-card" tabindex="-1">
            <p class="field-help">第 {{ item.position }} 题 · {{ item.type === 'true_false' ? '判断题' : '单选题' }} · {{ sourceLabel(item.source_type) }}</p>
            <h3>{{ item.stem }}</h3>
            <p v-if="!item.is_valid" class="notice">此题已确认有误，已排除统计：{{ item.disabled_reason }}</p>
            <fieldset class="answer-options" :disabled="state.busy || !!item.attempt || !item.is_valid"><label v-for="option in item.options" :key="option.key" :class="{ 'option-correct': item.attempt?.is_valid && item.attempt.reference_answer === option.key, 'option-incorrect': item.attempt?.is_valid && !item.attempt.is_correct && item.attempt.answer === option.key }"><input type="radio" :name="item.id" :value="option.key" :checked="(item.attempt?.answer ?? state.choices[item.id]) === option.key" @change="state.choices[item.id] = option.key"><span>{{ option.text }}</span></label></fieldset>
            <template v-if="!item.attempt && item.is_valid">
              <p v-if="item.hint" class="notice">提示：{{ item.hint }}</p>
              <div class="question-actions"><button class="primary-button" :disabled="state.busy || !state.choices[item.id]" @click="submit(item)">提交本题</button><button :disabled="state.busy || item.hinted" @click="hint(item)">{{ item.hinted ? '已使用提示' : '给我提示' }}</button></div>
              <p class="field-help">未提交的选择仅保存在当前账号的浏览器会话中，不计入统计。</p>
            </template>
            <div v-else-if="item.attempt" class="answer-result" :class="{ incorrect: item.attempt.is_valid && !item.attempt.is_correct }" role="status">
              <strong>{{ !item.attempt.is_valid ? '此结果已排除统计' : item.attempt.is_correct ? '回答正确' : '已加入错题本' }}</strong>
              <p>{{ item.source_type === 'ai' ? '参考答案' : '核验答案' }}：{{ item.options.find(option => option.key === item.attempt!.reference_answer)?.text }}</p><MarkdownContent :content="item.attempt.explanation" />
              <button v-if="state.items.some(value => !value.attempt && value.is_valid)" @click="nextQuestion(item.position)">下一道未作答题</button>
              <p class="field-help">{{ item.attempt.category === 'first_independent' ? '首次独立作答' : item.attempt.category === 'first_hinted' ? '首次提示作答' : item.attempt.category === 'review' ? '错题复习' : '重复练习' }}{{ item.attempt.hinted ? ' · 使用了提示' : '' }}</p>
              <RouterLink v-if="item.attempt.wrong_question_id" :to="'/wrong/' + item.attempt.wrong_question_id">查看错题与历次作答</RouterLink>
              <details><summary>依据与来源</summary><p v-for="source in item.attempt.source_info.sources" :key="source.url"><a :href="safeLink(source.url)" target="_blank" rel="noopener noreferrer">{{ source.title }}</a> · {{ source.author }} · {{ source.license }}</p><p v-for="(source, index) in item.attempt.source_info.citations" :key="index">{{ source.filename }}{{ source.source_deleted ? '（来源已删除，保留历史片段）' : '' }} {{ source.heading }} {{ source.page_number ? '第 ' + source.page_number + ' 页' : '' }}<span class="field-help">{{ source.text }}</span></p><p v-if="!item.attempt.source_info.sources?.length && !item.attempt.source_info.citations?.length" class="field-help">本题无资料引用，答案为生成时保存的 AI 参考答案。</p></details>
              <details><summary>反馈题目问题</summary><p v-if="item.feedback">反馈已保存，等待维护者核对：{{ item.feedback.reason }}</p><form v-else @submit.prevent="feedback(item, reasons[item.id] || '')"><textarea v-model="reasons[item.id]" minlength="5" maxlength="1000" required placeholder="请具体说明题干、选项或解析的问题"></textarea><button :disabled="state.busy">保存反馈</button></form></details>
            </div>
          </article>
        </template>
      </div>
    </div>
  </section>
</template>
