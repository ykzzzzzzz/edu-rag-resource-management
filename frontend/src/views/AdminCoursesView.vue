<template>
  <div class="page">
    <div class="page-head">
      <h2 class="page-title">课程管理</h2>
      <el-button type="primary" @click="openCreate">新建课程</el-button>
    </div>

    <el-card shadow="never">
      <LoadError v-if="error" :message="error" :loading="loading" @retry="load" />

      <el-table
        v-else
        v-loading="loading"
        :data="courses"
        row-key="id"
        empty-text="还没有课程，点击右上角“新建课程”开始"
      >
        <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip />
        <el-table-column label="描述" min-width="240">
          <template #default="{ row }">
            <span v-if="row.description" class="desc">{{ row.description }}</span>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="150">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <CourseFormDialog v-model="formVisible" :mode="formMode" :course="formTarget" @saved="load" @stale="load" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import type { Course } from '../api'
import CourseFormDialog from '../components/CourseFormDialog.vue'
import LoadError from '../components/LoadError.vue'
import { useApiError } from '../composables/useApiError'
import { formatDateTime } from '../utils/resource'

const { handle } = useApiError()

// 后端 GET /courses 不分页，按名称排序返回全部课程。
const courses = ref<Course[]>([])
const loading = ref(false)
const error = ref('')
let token = 0

async function load(): Promise<void> {
  const mine = ++token
  loading.value = true
  error.value = ''
  try {
    const result = await api.listCourses()
    if (mine !== token) return
    courses.value = result.items
  } catch (e) {
    const described = await handle(e, '课程列表加载失败，请稍后重试。')
    if (mine !== token) return
    courses.value = []
    error.value = described.message
  } finally {
    if (mine === token) loading.value = false
  }
}

const formVisible = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const formTarget = ref<Course | null>(null)

function openCreate(): void {
  formMode.value = 'create'
  formTarget.value = null
  formVisible.value = true
}

function openEdit(row: Course): void {
  formMode.value = 'edit'
  formTarget.value = row
  formVisible.value = true
}

onMounted(() => {
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

.desc {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.muted {
  color: var(--text-secondary);
}
</style>
