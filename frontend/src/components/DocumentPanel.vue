<script setup lang="ts">
import { computed, ref, toRef, watch } from 'vue'
import { RouterLink } from 'vue-router'

import { documentFileUrl } from '../api/documents'
import type { LibraryInfo, KnowledgePoint } from '../api/knowledge'
import { useDocuments } from '../state/documents'
import CourseDocumentDetails from './CourseDocumentDetails.vue'

const props = defineProps<{ library: LibraryInfo; points: KnowledgePoint[]; management?: boolean }>()
const { state, reload, upload, process, remove, setPage, setFilters } = useDocuments(toRef(props, 'library'), props.management)
const writable = computed(() => props.management || !props.library.is_readonly)
const attribution = ref({ author: '', source: '', license: '' })
const selfAuthored = ref(false)
const search = ref('')
const status = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const file = ref<File | null>(null)
const pointId = ref('')
const confirmId = ref<string | null>(null)
const localError = ref('')
const statusLabels = { processing: '处理中', ready: '可用于学习', failed: '处理失败', deleted: '已删除' }
const orderedPoints = computed(() => {
  const roots = props.points.filter(point => !point.parent_id).sort((a, b) => a.sort_order - b.sort_order)
  return roots.flatMap(root => [root, ...props.points.filter(point => point.parent_id === root.id).sort((a, b) => a.sort_order - b.sort_order)])
})

watch(() => props.library.id, () => {
  file.value = null
  pointId.value = ''
  confirmId.value = null
  localError.value = ''
})
function chooseFile(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
  localError.value = ''
}
async function submit() {
  if (!file.value || !state.config) return
  const extension = file.value.name.split('.').at(-1)?.toLowerCase() ?? ''
  if (!state.config.extensions.includes(extension)) {
    localError.value = '请上传 PDF、TXT 或 Markdown。'
    return
  }
  if (file.value.size === 0 || file.value.size > state.config.max_mib * 1024 * 1024) {
    localError.value = '文件为空或超过大小限制，请重新选择。'
    return
  }
  localError.value = ''
  const submitted = file.value
  if (await upload(submitted, pointId.value, props.management ? attribution.value : undefined)) {
    if (props.management) { search.value = ''; status.value = '' }
    if (file.value === submitted) {
      file.value = null
      if (fileInput.value) fileInput.value.value = ''
    }
  }
}
async function confirmDelete(id: string) {
  await remove(id)
  if (confirmId.value === id) confirmId.value = null
}
function sizeLabel(bytes: number) {
  return bytes < 1024 * 1024 ? (bytes / 1024).toFixed(1) + ' KiB' : (bytes / 1024 / 1024).toFixed(1) + ' MiB'
}
function safeLink(url: string) {
  try { return ['https:', 'http:'].includes(new URL(url).protocol) ? url : '#' } catch { return '#' }
}
function markSelfAuthored() {
  if (selfAuthored.value) {
    attribution.value.source = '自编课程资料'
    attribution.value.license = '作者授权本课程学习使用'
  }
}
function pointName(id: string | null) { return props.points.find(point => point.id === id)?.name || '未关联知识点' }
</script>

