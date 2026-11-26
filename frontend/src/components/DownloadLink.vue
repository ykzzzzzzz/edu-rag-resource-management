<template>
  <template v-if="allowed">
    <el-button
      type="primary"
      :link="variant === 'link'"
      :size="variant === 'link' ? 'small' : 'default'"
      tag="a"
      :href="url"
      target="_blank"
      rel="noopener"
    >
      {{ variant === 'button' ? '下载原件' : '下载' }}
    </el-button>
  </template>
  <span v-else class="download-unavailable">不提供下载</span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { resourceDownloadUrl } from '../api'
import type { Resource } from '../api'
import { session } from '../stores/session'
import { canDownload } from '../utils/resource'

const props = withDefaults(
  defineProps<{
    resource: Resource
    /** 详情页使用按钮样式，列表中使用文字按钮。 */
    variant?: 'button' | 'link'
  }>(),
  { variant: 'link' },
)

const allowed = computed(() => canDownload(session.user.value, props.resource))

// 同源直链：会话 Cookie 自动携带，文件名由服务端的 Content-Disposition 决定。
// 在新标签页打开，服务端若返回错误 JSON 也不会让当前页面离开。
const url = computed(() => resourceDownloadUrl(props.resource.id))
</script>

<style scoped>
.download-unavailable {
  color: var(--text-secondary);
  font-size: 13px;
}
</style>
