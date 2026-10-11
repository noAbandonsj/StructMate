<script setup lang="ts">
import { RouterLink, useRoute } from 'vue-router'

const route = useRoute()
</script>

<template>
  <section class="section-page">
    <p class="eyebrow">学习空间</p>
    <h1>{{ route.meta.title }}</h1>
    <p class="intro-copy">{{ route.meta.description }}</p>
    <div class="empty-state">
      <span class="phase-label">功能准备中</span>
      <h2>这个学习环节正在搭建</h2>
      <p>当前已建立页面入口，实际业务功能将在后续阶段接入。</p>
      <RouterLink class="primary-link" to="/">返回学习首页</RouterLink>
    </div>
  </section>
</template>