<template>
  <section class="document-panel" aria-labelledby="documents-title">
    <div class="section-heading">
      <h2 id="documents-title">{{ library.kind === 'course' ? '课程资料' : '我的资料' }}</h2>
      <button class="text-button" type="button" :disabled="state.loading || state.busy" @click="reload()">刷新资料</button>
    </div>
    <p v-if="library.is_readonly && !management" class="field-help">课程资料由管理员统一维护，学生可查看和下载。</p>
    <p v-if="state.config && !state.config.embedding_available" class="notice">
      向量服务尚未接通。文件可以先保存和预览，配置后再处理；未就绪的资料暂不能用于学习对话。
    </p>
    <component :is="management ? 'details' : 'div'" v-if="writable" class="course-upload">
    <summary v-if="management">上传课程资料</summary>
    <form class="upload-form" @submit.prevent="submit">
      <fieldset :disabled="state.busy">
        <label for="document-file">上传学习资料</label>
        <input id="document-file" ref="fileInput" type="file" accept=".pdf,.txt,.md,.markdown" @change="chooseFile">
        <p class="field-help">支持文本型 PDF、TXT、Markdown{{ state.config ? '，单文件最多 ' + state.config.max_mib + ' MiB' : '' }}；扫描或加密 PDF 暂不支持。</p>
        <div v-if="management" class="course-upload-fields">
          <label for="course-point">关联课程知识点</label>
          <select id="course-point" v-model="pointId" required>
            <option value="">请选择知识点</option>
            <option v-for="point in orderedPoints" :key="point.id" :value="point.id">{{ point.parent_id ? '　' : '' }}{{ point.name }}</option>
          </select>
          <label for="course-author">作者</label><input id="course-author" v-model="attribution.author" required maxlength="200" placeholder="作者或编写者">
          <label class="self-authored"><input v-model="selfAuthored" type="checkbox" @change="markSelfAuthored">这是我编写的资料（自动填写来源与许可，可修改）</label>
          <label for="course-source">来源</label><input id="course-source" v-model="attribution.source" required maxlength="1000" placeholder="来源名称或链接，也可注明自编">
          <label for="course-license">许可说明</label><input id="course-license" v-model="attribution.license" required maxlength="1000" placeholder="例如：作者授权本课程学习使用">
        </div>
        <details v-else class="upload-options">
          <summary>关联知识点（选填）</summary>
          <select v-model="pointId" aria-label="关联知识点">
            <option value="">暂不指定</option>
            <option v-for="point in points" :key="point.id" :value="point.id">{{ point.name }}</option>
          </select>
        </details>
        <button class="primary-button" type="submit" :disabled="!file || !state.config">
          {{ state.busy ? '正在提交…' : state.config?.embedding_available ? '上传并处理' : '保存资料' }}
        </button>
      </fieldset>
    </form>
    </component>
    <form v-if="management" class="course-filters" @submit.prevent="setFilters(search, status)">
      <label>名称搜索<input v-model="search" type="search" maxlength="240" placeholder="输入文件名"></label>
      <label>处理状态<select v-model="status" @change="setFilters(search, status)">
        <option value="">当前资料</option><option value="ready">可用于学习</option><option value="processing">处理中</option>
        <option value="failed">处理失败</option><option value="deleted">已删除</option>
      </select></label>
      <button class="text-button" type="submit" :disabled="state.busy || state.loading">搜索</button>
    </form>
    <p v-if="localError || state.actionError || state.error" class="form-error" role="alert">{{ localError || state.actionError || state.error }}</p>
    <p v-if="state.notice" class="field-help" role="status">{{ state.notice }}</p>
    <div v-if="state.deletion?.stage === 'cleanup_failed'" class="form-error" role="alert">
      {{ state.deletion.error_message }}
      <button class="text-button" type="button" :disabled="state.busy" @click="remove(state.deletion.id)">重试清理</button>
    </div>
    <p v-if="state.loading && !state.documents.length" class="notice" role="status">正在读取资料…</p>
    <div v-else-if="!state.documents.length && !state.error" class="document-empty">
      {{ management ? '没有符合条件的课程资料。可以调整筛选或上传新资料。' : library.is_readonly ? '暂无课程资料，等待管理员上传维护。' : '还没有资料，选择文件即可开始整理。' }}
    </div>
    <ul v-if="state.documents.length" class="document-list">
      <li v-for="document in state.documents" :key="document.id" class="document-row">
        <div class="document-main">
          <strong>{{ document.filename }}</strong>
          <p class="field-help">{{ document.file_type.toUpperCase() }} · {{ sizeLabel(document.size_bytes) }}</p>
          <p v-if="management" class="field-help">{{ pointName(document.knowledge_point_id) }} · 更新于 {{ new Date(document.updated_at).toLocaleString('zh-CN') }}</p>
          <span class="document-status" :class="document.status">{{ statusLabels[document.status] }}</span>
          <p v-if="library.is_readonly && !management && document.status === 'failed'" class="document-error">课程资料待维护者处理，暂不可用于答疑。上次处理失败于 {{ new Date(document.updated_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) }}：{{ document.error_message }}</p>
          <p v-else-if="document.error_message" class="document-error">{{ document.error_message }}</p>
          <p v-if="management && document.status === 'failed'" class="field-help">{{ document.retryable ? '请检查服务状态，恢复后重试处理。' : '请修正文件内容或格式后重新上传；索引不兼容时请联系本机维护者。' }}</p>
          <details v-if="document.source_info?.sources?.length" class="source-notice">
            <summary>来源与许可</summary>
            <p v-for="source in document.source_info.sources" :key="source.url" class="field-help">
              <a v-if="source.url" :href="safeLink(source.url)" target="_blank" rel="noopener noreferrer">{{ source.title }}</a><span v-else>{{ source.title }}</span>
              · {{ source.author }} · {{ source.license }}
            </p>
          </details>
        </div>
        <div class="document-actions">
          <RouterLink v-if="document.status === 'ready'" :to="{ path: '/chat', query: { document: document.id, point: document.knowledge_point_id || undefined } }">学习这份资料</RouterLink>
          <RouterLink v-if="document.status === 'ready'" :to="{ path: '/practice', query: { document: document.id } }">依据资料练习</RouterLink>
          <a v-if="document.status !== 'deleted'" :href="documentFileUrl(document.id, false, management)" target="_blank" rel="noopener noreferrer">预览</a>
          <a v-if="document.status !== 'deleted'" :href="documentFileUrl(document.id, true, management)" target="_blank" rel="noopener noreferrer">下载</a>
          <button v-if="writable && document.retryable && document.status !== 'deleted'" class="text-button" type="button"
            :disabled="state.busy || !state.config?.embedding_available" @click="process(document.id)">重试处理</button>
          <button v-if="writable && document.status === 'ready'" class="text-button" type="button"
            :disabled="state.busy || !state.config?.embedding_available" @click="process(document.id)">重新处理</button>
          <button v-if="writable && document.status !== 'deleted'" class="text-button danger-button" type="button"
            :disabled="state.busy" @click="confirmId = document.id">删除</button>
          <button v-if="management && document.stage === 'cleanup_failed'" class="text-button" :disabled="state.busy" @click="remove(document.id)">重试清理</button>
        </div>
        <div v-if="confirmId === document.id" class="delete-confirm" role="alert">
          <p>删除“{{ document.filename }}”{{ management ? '将影响所有学习者：资料不再参与新检索，原文件与向量将清理。历史对话、引用片段、练习和报告保留。已移除的预置资料不会被普通导入自动恢复。' : '后将停止检索并清理原文件，历史对话与作答仍保留。' }}</p>
          <button class="text-button danger-button" type="button" :disabled="state.busy" @click="confirmDelete(document.id)">确认删除</button>
          <button class="text-button" type="button" :disabled="state.busy" @click="confirmId = null">取消</button>
        </div>
        <CourseDocumentDetails v-if="management" :key="document.id + document.status + document.updated_at" :document="document" />
      </li>
    </ul>
    <div v-if="state.total > 20" class="document-pagination">
      <button class="text-button" type="button" :disabled="state.page === 1 || state.loading" @click="setPage(state.page - 1)">上一页</button>
      <span>{{ state.page }} / {{ Math.ceil(state.total / 20) }}</span>
      <button class="text-button" type="button" :disabled="state.page * 20 >= state.total || state.loading" @click="setPage(state.page + 1)">下一页</button>
    </div>
  </section>
</template>
