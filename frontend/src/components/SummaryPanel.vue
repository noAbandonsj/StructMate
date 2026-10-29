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
    <p v-if="!canGenerate" class="notice">生成模型尚未接通，已有总结仍可查看和导出。</p>
    <p v-if="summary?.status === 'generating'" class="notice" role="status">正在生成总结…</p>
    <p v-if="error || summary?.error_message" class="form-error" role="alert">{{ error || summary?.error_message }}</p>
    <template v-if="summary?.content">
      <p class="field-help">{{ summary.status === 'completed' ? '已完成' : '上次总结' }} · {{ summary.message_count / 2 }} 轮问答 · {{ time(summary.generated_at) }}</p>
      <MarkdownContent :content="summary.content" />
      <a :href="summaryExportUrl(id)">导出 Markdown</a>
      <p v-if="summary.has_newer_messages && summary.status !== 'generating'" class="field-help">有新回答待总结。</p>
    </template>
    <button class="primary-button" type="button" :disabled="busy || loading || !canGenerate || summary?.status === 'generating'" @click="emit('generate')">{{ summary?.content ? '重新总结本次学习' : '生成学习总结' }}</button>
  </section>
</template>
