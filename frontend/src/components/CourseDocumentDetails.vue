<script setup lang="ts">
import { onScopeDispose, ref } from 'vue'
import { ApiError } from '../api/client'
import { getCourseChunks, getCourseHistory, type DocumentInfo, type MaintenanceEvent, type ParsedChunk } from '../api/documents'
import { restoreAccount } from '../state/auth'

const props = defineProps<{ document: DocumentInfo }>()
const open = ref(false)
const busy = ref(false)
const error = ref('')
const chunks = ref<ParsedChunk[]>([])
const history = ref<MaintenanceEvent[]>([])
const page = ref(1)
const total = ref(0)
const controller = new AbortController()
let disposed = false
const actions = { upload: '上传资料', process: '提交处理', delete: '移除 / 清理' }
onScopeDispose(() => { disposed = true; controller.abort() })
async function load(next = 1) {
  if (busy.value) return
  open.value = true
  busy.value = true
  error.value = ''
  try {
    const [events, parsed] = await Promise.all([
      getCourseHistory(props.document.id, controller.signal),
      props.document.status === 'ready' ? getCourseChunks(props.document.id, next, controller.signal) : Promise.resolve({ items: [], total: 0 }),
    ])
    if (disposed) return
    history.value = events
    chunks.value = parsed.items
    total.value = parsed.total
    page.value = next
  } catch (reason) {
    if (disposed) return
    if (reason instanceof ApiError && [401, 403].includes(reason.status)) await restoreAccount(true)
    else error.value = reason instanceof Error ? reason.message : '读取失败，请重试。'
  } finally { if (!disposed) busy.value = false }
}
</script>

<template>
  <div class="course-document-details disclosure-panel">
    <button class="disclosure-toggle" type="button" :aria-expanded="open" @click="open ? open = false : load()"><span class="disclosure-title">解析片段与维护记录</span></button>
    <div v-if="open" class="disclosure-content">
      <p v-if="busy" role="status">正在读取…</p>
      <p v-if="error" class="form-error" role="alert">{{ error }} <button class="text-button" @click="load(page)">重试</button></p>
      <template v-if="!busy && !error">
        <h3>维护记录</h3>
        <p v-if="!history.length" class="field-help">暂无维护记录。</p>
        <ul><li v-for="(event, index) in history" :key="index">{{ actions[event.action] }} · {{ event.actor }} · {{ new Date(event.created_at).toLocaleString('zh-CN') }}</li></ul>
        <h3>解析片段</h3>
        <p v-if="document.status !== 'ready'" class="field-help">资料尚未就绪或已删除，暂不提供当前解析片段。</p>
        <article v-for="chunk in chunks" :key="chunk.id" class="parsed-chunk">
          <p class="field-help">{{ chunk.heading }} · {{ chunk.page_number ? '第 ' + chunk.page_number + ' 页' : '第 ' + chunk.line_start + '–' + chunk.line_end + ' 行' }}</p>
          <pre>{{ chunk.text }}</pre>
        </article>
        <div v-if="total > 20" class="document-pagination">
          <button class="text-button" :disabled="page === 1" @click="load(page - 1)">上一页片段</button>
          <span>{{ page }} / {{ Math.ceil(total / 20) }}</span>
          <button class="text-button" :disabled="page * 20 >= total" @click="load(page + 1)">下一页片段</button>
        </div>
      </template>
    </div>
  </div>
</template>
