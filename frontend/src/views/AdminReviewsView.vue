<template>
  <div class="page">
    <h2 class="page-title">审核管理</h2>

    <el-card shadow="never">
      <el-form class="filters" inline @submit.prevent="onSearch">
        <el-form-item label="审核状态">
          <el-select v-model="filters.reviewStatus" clearable placeholder="全部" @change="onSearch">
            <el-option
              v-for="option in REVIEW_STATUS_OPTIONS"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="索引状态">
          <el-select v-model="filters.indexStatus" clearable placeholder="全部" @change="onSearch">
            <el-option
              v-for="option in INDEX_STATUS_OPTIONS"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="课程">
          <el-select
            v-model="filters.courseId"
            clearable
            filterable
            placeholder="全部课程"
            :loading="coursesLoading"
            :no-data-text="courseError || '暂无课程'"
            @change="onSearch"
          >
            <el-option v-for="course in courses" :key="course.id" :label="course.name" :value="course.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit" :loading="loading">查询</el-button>
          <el-button :disabled="loading" @click="onReset">重置</el-button>
        </el-form-item>
      </el-form>

      <LoadError v-if="error" :message="error" :loading="loading" @retry="load" />

      <template v-else>
        <el-table v-loading="loading" :data="items" row-key="id" empty-text="没有符合条件的资源">
          <el-table-column label="标题" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <router-link class="title-link" :to="{ name: 'resource-detail', params: { id: row.id } }">
                {{ row.title }}
              </router-link>
            </template>
          </el-table-column>
          <el-table-column prop="course_name" label="课程" min-width="110" show-overflow-tooltip />
          <el-table-column prop="owner_name" label="上传者" min-width="90" show-overflow-tooltip />
          <el-table-column prop="original_filename" label="文件名" min-width="160" show-overflow-tooltip />
          <el-table-column label="大小" width="90">
            <template #default="{ row }">{{ formatSize(row.size_bytes) }}</template>
          </el-table-column>
          <el-table-column label="审核状态" width="100">
            <template #default="{ row }">
              <ResourceStatusTag kind="review" :value="row.review_status" />
            </template>
          </el-table-column>
          <el-table-column label="索引状态" width="120">
            <template #default="{ row }">
              <ResourceStatusTag kind="index" :value="row.index_status" />
            </template>
          </el-table-column>
          <el-table-column label="驳回原因 / 索引错误" min-width="180">
            <template #default="{ row }">
              <div v-if="row.review_reason" class="note note-danger">驳回原因：{{ row.review_reason }}</div>
              <div v-if="row.index_error" class="note note-danger">索引错误：{{ row.index_error }}</div>
              <span v-if="!row.review_reason && !row.index_error" class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="更新时间" width="150">
            <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="190" fixed="right">
            <template #default="{ row }">
              <div class="actions">
                <template v-if="row.review_status === 'pending'">
                  <el-button
                    link
                    type="success"
                    size="small"
                    :loading="busy[row.id]"
                    @click="approve(row)"
                  >
                    通过
                  </el-button>
                  <el-button link type="danger" size="small" :disabled="busy[row.id]" @click="openReject(row)">
                    驳回
                  </el-button>
                </template>
                <el-button
                  v-if="row.review_status === 'published'"
                  link
                  type="danger"
                  size="small"
                  :loading="busy[row.id]"
                  @click="archive(row)"
                >
                  下架
                </el-button>
                <el-button
                  v-if="row.review_status === 'published' && row.index_status === 'failed'"
                  link
                  type="primary"
                  size="small"
                  :loading="busy[row.id]"
                  @click="retryIndex(row)"
                >
                  重试索引
                </el-button>
                <DownloadLink :resource="row" />
              </div>
            </template>
          </el-table-column>
        </el-table>

        <div class="pager">
          <el-pagination
            background
            layout="total, sizes, prev, pager, next"
            :total="total"
            :current-page="page"
            :page-size="pageSize"
            :page-sizes="PAGE_SIZE_OPTIONS"
            :disabled="loading"
            @current-change="changePage"
            @size-change="changePageSize"
          />
        </div>
      </template>
    </el-card>

    <el-dialog
      v-model="rejectVisible"
      title="驳回资源"
      width="480px"
      :close-on-click-modal="false"
      :close-on-press-escape="!rejecting"
      :show-close="!rejecting"
      :before-close="beforeRejectClose"
    >
      <p v-if="rejectTarget" class="reject-target">资源：{{ rejectTarget.title }}</p>
      <el-form ref="rejectFormRef" :model="rejectForm" :rules="rejectRules" label-position="top" @submit.prevent="confirmReject">
        <el-form-item label="驳回原因（教师可见）" prop="reason">
          <el-input
            v-model="rejectForm.reason"
            type="textarea"
            :rows="4"
            :maxlength="REASON_MAX_LENGTH"
            show-word-limit
            placeholder="请说明驳回原因，便于教师修改"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="rejecting" @click="rejectVisible = false">取消</el-button>
        <el-button type="danger" :loading="rejecting" :disabled="rejecting" @click="confirmReject">确认驳回</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { api } from '../api'
