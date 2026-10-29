<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import LearningStats from '../components/LearningStats.vue'
import MarkdownContent from '../components/MarkdownContent'
import { recentDateRange } from '../learning-options'
import { useReports } from '../state/reports'
import { exportUrl } from '../api/reports'
const route = useRoute(), router = useRouter()
const selected = computed(() => typeof route.params.id === 'string' ? route.params.id : '')
const { state, reload, applyRange, generate } = useReports(selected)
const time = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
const invalidRange = computed(() => !!state.range.from_date && !!state.range.to_date && state.range.from_date > state.range.to_date)
const unappliedRange = computed(() => !!state.stats && (state.range.from_date !== state.stats.from_date || state.range.to_date !== state.stats.to_date))
const matchesDays = (days: 7 | 30) => { const range = recentDateRange(days); return range.from_date === state.range.from_date && range.to_date === state.range.to_date }
async function chooseDays(days: 7 | 30) { state.range = recentDateRange(days); await reload() }
async function save() { const report = await generate(); if (report) { if (selected.value === report.id) await reload(); else await router.push('/reports/' + report.id) } }
</script>
<template>
  <section>
    <div class="section-heading"><h1>学习报告</h1></div>
    <p v-if="state.readError" class="form-error" role="alert">{{ state.readError }} <button @click="reload()">重新读取</button></p>
    <article class="report-panel">
      <h2>实时统计</h2>
      <div class="date-presets" role="group" aria-label="统计日期快捷选择"><button :aria-pressed="matchesDays(7)" :disabled="state.loading" @click="chooseDays(7)">近 7 天</button><button :aria-pressed="matchesDays(30)" :disabled="state.loading" @click="chooseDays(30)">近 30 天</button></div>
      <form class="report-range" @submit.prevent="applyRange()"><label>开始日期<input v-model="state.range.from_date" type="date" :max="state.range.to_date || undefined" @change="applyRange()"></label><label>结束日期<input v-model="state.range.to_date" type="date" :min="state.range.from_date || undefined" @change="applyRange()"></label></form>
      <p v-if="state.loading" role="status">正在读取…</p>
      <LearningStats v-if="state.stats && !unappliedRange && !invalidRange" :stats="state.stats" />
      <p v-if="invalidRange" class="form-error" role="alert">开始日期不能晚于结束日期。</p>
      <p v-else-if="!state.loading && (!state.range.from_date || !state.range.to_date)" class="field-help" role="status">请选择完整日期范围。</p>
      <p v-if="state.stats && !state.readError && !state.loading && !state.generationAvailable" class="notice">生成模型尚未接通，仍可保存和导出真实统计快照；文字报告暂不可用。</p>
      <p v-if="state.error" class="form-error" role="alert">{{ state.error }} 日期范围已保留，可重试。</p>
      <button class="primary-button" :disabled="state.busy || state.loading || !!state.readError || !state.stats || invalidRange || unappliedRange" @click="save()">{{ state.busy ? '正在保存…' : state.generationAvailable ? '按所选日期生成新报告' : '按所选日期保存统计快照' }}</button>
    </article>
    <div class="reports-layout">
      <aside class="report-panel"><h2>历史报告</h2><p v-if="state.loading && !state.reports.length" class="field-help">正在读取历史报告…</p><p v-else-if="state.readError && !state.reports.length" class="field-help">暂时无法读取历史报告，请重试。</p><p v-else-if="!state.reports.length" class="field-help">还没有保存的报告。</p><RouterLink v-for="report in state.reports" :key="report.id" class="conversation-link" :class="{ selected: selected === report.id }" :to="'/reports/' + report.id">{{ report.from_date }} 至 {{ report.to_date }}<span class="field-help">{{ time(report.created_at) }} · {{ report.status === 'completed' ? '已生成' : report.status === 'generating' ? '生成中' : '仅统计快照' }}</span></RouterLink><div v-if="state.total > 20" class="document-pagination"><button :disabled="state.loading || state.page <= 1" @click="state.page--; reload()">上一页</button><span>{{ state.page }}</span><button :disabled="state.loading || state.page * 20 >= state.total" @click="state.page++; reload()">下一页</button></div></aside>
      <article class="report-panel">
        <template v-if="state.report"><h2>已保存的历史快照</h2><p class="notice">本报告采用保存时口径。后续作答或题目停用不会改写它；最新数据请看上方实时统计。</p><p class="field-help">统计截止：{{ time(state.report.cutoff_at) }}（上海时间）<br>文字生成：{{ state.report.generated_at ? time(state.report.generated_at) : '尚未完成' }}</p><LearningStats :stats="state.report.snapshot" /><p v-if="state.report.status === 'generating'" role="status">正在生成文字说明，可继续学习，返回此页会恢复状态。</p><p v-if="state.report.error_message" class="notice">{{ state.report.error_message }}</p><MarkdownContent v-if="state.report.content" :content="state.report.content" /><a class="primary-link" :href="exportUrl(state.report.id)">导出{{ state.report.content ? '报告' : '统计快照' }} Markdown</a></template>
        <p v-else class="field-help">{{ state.loading ? "正在读取报告…" : state.readError ? "暂时无法读取报告，请重试。" : "选择一份历史报告查看，或按上方日期范围保存新报告。" }}</p>
      </article>
    </div>
  </section>
</template>
