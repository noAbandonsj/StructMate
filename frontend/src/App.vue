<script setup lang="ts">
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'

import { serviceState, checkService, markServiceUnavailable } from './state/connection'
import AccountMenu from './components/AccountMenu.vue'
import { navigation, safeReturnPath } from './navigation'
import { authState, restoreAccount } from './state/auth'

const route = useRoute()
const router = useRouter()
const connection = computed(() => serviceState.status)
const connectionLabel = computed(() => ({
  checking: '正在连接服务',
  connected: '后端服务正常',
  disconnected: '服务连接异常',
})[connection.value])

const checkConnection = () => { if (!document.hidden) void checkService() }
let connectionTimer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  checkConnection()
  connectionTimer = setInterval(checkConnection, 30000)
  window.addEventListener('focus', checkConnection)
  window.addEventListener('online', checkConnection)
  window.addEventListener('offline', markServiceUnavailable)
  document.addEventListener('visibilitychange', checkConnection)
})
onUnmounted(() => {
  clearInterval(connectionTimer)
  window.removeEventListener('focus', checkConnection)
  window.removeEventListener('online', checkConnection)
  window.removeEventListener('offline', markServiceUnavailable)
  document.removeEventListener('visibilitychange', checkConnection)
})
const inSection = (path: string) => route.path === path || (path !== '/' && route.path.startsWith(path + '/'))

watch(() => authState.account, (account) => {
  if (!account && authState.status === 'ready' && route.meta.requiresAuth) {
    void router.replace({ name: 'login', query: { redirect: safeReturnPath(route.fullPath) } })
  }
})

async function retryAccount() {
  await restoreAccount(true)
  if (authState.status !== 'ready') return
  if (!authState.account && route.meta.requiresAuth) {
    await router.replace({ name: 'login', query: { redirect: safeReturnPath(route.fullPath) } })
  } else if (authState.account && route.meta.authPage) {
    await router.replace(safeReturnPath(route.query.redirect))
  }
}
</script>

<template>
  <div v-if="authState.status === 'loading' && !route.meta.authPage" class="account-loading" role="status">
    正在恢复登录…
  </div>
  <div
    v-else-if="authState.status === 'error' && !route.meta.authPage"
    class="account-loading"
    role="alert"
  >
    <p>{{ authState.error }}</p>
    <button class="primary-button" type="button" @click="retryAccount">重新连接</button>
  </div>
  <RouterView v-else-if="route.meta.authPage || !authState.account" :key="authState.account?.user.id" />
  <div v-else class="workspace">
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
          :class="{ active: inSection(page.path) }"
          :aria-current="inSection(page.path) ? 'page' : undefined"
        >
          <span class="nav-index">{{ String(index + 1).padStart(2, '0') }}</span>
          {{ page.title }}
        </RouterLink>
      </nav>
      <div class="sidebar-footer">
        <span class="phase-label">个人学习空间</span>
        <p>从理解概念，到独立解题。</p>
      </div>
    </aside>
    <div class="main-area">
      <header class="topbar">
        <span>学习空间 <span class="breadcrumb-separator">/</span> {{ route.meta.title }}</span>
        <div class="topbar-actions">
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
          <AccountMenu :key="authState.account.user.id" />
        </div>
      </header>
      <main id="main-content" class="page-content">
        <RouterView :key="authState.account.user.id" />
      </main>
    </div>
  </div>
</template>
