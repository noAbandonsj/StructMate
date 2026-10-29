<script setup lang="ts">
defineProps<{ title: string; badge?: string; open?: boolean }>()
</script>

<template>
  <details class="disclosure-panel" :open="open">
    <summary><span class="disclosure-title">{{ title }}</span><span v-if="badge" class="disclosure-badge">{{ badge }}</span></summary>
    <div class="disclosure-content"><slot /></div>
  </details>
</template>
