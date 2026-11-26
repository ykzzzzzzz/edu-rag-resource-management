<template>
  <div class="page">
    <h2 class="page-title">资源浏览</h2>

    <el-card shadow="never">
      <el-form class="filters" inline @submit.prevent="onSearch">
        <el-form-item label="关键词">
          <el-input
            v-model="form.q"
            clearable
            maxlength="100"
            placeholder="标题或描述"
            @keyup.enter="onSearch"
            @clear="onSearch"
          />
        </el-form-item>
        <el-form-item label="课程">
          <el-select
            v-model="form.courseId"
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
          <el-table-column prop="course_name" label="课程" min-width="120" show-overflow-tooltip />
          <el-table-column prop="owner_name" label="上传者" min-width="100" show-overflow-tooltip />
          <el-table-column prop="original_filename" label="文件名" min-width="180" show-overflow-tooltip />
          <el-table-column label="大小" width="90">
            <template #default="{ row }">{{ formatSize(row.size_bytes) }}</template>
          </el-table-column>
          <el-table-column label="发布时间" width="150">
            <template #default="{ row }">{{ formatDateTime(row.published_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="80" fixed="right">
            <template #default="{ row }">
              <DownloadLink :resource="row" />
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
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive } from 'vue'
import { api } from '../api'
import DownloadLink from '../components/DownloadLink.vue'
import LoadError from '../components/LoadError.vue'
import { PAGE_SIZE_OPTIONS, usePagedResources } from '../composables/usePagedResources'
import { useCourses } from '../composables/useCourses'
import { formatDateTime, formatSize } from '../utils/resource'

const form = reactive({ q: '', courseId: '' })
// 已生效的筛选条件：翻页时沿用上次点击“查询”时的条件，而不是输入框里尚未提交的内容。
const applied = reactive({ q: '', courseId: '' })

const { items, total, page, pageSize, loading, error, load, search, changePage, changePageSize } =
  usePagedResources((p, size) =>
    api.listResources({
      q: applied.q || undefined,
      course_id: applied.courseId || undefined,
      page: p,
      page_size: size,
    }),
  )

const { courses, loading: coursesLoading, error: courseError, loadCourses } = useCourses()

function onSearch(): void {
  applied.q = form.q.trim()
  applied.courseId = form.courseId || ''
  void search()
}

function onReset(): void {
  form.q = ''
  form.courseId = ''
  onSearch()
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

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
  overflow-x: auto;
}
</style>
