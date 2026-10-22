<script setup lang="ts">
import { computed, ref } from 'vue'

import { useKnowledge } from '../state/knowledge'
import DocumentPanel from '../components/DocumentPanel.vue'

const { state, reload, selectLibrary } = useKnowledge()
const search = ref('')
const selectedChapter = ref('')
const chapters = computed(() => state.chapters.filter(chapter => chapter.name.includes(search.value.trim())))
const dateLabel = computed(() => state.detail
  ? new Date(state.detail.created_at).toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai' })
  : '')
</script>

<template>
  <section>
    <p class="eyebrow">YOUR KNOWLEDGE</p>
    <h1>我的知识库</h1>
    <p class="intro-copy">个人资料与课程内容，在同一个学习空间里。</p>

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
        <span class="library-description">
          {{ library.is_readonly ? '按课程章节组织，用于日常学习。' : '用于整理你自己的学习资料。' }}
        </span>
        <span class="entry-link">查看基础信息 <span aria-hidden="true">↗</span></span>
      </button>
    </div>

    <section v-if="state.selectedId && state.librariesStatus === 'ready'" class="library-info" aria-label="知识库基础信息">
      <p v-if="state.detailStatus === 'loading'" role="status">正在读取知识库信息…</p>
      <div v-else-if="state.detailStatus === 'error'" class="form-error" role="alert">
        {{ state.detailError }}
        <button class="text-button" type="button" @click="selectLibrary(state.selectedId)">重试</button>
      </div>
      <template v-else-if="state.detail">
        <div>
          <h2>{{ state.detail.name }}</h2>
          <p class="field-help">创建于 {{ dateLabel }} · {{ state.detail.is_readonly ? '课程内容由维护者更新' : '资料仅供本账号使用' }}</p>
        </div>
      </template>
    </section>

    <section class="course-catalog" aria-labelledby="catalog-title">
      <div class="section-heading"><h2 id="catalog-title">课程章节</h2><span v-if="state.chaptersStatus === 'ready'">{{ state.chapters.length }} 个内置章节</span></div>
      <p v-if="state.chaptersStatus === 'loading'" role="status">正在读取章节…</p>
      <p v-else-if="state.chaptersStatus === 'error'" class="form-error">{{ state.chaptersError }} <button @click="reload">重试</button></p>
      <template v-else>
        <label class="catalog-search-label" for="catalog-search">搜索章节</label>
        <input id="catalog-search" v-model="search" class="catalog-search" type="search" placeholder="输入章节名称">
        <p class="field-help">点击章节筛选资料，再次点击取消筛选。</p>
        <div class="catalog-grid"><button v-for="chapter in chapters" :key="chapter.id" class="chapter-card" :aria-pressed="selectedChapter === chapter.id" @click="selectedChapter = selectedChapter === chapter.id ? '' : chapter.id">{{ chapter.name }}</button></div>
        <p v-if="!chapters.length" class="field-help">没有找到对应章节。</p>
      </template>
    </section>

    <DocumentPanel v-if="state.detail" :key="state.detail.id" :library="state.detail" :chapters="state.chapters" :chapter-id="selectedChapter" />
  </section>
</template>
