<template>
  <div class="page">
    <h2 class="page-title">问答日志</h2>

    <el-card shadow="never">
      <el-form class="filters" inline @submit.prevent="onSearch">
        <el-form-item label="状态">
          <el-select v-model="filters.status" clearable placeholder="全部" @change="onSearch">
            <el-option v-for="option in QA_LOG_STATUS_OPTIONS" :key="option.value" :label="option.label" :value="option.value" />
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
        <el-form-item label="日期">
          <el-date-picker
            v-model="filters.dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            :disabled-date="disableFuture"
            @change="onSearch"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit" :loading="loading">查询</el-button>
          <el-button :disabled="loading" @click="onReset">重置</el-button>
        </el-form-item>
      </el-form>

      <p class="privacy-note">日志为匿名记录，不含用户标识。</p>

      <LoadError v-if="error" :message="error" :loading="loading" @retry="load" />

      <template v-else>
        <el-table v-loading="loading" :data="items" row-key="id" empty-text="没有符合条件的问答日志">
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="detail">
                <h4 class="detail-title">回答</h4>
                <p v-if="row.answer" class="detail-text">{{ row.answer }}</p>
                <p v-else class="muted">无回答内容</p>

                <h4 class="detail-title">命中片段（{{ row.retrieved.length }}）</h4>
                <el-table v-if="row.retrieved.length > 0" :data="row.retrieved" size="small" border>
                  <el-table-column prop="rank" label="排名" width="70" />
                  <el-table-column label="相似度" width="100">
                    <template #default="{ row: hit }">{{ formatSimilarity(hit.similarity) }}</template>
                  </el-table-column>
                  <el-table-column label="是否被引用" width="110">
                    <template #default="{ row: hit }">{{ row.cited_chunk_ids.includes(hit.chunk_id) ? '是' : '否' }}</template>
                  </el-table-column>
                  <el-table-column prop="chunk_id" label="片段 ID" min-width="220" show-overflow-tooltip />
                  <el-table-column prop="resource_id" label="资源 ID" min-width="220" show-overflow-tooltip />
                </el-table>
                <p v-else class="muted">没有命中片段</p>

                <h4 class="detail-title">各阶段耗时</h4>
                <el-descriptions :column="3" border size="small">
                  <el-descriptions-item label="检索">{{ formatMs(row.timings.retrieval_ms) }}</el-descriptions-item>
                  <el-descriptions-item label="生成">{{ formatMs(row.timings.generation_ms) }}</el-descriptions-item>
                  <el-descriptions-item label="总计">{{ formatMs(row.timings.total_ms) }}</el-descriptions-item>
                </el-descriptions>

                <h4 class="detail-title">模型配置</h4>
                <el-descriptions v-if="configEntries(row).length > 0" :column="1" border size="small">
                  <el-descriptions-item v-for="[key, value] in configEntries(row)" :key="key" :label="key">
                    <span class="detail-text">{{ value }}</span>
                  </el-descriptions-item>
                </el-descriptions>
                <p v-else class="muted">无模型配置记录</p>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="时间" width="150">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="课程" min-width="110" show-overflow-tooltip>
            <template #default="{ row }">{{ row.course_name || '全部课程' }}</template>
          </el-table-column>
          <el-table-column prop="question" label="问题" min-width="240" show-overflow-tooltip />
          <el-table-column label="状态" width="130">
            <template #default="{ row }">
              <el-tag size="small" effect="light" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="命中片段" width="90" align="right">
            <template #default="{ row }">{{ row.retrieved.length }}</template>
          </el-table-column>
          <el-table-column label="引用数" width="80" align="right">
            <template #default="{ row }">{{ row.cited_chunk_ids.length }}</template>
          </el-table-column>
          <el-table-column label="总耗时" width="100" align="right">
            <template #default="{ row }">{{ formatMs(row.timings.total_ms) }}</template>
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
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive } from 'vue'
import { api } from '../api'
import type { QaLogItem, QaLogStatus } from '../api'
import LoadError from '../components/LoadError.vue'
import { useCourses } from '../composables/useCourses'
import { usePagedList } from '../composables/usePagedList'
import { PAGE_SIZE_OPTIONS } from '../composables/usePagedResources'
import {
  QA_LOG_STATUS_LABELS,
  QA_LOG_STATUS_OPTIONS,
  QA_LOG_STATUS_TAG_TYPES,
  formatConfigValue,
  formatMs,
} from '../utils/qa'
import { formatDateTime } from '../utils/resource'

interface Filters {
  status: QaLogStatus | ''
  courseId: string
  /** [开始, 结束]，YYYY-MM-DD；清空时为 null。 */
  dateRange: [string, string] | null
}

const filters = reactive<Filters>({ status: '', courseId: '', dateRange: null })

const { items, total, page, pageSize, loading, error, load, search, changePage, changePageSize } = usePagedList<QaLogItem>(
  (p, size) =>
    api.listQaLogs({
      status: filters.status || undefined,
      course_id: filters.courseId || undefined,
      date_from: filters.dateRange?.[0],
      date_to: filters.dateRange?.[1],
      page: p,
      page_size: size,
    }),
)

const { courses, loading: coursesLoading, error: courseError, loadCourses } = useCourses()

function onSearch(): void {
  void search()
}

function onReset(): void {
  filters.status = ''
  filters.courseId = ''
  filters.dateRange = null
  void search()
}

function disableFuture(date: Date): boolean {
  return date.getTime() > Date.now()
}

// 后端枚举扩展时，未知状态直接显示原始值。
function statusLabel(status: QaLogStatus): string {
  return QA_LOG_STATUS_LABELS[status] ?? status
}

function statusType(status: QaLogStatus): 'success' | 'warning' | 'danger' | 'info' {
  return QA_LOG_STATUS_TAG_TYPES[status] ?? 'info'
}

function formatSimilarity(value: number): string {
  return Number.isFinite(value) ? value.toFixed(3) : '-'
}

/** 模型配置转成键值对；值一律转成文本后插值渲染。 */
function configEntries(row: QaLogItem): [string, string][] {
  return Object.entries(row.model_config ?? {}).map(([key, value]) => [key, formatConfigValue(value)])
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

.privacy-note {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--text-secondary);
}

.detail {
  padding: 4px 16px 12px 48px;
}

.detail-title {
  margin: 12px 0 8px;
  font-size: 14px;
}

.detail-title:first-child {
  margin-top: 0;
}

.detail-text {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.muted {
  margin: 0;
  color: var(--text-secondary);
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
  overflow-x: auto;
}
</style>
