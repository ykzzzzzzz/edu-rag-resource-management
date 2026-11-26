<template>
  <el-tag size="small" :type="tagType" effect="light">{{ label }}</el-tag>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { IndexStatus, ReviewStatus } from '../api'
import { INDEX_STATUS_LABELS, REVIEW_STATUS_LABELS } from '../utils/resource'

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

const props = defineProps<{
  kind: 'review' | 'index'
  value: ReviewStatus | IndexStatus
}>()

const REVIEW_TYPES: Record<ReviewStatus, TagType> = {
  draft: 'info',
  pending: 'warning',
  published: 'success',
  rejected: 'danger',
  archived: 'info',
}

const INDEX_TYPES: Record<IndexStatus, TagType> = {
  not_indexed: 'info',
  queued: 'warning',
  processing: 'primary',
  ready: 'success',
  failed: 'danger',
}

const label = computed(() =>
  props.kind === 'review'
    ? (REVIEW_STATUS_LABELS[props.value as ReviewStatus] ?? props.value)
    : (INDEX_STATUS_LABELS[props.value as IndexStatus] ?? props.value),
)

const tagType = computed<TagType>(() =>
  props.kind === 'review'
    ? (REVIEW_TYPES[props.value as ReviewStatus] ?? 'info')
    : (INDEX_TYPES[props.value as IndexStatus] ?? 'info'),
)
</script>
