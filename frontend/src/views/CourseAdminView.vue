<script setup lang="ts">
import { computed } from 'vue'
import DocumentPanel from '../components/DocumentPanel.vue'
import { authState } from '../state/auth'
import { useKnowledge } from '../state/knowledge'

const { state, reload } = useKnowledge()
const course = computed(() => state.libraries.find(library => library.kind === 'course'))
</script>

<template>
  <section v-if="authState.account?.user.role === 'admin'">
    <div class="page-heading"><p class="eyebrow">课程维护</p><h1>课程资料管理</h1>
      <p>课程资料面向所有学习者。更新时先上传新文件，处理完成并核对后再移除旧文件。</p>
    </div>
    <p v-if="state.librariesError || state.pointsError" class="form-error" role="alert">
      {{ state.librariesError || state.pointsError }} <button class="text-button" @click="reload">重新加载</button>
    </p>
    <DocumentPanel v-if="course && state.pointsStatus === 'ready'" :library="course" :points="state.points" management />
    <p v-else-if="state.librariesStatus === 'loading' || state.pointsStatus === 'loading'" class="notice">正在读取课程目录…</p>
    <p v-else-if="!course" class="notice">课程尚未初始化，请由本机维护者运行课程初始化命令。</p>
  </section>
  <section v-else><h1>管理员权限已失效</h1><p>请返回学习空间，或由本机维护者重新授权后刷新页面。</p><RouterLink to="/">返回学习首页</RouterLink></section>
</template>
