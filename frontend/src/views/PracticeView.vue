<script setup lang="ts">
import { computed, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { usePractice } from '../state/practice'
import { difficultyOptions } from '../learning-options'
import { practiceProgress } from '../practice-answers'
import PracticeQuestionCard from '../components/PracticeQuestionCard.vue'
import DisclosurePanel from '../components/DisclosurePanel.vue'
const route = useRoute(), router = useRouter()
const selected = computed(() => typeof route.params.id === 'string' ? route.params.id : '')
const { state, reload, create, submitAll, hint } = usePractice(selected)
const progress = computed(() => practiceProgress(state.items, state.choices))
const submitReason = computed(() => {
  if (state.busy) return '正在提交，请稍候。'
  if (state.loading || state.readError || !state.ready) return '练习数据尚未就绪，请刷新后重试。'
  if (progress.value.missingItems.length) return `还有 ${progress.value.missingItems.length} 道题未作答。`
  return ''
})
const unavailableMaterials = computed(() => state.form.document_ids.filter(id => !state.materials.some(item => item.id === id && (!item.chapter_id || item.chapter_id === state.form.chapter_id))))
const startReason = computed(() => {
  if (state.busy) return '正在提交，请稍候。'
  if (state.loading) return '正在读取练习设置。'
  if (state.readError || !state.ready) return '练习设置暂未就绪，请刷新重试。'
  if (state.practice?.status === 'generating') return '当前题组正在生成并复核，请等待完成后再开始新练习。'
  if (!state.generationAvailable) return 'AI 出题暂不可用，请联系管理员配置生成模型后重试。'
  if (!state.chapters.some(chapter => chapter.id === state.form.chapter_id)) return '请选择练习章节。'
  if (unavailableMaterials.value.length) return '有参考资料已不可用或属于其他章节，请移除后重新选择。'
  if (!Number.isInteger(state.form.count) || state.form.count < 1 || state.form.count > 20) return '题量须为 1 至 20 的整数。'
  return ''
})
function jumpTo(id: string) {
  const element = document.getElementById('question-' + id)
  element?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  element?.focus({ preventScroll: true })
}
function time(value: string) { return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) }
watch(() => route.query.requirements, value => { if (typeof value === 'string') state.form.generation_requirements = value.slice(0, 1000) }, { immediate: true })
watch(() => route.query.chapter, value => { if (typeof value === 'string') state.form.chapter_id = value }, { immediate: true })
const availableMaterials = computed(() => state.materials.filter(item => !item.chapter_id || item.chapter_id === state.form.chapter_id))
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
  state.form = { chapter_id: state.practice.chapter_id || '',
    document_ids: old.document_ids || [], count: old.count || 5, difficulty: old.difficulty || 'basic',
    generation_requirements: old.generation_requirements || '' }
  void start()
}
</script>
<template>
  <section>
    <div class="section-heading"><h1>练习中心</h1></div>
    <p v-if="state.readError" class="form-error" role="alert">暂时无法更新练习与设置，已有内容已保留。{{ state.readError }} <button @click="reload()" :disabled="state.loading">重试读取</button></p>
    <p v-if="state.error" class="form-error" role="alert">{{ state.error }}</p>
    <div class="practice-layout">
      <aside class="practice-settings">
        <form @submit.prevent="start">
          <fieldset :disabled="state.busy">
            <legend>开始新练习</legend>
            <label>练习章节<select v-model="state.form.chapter_id" required><option value="" disabled>请选择章节</option><option v-for="chapter in state.chapters" :key="chapter.id" :value="chapter.id">{{ chapter.name }}</option></select></label>
            <fieldset class="choice-field"><legend>难度</legend><div class="segmented-control"><label v-for="option in difficultyOptions" :key="option.value"><input type="radio" v-model="state.form.difficulty" :value="option.value"><span>{{ option.label }}</span></label></div></fieldset>
            <fieldset class="choice-field"><legend>题量</legend><div class="count-options"><button v-for="count in [5, 10, 20]" :key="count" type="button" :aria-pressed="state.form.count === count" @click="state.form.count = count">{{ count }} 题</button><label class="custom-count">自定义<input type="number" v-model.number="state.form.count" min="1" max="20" required aria-label="自定义题量"></label></div></fieldset>
            <DisclosurePanel class="material-picker" title="参考资料" :badge="state.form.document_ids.length ? `已选 ${state.form.document_ids.length} 份` : '选填'">
              <p class="field-help">最多选择 5 份资料。</p>
              <p v-if="!availableMaterials.length" class="field-help">暂无匹配资料，可前往<RouterLink to="/knowledge">我的知识库</RouterLink>上传。</p>
              <label v-for="material in availableMaterials" :key="material.id" class="check-row"><input type="checkbox" v-model="state.form.document_ids" :value="material.id" :disabled="state.form.document_ids.length >= 5 && !state.form.document_ids.includes(material.id)">{{ material.filename }} · {{ material.kind === 'course' ? '课程资料' : '我的笔记' }}</label>
              <p v-for="id in unavailableMaterials" :key="id" class="form-error">一份所选资料已不可用或属于其他章节。<button type="button" @click="state.form.document_ids = state.form.document_ids.filter(value => value !== id)">移除选择</button></p>
              <button type="button" class="text-button" :disabled="state.loading" @click="reload()">刷新资料</button>
            </DisclosurePanel>
            <DisclosurePanel class="practice-requirements" title="练习要求" :badge="state.form.generation_requirements.trim() ? '已填写' : '选填'" :open="typeof route.query.requirements === 'string' && !!route.query.requirements.trim()">
              <textarea v-model="state.form.generation_requirements" aria-label="练习要求" maxlength="1000" rows="4" placeholder="例如：侧重复杂度分析"></textarea>
            </DisclosurePanel>
            <p v-if="startReason" id="practice-start-reason" class="field-help" role="status">{{ startReason }}</p>
            <button class="primary-button" :disabled="!!startReason" :aria-describedby="startReason ? 'practice-start-reason' : undefined">{{ state.busy ? '正在提交…' : state.practice?.status === 'generating' ? '正在生成并复核…' : '开始新练习' }}</button>
          </fieldset>
        </form>
        <h2 class="history-heading">已有练习</h2><p v-if="state.loading && !state.history.length" class="field-help">正在读取已有练习…</p><p v-else-if="state.readError && !state.history.length" class="field-help">暂时无法读取已有练习，请重试。</p><p v-else-if="!state.history.length" class="field-help">开始一组练习后会保存在这里。</p>
        <RouterLink v-for="practice in state.history" :key="practice.id" :to="'/practice/' + practice.id" class="conversation-link" :class="{ selected: selected === practice.id }">{{ practice.title || 'AI 练习' }} · {{ practice.actual_count }} 题<span class="field-help">{{ time(practice.created_at) }}</span></RouterLink>
        <div v-if="state.total > 20" class="document-pagination"><button :disabled="state.page <= 1 || state.loading" @click="state.page--; reload()">上一页</button><span>{{ state.page }}</span><button :disabled="state.page * 20 >= state.total || state.loading" @click="state.page++; reload()">下一页</button></div>
      </aside>
      <div class="practice-main">
        <p v-if="!state.practice" class="notice">{{ state.loading ? '正在读取练习…' : state.readError ? '练习读取失败，请重试。' : selected ? '暂未取得这组练习，请刷新重试。' : '选择章节，开始一组练习。' }}</p>
        <template v-else>
          <div class="section-heading"><h2>{{ state.practice.title || 'AI 练习' }}</h2><RouterLink v-if="state.practice.source_conversation_id" :to="'/chat/' + state.practice.source_conversation_id">返回原会话</RouterLink></div>
          <p v-if="state.practice.settings.document_ids?.length" class="field-help">参考资料：{{ (state.practice.settings.reference_documents || []).map(item => item.filename).join('、') }}</p>
          <p v-if="state.practice.status === 'generating'" class="notice" role="status">正在生成并复核题目…</p>
          <div v-if="state.practice.status === 'failed'" class="form-error" role="alert">{{ state.practice.error_message }} <button @click="retryGeneration" :disabled="state.busy">按原设置重试</button></div>
          <p v-if="state.practice.notice" class="notice">{{ state.practice.notice }}</p>
          <p v-if="state.practice.status === 'completed'" class="field-help" role="status">本组已完成 · 答对 {{ state.practice.correct_count }} / {{ state.practice.effective_count }} 题</p>
          <nav v-if="state.items.length" class="question-nav" aria-label="题号导航"><button v-for="item in state.items" :key="item.id" :class="{ answered: !!item.attempt, drafted: !item.attempt && !!state.choices[item.id], incorrect: item.attempt?.is_valid && !item.attempt.is_correct }" :aria-label="`第 ${item.position} 题，${!item.is_valid ? '已停用' : item.attempt ? item.attempt.is_correct ? '已答对' : '已答错' : state.choices[item.id] ? '已作答，未提交' : '未作答'}`" @click="jumpTo(item.id)">{{ item.position }}</button></nav>
          <PracticeQuestionCard
            v-for="item in state.items" :key="item.id" :item="item"
            :choice="state.choices[item.id]" :busy="state.busy"
            @choose="(id, answer) => state.choices[id] = answer" @hint="hint"
          />
          <section v-if="progress.pendingItems.length && state.practice.status === 'ready'" class="practice-submit" aria-label="提交整组练习">
            <p>已答 {{ progress.answeredCount }} / {{ progress.effectiveItems.length }} 题</p>
            <p v-if="submitReason" id="practice-submit-reason" class="field-help" role="status">{{ submitReason }}</p>
            <button class="primary-button" :disabled="!!submitReason" :aria-describedby="submitReason ? 'practice-submit-reason' : undefined" @click="submitAll()">{{ state.busy ? '正在提交…' : '提交全部答案' }}</button>
          </section>
        </template>
      </div>
    </div>
  </section>
</template>
