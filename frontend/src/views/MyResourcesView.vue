<template>
  <div class="page">
    <div class="page-head">
      <h2 class="page-title">我的资源</h2>
      <el-button type="primary" @click="openCreate">上传资源</el-button>
    </div>

    <el-card shadow="never">
      <el-form class="filters" inline @submit.prevent="onSearch">
        <el-form-item label="审核状态">
          <el-select v-model="reviewStatus" clearable placeholder="全部" @change="onSearch">
            <el-option
              v-for="option in REVIEW_STATUS_OPTIONS"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button :loading="loading" native-type="submit">刷新</el-button>
        </el-form-item>
      </el-form>

      <el-alert
        v-if="courseError"
        class="top-alert"
        type="error"
        show-icon
        :closable="false"
        :title="courseError"
      />
      <el-alert
        v-else-if="coursesLoaded && courses.length === 0"
        class="top-alert"
        type="warning"
        show-icon
        :closable="false"
        title="暂无课程，请联系管理员先创建课程"
      />

      <LoadError v-if="error" :message="error" :loading="loading" @retry="load" />

      <template v-else>
        <el-table v-loading="loading" :data="items" row-key="id" empty-text="还没有资源，点击右上角“上传资源”开始">
          <el-table-column label="标题" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <router-link class="title-link" :to="{ name: 'resource-detail', params: { id: row.id } }">
                {{ row.title }}
              </router-link>
            </template>
          </el-table-column>
          <el-table-column prop="course_name" label="课程" min-width="120" show-overflow-tooltip />
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
          <el-table-column label="驳回原因 / 索引错误" min-width="200">
            <template #default="{ row }">
              <div v-if="row.review_reason" class="note note-danger">驳回原因：{{ row.review_reason }}</div>
              <div v-if="row.index_error" class="note note-danger">索引错误：{{ row.index_error }}</div>
              <span v-if="!row.review_reason && !row.index_error" class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="更新时间" width="150">
            <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="200" fixed="right">
            <template #default="{ row }">
              <div class="actions">
                <el-button v-if="row.review_status === 'draft'" link type="primary" size="small" @click="openEdit(row)">
                  编辑
                </el-button>
                <el-button
                  v-if="row.review_status === 'draft'"
                  link
                  type="primary"
                  size="small"
                  :loading="busy[row.id]"
                  @click="submitForReview(row)"
                >
                  提交审核
                </el-button>
                <el-button
                  v-if="row.review_status === 'rejected'"
                  link
                  type="warning"
                  size="small"
                  :loading="busy[row.id]"
                  @click="revise(row)"
                >
                  退回修改
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

    <ResourceFormDialog
      v-model="dialogVisible"
      :mode="dialogMode"
      :resource="editing"
      :courses="courses"
      :courses-error="courseError"
      @saved="onSaved"
      @stale="load"
    />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import type { Resource, ReviewStatus } from '../api'
import DownloadLink from '../components/DownloadLink.vue'
import LoadError from '../components/LoadError.vue'
import ResourceFormDialog from '../components/ResourceFormDialog.vue'
import ResourceStatusTag from '../components/ResourceStatusTag.vue'
import { useCourses } from '../composables/useCourses'
import { PAGE_SIZE_OPTIONS, usePagedResources } from '../composables/usePagedResources'
import { useRowAction } from '../composables/useRowAction'
import { REVIEW_STATUS_OPTIONS, formatDateTime, formatSize } from '../utils/resource'

const reviewStatus = ref<ReviewStatus | ''>('')

const { items, total, page, pageSize, loading, error, load, search, changePage, changePageSize } =
  usePagedResources((p, size) =>
    api.listMyResources({
      review_status: reviewStatus.value || undefined,
      page: p,
      page_size: size,
    }),
  )

const { courses, error: courseError, loaded: coursesLoaded, loadCourses } = useCourses()
const { busy, run } = useRowAction(load)

const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const editing = ref<Resource | null>(null)

function onSearch(): void {
  void search()
}

function openCreate(): void {
  dialogMode.value = 'create'
  editing.value = null
  dialogVisible.value = true
}

function openEdit(row: Resource): void {
  dialogMode.value = 'edit'
  editing.value = row
  dialogVisible.value = true
}

function onSaved(): void {
  // 新上传的草稿排在最前，回到第一页才能看到。
  if (dialogMode.value === 'create') {
    void search()
  } else {
    void load()
  }
}

function submitForReview(row: Resource): Promise<unknown> {
  return run(row.id, () => api.submitResource(row.id), '已提交审核，请等待管理员审核', '提交审核失败，请稍后重试。')
}

function revise(row: Resource): Promise<unknown> {
  return run(row.id, () => api.reviseResource(row.id), '已退回草稿，可以修改后重新提交', '退回修改失败，请稍后重试。')
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

.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.page-title {
  margin: 0;
  font-size: 20px;
}

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0 8px;
}

.top-alert {
  margin-bottom: 12px;
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

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
  overflow-x: auto;
}
</style>
