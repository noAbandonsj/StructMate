<script setup lang="ts">
import type { Stats, Category } from '../api/reports'
defineProps<{ stats: Stats }>()
const categories: [Category, string][] = [['first_independent', '首次独立新题'], ['first_hinted', '首次提示作答'], ['repeat', '重复练习'], ['review', '错题复习']]
const percent = (value: number | null) => value === null ? '未评估' : (value * 100).toFixed(1) + '%'
</script>
<template>
  <p class="field-help">{{ stats.from_date }} 至 {{ stats.to_date }} · 上海日期，两端包含</p>
  <div class="stats-grid">
    <div><span>有效作答</span><strong>{{ stats.attempts.count }} 次</strong></div>
    <div><span>首次独立正确率</span><strong>{{ percent(stats.categories.first_independent.accuracy) }}</strong><small>{{ stats.categories.first_independent.count }} 道不同新题</small></div>
    <div><span>范围内新增错题</span><strong>{{ stats.wrong_questions.new_in_range }} 道</strong></div>
    <div><span>记录活跃天数</span><strong>{{ stats.learning.active_days }} 天</strong><small>不估算学习时长</small></div>
  </div>
  <p v-if="!stats.attempts.count && !stats.learning.asked_questions" class="notice">这段时间还没有学习记录。可以先开始对话或做一组题库练习。</p>
  <table class="stats-table"><caption>作答类型分开统计</caption><thead><tr><th scope="col">类别</th><th scope="col">次数</th><th scope="col">答对</th><th scope="col">正确率</th></tr></thead><tbody><tr v-for="[key, label] in categories" :key="key"><th scope="row">{{ label }}</th><td>{{ stats.categories[key].count }}</td><td>{{ stats.categories[key].correct_count }}</td><td>{{ percent(stats.categories[key].accuracy) }}</td></tr></tbody></table>
  <p class="field-help">核验题库 {{ stats.sources.bank.count }} 次；AI 参考答案题 {{ stats.sources.ai.count }} 次。使用提示共 {{ stats.hinted_attempt_count }} 次。</p>
  <p>范围内提问 {{ stats.learning.asked_questions }} 次，完成回答 {{ stats.learning.completed_answers }} 次。截止时待复习 {{ stats.wrong_questions.current_pending }} 道（此项不限日期范围）。</p>
  <details><summary>章节表现与统计口径</summary><table class="stats-table"><thead><tr><th scope="col">章节</th><th scope="col">独立新题</th><th scope="col">正确率</th><th scope="col">证据</th></tr></thead><tbody><tr v-for="point in stats.knowledge_points" :key="point.knowledge_point_id"><th scope="row">{{ point.name }}</th><td>{{ point.independent.count }}</td><td>{{ percent(point.independent.accuracy) }}</td><td>{{ point.evidence === 'insufficient' ? '证据不足（少于 5 道）' : '可供参考' }}</td></tr></tbody></table><p class="field-help">{{ stats.basis }}</p></details>
</template>
