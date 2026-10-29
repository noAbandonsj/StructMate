<script setup lang="ts">
import type { Stats, Category } from '../api/reports'
import DisclosurePanel from './DisclosurePanel.vue'
defineProps<{ stats: Stats }>()
const categories: [Category, string][] = [['first', '首次作答'], ['repeat', '重复练习'], ['review', '错题复习']]
const percent = (value: number | null) => value === null ? '未评估' : (value * 100).toFixed(1) + '%'
</script>
<template>
  <div class="stats-grid">
    <div><span>有效作答</span><strong>{{ stats.attempts.count }} 次</strong></div>
    <div><span>首次作答正确率</span><strong>{{ percent(stats.categories.first.accuracy) }}</strong><small>{{ stats.categories.first.count }} 道新题</small></div>
    <div><span>范围内新增错题</span><strong>{{ stats.wrong_questions.new_in_range }} 道</strong></div>
    <div><span>记录活跃天数</span><strong>{{ stats.learning.active_days }} 天</strong></div>
  </div>
  <p v-if="!stats.attempts.count && !stats.learning.asked_questions" class="notice">这段时间还没有学习记录。可以先开始对话或做一组 AI 练习。</p>
  <DisclosurePanel title="查看作答明细"><div class="disclosure-table"><table class="stats-table"><thead><tr><th scope="col">类别</th><th scope="col">次数</th><th scope="col">答对</th><th scope="col">正确率</th></tr></thead><tbody><tr v-for="[key, label] in categories" :key="key"><th scope="row">{{ label }}</th><td>{{ stats.categories[key].count }}</td><td>{{ stats.categories[key].correct_count }}</td><td>{{ percent(stats.categories[key].accuracy) }}</td></tr></tbody></table></div></DisclosurePanel>
  <DisclosurePanel v-if="stats.question_types" title="按题型查看"><p v-for="(item, kind) in stats.question_types" :key="kind">{{ kind === 'single_choice' ? '单选题' : '判断题' }}：{{ item.count }} 次作答，正确率 {{ percent(item.accuracy) }}</p></DisclosurePanel>
  <DisclosurePanel title="按章节查看" open><div class="disclosure-table"><table class="stats-table"><thead><tr><th scope="col">章节</th><th scope="col">作答</th><th scope="col">首次作答新题</th><th scope="col">首次正确率</th><th scope="col">证据</th></tr></thead><tbody><tr v-for="point in stats.chapters" :key="point.chapter_id"><th scope="row">{{ point.name }}</th><td>{{ point.attempts.count }}</td><td>{{ point.first.count }}</td><td>{{ percent(point.first.accuracy) }}</td><td>{{ point.evidence === 'insufficient' ? '证据不足（少于 5 道）' : '可供参考' }}</td></tr></tbody></table></div></DisclosurePanel>
</template>
