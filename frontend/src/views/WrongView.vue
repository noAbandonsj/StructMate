<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useWrong } from '../state/wrong'
import MarkdownContent from '../components/MarkdownContent'
const route = useRoute(), router = useRouter()
const selected = computed(() => typeof route.params.id === 'string' ? route.params.id : '')
const { state, reload, review } = useWrong(selected)
async function start(ids: string[]) { const practice = await review(ids); if (practice) await router.push('/practice/' + practice.id) }
function safeLink(value: string) { try { return ['https:', 'http:'].includes(new URL(value).protocol) ? value : '#' } catch { return '#' } }
</script>
<template>
  <section>
    <div class="section-heading"><h1>错题本</h1><button :disabled="state.loading" @click="reload()">刷新</button></div>
    <p class="intro-copy">错误自动收录，复习保留历次记录。不同上海日期连续两次答对可标记该题已巩固，再次答错会回到待复习。</p>
    <p v-if="state.error" class="form-error" role="alert">{{ state.error }}</p>
    <div class="wrong-filters"><label>复习状态<select v-model="state.status" @change="state.page = 1; reload()"><option value="pending">待复习</option><option value="consolidated">已巩固</option><option value="">全部</option></select></label><label>搜索主题或题目<input type="search" v-model="state.search" maxlength="500" placeholder="例如：循环队列" @change="state.page = 1; reload()"></label><button class="primary-button" :disabled="state.busy || !state.checked.length" @click="start(state.checked)">复习所选（{{ state.checked.length }}）</button></div>
    <div class="wrong-layout">
      <div>
        <p v-if="state.loading && !state.items.length">正在读取错题…</p><p v-else-if="state.error && !state.items.length" class="notice">暂时无法读取错题，请刷新重试。</p><p v-else-if="!state.items.length" class="notice">当前筛选没有错题，可以去练习中心开始一组练习。</p>
        <article v-for="item in state.items" :key="item.id" class="wrong-card">
          <label><input type="checkbox" :value="item.id" v-model="state.checked">选择复习</label><RouterLink :to="'/wrong/' + item.id"><h2>{{ item.stem }}</h2></RouterLink>
          <p v-if="item.topic" class="field-help">练习主题：{{ item.topic }}</p>
          <p class="field-help">{{ item.source_type === 'ai' ? 'AI 题 · 参考答案' : '核验题库' }} · {{ item.status === 'consolidated' ? '该题已巩固' : '待复习' }} · {{ item.error_count }} 次错误 / {{ item.attempt_count }} 次作答</p>
          <button :disabled="state.busy" @click="start([item.id])">重做这道题</button>
        </article>
        <div v-if="state.total > 20" class="document-pagination"><button :disabled="state.page <= 1 || state.loading" @click="state.page--; reload()">上一页</button><span>{{ state.page }}</span><button :disabled="state.page * 20 >= state.total || state.loading" @click="state.page++; reload()">下一页</button></div>
      </div>
      <aside v-if="state.detail" class="wrong-detail">
        <h2>原题与历次作答</h2><strong>{{ state.detail.stem }}</strong>
        <p v-if="!state.detail.is_valid" class="notice">此题已停用并排除统计：{{ state.detail.disabled_reason }}</p>
        <ul><li v-for="option in state.detail.question?.options" :key="option.key">{{ option.text }}</li></ul>
        <p>{{ state.detail.source_type === 'ai' ? '参考答案' : '核验答案' }}：{{ state.detail.question?.options.find(option => option.key === state.detail!.question?.answer)?.text }}</p><MarkdownContent v-if="state.detail.question" :content="state.detail.question.explanation" />
        <button :disabled="state.busy || !state.detail.is_valid" @click="start([state.detail.id])">开始原题复习</button>
        <details><summary>原题依据与来源</summary>
          <p v-for="source in state.detail.question?.source_info.sources" :key="source.url"><a :href="safeLink(source.url)" target="_blank" rel="noopener noreferrer">{{ source.title }}</a> · {{ source.author }} · {{ source.license }}</p>
          <p v-for="(source, index) in state.detail.question?.source_info.citations" :key="index">{{ source.filename }}{{ source.source_deleted ? '（来源已删除，保留历史片段）' : '' }}<span class="field-help">{{ source.text }}</span></p>
        </details>
        <ol class="attempt-history"><li v-for="attempt in state.detail.attempts" :key="attempt.id">{{ new Date(attempt.created_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) }} · {{ attempt.is_correct ? '答对' : '答错' }} · {{ attempt.hinted ? '使用提示' : '未使用提示' }}{{ attempt.is_valid ? '' : ' · 已排除统计' }}</li></ol>
      </aside>
    </div>
  </section>
</template>
