<template>
  <p class="answer-text">
    <template v-for="(segment, index) in segments" :key="index">
      <button
        v-if="segment.kind === 'cite'"
        type="button"
        class="cite-mark"
        :title="`查看引用 ${segment.number} 的出处`"
        @click="emit('open', segment.number)"
      >
        {{ segment.number }}
      </button>
      <template v-else>{{ segment.text }}</template>
    </template>
  </p>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { QaCitation } from '../api'
import { parseAnswer } from '../utils/qa'

const props = defineProps<{
  answer: string
  citations: QaCitation[]
}>()

const emit = defineEmits<{ open: [number: number] }>()

// 只通过文本插值渲染；answer 中的任何 HTML 标签都会按普通字符显示。
const segments = computed(() => parseAnswer(props.answer, new Set(props.citations.map((c) => c.number))))
</script>

<style scoped>
.answer-text {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.8;
}

.cite-mark {
  display: inline-block;
  min-width: 18px;
  height: 18px;
  margin: 0 2px;
  padding: 0 4px;
  box-sizing: border-box;
  border: 1px solid var(--el-color-primary-light-5);
  border-radius: 9px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-size: 12px;
  line-height: 16px;
  text-align: center;
  vertical-align: text-top;
  cursor: pointer;
}

.cite-mark:hover,
.cite-mark:focus-visible {
  background: var(--el-color-primary);
  color: #fff;
}
</style>
