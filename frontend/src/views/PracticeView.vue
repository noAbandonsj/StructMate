<script setup lang="ts">
import { computed, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { usePractice } from '../state/practice'
import { difficultyOptions, practiceSourceLabel as sourceLabel } from '../learning-options'
import { practiceProgress } from '../practice-answers'
import PracticeQuestionCard from '../components/PracticeQuestionCard.vue'
const route = useRoute(), router = useRouter()
const selected = computed(() => typeof route.params.id === 'string' ? route.params.id : '')
const { state, reload, create, submitAll, hint } = usePractice(selected)
const progress = computed(() => practiceProgress(state.items, state.choices))
const submitReason = computed(() => {
  if (state.busy) return '正在提交，请稍候。'
  if (state.loading || state.readError || !state.ready) return '练习数据尚未就绪，请刷新后重试。'
  if (progress.value.missingItems.length) return `还有 ${progress.value.missingItems.length} 道题未作答，完成后可统一提交。`
  return ''
})
const unavailableMaterials = computed(() => state.form.document_ids.filter(id => !state.materials.some(item => item.id === id)))
const selectedDifficulty = computed(() => difficultyOptions.find(option => option.value === state.form.difficulty))
const startReason = computed(() => {
  if (state.busy) return '正在提交，请稍候。'
  if (state.loading) return '正在读取练习设置。'
  if (state.readError || !state.ready) return '练习设置暂未就绪，请刷新重试。'
  if (state.practice?.status === 'generating') return '当前题组正在生成并复核，请等待完成后再开始新练习。'
  if (!state.generationAvailable) return 'AI 出题暂不可用，请联系管理员配置生成模型后重试。'
  if (!state.form.topic.trim() && !state.form.document_ids.length) return '请填写练习主题或选择参考资料。'
  if (unavailableMaterials.value.length) return '有参考资料已不可用，请移除后重新选择。'
  if (!Number.isInteger(state.form.count) || state.form.count < 1 || state.form.count > 20) return '题量须为 1 至 20 的整数。'
  return ''
})
function jumpTo(id: string) {
  const element = document.getElementById('question-' + id)
  element?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  element?.focus({ preventScroll: true })
}
function time(value: string) { return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) }
watch(() => route.query.topic, value => { if (typeof value === 'string') state.form.topic = value.slice(0, 500) }, { immediate: true })
watch(() => route.query.document, value => { if (typeof value === 'string') state.form.document_ids = [value] }, { immediate: true })
async function start() {
  if (startReason.value) return
  const source = typeof route.query.conversation === 'string' ? route.query.conversation : state.practice?.source_conversation_id ?? undefined
  const practice = await create(source)
  if (practice) await router.push('/practice/' + practice.id)
}
function retryGeneration() {
  if (!state.practice || state.practice.mode === 'review') return
  const old = state.practice.settings
  state.form = { question_source: 'ai', topic: old.topic_from_materials ? '' : old.topic || state.practice.title || '数据结构综合练习',
    document_ids: old.document_ids || [], count: old.count || 5, difficulty: old.difficulty || 'basic',
    generation_requirements: old.generation_requirements || '' }
  void start()
}
</script>
<template>
  <section>
    <div class="section-heading"><h1>练习中心</h1><button class="text-button" :disabled="state.loading" @click="reload()">刷新练习</button></div>
    <p class="intro-copy">全部作答后统一提交，再查看本组判题和解析。提交前可以修改选择，草稿会自动保留。</p>
    <p v-if="state.readError" class="form-error" role="alert">暂时无法更新练习与设置，已有内容已保留。{{ state.readError }} <button @click="reload()" :disabled="state.loading">重试读取</button></p>
    <p v-if="state.error" class="form-error" role="alert">{{ state.error }}</p>
    <div class="practice-layout">
      <aside class="practice-settings">
        <form @submit.prevent="start">
          <fieldset :disabled="state.busy">
            <legend>开始新练习</legend>
            <label>本次想练什么<textarea v-model="state.form.topic" maxlength="500" rows="3" placeholder="例如：循环队列的判满与判空，侧重代码理解" aria-describedby="practice-topic-help"></textarea></label>
            <p id="practice-topic-help" class="field-help">填写练习主题，或选择下方参考资料，至少提供一项。</p>
            <details class="material-picker"><summary>参考资料（选填）{{ state.form.document_ids.length ? ` · 已选 ${state.form.document_ids.length} 份` : '' }}</summary>
              <p class="field-help">可选课程资料或自己的笔记，最多 5 份。所选资料的相关片段将作为出题依据。</p>
              <p v-if="!state.materials.length" class="field-help">暂无可用于出题的资料。可先填写主题，或前往<RouterLink to="/knowledge">我的知识库</RouterLink>上传资料。</p>
              <label v-for="material in state.materials" :key="material.id" class="check-row"><input type="checkbox" v-model="state.form.document_ids" :value="material.id" :disabled="state.form.document_ids.length >= 5 && !state.form.document_ids.includes(material.id)">{{ material.filename }} · {{ material.kind === 'course' ? '课程资料' : '我的笔记' }}</label>
              <p v-for="id in unavailableMaterials" :key="id" class="form-error">一份所选资料已不可用。<button type="button" @click="state.form.document_ids = state.form.document_ids.filter(value => value !== id)">移除选择</button></p>
              <button type="button" class="text-button" :disabled="state.loading" @click="reload()">刷新资料</button>
            </details>
            <p class="field-help" role="status">{{ state.form.document_ids.length ? '依据所选资料片段出题；填写主题可进一步限定范围。' : '未选择参考资料：依据 AI 通用知识出题，不代表来自课程教材。' }}</p>
            <fieldset class="choice-field"><legend>难度</legend><div class="segmented-control"><label v-for="option in difficultyOptions" :key="option.value"><input type="radio" v-model="state.form.difficulty" :value="option.value"><span>{{ option.label }}</span></label></div><p class="field-help">{{ selectedDifficulty?.help }}，实际难度以具体题目为准。</p></fieldset>
            <fieldset class="choice-field"><legend>题量</legend><div class="count-options"><button v-for="count in [5, 10, 20]" :key="count" type="button" :aria-pressed="state.form.count === count" @click="state.form.count = count">{{ count }} 题</button><label class="custom-count">自定义<input type="number" v-model.number="state.form.count" min="1" max="20" required aria-label="自定义题量"></label></div></fieldset>
            <details><summary>额外出题要求（选填）</summary><label>出题要求<textarea v-model="state.form.generation_requirements" maxlength="1000" rows="3" placeholder="例如：侧重概念辨析与复杂度分析"></textarea></label></details>
            <p v-if="startReason" id="practice-start-reason" class="field-help" role="status">{{ startReason }}</p>
            <button class="primary-button" :disabled="!!startReason" :aria-describedby="startReason ? 'practice-start-reason' : undefined">{{ state.busy ? '正在提交…' : state.practice?.status === 'generating' ? '正在生成并复核…' : '开始新练习' }}</button>
          </fieldset>
        </form>
        <h2 class="history-heading">已有练习</h2><p v-if="state.loading && !state.history.length" class="field-help">正在读取已有练习…</p><p v-else-if="state.readError && !state.history.length" class="field-help">暂时无法读取已有练习，请重试。</p><p v-else-if="!state.history.length" class="field-help">开始一组练习后会保存在这里。</p>
        <RouterLink v-for="practice in state.history" :key="practice.id" :to="'/practice/' + practice.id" class="conversation-link" :class="{ selected: selected === practice.id }">{{ practice.title || sourceLabel(practice.question_source) }} · {{ practice.actual_count }} 题<span class="field-help">{{ time(practice.created_at) }}</span></RouterLink>
        <div v-if="state.total > 20" class="document-pagination"><button :disabled="state.page <= 1 || state.loading" @click="state.page--; reload()">上一页</button><span>{{ state.page }}</span><button :disabled="state.page * 20 >= state.total || state.loading" @click="state.page++; reload()">下一页</button></div>
      </aside>
      <div class="practice-main">
        <p v-if="!state.practice" class="notice">{{ state.loading ? '正在读取练习…' : state.readError ? '练习尚未读取成功，重试后可继续学习。' : selected ? '暂未取得这组练习，请刷新重试。' : '填写主题或选择参考资料，设置难度和题量，即可开始 AI 练习。' }}</p>
        <template v-else>
          <div class="section-heading"><h2>{{ state.practice.title || sourceLabel(state.practice.question_source) }}</h2><RouterLink v-if="state.practice.source_conversation_id" :to="'/chat/' + state.practice.source_conversation_id">返回原会话</RouterLink></div>
          <p v-if="state.practice.question_source === 'ai'" class="field-help">{{ state.practice.settings.document_ids?.length ? '参考资料：' + (state.practice.settings.reference_documents || []).map(item => item.filename).join('、') : 'AI 通用知识练习 · 按保存的参考答案判题' }}</p>
          <p v-if="state.practice.status === 'generating'" class="notice" role="status">正在生成并复核题目，通常需要一些时间。可离开页面，回来后自动恢复状态；无需重复创建。</p>
          <div v-if="state.practice.status === 'failed'" class="form-error" role="alert">{{ state.practice.error_message }} <button @click="retryGeneration" :disabled="state.busy">按原设置重试</button></div>
          <p v-if="state.practice.notice" class="notice">{{ state.practice.notice }}</p>
          <p v-if="state.practice.actual_count" class="practice-progress">{{ progress.pendingItems.length ? `已作答 ${progress.answeredCount} / ${progress.effectiveItems.length} 道有效题，完成后统一提交。` : `已提交 ${state.practice.submitted_count} / ${state.practice.effective_count} 道有效题，答对 ${state.practice.correct_count} 道。` }}{{ state.practice.status === 'completed' ? '本组已完成。' : '' }}</p>
          <nav v-if="state.items.length" class="question-nav" aria-label="题号导航"><button v-for="item in state.items" :key="item.id" :class="{ answered: !!item.attempt, drafted: !item.attempt && !!state.choices[item.id], incorrect: item.attempt?.is_valid && !item.attempt.is_correct }" :aria-label="`第 ${item.position} 题，${!item.is_valid ? '已停用' : item.attempt ? item.attempt.is_correct ? '已答对' : '已答错' : state.choices[item.id] ? '已作答，未提交' : '未作答'}`" @click="jumpTo(item.id)">{{ item.position }}</button></nav>
          <PracticeQuestionCard
            v-for="item in state.items" :key="item.id" :item="item"
            :choice="state.choices[item.id]" :busy="state.busy"
            @choose="(id, answer) => state.choices[id] = answer" @hint="hint"
          />
          <section v-if="progress.pendingItems.length && state.practice.status === 'ready'" class="practice-submit" aria-label="提交整组练习">
            <p>已作答 {{ progress.answeredCount }} / {{ progress.effectiveItems.length }} 道有效题。</p>
            <p v-if="submitReason" id="practice-submit-reason" class="field-help" role="status">{{ submitReason }}</p>
            <p v-else class="field-help">全部题目已作答，可以统一提交并查看结果。</p>
            <button class="primary-button" :disabled="!!submitReason" :aria-describedby="submitReason ? 'practice-submit-reason' : undefined" @click="submitAll()">{{ state.busy ? '正在提交…' : '提交全部答案' }}</button>
            <p class="field-help">提交前可修改任意选择。未提交的选择只保存在当前账号的浏览器会话中，不计入统计。</p>
          </section>
        </template>
      </div>
    </div>
  </section>
</template>
