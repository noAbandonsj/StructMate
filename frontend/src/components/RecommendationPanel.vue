<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { useRecommendations } from '../state/recommendations'
const props = defineProps<{ pointId?: string }>()
const { state, reload, read, closePreview } = useRecommendations(computed(() => props.pointId || ''))
const level = (value: string | null) => value === 'basic' ? '基础' : value === 'intermediate' ? '进阶' : value === 'advanced' ? '提高' : '难度未评定'
function safeExternal(value: string) { try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? value : '#' } catch { return '#' } }
</script>
<template>
  <section class="recommendation-panel" aria-label="资料推荐">
    <div class="section-heading"><h2>接下来可以读</h2><button :disabled="state.loading" @click="reload()">刷新推荐</button></div>
    <p class="field-help">按知识点、有效错题和难度匹配，推荐理由可查看。</p>
    <div class="report-range"><label>知识点<select v-model="state.point" @change="reload()"><option value="">全部章节</option><option v-for="point in state.points" :key="point.id" :value="point.id">{{ point.name }}</option></select></label><label>优先难度<select v-model="state.difficulty" @change="reload()"><option value="basic">基础</option><option value="intermediate">进阶</option><option value="advanced">提高</option></select></label></div>
    <p v-if="state.loading" role="status">正在查找可读资料…</p><p v-if="state.error" class="form-error" role="alert">{{ state.error }} <button @click="reload()">重试</button></p>
    <p v-else-if="!state.loading && !state.items.length" class="notice">当前知识点暂无可推荐资料，可以调整范围，或在知识库上传并标注资料。</p>
    <div class="recommendation-grid"><article v-for="item in state.items" :key="item.id" class="recommendation-card"><h3>{{ item.title }}</h3><p class="field-help">{{ item.kind === 'document' ? '知识库原文' : '外部资源' }} · {{ item.language }} · {{ level(item.difficulty) }}</p><p>{{ item.description }}</p><ul class="field-help"><li v-for="reason in item.reasons" :key="reason">{{ reason }}</li></ul><button v-if="item.kind === 'document'" :disabled="state.previewLoading" @click="read(item)">阅读片段</button><a v-else :href="safeExternal(item.url)" target="_blank" rel="noopener noreferrer">打开原资源 ↗</a><RouterLink v-if="item.knowledge_point_id" class="text-button" :to="{ path: '/practice', query: { point: item.knowledge_point_id } }">练习此知识点</RouterLink><p v-if="item.source_info?.author" class="field-help">{{ item.source_info.author }} · {{ item.source_info.license }} · 链接核对于 {{ item.source_info.checked_on }}</p></article></div>
    <p v-if="state.previewLoading" role="status">正在核对权限并读取原文…</p><p v-if="state.previewError" class="form-error" role="alert">{{ state.previewError }} <button @click="reload()">刷新推荐</button></p>
    <aside v-if="state.preview" class="recommendation-preview" aria-label="推荐资料原文"><div class="section-heading"><h3>{{ state.preview.item.title }}</h3><button @click="closePreview()">关闭</button></div><p class="field-help">{{ state.preview.chunk.heading }}{{ state.preview.chunk.page_number ? ' · 第 ' + state.preview.chunk.page_number + ' 页' : '' }}{{ state.preview.chunk.line_start ? ' · 第 ' + state.preview.chunk.line_start + '–' + state.preview.chunk.line_end + ' 行' : '' }}</p><pre>{{ state.preview.chunk.text }}</pre><a :href="'/api/v1/documents/' + encodeURIComponent(state.preview.item.document_id!) + '/file'" target="_blank" rel="noopener">查看原文件</a></aside>
    <details v-if="state.basis"><summary>推荐依据</summary><p class="field-help">{{ state.basis }}</p></details>
  </section>
</template>
