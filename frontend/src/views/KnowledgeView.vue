<script setup lang="ts">
import { computed, ref } from 'vue'

import { useKnowledge } from '../state/knowledge'
import DocumentPanel from '../components/DocumentPanel.vue'

const { state, reload, selectLibrary } = useKnowledge()
const search = ref('')
const selectedChapter = ref('')
const chapters = computed(() => state.chapters.filter(chapter => chapter.name.includes(search.value.trim())))
</script>

<template>
  <section>
    <p class="eyebrow">YOUR KNOWLEDGE</p>
    <h1>我的知识库</h1>

    <div v-if="state.librariesStatus === 'loading'" class="notice" role="status">正在读取知识库…</div>
    <div v-else-if="state.librariesStatus === 'error'" class="form-error" role="alert">
      {{ state.librariesError }}
      <button class="text-button" type="button" @click="reload">重新加载</button>
    </div>
    <p v-else-if="!state.libraries.length" class="notice">知识库尚未准备好，请稍后重试。</p>
    <div v-else class="library-grid" aria-label="可访问的知识库">
      <button
        v-for="library in state.libraries"
        :key="library.id"
        class="library-card"
        :class="{ selected: state.selectedId === library.id }"
        type="button"
        :aria-pressed="state.selectedId === library.id"
        @click="selectLibrary(library.id)"
      >
        <span class="phase-label">{{ library.is_readonly ? '课程资料 · 只读' : '个人资料 · 仅自己可见' }}</span>
        <strong>{{ library.name }}</strong>
        <span class="entry-link">{{ state.selectedId === library.id ? '当前知识库' : '查看资料' }} <span aria-hidden="true">{{ state.selectedId === library.id ? '✓' : '→' }}</span></span>
      </button>
    </div>

    <template v-if="state.selectedId && state.librariesStatus === 'ready'">
      <p v-if="state.detailStatus === 'loading'" role="status">正在读取知识库信息…</p>
      <div v-else-if="state.detailStatus === 'error'" class="form-error" role="alert">
        {{ state.detailError }}
        <button class="text-button" type="button" @click="selectLibrary(state.selectedId)">重试</button>
      </div>
    </template>

    <section class="course-catalog" aria-labelledby="catalog-title">
      <div class="section-heading"><h2 id="catalog-title">课程章节</h2></div>
      <p v-if="state.chaptersStatus === 'loading'" role="status">正在读取章节…</p>
      <p v-else-if="state.chaptersStatus === 'error'" class="form-error">{{ state.chaptersError }} <button @click="reload">重试</button></p>
      <template v-else>
        <input id="catalog-search" v-model="search" class="catalog-search" type="search" aria-label="搜索章节" placeholder="输入章节名称">
        <div class="catalog-grid"><button v-for="chapter in chapters" :key="chapter.id" class="chapter-card" :aria-pressed="selectedChapter === chapter.id" @click="selectedChapter = selectedChapter === chapter.id ? '' : chapter.id">{{ chapter.name }}</button></div>
        <p v-if="!chapters.length" class="field-help">没有找到对应章节。</p>
      </template>
    </section>

    <DocumentPanel v-if="state.detail" :key="state.detail.id" :library="state.detail" :chapters="state.chapters" :chapter-id="selectedChapter" />
  </section>
</template>
