<template>
  <el-card shadow="never">
    <h2 class="welcome">欢迎，{{ user?.display_name || user?.username }}</h2>
    <p class="hint">请从左侧菜单选择功能。当前为骨架版本，多数功能页面仍在建设中。</p>
  </el-card>
</template>

<script setup lang="ts">
import { session } from '../stores/session'

const user = session.user
</script>

<style scoped>
.welcome {
  margin: 0 0 8px;
  font-size: 20px;
}

.hint {
  margin: 0;
  color: var(--text-secondary);
}
</style>
