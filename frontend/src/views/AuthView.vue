<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import { safeReturnPath } from '../navigation'
import { authState, restoreAccount, signIn, signUp } from '../state/auth'

const route = useRoute()
const router = useRouter()
const isRegister = computed(() => route.name === 'register')
const username = ref('')
const password = ref('')
const displayName = ref('')
const showPassword = ref(false)
const error = ref('')
const alternate = computed(() => ({
  name: isRegister.value ? 'login' : 'register',
  query: { redirect: safeReturnPath(route.query.redirect) },
}))

watch(isRegister, () => {
  password.value = ''
  error.value = ''
  showPassword.value = false
})

async function submit() {
  if (authState.busy) return
  error.value = ''
  try {
    const credentials = { username: username.value, password: password.value }
    if (isRegister.value) {
      await signUp({
        ...credentials,
        display_name: displayName.value.trim() || undefined,
      })
    } else {
      await signIn(credentials)
    }
    password.value = ''
    await router.replace(safeReturnPath(route.query.redirect))
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '操作失败，请重试。'
  }
}

async function retryConnection() {
  await restoreAccount(true)
  if (authState.account) await router.replace(safeReturnPath(route.query.redirect))
}
</script>

<template>
  <div class="auth-layout">
    <section class="auth-intro">
      <RouterLink class="brand" to="/" aria-label="知序学习首页">
        <span class="brand-mark" aria-hidden="true">序</span>
        <span><strong>知序</strong><small>数据结构学习助手</small></span>
      </RouterLink>
      <p class="eyebrow">YOUR LEARNING SPACE</p>
      <h1>一步一步，<br>建立自己的理解。</h1>
      <p class="intro-copy">
        从线性表、栈与队列，到树与图，<br>把每一次学习留在自己的空间里。
      </p>
      <p class="auth-progress">
        注册后自动创建个人知识库。<br>结合课程资料、答疑与练习，逐步巩固理解。
      </p>
    </section>
    <section class="auth-card" aria-labelledby="auth-title">
      <p class="eyebrow">{{ isRegister ? 'GET STARTED' : 'WELCOME BACK' }}</p>
      <h2 id="auth-title">{{ isRegister ? '创建学习账号' : '登录学习空间' }}</h2>
      <p class="auth-description">
        {{ isRegister ? '填写用户名和密码，注册后即可进入。' : '欢迎回来，继续你的学习。' }}
      </p>
      <div v-if="authState.status === 'error'" class="form-error" role="alert">
        {{ authState.error }}
        <button type="button" class="text-button" @click="retryConnection">重新连接</button>
      </div>
      <form @submit.prevent="submit">
        <fieldset :disabled="authState.busy">
          <label for="username">用户名</label>
          <input
            id="username"
            v-model="username"
            name="username"
            autocomplete="username"
            autocapitalize="none"
            :spellcheck="false"
            required
            minlength="3"
            maxlength="32"
            aria-describedby="username-help"
          >
          <p id="username-help" class="field-help">3–32 位英文字母、数字或下划线。</p>
          <template v-if="isRegister">
            <label for="display-name">显示名称 <span class="optional">选填</span></label>
            <input
              id="display-name"
              v-model="displayName"
              name="display_name"
              autocomplete="nickname"
              maxlength="32"
              placeholder="你希望被怎么称呼"
            >
          </template>
          <label for="password">密码</label>
          <div class="password-field">
            <input
              id="password"
              v-model="password"
              name="password"
              :type="showPassword ? 'text' : 'password'"
              :autocomplete="isRegister ? 'new-password' : 'current-password'"
              required
              minlength="8"
              maxlength="128"
              aria-describedby="password-help"
            >
            <button
              class="text-button"
              type="button"
              :aria-pressed="showPassword"
              @click="showPassword = !showPassword"
            >{{ showPassword ? '隐藏' : '显示' }}</button>
          </div>
          <p id="password-help" class="field-help">8–128 个字符，支持空格和粘贴。</p>
          <p v-if="error" class="form-error" role="alert">{{ error }}</p>
          <button class="primary-button auth-submit" type="submit">
            {{ authState.busy ? '正在提交…' : isRegister ? '注册并进入' : '登录' }}
          </button>
        </fieldset>
      </form>
      <p class="auth-alternate">
        {{ isRegister ? '已经有账号？' : '还没有账号？' }}
        <RouterLink :to="alternate">{{ isRegister ? '直接登录' : '创建账号' }}</RouterLink>
      </p>
    </section>
  </div>
</template>
