<template>
  <el-empty description="建设中">
    <template #description>
      <p class="placeholder-title">{{ title }}</p>
      <p class="placeholder-text">该功能页面尚未实现，当前仅保留路由与菜单。</p>
    </template>
  </el-empty>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const title = computed(() => (typeof route.meta.title === 'string' ? route.meta.title : '页面'))
</script>

<style scoped>
.placeholder-title {
  margin: 0;
  font-size: 16px;
  color: var(--text-primary);
}

.placeholder-text {
  margin: 4px 0 0;
  color: var(--text-secondary);
}
</style>
