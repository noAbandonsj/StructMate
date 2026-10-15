<script setup lang="ts">
import { ref, toRef, watch } from 'vue'
import { RouterLink } from 'vue-router'

import { documentFileUrl } from '../api/documents'
import type { LibraryInfo, KnowledgePoint } from '../api/knowledge'
import { useDocuments } from '../state/documents'

const props = defineProps<{ library: LibraryInfo; points: KnowledgePoint[] }>()
const { state, reload, upload, process, remove, setPage } = useDocuments(toRef(props, 'library'))
const fileInput = ref<HTMLInputElement | null>(null)
const file = ref<File | null>(null)
const pointId = ref('')
const confirmId = ref<string | null>(null)
const localError = ref('')
const statusLabels = { processing: '处理中', ready: '可用于学习', failed: '处理失败', deleted: '已删除' }

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
  if (await upload(submitted, pointId.value)) {
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
</script>

<template>
  <section class="document-panel" aria-labelledby="documents-title">
    <div class="section-heading">
      <h2 id="documents-title">{{ library.is_readonly ? '课程资料' : '我的资料' }}</h2>
      <button class="text-button" type="button" :disabled="state.loading || state.busy" @click="reload()">刷新资料</button>
    </div>
    <p v-if="library.is_readonly" class="field-help">课程资料由维护者统一导入，学生可查看和下载。</p>
    <p v-if="state.config && !state.config.embedding_available" class="notice">
      向量服务尚未接通。文件可以先保存和预览，配置后再处理；未就绪的资料暂不能用于学习对话。
    </p>
    <form v-if="!library.is_readonly" class="upload-form" @submit.prevent="submit">
      <fieldset :disabled="state.busy">
        <label for="document-file">上传学习资料</label>
        <input id="document-file" ref="fileInput" type="file" accept=".pdf,.txt,.md,.markdown" @change="chooseFile">
        <p class="field-help">支持文本型 PDF、TXT、Markdown{{ state.config ? '，单文件最多 ' + state.config.max_mib + ' MiB' : '' }}；扫描或加密 PDF 暂不支持。</p>
        <details class="upload-options">
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
    <p v-if="localError || state.actionError || state.error" class="form-error" role="alert">{{ localError || state.actionError || state.error }}</p>
    <p v-if="state.notice" class="field-help" role="status">{{ state.notice }}</p>
    <div v-if="state.deletion?.stage === 'cleanup_failed'" class="form-error" role="alert">
      {{ state.deletion.error_message }}
      <button class="text-button" type="button" :disabled="state.busy" @click="remove(state.deletion.id)">重试清理</button>
    </div>
    <p v-if="state.loading && !state.documents.length" class="notice" role="status">正在读取资料…</p>
    <div v-else-if="!state.documents.length && !state.error" class="document-empty">
      {{ library.is_readonly ? '课程资料尚未导入。' : '还没有资料，选择文件即可开始整理。' }}
    </div>
    <ul v-if="state.documents.length" class="document-list">
      <li v-for="document in state.documents" :key="document.id" class="document-row">
        <div class="document-main">
          <strong>{{ document.filename }}</strong>
          <p class="field-help">{{ document.file_type.toUpperCase() }} · {{ sizeLabel(document.size_bytes) }}</p>
          <span class="document-status" :class="document.status">{{ statusLabels[document.status] }}</span>
          <p v-if="document.error_message" class="document-error">{{ document.error_message }}</p>
          <details v-if="document.source_info?.sources?.length" class="source-notice">
            <summary>来源与许可</summary>
            <p v-for="source in document.source_info.sources" :key="source.url" class="field-help">
              <a :href="safeLink(source.url)" target="_blank" rel="noopener noreferrer">{{ source.title }}</a>
              · {{ source.author }} · {{ source.license }}
            </p>
          </details>
        </div>
        <div class="document-actions">
          <RouterLink v-if="document.status === 'ready'" :to="{ path: '/chat', query: { document: document.id, point: document.knowledge_point_id || undefined } }">学习这份资料</RouterLink>
          <a :href="documentFileUrl(document.id)" target="_blank" rel="noopener noreferrer">预览</a>
          <a :href="documentFileUrl(document.id, true)" target="_blank" rel="noopener noreferrer">下载</a>
          <button v-if="!library.is_readonly && document.retryable" class="text-button" type="button"
            :disabled="state.busy || !state.config?.embedding_available" @click="process(document.id)">重试处理</button>
          <button v-if="!library.is_readonly && document.status === 'ready'" class="text-button" type="button"
            :disabled="state.busy" @click="process(document.id)">重新处理</button>
          <button v-if="!library.is_readonly" class="text-button danger-button" type="button"
            :disabled="state.busy" @click="confirmId = document.id">删除</button>
        </div>
        <div v-if="confirmId === document.id" class="delete-confirm" role="alert">
          <p>删除“{{ document.filename }}”后将停止检索并清理原文件，历史对话与作答仍保留。</p>
          <button class="text-button danger-button" type="button" :disabled="state.busy" @click="confirmDelete(document.id)">确认删除</button>
          <button class="text-button" type="button" :disabled="state.busy" @click="confirmId = null">取消</button>
        </div>
      </li>
    </ul>
    <div v-if="state.total > 20" class="document-pagination">
      <button class="text-button" type="button" :disabled="state.page === 1 || state.loading" @click="setPage(state.page - 1)">上一页</button>
      <span>{{ state.page }} / {{ Math.ceil(state.total / 20) }}</span>
      <button class="text-button" type="button" :disabled="state.page * 20 >= state.total || state.loading" @click="setPage(state.page + 1)">下一页</button>
    </div>
  </section>
</template>
