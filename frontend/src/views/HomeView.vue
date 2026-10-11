<script setup lang="ts">
import { RouterLink } from 'vue-router'

import { navigation } from '../router'
</script>

<template>
  <section class="intro">
    <p class="eyebrow">DATA STRUCTURES</p>
    <h1>一步一步，理解数据结构</h1>
    <p class="intro-copy">将资料、对话与练习放在同一个学习空间里。</p>
    <div class="notice">
      网页基础框架已建立。课程资料、学习对话和练习功能将逐步接入。
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
