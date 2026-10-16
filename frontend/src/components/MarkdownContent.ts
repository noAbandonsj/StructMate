import { computed, defineComponent, h, ref, watch, type PropType } from 'vue'
import { renderMarkdown } from '../markdown'

export default defineComponent({
  name: 'MarkdownContent',
  props: { content: { type: String, required: true }, citations: { type: Array as PropType<number[]>, default: () => [] } },
  emits: { citation: (_number: number) => true },
  setup(props, { emit }) {
    const copyStatus = ref('')
    watch(() => props.content, () => { copyStatus.value = '' })
    async function copy(text: string) {
      try { await navigator.clipboard.writeText(text); copyStatus.value = '代码已复制。' }
      catch { copyStatus.value = '无法自动复制，请选中代码后手动复制。' }
    }
    const nodes = computed(() => renderMarkdown(props.content, props.citations, number => emit('citation', number), text => void copy(text)))
    return () => h('div', { class: 'markdown-content' }, [...nodes.value, copyStatus.value ? h('p', { class: 'field-help', role: 'status' }, copyStatus.value) : null])
  },
})
