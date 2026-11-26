<template>
  <div class="page">
    <div class="page-head">
      <router-link class="back" to="/resources">&larr; 返回资源浏览</router-link>
    </div>

    <el-skeleton v-if="loading && !resource" :rows="6" animated />

    <el-result v-else-if="notFound" icon="warning" title="资源不存在或无权查看">
      <template #extra>
        <el-button type="primary" @click="router.push('/resources')">返回资源浏览</el-button>
      </template>
    </el-result>

    <LoadError v-else-if="error" :message="error" :loading="loading" @retry="load" />

    <el-card v-else-if="resource" shadow="never">
      <template #header>
        <div class="card-head">
          <h2 class="resource-title">{{ resource.title }}</h2>
          <DownloadLink :resource="resource" variant="button" />
        </div>
      </template>

      <el-alert
        v-if="resource.review_status === 'published' && resource.index_status !== 'ready'"
        class="qa-hint"
        type="info"
        show-icon
        :closable="false"
        title="该资料暂不可用于问答，仍可浏览并下载原件。"
      />

      <el-descriptions :column="1" border class="meta">
        <el-descriptions-item label="课程">{{ resource.course_name }}</el-descriptions-item>
        <el-descriptions-item label="上传者">{{ resource.owner_name }}</el-descriptions-item>
        <el-descriptions-item label="文件名">{{ resource.original_filename }}</el-descriptions-item>
        <el-descriptions-item label="文件大小">{{ formatSize(resource.size_bytes) }}</el-descriptions-item>
        <el-descriptions-item label="发布时间">{{ formatDateTime(resource.published_at) }}</el-descriptions-item>
        <el-descriptions-item label="描述">
          <span class="description">{{ resource.description || '暂无描述' }}</span>
        </el-descriptions-item>
      </el-descriptions>

      <template v-if="internal">
        <h3 class="section-title">处理状态</h3>
        <el-descriptions :column="1" border class="meta">
          <el-descriptions-item label="审核状态">
            <ResourceStatusTag kind="review" :value="resource.review_status" />
          </el-descriptions-item>
          <el-descriptions-item v-if="resource.review_reason" label="驳回原因">
            <span class="description">{{ resource.review_reason }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="索引状态">
            <ResourceStatusTag kind="index" :value="resource.index_status" />
          </el-descriptions-item>
          <el-descriptions-item v-if="resource.index_error" label="索引错误">
            <span class="description">{{ resource.index_error }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatDateTime(resource.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="更新时间">{{ formatDateTime(resource.updated_at) }}</el-descriptions-item>
        </el-descriptions>
        <div v-if="isOwnerTeacher" class="more">
          <router-link to="/my-resources">前往“我的资源”管理</router-link>
        </div>
      </template>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import type { Resource } from '../api'
import DownloadLink from '../components/DownloadLink.vue'
import LoadError from '../components/LoadError.vue'
import ResourceStatusTag from '../components/ResourceStatusTag.vue'
import { useApiError } from '../composables/useApiError'
import { session } from '../stores/session'
import { canSeeInternalStatus, formatDateTime, formatSize } from '../utils/resource'

const route = useRoute()
const router = useRouter()
const { handle } = useApiError()

const resource = ref<Resource | null>(null)
const loading = ref(false)
const error = ref('')
const notFound = ref(false)
let token = 0

const resourceId = computed(() => String(route.params.id ?? ''))

// 审核、索引状态与驳回原因、索引错误仅所有者和管理员可见，其他角色一律不渲染。
const internal = computed(() => resource.value !== null && canSeeInternalStatus(session.user.value, resource.value))
const isOwnerTeacher = computed(
  () => session.user.value?.role === 'teacher' && resource.value?.owner_id === session.user.value.id,
)

async function load(): Promise<void> {
  const mine = ++token
  loading.value = true
  error.value = ''
  notFound.value = false
  try {
    const result = await api.getResource(resourceId.value)
    if (mine !== token) return
    resource.value = result
  } catch (e) {
    const described = await handle(e, '资源加载失败，请稍后重试。')
    if (mine !== token) return
    resource.value = null
    if (described.status === 404) {
      notFound.value = true
    } else {
      error.value = described.message
    }
  } finally {
    if (mine === token) loading.value = false
  }
}

watch(resourceId, () => {
  resource.value = null
  void load()
})

onMounted(load)
</script>

<style scoped>
.page {
  min-width: 0;
  max-width: 900px;
}

.page-head {
  margin-bottom: 12px;
}

.back {
  color: var(--el-color-primary);
  text-decoration: none;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.resource-title {
  margin: 0;
  font-size: 20px;
  overflow-wrap: anywhere;
}

.qa-hint {
  margin-bottom: 16px;
}

.section-title {
  margin: 24px 0 12px;
  font-size: 16px;
}

.description {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.more {
  margin-top: 12px;
}

.meta :deep(.el-descriptions__label) {
  width: 110px;
}

.meta :deep(.el-descriptions__content) {
  overflow-wrap: anywhere;
}
</style>
