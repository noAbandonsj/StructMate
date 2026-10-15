<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import LearningStats from '../components/LearningStats.vue'
import { useReports } from '../state/reports'
import { exportUrl } from '../api/reports'
const route = useRoute(), router = useRouter()
const selected = computed(() => typeof route.params.id === 'string' ? route.params.id : '')
const { state, reload, generate } = useReports(selected)
const time = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
async function save() { const report = await generate(); if (report) { if (selected.value === report.id) await reload(); else await router.push('/reports/' + report.id) } }
</script>
<template>
  <section>
    <div class="section-heading"><h1>学习报告</h1><button :disabled="state.loading" @click="reload()">刷新</button></div>
    <p class="intro-copy">先查看真实记录，再按需生成说明。历史报告保留当时的统计范围和数据。</p>
    <p v-if="state.readError" class="form-error" role="alert">{{ state.readError }} <button @click="reload()">重新读取</button></p>
    <article class="report-panel">
      <h2>实时统计</h2>
      <form class="report-range" @submit.prevent="reload()"><label>开始日期<input v-model="state.range.from_date" type="date" :max="state.range.to_date || undefined"></label><label>结束日期<input v-model="state.range.to_date" type="date" :min="state.range.from_date || undefined"></label><button :disabled="state.loading">查看统计</button></form>
      <p v-if="state.loading" role="status">正在读取…</p>
      <LearningStats v-if="state.stats" :stats="state.stats" />
      <p v-if="!state.generationAvailable" class="notice">生成模型尚未接通，仍可保存和导出真实统计快照；文字报告暂不可用。</p>
      <p v-if="state.error" class="form-error" role="alert">{{ state.error }} 日期范围已保留，可重试。</p>
      <button class="primary-button" :disabled="state.busy || state.loading || (!!state.range.from_date && !!state.range.to_date && state.range.from_date > state.range.to_date)" @click="save()">{{ state.busy ? '正在保存…' : state.generationAvailable ? '按所选日期生成新报告' : '按所选日期保存统计快照' }}</button>
    </article>
    <div class="reports-layout">
      <aside class="report-panel"><h2>历史报告</h2><p v-if="!state.reports.length" class="field-help">还没有保存的报告。</p><RouterLink v-for="report in state.reports" :key="report.id" class="conversation-link" :class="{ selected: selected === report.id }" :to="'/reports/' + report.id">{{ report.from_date }} 至 {{ report.to_date }}<span class="field-help">{{ time(report.created_at) }} · {{ report.status === 'completed' ? '已生成' : report.status === 'generating' ? '生成中' : '仅统计快照' }}</span></RouterLink><div v-if="state.total > 20" class="document-pagination"><button :disabled="state.loading || state.page <= 1" @click="state.page--; reload()">上一页</button><span>{{ state.page }}</span><button :disabled="state.loading || state.page * 20 >= state.total" @click="state.page++; reload()">下一页</button></div></aside>
      <article class="report-panel">
        <template v-if="state.report"><h2>已保存的历史快照</h2><p class="notice">本报告采用保存时口径。后续作答或题目停用不会改写它；最新数据请看上方实时统计。</p><p class="field-help">统计截止：{{ time(state.report.cutoff_at) }}（上海时间）<br>文字生成：{{ state.report.generated_at ? time(state.report.generated_at) : '尚未完成' }}</p><LearningStats :stats="state.report.snapshot" /><p v-if="state.report.status === 'generating'" role="status">正在生成文字说明，可继续学习，返回此页会恢复状态。</p><p v-if="state.report.error_message" class="notice">{{ state.report.error_message }}</p><div v-if="state.report.content" class="summary-content">{{ state.report.content }}</div><a class="primary-link" :href="exportUrl(state.report.id)">导出{{ state.report.content ? '报告' : '统计快照' }} Markdown</a></template>
        <p v-else class="field-help">选择一份历史报告查看，或按上方日期范围保存新报告。</p>
      </article>
    </div>
  </section>
</template>
