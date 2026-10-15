<script setup lang="ts">
import { RouterLink } from 'vue-router'

import { navigation } from '../navigation'
import { authState } from '../state/auth'
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
      资料管理、学习会话、题库练习和错题复习已接入。真实答疑与 AI 出题需接通模型，报告与推荐继续完善。
    </div>
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
</template>
