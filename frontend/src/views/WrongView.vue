<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useWrong } from '../state/wrong'
import MarkdownContent from '../components/MarkdownContent'
import DisclosurePanel from '../components/DisclosurePanel.vue'
const route = useRoute(), router = useRouter()
const selected = computed(() => typeof route.params.id === 'string' ? route.params.id : '')
const { state, reload, review } = useWrong(selected)
const allSelected = computed(() => state.items.length > 0 && state.items.every(item => state.checked.includes(item.id)))
const partiallySelected = computed(() => state.checked.length > 0 && !allSelected.value)
function toggleAll() { state.checked = allSelected.value ? [] : state.items.map(item => item.id) }
async function start(ids: string[]) { const practice = await review(ids); if (practice) await router.push('/practice/' + practice.id) }
</script>
<template>
  <section>
    <div class="section-heading"><h1>错题本</h1></div>
    <p v-if="state.error" class="form-error" role="alert">{{ state.error }} <button :disabled="state.loading" @click="reload()">重试</button></p>
    <div class="wrong-filters"><label>章节<select v-model="state.chapter" @change="state.page = 1; reload()"><option value="">全部章节</option><option v-for="chapter in state.chapters" :key="chapter.id" :value="chapter.id">{{ chapter.name }}</option></select></label><label>复习状态<select v-model="state.status" @change="state.page = 1; reload()"><option value="pending">待复习</option><option value="consolidated">已巩固</option><option value="">全部</option></select></label><label>搜索题目<input type="search" v-model="state.search" maxlength="500" @change="state.page = 1; reload()"></label><button class="primary-button" :disabled="state.busy || !state.checked.length" @click="start(state.checked)">复习所选（{{ state.checked.length }}）</button></div>
    <div class="wrong-layout">
      <div>
        <label class="wrong-select-all"><input type="checkbox" :checked="allSelected" :indeterminate="partiallySelected" :disabled="state.loading || state.busy || !state.items.length" @change="toggleAll">全选本页（{{ state.items.length }} 题）</label>
        <p v-if="state.loading && !state.items.length">正在读取错题…</p><p v-else-if="state.error && !state.items.length" class="notice">暂时无法读取错题，请刷新重试。</p><p v-else-if="!state.items.length" class="notice">当前筛选没有错题，可以去练习中心开始一组练习。</p>
        <article v-for="item in state.items" :key="item.id" class="wrong-card">
          <label><input type="checkbox" :value="item.id" v-model="state.checked">选择复习</label><RouterLink :to="'/wrong/' + item.id"><h2>{{ item.stem }}</h2></RouterLink>
          <p class="field-help">章节：{{ item.chapter_name }}</p>
          <p class="field-help">{{ item.status === 'consolidated' ? '已巩固' : '待复习' }} · {{ item.error_count }} 次错误 / {{ item.attempt_count }} 次作答</p>
          <button :disabled="state.busy" @click="start([item.id])">重做这道题</button>
        </article>
        <div v-if="state.total > 20" class="document-pagination"><button :disabled="state.page <= 1 || state.loading" @click="state.page--; reload()">上一页</button><span>{{ state.page }}</span><button :disabled="state.page * 20 >= state.total || state.loading" @click="state.page++; reload()">下一页</button></div>
      </div>
      <aside v-if="state.detail" class="wrong-detail">
        <h2>原题与历次作答</h2><strong>{{ state.detail.stem }}</strong>
        <p v-if="!state.detail.is_valid" class="notice">此题已停用并排除统计：{{ state.detail.disabled_reason }}</p>
        <ul><li v-for="option in state.detail.question?.options" :key="option.key">{{ option.text }}</li></ul>
        <p>参考答案：{{ state.detail.question?.options.find(option => option.key === state.detail!.question?.answer)?.text }}</p><MarkdownContent v-if="state.detail.question" :content="state.detail.question.explanation" />
        <button :disabled="state.busy || !state.detail.is_valid" @click="start([state.detail.id])">开始原题复习</button>
        <DisclosurePanel title="原题依据与来源">
          <p v-for="(source, index) in state.detail.question?.source_info.citations" :key="index">{{ source.filename }}{{ source.source_deleted ? '（来源已删除，保留历史片段）' : '' }}<span class="field-help">{{ source.text }}</span></p>
        </DisclosurePanel>
        <ol class="attempt-history"><li v-for="attempt in state.detail.attempts" :key="attempt.id">{{ new Date(attempt.created_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) }} · {{ attempt.is_correct ? '答对' : '答错' }} · {{ attempt.hinted ? '使用提示' : '未使用提示' }}{{ attempt.is_valid ? '' : ' · 已排除统计' }}</li></ol>
      </aside>
    </div>
  </section>
</template>
