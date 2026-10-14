<script setup lang="ts">
import { ref, watch } from 'vue'

import { authState, changeDisplayName, signOut } from '../state/auth'

const displayName = ref('')
const error = ref('')
const saved = ref(false)

watch(() => authState.account?.user.display_name, (name) => {
  displayName.value = name ?? ''
  error.value = ''
  saved.value = false
}, { immediate: true })

async function saveName() {
  error.value = ''
  saved.value = false
  try {
    await changeDisplayName(displayName.value.trim())
    saved.value = true
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '修改失败，请重试。'
  }
}

async function logout() {
  error.value = ''
  try {
    await signOut()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '退出失败，请重试。'
  }
}
</script>

<template>
  <details class="account-menu">
    <summary>{{ authState.account?.user.display_name }} <span aria-hidden="true">⌄</span></summary>
    <div class="account-panel">
      <p class="account-username">用户名：{{ authState.account?.user.username }}</p>
      <form @submit.prevent="saveName">
        <label for="account-name">显示名称</label>
        <input
          id="account-name"
          v-model="displayName"
          required
          maxlength="32"
          :disabled="authState.busy"
          autocomplete="nickname"
        >
        <button class="text-button" type="submit" :disabled="authState.busy">保存名称</button>
      </form>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <p v-else-if="saved" class="field-help" role="status">名称已保存。</p>
      <button class="secondary-button" type="button" :disabled="authState.busy" @click="logout">
        {{ authState.busy ? '正在处理…' : '退出登录' }}
      </button>
    </div>
  </details>
</template>
