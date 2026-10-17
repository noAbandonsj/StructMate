<script setup lang="ts">
import type { Summary } from '../api/chat'
import { summaryExportUrl } from '../api/chat'
import MarkdownContent from './MarkdownContent'
defineProps<{ id: string; summary: Summary | null; canGenerate: boolean; busy: boolean; loading: boolean; error: string }>()
const emit = defineEmits<{ generate: []; refresh: [] }>()
function time(value: string | null) { return value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '尚未生成' }
</script>
<template>
  <section class="summary-panel" aria-labelledby="summary-title">
    <div class="section-heading"><h2 id="summary-title">总结本次学习</h2><button class="text-button" type="button" :disabled="loading" @click="emit('refresh')">刷新总结</button></div>
    <p class="field-help">总结已完成的有效问答，排除资料不足的回复；不把“讨论过”当作“已掌握”。新总结失败时保留上一次成功内容。</p>
    <p v-if="!canGenerate" class="notice">生成模型尚未接通，已有总结仍可查看和导出。</p>
    <p v-if="summary?.status === 'generating'" class="notice" role="status">正在生成总结，离开或刷新后可恢复状态。</p>
    <p v-if="error || summary?.error_message" class="form-error" role="alert">{{ error || summary?.error_message }}</p>
    <template v-if="summary?.content">
      <p class="field-help">{{ summary.status === 'completed' ? '已完成总结' : '上一次成功总结' }} · 覆盖 {{ summary.message_count / 2 }} 轮完整问答 · 消息截止 {{ time(summary.cutoff_at) }} · 生成于 {{ time(summary.generated_at) }}</p>
      <MarkdownContent :content="summary.content" />
      <a :href="summaryExportUrl(id)">导出 Markdown</a>
      <p v-if="summary.has_newer_messages && summary.status !== 'generating'" class="field-help">还有新回答未包含在这份总结中，可以重新总结。</p>
    </template>
    <p v-else-if="summary?.status !== 'generating'" class="field-help">完成一轮答疑后，可在这里整理本次讨论和后续学习方向。</p>
    <button class="primary-button" type="button" :disabled="busy || loading || !canGenerate || summary?.status === 'generating'" @click="emit('generate')">{{ summary?.content ? '重新总结本次学习' : '生成学习总结' }}</button>
  </section>
</template>
