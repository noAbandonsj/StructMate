<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import { authState } from '../state/auth'
import { useOverview } from '../state/overview'
const { state, reload } = useOverview()
const readiness = computed(() => !state.loading && !state.error ? state.data?.readiness : null)
const canStudy = computed(() => readiness.value?.generation_available)
const practiceStatus = { completed: '已完成', failed: '生成失败', generating: '生成中', ready: '继续作答' }
</script>

<template>
  <section class="intro">
    <p class="eyebrow">DATA STRUCTURES</p>
    <h1>{{ authState.account?.user.display_name }}，欢迎回来</h1>
    <div class="home-actions">
      <RouterLink v-if="canStudy" class="primary-link" to="/chat">开始学习 <span aria-hidden="true">→</span></RouterLink>
      <RouterLink :class="canStudy ? 'home-secondary-link' : 'primary-link'" to="/practice">前往练习中心 <span aria-hidden="true">→</span></RouterLink>
      <RouterLink v-if="readiness && !canStudy" class="home-secondary-link" to="/knowledge">查看或上传资料 <span aria-hidden="true">→</span></RouterLink>
    </div>
    <p v-if="readiness && !canStudy" class="notice" role="status">AI 答疑与出题暂不可用，请联系管理员配置生成模型。资料仍可上传和预览。</p>
  </section>
  <section class="report-panel" aria-labelledby="recent-learning-title">
    <div class="section-heading"><h2 id="recent-learning-title">最近 7 天</h2></div>
    <p v-if="state.loading">正在读取学习记录…</p><p v-if="state.error" class="form-error" role="alert">{{ state.error }} <button @click="reload()">重试</button></p>
    <template v-if="state.data"><p class="field-help">{{ state.data.stats.from_date }} 至 {{ state.data.stats.to_date }} · 上海日期</p><div class="stats-grid"><div><span>有效作答</span><strong>{{ state.data.stats.attempts.count }} 次</strong></div><div><span>首次作答新题</span><strong>{{ state.data.stats.categories.first.count }} 道</strong></div><div><span>有效答疑</span><strong>{{ state.data.stats.learning.completed_answers }} 次</strong></div><div><span>当前待复习</span><strong>{{ state.data.stats.wrong_questions.current_pending }} 道</strong><small>不限日期范围</small></div></div>
      <div class="home-recent-grid">
        <section class="home-recent-panel" aria-labelledby="recent-conversations-title">
          <div class="home-recent-heading"><h3 id="recent-conversations-title">继续对话</h3><span class="home-record-count">{{ state.data.recent_conversations.length }} 条</span></div>
          <p v-if="!state.data.recent_conversations.length" class="home-record-empty">暂无会话，点击“开始学习”提出第一个问题。</p>
          <ul v-else class="home-record-list">
            <li v-for="item in state.data.recent_conversations" :key="item.id">
              <RouterLink class="home-record" :to="'/chat/' + item.id">
                <span class="home-record-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H8l-4 3v-7a7.5 7.5 0 1 1 16-3.5Z" /><path d="M8 9h8M8 13h5" /></svg></span>
                <span class="home-record-main"><strong class="home-record-title">{{ item.title }}</strong></span>
                <span class="home-record-arrow" aria-hidden="true">→</span>
              </RouterLink>
            </li>
          </ul>
        </section>
        <section class="home-recent-panel" aria-labelledby="recent-practices-title">
          <div class="home-recent-heading"><h3 id="recent-practices-title">最近练习</h3><span class="home-record-count">{{ state.data.recent_practices.length }} 组</span></div>
          <p v-if="!state.data.recent_practices.length" class="home-record-empty">暂无练习，可以先做一组基础题。</p>
          <ul v-else class="home-record-list">
            <li v-for="item in state.data.recent_practices" :key="item.id">
              <RouterLink class="home-record" :to="'/practice/' + item.id">
                <span class="home-record-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="5" y="4" width="14" height="17" rx="2" /><path d="M9 3h6v3H9zM9 11h6M9 15h4" /></svg></span>
                <span class="home-record-main">
                  <span class="home-record-topline"><strong class="home-record-title">{{ item.mode === 'review' ? '错题复习' : 'AI 练习' }}</strong><span class="home-record-status" :class="'status-' + item.status">{{ practiceStatus[item.status] }}</span></span>
                  <span class="home-record-meta">{{ item.chapter_name ? item.chapter_name + ' · ' : '' }}{{ item.submitted_count }}/{{ item.actual_count }} 已答</span>
                </span>
                <span class="home-record-arrow" aria-hidden="true">→</span>
              </RouterLink>
            </li>
          </ul>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.home-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: 26px; }
.home-actions .primary-link, .home-secondary-link { display: inline-flex; justify-content: center; align-items: center; gap: 16px; min-height: 42px; margin: 0; padding: 10px 18px; border: 1px solid var(--accent); border-radius: 8px; font-size: 13px; font-weight: 600; line-height: 1.5; transition: background-color .16s, border-color .16s; }
.home-actions .primary-link:hover { background: #245648; border-color: #245648; }
.home-secondary-link { color: var(--accent); border-color: #cbd6cd; background: #fffefa; }
.home-secondary-link:hover { border-color: #91b2a4; background: #edf3ee; }
.home-actions a > span { font-size: 16px; font-weight: 400; }
.home-recent-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); gap: 18px; margin-top: 26px; padding-top: 24px; border-top: 1px solid var(--line); }
.home-recent-panel { min-width: 0; padding: 18px; border: 1px solid var(--line); border-radius: 12px; background: #fcfcf9; }
.home-recent-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.home-recent-heading h3 { margin: 0; font-size: 15px; font-weight: 600; }
.home-record-count { flex-shrink: 0; padding: 3px 8px; border-radius: 6px; background: #edf0e9; color: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.home-record-list { list-style: none; padding: 0; margin: 0; }
.home-record-list > li + li { border-top: 1px solid var(--line); }
.home-record { display: flex; align-items: center; gap: 11px; min-height: 76px; padding: 12px 8px; border-radius: 8px; transition: background-color .16s; }
.home-record:hover, .home-record:focus-visible { background: #edf3ee; }
.home-record-icon { display: grid; place-items: center; width: 34px; height: 34px; flex-shrink: 0; color: var(--accent); border: 1px solid #dce7dd; border-radius: 9px; background: #f0f5ef; }
.home-record-icon svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.home-record-main { display: grid; flex: 1; min-width: 0; gap: 6px; }
.home-record-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; line-height: 1.5; font-weight: 600; }
.home-record-topline { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; }
.home-record-meta { color: var(--muted); font-size: 11px; line-height: 1.6; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.home-record-status { flex-shrink: 0; padding: 2px 7px; border-radius: 5px; color: var(--muted); background: #edf0e9; font-size: 10px; font-weight: 500; line-height: 1.5; }
.status-ready { background: #e7eee8; color: var(--accent); }
.status-failed { background: #faf0ec; color: #974b3d; }
.home-record-arrow { flex-shrink: 0; color: #91a398; font-size: 17px; }
.home-record:hover .home-record-arrow, .home-record:focus-visible .home-record-arrow { color: var(--accent); }
.home-record-empty { margin: 0; padding: 24px 8px; color: var(--muted); font-size: 12px; line-height: 1.8; }
@media (prefers-reduced-motion: reduce) {
  .home-actions .primary-link, .home-secondary-link, .home-record { transition: none; }
}
</style>
