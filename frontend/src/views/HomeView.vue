<script setup lang="ts">
import { RouterLink } from 'vue-router'

import { navigation } from '../navigation'
import { authState } from '../state/auth'
import { useOverview } from '../state/overview'
import RecommendationPanel from '../components/RecommendationPanel.vue'
const { state, reload } = useOverview()
</script>

<template>
  <section class="intro">
    <p class="eyebrow">DATA STRUCTURES</p>
    <h1>{{ authState.account?.user.display_name }}，欢迎回来</h1>
    <p class="intro-copy">将资料、对话与练习放在同一个学习空间里。</p>
    <RouterLink class="primary-link" to="/chat">开始学习</RouterLink>
    <RouterLink class="text-button" to="/practice">先做基础练习</RouterLink>
    <div class="notice">
      个人知识库“{{ authState.account?.default_knowledge_base.name }}”已创建。
      可以直接使用课程资料开始学习，也可以上传自己的笔记，结合答疑与练习巩固理解。
    </div>
  </section>
  <section class="report-panel" aria-labelledby="recent-learning-title">
    <div class="section-heading"><h2 id="recent-learning-title">最近 7 天</h2><RouterLink to="/reports">查看完整统计</RouterLink></div>
    <p v-if="state.loading">正在读取学习记录…</p><p v-if="state.error" class="form-error" role="alert">{{ state.error }} <button @click="reload()">重试</button></p>
    <template v-if="state.data"><p class="field-help">{{ state.data.stats.from_date }} 至 {{ state.data.stats.to_date }} · 上海日期</p><div class="stats-grid"><div><span>有效作答</span><strong>{{ state.data.stats.attempts.count }} 次</strong></div><div><span>独立新题</span><strong>{{ state.data.stats.categories.first_independent.count }} 道</strong></div><div><span>完成回答</span><strong>{{ state.data.stats.learning.completed_answers }} 次</strong></div><div><span>当前待复习</span><strong>{{ state.data.stats.wrong_questions.current_pending }} 道</strong><small>不限日期范围</small></div></div>
      <div class="reports-layout"><div><h3>继续对话</h3><p v-if="!state.data.recent_conversations.length" class="field-help">暂无会话，点击“开始学习”提出第一个问题。</p><RouterLink v-for="item in state.data.recent_conversations" :key="item.id" class="conversation-link" :to="'/chat/' + item.id">{{ item.title }}</RouterLink></div><div><h3>最近练习</h3><p v-if="!state.data.recent_practices.length" class="field-help">暂无练习，可以先做一组基础题。</p><RouterLink v-for="item in state.data.recent_practices" :key="item.id" class="conversation-link" :to="'/practice/' + item.id">{{ item.mode === 'review' ? '错题复习' : item.question_source === 'ai' ? 'AI 练习' : '题库练习' }} · {{ item.submitted_count }}/{{ item.actual_count }} 已答 · {{ item.status === 'completed' ? '已完成' : item.status === 'failed' ? '生成失败' : item.status === 'generating' ? '生成中' : '继续作答' }}</RouterLink></div></div>
    </template>
  </section>
  <section aria-labelledby="learning-entry-title">
    <div class="section-heading">
      <h2 id="learning-entry-title">学习入口</h2>
      <span>五个环节，连接一次完整学习</span>
    </div>
    <div class="entry-grid">
      <RouterLink
        v-for="(page, index) in navigation.slice(1)"
        :key="page.path"
        :to="page.path"
        class="entry-card"
      >
        <span class="entry-number">{{ String(index + 1).padStart(2, '0') }}</span>
        <h3>{{ page.title }}</h3>
        <p>{{ page.description }}</p>
        <span class="entry-link">查看入口 <span aria-hidden="true">↗</span></span>
      </RouterLink>
    </div>
  </section>
  <RecommendationPanel />
</template>
