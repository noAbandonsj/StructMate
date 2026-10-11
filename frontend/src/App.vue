<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'

import { getHealth } from './api/health'
import { navigation } from './router'

const route = useRoute()
const connection = ref<'checking' | 'connected' | 'disconnected'>('checking')
const connectionLabel = computed(() => ({
  checking: '正在连接服务',
  connected: '服务已连接',
  disconnected: '服务未连接',
})[connection.value])

async function checkConnection() {
  connection.value = 'checking'
  try {
    await getHealth()
    connection.value = 'connected'
  } catch {
    connection.value = 'disconnected'
  }
}

onMounted(checkConnection)
</script>

<template>
  <div class="workspace">
    <aside class="sidebar">
      <RouterLink class="brand" to="/" aria-label="知序学习首页">
        <span class="brand-mark" aria-hidden="true">序</span>
        <span><strong>知序</strong><small>数据结构学习助手</small></span>
      </RouterLink>
      <p class="nav-label">学习空间</p>
      <nav aria-label="主要导航">
        <RouterLink
          v-for="(page, index) in navigation"
          :key="page.path"
          :to="page.path"
          class="nav-item"
          :class="{ active: route.path === page.path }"
          :aria-current="route.path === page.path ? 'page' : undefined"
        >
          <span class="nav-index">{{ String(index + 1).padStart(2, '0') }}</span>
          {{ page.title }}
        </RouterLink>
      </nav>
      <div class="sidebar-footer">
        <span class="phase-label">初始化阶段</span>
        <p>从理解概念，到独立解题。</p>
      </div>
    </aside>
    <div class="main-area">
      <header class="topbar">
        <span>学习空间 <span class="breadcrumb-separator">/</span> {{ route.meta.title }}</span>
        <div class="connection-status" role="status" aria-live="polite">
          <span class="status-dot" :class="connection" aria-hidden="true"></span>
          {{ connectionLabel }}
          <button
            v-if="connection === 'disconnected'"
            class="text-button"
            type="button"
            @click="checkConnection"
          >重试</button>
        </div>
      </header>
      <main id="main-content" class="page-content">
        <RouterView />
      </main>
    </div>
  </div>
</template>