import type { IndexStatus, Resource, ReviewStatus } from '../api'
import DownloadLink from '../components/DownloadLink.vue'
import LoadError from '../components/LoadError.vue'
import ResourceStatusTag from '../components/ResourceStatusTag.vue'
import { useApiError } from '../composables/useApiError'
import { useCourses } from '../composables/useCourses'
import { PAGE_SIZE_OPTIONS, usePagedResources } from '../composables/usePagedResources'
import { useRowAction } from '../composables/useRowAction'
import {
  INDEX_STATUS_OPTIONS,
  REASON_MAX_LENGTH,
  REVIEW_STATUS_OPTIONS,
  formatDateTime,
  formatSize,
} from '../utils/resource'

interface Filters {
  reviewStatus: ReviewStatus | ''
  indexStatus: IndexStatus | ''
  courseId: string
}

// 默认只看待审核，管理员进入页面即可处理积压；清空筛选可看全部。
const filters = reactive<Filters>({ reviewStatus: 'pending', indexStatus: '', courseId: '' })

const { items, total, page, pageSize, loading, error, load, search, changePage, changePageSize } =
  usePagedResources((p, size) =>
    api.listAdminResources({
      review_status: filters.reviewStatus || undefined,
      index_status: filters.indexStatus || undefined,
      course_id: filters.courseId || undefined,
      page: p,
      page_size: size,
    }),
  )

const { courses, loading: coursesLoading, error: courseError, loadCourses } = useCourses()
const { handle } = useApiError()
const { busy, run } = useRowAction(load)

function onSearch(): void {
  void search()
}

function onReset(): void {
  filters.reviewStatus = ''
  filters.indexStatus = ''
  filters.courseId = ''
  void search()
}

function approve(row: Resource): Promise<unknown> {
  return run(
    row.id,
    () => api.reviewResource(row.id, { action: 'approve' }),
    '已通过审核，资源已发布并进入索引队列',
    '审核失败，请稍后重试。',
  )
}

async function archive(row: Resource): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `下架“${row.title}”后，学生将立即看不到该资源，也无法下载或在问答中引用。确定下架吗？`,
      '确认下架',
      { type: 'warning', confirmButtonText: '确认下架', cancelButtonText: '取消', autofocus: false },
    )
  } catch {
    return
  }
  await run(row.id, () => api.archiveResource(row.id), '资源已下架', '下架失败，请稍后重试。')
}

function retryIndex(row: Resource): Promise<unknown> {
  return run(
    row.id,
    () => api.retryResourceIndex(row.id),
    '已重新加入索引队列',
    '重试索引失败，请稍后重试。',
  )
}

// ---- 驳回对话框 ----
const rejectVisible = ref(false)
const rejecting = ref(false)
const rejectTarget = ref<Resource | null>(null)
const rejectFormRef = ref<FormInstance>()
const rejectForm = reactive({ reason: '' })

const rejectRules: FormRules = {
  reason: [
    {
      validator: (_rule, value: string, callback) => {
        const text = (value ?? '').trim()
        if (!text) callback(new Error('请填写驳回原因'))
        else if (text.length > REASON_MAX_LENGTH) callback(new Error(`原因不能超过 ${REASON_MAX_LENGTH} 个字符`))
        else callback()
      },
      trigger: ['blur', 'change'],
    },
  ],
}

function openReject(row: Resource): void {
  rejectTarget.value = row
  rejectForm.reason = ''
  rejectVisible.value = true
  rejectFormRef.value?.clearValidate()
}

function beforeRejectClose(done: () => void): void {
  if (!rejecting.value) done()
}

async function confirmReject(): Promise<void> {
  if (rejecting.value || !rejectTarget.value) return
  const valid = await rejectFormRef.value?.validate().catch(() => false)
  if (!valid) return

  const target = rejectTarget.value
  rejecting.value = true
  let refresh = false
  try {
    await api.reviewResource(target.id, { action: 'reject', reason: rejectForm.reason.trim() })
    ElMessage.success('已驳回，教师可在“我的资源”中查看原因')
    rejectVisible.value = false
    refresh = true
  } catch (e) {
    const described = await handle(e, '驳回失败，请稍后重试。')
    if (described.status === 404 || described.status === 409) {
      ElMessage.error(`${described.message}（列表已刷新）`)
      rejectVisible.value = false
      refresh = true
    } else {
      ElMessage.error(described.message)
    }
  } finally {
    rejecting.value = false
  }
  if (refresh) await load()
}

onMounted(() => {
  void loadCourses()
  void load()
})
</script>

<style scoped>
.page {
  min-width: 0;
}

.page-title {
  margin: 0 0 16px;
  font-size: 20px;
}

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0 8px;
}

.title-link {
  color: var(--el-color-primary);
  text-decoration: none;
}

.title-link:hover {
  text-decoration: underline;
}

.note {
  font-size: 13px;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.note-danger {
  color: var(--el-color-danger);
}

.muted {
  color: var(--text-secondary);
}

.actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 8px;
}

.actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.reject-target {
  margin: 0 0 12px;
  overflow-wrap: anywhere;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
  overflow-x: auto;
}
</style>
