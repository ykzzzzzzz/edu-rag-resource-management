<template>
  <div class="load-error">
    <el-alert :title="message" type="error" show-icon :closable="false" />
    <el-button class="retry" :loading="loading" @click="emit('retry')">重试</el-button>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  message: string
  loading?: boolean
}>()

const emit = defineEmits<{ retry: [] }>()
</script>

<style scoped>
.load-error {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.load-error :deep(.el-alert) {
  flex: 1 1 280px;
  width: auto;
}

.retry {
  flex: none;
}
</style>
