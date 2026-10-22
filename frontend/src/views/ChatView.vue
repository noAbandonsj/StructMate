<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useChat } from '../state/chat'
import SummaryPanel from '../components/SummaryPanel.vue'
import RecommendationPanel from '../components/RecommendationPanel.vue'
import MarkdownContent from '../components/MarkdownContent'
import type { Citation, Scope } from '../api/chat'
import { documentFileUrl, getDocument } from '../api/documents'

const route = useRoute(), router = useRouter()
const selected = computed(() => typeof route.params.id === 'string' ? route.params.id : '')
const { state, active, reload, create, send, retry, cancel, update, older, reconnect, generateSummary, refreshSummary } = useChat(selected)
const newScope = ref<Scope>('combined')
const title = ref('')
const citation = ref<Citation | null>(null)
const citationError = ref('')
const citationPane = ref<HTMLElement | null>(null)
let citationTrigger: HTMLElement | null = null
let citationVersion = 0
watch(selected, () => { citationVersion++; citation.value = null; citationError.value = '' })
watch(() => state.conversation?.title, value => { title.value = value ?? '' })
const available = computed(() => state.config?.generation_available && state.config.embedding_available)
const noReadyMaterials = computed(() => state.config?.ready_document_count === 0)
const practiceRequirements = computed(() => ([...state.messages].reverse().find(message => message.role === 'user')?.content || state.conversation?.title || '').slice(0, 500))
async function start() {
  const documents = typeof route.query.document === 'string' ? [route.query.document] : []
  const point = typeof route.query.chapter === 'string' ? route.query.chapter : undefined
  const conversation = await create(newScope.value, documents, point)
  if (conversation) await router.push('/chat/' + conversation.id)
}
async function showCitation(value: Citation) {
  const version = ++citationVersion
  if (!citation.value) citationTrigger = document.activeElement instanceof HTMLElement ? document.activeElement : null
  citation.value = value; citationError.value = ''
  await nextTick()
  if (version !== citationVersion) return
  citationPane.value?.focus({ preventScroll: true })
  try {
    const document = await getDocument(value.document_id, new AbortController().signal)
    if (version === citationVersion) citation.value = { ...value, source_deleted: document.status === 'deleted' }
  } catch { if (version === citationVersion) citationError.value = '无法核对来源状态，请重试。' }
}
function closeCitation() { citation.value = null; citationVersion++; citationTrigger?.focus({ preventScroll: true }) }
function openCitation(number: number, citations: Citation[]) { const value = citations.find(item => item.number === number); if (value) void showCitation(value) }
</script>
<template>
  <section class="chat-page">
    <div class="section-heading"><h1>学习对话</h1><button class="text-button" @click="reload()" :disabled="state.loading">刷新</button></div>
    <p v-if="state.config && !available" class="notice">生成模型或向量模型尚未接通。会话可以建立和保存，提问需在接通服务后使用。</p>
    <p v-if="state.error" class="form-error" role="alert">{{ state.error }}</p>
    <div class="chat-layout" :class="{ 'with-citation': citation }">
      <aside class="conversation-list" aria-label="学习会话">
        <form @submit.prevent="start">
          <label for="new-scope">新学习的资料范围</label>
          <select id="new-scope" v-model="newScope"><option value="combined">课程＋我的资料</option><option value="course">仅课程资料</option><option value="personal">仅我的资料</option></select>
          <p v-if="route.query.document" class="field-help">本次只使用从知识库选择的资料。</p>
          <button class="primary-button" :disabled="state.busy">新建学习</button>
        </form>
        <label class="archive-toggle"><input type="checkbox" v-model="state.archived" @change="state.page = 1; reload()">显示已归档</label>
        <p v-if="state.loading && !state.conversations.length">正在读取会话…</p>
        <p v-else-if="!state.conversations.length && !state.error" class="field-help">还没有{{ state.archived ? '归档' : '' }}会话。</p>
        <RouterLink v-for="conversation in state.conversations" :key="conversation.id" :to="'/chat/' + conversation.id" class="conversation-link" :class="{ selected: selected === conversation.id }">{{ conversation.title }}</RouterLink>
        <div class="document-pagination" v-if="state.total > 20">
          <button :disabled="state.page <= 1 || state.loading" @click="state.page--; reload()">上一页</button>
          <span>{{ state.page }} / {{ Math.ceil(state.total / 20) }}</span>
          <button :disabled="state.page * 20 >= state.total || state.loading" @click="state.page++; reload()">下一页</button>
        </div>
      </aside>
      <div class="conversation-main">
        <p v-if="!state.conversation" class="notice">{{ state.loading ? '正在读取…' : '选择已有会话，或新建学习后输入问题。' }}</p>
        <template v-else>
          <details class="chat-options">
            <summary>{{ state.conversation.title }} · 会话设置</summary>
            <form @submit.prevent="update({ title })"><label>会话名称<input v-model="title" maxlength="100" required></label><button :disabled="state.busy">保存名称</button></form>
            <label>资料范围<select :value="state.conversation.scope" :disabled="state.busy || !!active" @change="update({ scope: ($event.target as HTMLSelectElement).value as Scope, document_ids: [] })"><option value="combined">课程＋我的资料</option><option value="course">仅课程资料</option><option value="personal">仅我的资料</option></select></label>
            <p v-if="state.conversation.document_ids.length" class="field-help">当前限于指定资料；更改范围会取消该限定。</p>
            <button :disabled="state.busy || !!active" @click="update({ archived: !state.conversation.archived })">{{ state.conversation.archived ? '恢复会话' : '归档会话' }}</button>
          </details>
          <div v-if="noReadyMaterials" class="notice" role="status">
            当前资料范围没有可用于学习的资料，暂不能提问。可在会话设置中切换资料范围，
            <RouterLink to="/knowledge">上传自己的笔记</RouterLink>，或<RouterLink to="/practice">前往练习中心使用实时 AI 出题</RouterLink>。
            <button type="button" class="text-button" :disabled="state.loading" @click="reload()">重新检查资料</button>
          </div>
          <div class="message-history" aria-label="会话记录">
            <RouterLink :to="{ path: '/practice', query: { conversation: selected, chapter: state.conversation?.chapter_id || undefined, requirements: practiceRequirements || undefined } }">围绕本次对话练习</RouterLink>
            <button v-if="state.historyPage > 1" @click="older()" :disabled="state.loading">查看更早消息</button>
            <p v-if="!state.messages.length" class="field-help">可以问：“栈和队列有什么区别？”或“用例子解释二叉树遍历”。</p>
            <article v-for="(message, index) in state.messages" :key="message.id" class="chat-message" :class="message.role">
              <strong>{{ message.role === 'user' ? '我' : '学习助手' }}</strong>
              <MarkdownContent v-if="message.role === 'assistant'" :content="message.content" :citations="message.citations.map(value => value.number)" @citation="openCitation($event, message.citations)" />
              <div v-else class="message-content">{{ message.content }}</div>
              <p v-if="message.status === 'generating'" class="field-help">正在检索和生成回答…</p>
              <p v-if="message.status === 'failed'" class="form-error" role="alert">{{ message.error_message }}</p>
              <p v-if="message.status === 'cancelled'" class="field-help">回答已取消，已生成内容保留。</p>
              <p v-if="message.answer_outcome === 'insufficient_materials'" class="field-help">资料不足 · 未计入有效答疑，也不参与新的学习总结。可调整资料范围或补充资料后重新提问。</p>
              <div v-if="message.citations.length" class="citation-links"><span>检索依据：</span><button v-for="value in message.citations" :key="value.number" class="text-button" @click="showCitation(value)">[{{ value.number }}] {{ value.filename }}{{ value.source_deleted ? '（来源已删除）' : '' }}</button></div>
              <RouterLink v-if="message.citations.length" :to="{ path: '/practice', query: { conversation: selected, document: message.citations[0]?.document_id, chapter: message.citations[0]?.chapter_id || state.conversation?.chapter_id || undefined, requirements: practiceRequirements || undefined } }">依据引用资料练习</RouterLink>
              <button v-if="index === state.messages.length - 1 && ['failed','cancelled'].includes(message.status)" :disabled="state.busy || !!active || !available" @click="retry(message.id)">重试这个问题</button>
            </article>
          </div>
          <p v-if="state.streamError" class="form-error" role="alert">{{ state.streamError }} <button @click="reconnect()" :disabled="!active">重新连接</button></p>
          <form class="chat-composer" @submit.prevent="send">
            <label for="chat-question">学习问题</label>
            <textarea id="chat-question" v-model="state.draft" maxlength="4000" rows="3" placeholder="输入问题，或继续追问…" :disabled="state.conversation.archived"></textarea>
            <div class="composer-actions"><select v-model="state.intent" aria-label="回答方式"><option value="explain">直接讲解</option><option value="hint">给我提示</option><option value="example">用例子解释</option></select>
              <button v-if="active" type="button" @click="cancel()" :disabled="state.busy">取消回答</button>
              <button v-else class="primary-button" :disabled="state.busy || state.loading || !available || noReadyMaterials || !state.draft.trim() || state.conversation.archived">{{ state.busy ? '正在发送…' : '发送问题' }}</button>
            </div>
            <p v-if="state.conversation.archived" class="field-help">会话已归档，恢复后可继续提问。</p>
          </form>
          <SummaryPanel :id="selected" :summary="state.summary" :can-generate="!!state.config?.generation_available" :busy="state.busy" :loading="state.loading || state.summaryLoading" :error="state.summaryError" @generate="generateSummary" @refresh="refreshSummary" />
          <details class="chat-recommendations"><summary>阅读相关资料</summary><RecommendationPanel  /></details>
        </template>
      </div>
      <aside v-if="citation" ref="citationPane" class="citation-pane" aria-label="引用原文" tabindex="-1" @keydown.esc="closeCitation">
        <div class="section-heading"><h2>引用原文</h2><button @click="closeCitation">关闭</button></div>
        <strong>{{ citation.filename }}</strong>
        <p class="field-help">{{ citation.heading }}{{ citation.page_number ? ' · 第 ' + citation.page_number + ' 页' : '' }}{{ citation.line_start ? ' · 第 ' + citation.line_start + '–' + citation.line_end + ' 行' : '' }}</p>
        <p v-if="citation.source_deleted" class="notice">来源已删除，以下是本次回答保留的历史片段。</p>
        <p v-if="citationError" class="form-error">{{ citationError }}</p>
        <pre>{{ citation.text }}</pre>
        <a v-if="!citation.source_deleted && !citationError" :href="documentFileUrl(citation.document_id)" target="_blank" rel="noopener">查看原文件</a>
      </aside>
    </div>
  </section>
</template>
