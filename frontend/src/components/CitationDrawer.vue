<template>
  <el-drawer
    :model-value="modelValue"
    :title="drawerTitle"
    direction="rtl"
    size="min(560px, 100vw)"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-skeleton v-if="loading" :rows="6" animated />

    <el-result v-else-if="unavailable" icon="warning" :title="CITATION_UNAVAILABLE_TEXT">
      <template #sub-title>该出处无法再查看，请回到回答重新提问，或在资源浏览中查找最新资料。</template>
    </el-result>

    <LoadError v-else-if="error" :message="error" :loading="loading" @retry="load" />

    <template v-else-if="detail">
      <el-descriptions :column="1" border class="meta">
        <el-descriptions-item label="标题">{{ detail.title }}</el-descriptions-item>
        <el-descriptions-item label="课程">{{ detail.course_name }}</el-descriptions-item>
        <el-descriptions-item label="文件名">{{ detail.original_filename }}</el-descriptions-item>
        <el-descriptions-item label="位置">{{ formatLocator(detail.locator) }}</el-descriptions-item>
      </el-descriptions>

      <h3 class="section-title">片段内容</h3>
      <pre class="content">{{ detail.content }}</pre>

      <div class="actions">
        <el-button type="primary" @click="openResource">查看资源详情</el-button>
        <!-- 能取到出处说明资料已发布，所有登录角色均可下载；服务端仍会再次校验。 -->
        <el-button tag="a" :href="resourceDownloadUrl(detail.resource_id)" target="_blank" rel="noopener">
          下载原件
        </el-button>
      </div>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, resourceDownloadUrl } from '../api'
import type { CitationDetail } from '../api'
import LoadError from './LoadError.vue'
import { useApiError } from '../composables/useApiError'
import { CITATION_UNAVAILABLE_TEXT, formatLocator } from '../utils/qa'

const props = defineProps<{
  modelValue: boolean
  /** 引用编号，仅用于标题。 */
  number: number | null
  resourceId: string
  chunkId: string
}>()

const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const router = useRouter()
const { handle } = useApiError()

const detail = ref<CitationDetail | null>(null)
const loading = ref(false)
const error = ref('')
const unavailable = ref(false)
let token = 0

const drawerTitle = computed(() => (props.number === null ? '引用出处' : `引用 [${props.number}] 的出处`))

async function load(): Promise<void> {
  const mine = ++token
  loading.value = true
  error.value = ''
  unavailable.value = false
  detail.value = null
  try {
    // 每次打开都重新请求，不使用回答里缓存的摘录：资料可能已在回答之后下架。
    const result = await api.getCitation(props.resourceId, props.chunkId)
    if (mine !== token) return
    detail.value = result
  } catch (e) {
    const described = await handle(e, '出处加载失败，请稍后重试。')
    if (mine !== token) return
    if (described.status === 404) {
      unavailable.value = true
    } else {
      error.value = described.message
    }
  } finally {
    if (mine === token) loading.value = false
  }
}

// 打开或切换到另一个出处时重新请求；关闭时让进行中的请求作废。
watch(
  () => [props.modelValue, props.resourceId, props.chunkId] as const,
  ([visible]) => {
    if (visible) {
      void load()
    } else {
      token += 1
    }
  },
  { immediate: true },
)

function openResource(): void {
  if (!detail.value) return
  const id = detail.value.resource_id
  emit('update:modelValue', false)
  void router.push({ name: 'resource-detail', params: { id } })
}
</script>

<style scoped>
.meta :deep(.el-descriptions__label) {
  width: 80px;
}

.meta :deep(.el-descriptions__content) {
  overflow-wrap: anywhere;
}

.section-title {
  margin: 20px 0 8px;
  font-size: 15px;
}

.content {
  margin: 0;
  padding: 12px;
  max-height: 50vh;
  overflow: auto;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  background: var(--el-fill-color-light);
  font-family: inherit;
  font-size: 14px;
  line-height: 1.8;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
}

.actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
</style>
