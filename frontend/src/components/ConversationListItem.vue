<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { RouterLink } from 'vue-router'
import type { Conversation } from '../api/chat'

const props = defineProps<{
  conversation: Conversation
  selected: boolean
  busy: boolean
  canArchive: boolean
  rename: (title: string) => Promise<boolean>
}>()
defineEmits<{ archive: [] }>()
const editing = ref(false), title = ref('')
const input = ref<HTMLInputElement | null>(null)
async function edit() {
  title.value = props.conversation.title
  editing.value = true
  await nextTick()
  input.value?.focus()
  input.value?.select()
}
async function save() {
  const value = title.value.trim()
  if (!value || props.busy) return
  if (value === props.conversation.title || await props.rename(value)) editing.value = false
}
</script>

<template>
  <div class="conversation-row" :class="{ selected }">
    <form v-if="editing" class="conversation-rename" @submit.prevent="save" @keydown.esc.prevent="editing = false">
      <input ref="input" v-model="title" aria-label="会话名称" maxlength="100" required :disabled="busy">
      <div class="conversation-rename-actions"><button type="submit" :disabled="busy || !title.trim()">保存</button><button type="button" :disabled="busy" @click="editing = false">取消</button></div>
    </form>
    <template v-else>
      <RouterLink :to="'/chat/' + conversation.id" class="conversation-link" :aria-current="selected ? 'page' : undefined">{{ conversation.title }}<small v-if="conversation.archived" class="field-help">已归档</small></RouterLink>
      <div class="conversation-actions">
        <button type="button" class="conversation-icon" aria-label="重命名会话" title="重命名会话" :disabled="busy" @click="edit">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m16 3 5 5M4 20l5-1L21 7a2 2 0 0 0-5-5L4 14Z" /></svg>
        </button>
        <button type="button" class="conversation-icon" :aria-label="conversation.archived ? '恢复会话' : '归档会话'" :title="conversation.archived ? '恢复会话' : '归档会话'" :disabled="busy || !canArchive" @click="$emit('archive')">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 4h18v4H3zM5 8v12h14V8M9 12h6" /><path v-if="conversation.archived" d="m9 17 3-3 3 3m-3-3v6" /></svg>
        </button>
      </div>
    </template>
  </div>
</template>
