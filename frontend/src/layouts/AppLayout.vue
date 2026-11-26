<template>
  <el-container class="app-layout">
    <el-header class="app-header">
      <div class="brand">教育资源管理系统</div>
      <div class="header-right">
        <span class="user-info">
          {{ user?.display_name || user?.username }}
          <el-tag size="small" effect="plain">{{ roleLabel }}</el-tag>
        </span>
        <el-tag size="small" :type="modeTagType" effect="plain">{{ modeLabel }}</el-tag>
        <el-button size="small" :loading="loggingOut" @click="logout">退出</el-button>
      </div>
    </el-header>

    <el-container>
      <el-aside width="200px" class="app-aside">
        <el-menu :default-active="activePath" router>
          <el-menu-item index="/">首页</el-menu-item>
          <el-menu-item v-for="item in menuItems" :key="item.path" :index="item.path">
            {{ item.title }}
          </el-menu-item>
        </el-menu>
      </el-aside>

      <el-main class="app-main">
        <RouterView />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { NAV_ITEMS, ROLE_LABELS } from '../config/navigation'
import { session } from '../stores/session'

const router = useRouter()
const route = useRoute()
const loggingOut = ref(false)

const user = session.user
const roleLabel = computed(() => (user.value ? ROLE_LABELS[user.value.role] : ''))

const menuItems = computed(() =>
  NAV_ITEMS.filter((item) => user.value !== null && item.roles.includes(user.value.role)),
)

const activePath = computed(() => route.path)

const modeLabel = computed(() => {
  switch (session.qaMode.value) {
    case 'demo':
      return '资料摘录演示'
    case 'cloud':
      return '云端生成'
    default:
      return '模式未知'
  }
})

const modeTagType = computed(() => (session.qaMode.value === null ? 'info' : 'success'))

onMounted(() => {
  void session.loadQaMode()
})

async function logout(): Promise<void> {
  loggingOut.value = true
  try {
    await session.logout()
    await router.replace({ name: 'login' })
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '退出失败，请稍后重试。')
  } finally {
    loggingOut.value = false
  }
}
</script>

<style scoped>
.app-layout {
  height: 100%;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  background: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color-light);
  padding: 0 16px;
  flex-wrap: wrap;
  height: auto;
  min-height: 56px;
}

.brand {
  font-size: 16px;
  font-weight: 600;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.user-info {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.app-aside {
  background: var(--el-bg-color);
  border-right: 1px solid var(--el-border-color-light);
}

.app-aside :deep(.el-menu) {
  border-right: none;
}

.app-main {
  padding: 24px;
}

@media (max-width: 768px) {
  .app-aside {
    width: 160px !important;
  }
}
</style>
