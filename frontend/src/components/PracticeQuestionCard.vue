<script setup lang="ts">
import { RouterLink } from 'vue-router'
import type { Item } from '../api/practice'
import MarkdownContent from './MarkdownContent'
import DisclosurePanel from './DisclosurePanel.vue'

defineProps<{ item: Item; choice?: string; busy: boolean }>()
const emit = defineEmits<{
  choose: [itemId: string, answer: string]
  hint: [item: Item]
}>()

</script>

<template>
  <article :id="'question-' + item.id" class="question-card" tabindex="-1">
    <p class="field-help">第 {{ item.position }} 题 · {{ item.type === 'true_false' ? '判断题' : '单选题' }} · AI 参考答案</p>
    <h3>{{ item.stem }}</h3>
    <p v-if="!item.is_valid" class="notice">此题已确认有误，已排除统计：{{ item.disabled_reason }}</p>

    <fieldset class="answer-options" :disabled="busy || !!item.attempt || !item.is_valid">
      <label
        v-for="option in item.options" :key="option.key"
        :class="{
          'option-correct': item.attempt?.is_valid && item.attempt.reference_answer === option.key,
          'option-incorrect': item.attempt?.is_valid && !item.attempt.is_correct && item.attempt.answer === option.key,
        }"
      >
        <input
          type="radio" :name="item.id" :value="option.key"
          :checked="(item.attempt?.answer ?? choice) === option.key"
          @change="emit('choose', item.id, option.key)"
        >
        <span>{{ option.text }}</span>
      </label>
    </fieldset>

    <template v-if="!item.attempt && item.is_valid">
      <p v-if="item.hint" class="notice">提示：{{ item.hint }}</p>
      <div class="question-actions">
        <button :disabled="busy || item.hinted" @click="emit('hint', item)">{{ item.hinted ? '已使用提示' : '给我提示' }}</button>
      </div>
    </template>
    <div
      v-else-if="item.attempt" class="answer-result" role="status"
      :class="{ incorrect: item.attempt.is_valid && !item.attempt.is_correct }"
    >
      <strong>{{ !item.attempt.is_valid ? '此结果已排除统计' : item.attempt.is_correct ? '回答正确' : '已加入错题本' }}</strong>
      <p>参考答案：{{ item.options.find(option => option.key === item.attempt!.reference_answer)?.text }}</p>
      <MarkdownContent :content="item.attempt.explanation" />
      <p class="field-help">{{ item.attempt.category === 'first' ? '首次作答' : item.attempt.category === 'review' ? '错题复习' : '重复练习' }}{{ item.attempt.hinted ? ' · 使用了提示' : '' }}</p>
      <RouterLink v-if="item.attempt.wrong_question_id" :to="'/wrong/' + item.attempt.wrong_question_id">查看错题与历次作答</RouterLink>
      <DisclosurePanel title="依据与来源">
        <p v-for="(source, index) in item.attempt.source_info.citations" :key="index">
          {{ source.filename }}{{ source.source_deleted ? '（来源已删除，保留历史片段）' : '' }} {{ source.heading }} {{ source.page_number ? '第 ' + source.page_number + ' 页' : '' }}
          <span class="field-help">{{ source.text }}</span>
        </p>
        <p v-if="!item.attempt.source_info.citations?.length" class="field-help">暂无资料引用。</p>
      </DisclosurePanel>
    </div>
  </article>
</template>
