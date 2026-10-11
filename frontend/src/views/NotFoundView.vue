<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <section class="empty-state">
    <p class="eyebrow">404</p>
    <h1>没有找到这个页面</h1>
    <p>请通过左侧导航进入学习空间。</p>
    <RouterLink class="primary-link" to="/">返回学习首页</RouterLink>
  </section>
</template>
