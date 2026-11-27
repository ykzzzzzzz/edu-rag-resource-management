<template>
  <div class="page">
    <div class="page-head">
      <h2 class="page-title">用户管理</h2>
      <el-button type="primary" @click="openCreate">新建账号</el-button>
    </div>

    <el-card shadow="never">
      <el-form class="filters" inline @submit.prevent="onSearch">
        <el-form-item label="角色">
          <el-select v-model="filters.role" clearable placeholder="全部" @change="onSearch">
            <el-option v-for="option in ROLE_OPTIONS" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.status" clearable placeholder="全部" @change="onSearch">
            <el-option label="启用" value="active" />
            <el-option label="停用" value="disabled" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit" :loading="loading">查询</el-button>
          <el-button :disabled="loading" @click="onReset">重置</el-button>
        </el-form-item>
      </el-form>

      <LoadError v-if="error" :message="error" :loading="loading" @retry="load" />

      <template v-else>
        <el-table v-loading="loading" :data="pageItems" row-key="id" empty-text="没有符合条件的账号">
          <el-table-column label="用户名" min-width="140" show-overflow-tooltip>
            <template #default="{ row }">
              <span>{{ row.username }}</span>
              <el-tag v-if="isSelf(row)" class="self-tag" size="small" type="warning" effect="plain">当前账号</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="display_name" label="显示名" min-width="120" show-overflow-tooltip />
          <el-table-column label="角色" width="90">
            <template #default="{ row }">{{ ROLE_LABELS[row.role as Role] }}</template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
                {{ row.is_active ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="创建时间" width="150">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="220" fixed="right">
            <template #default="{ row }">
              <div class="actions">
                <el-button link type="primary" size="small" :disabled="busy[row.id]" @click="openEdit(row)">
                  编辑
                </el-button>
                <el-button link type="primary" size="small" :disabled="busy[row.id]" @click="openReset(row)">
                  重置密码
                </el-button>
                <el-button
                  v-if="row.is_active"
                  link
                  type="danger"
                  size="small"
                  :loading="busy[row.id]"
                  @click="disable(row)"
                >
                  停用
                </el-button>
                <el-button v-else link type="success" size="small" :loading="busy[row.id]" @click="enable(row)">
                  启用
                </el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>

        <div class="pager">
          <el-pagination
            background
            layout="total, sizes, prev, pager, next"
            :total="items.length"
            :current-page="page"
            :page-size="pageSize"
            :page-sizes="PAGE_SIZE_OPTIONS"
            :disabled="loading"
            @current-change="page = $event"
            @size-change="onSizeChange"
          />
        </div>
      </template>
    </el-card>

    <UserFormDialog
      v-model="formVisible"
      :mode="formMode"
      :user="formTarget"
      @saved="onSaved"
      @stale="onStale"
    />
    <ResetPasswordDialog v-model="resetVisible" :user="resetTarget" @stale="onStale" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import type { AdminUser, AdminUserListQuery, Role } from '../api'
import LoadError from '../components/LoadError.vue'
import ResetPasswordDialog from '../components/ResetPasswordDialog.vue'
import UserFormDialog from '../components/UserFormDialog.vue'
import { PAGE_SIZE_OPTIONS } from '../composables/usePagedResources'
import { useApiError } from '../composables/useApiError'
import { ROLE_LABELS } from '../config/navigation'
import { session } from '../stores/session'
import { ROLE_OPTIONS } from '../utils/admin'
import { formatDateTime } from '../utils/resource'

interface Filters {
  role: Role | ''
  status: 'active' | 'disabled' | ''
}

const router = useRouter()
const { handle } = useApiError()

const filters = reactive<Filters>({ role: '', status: '' })

// 后端 GET /admin/users 不分页，一次返回全部符合条件的账号；这里在前端按页切片。
const items = ref<AdminUser[]>([])
const loading = ref(false)
const error = ref('')
const page = ref(1)
const pageSize = ref(20)
const busy = reactive<Record<string, boolean>>({})
let token = 0

const pageItems = computed(() => items.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))

function isSelf(row: AdminUser): boolean {
  return session.user.value?.id === row.id
}

async function load(): Promise<void> {
  const mine = ++token
  loading.value = true
  error.value = ''
  const query: AdminUserListQuery = {
    role: filters.role || undefined,
    is_active: filters.status === '' ? undefined : filters.status === 'active',
  }
  try {
    const result = await api.listUsers(query)
    if (mine !== token) return
    items.value = result.items
    const lastPage = Math.max(1, Math.ceil(result.items.length / pageSize.value))
    if (page.value > lastPage) page.value = lastPage
  } catch (e) {
    const described = await handle(e, '用户列表加载失败，请稍后重试。')
    if (mine !== token) return
    items.value = []
    error.value = described.message
  } finally {
    if (mine === token) loading.value = false
  }
}

function onSearch(): void {
  page.value = 1
  void load()
}

function onReset(): void {
  filters.role = ''
  filters.status = ''
  onSearch()
}

function onSizeChange(value: number): void {
  pageSize.value = value
  page.value = 1
}

/** 修改的是自己时，同步本地会话里的显示名和角色；角色不再是管理员则离开本页。 */
async function syncSelf(): Promise<void> {
  await session.restore()
  const user = session.user.value
  if (user === null) {
    await router.replace({ name: 'login' })
  } else if (user.role !== 'admin') {
    ElMessage.warning('你已不是管理员，无法继续访问该页面')
    await router.replace('/')
  }
}

// ---- 新建 / 编辑 ----
const formVisible = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const formTarget = ref<AdminUser | null>(null)

function openCreate(): void {
  formMode.value = 'create'
  formTarget.value = null
  formVisible.value = true
}

function openEdit(row: AdminUser): void {
  formMode.value = 'edit'
  formTarget.value = row
  formVisible.value = true
}

async function onSaved(saved: AdminUser): Promise<void> {
  const editedSelf = formMode.value === 'edit' && isSelf(saved)
  await load()
  if (editedSelf) await syncSelf()
}

function onStale(): void {
  void load()
}

// ---- 重置密码 ----
const resetVisible = ref(false)
const resetTarget = ref<AdminUser | null>(null)

function openReset(row: AdminUser): void {
  resetTarget.value = row
  resetVisible.value = true
}

// ---- 启用 / 停用 ----
/** 保护规则（不能停用自己、最后一个管理员等）全部由后端判断，这里只原样显示后端消息。 */
async function toggleActive(row: AdminUser, isActive: boolean, successText: string): Promise<void> {
  if (busy[row.id]) return
  busy[row.id] = true
  let refresh = false
  try {
    await api.updateUser(row.id, { is_active: isActive })
    ElMessage.success(successText)
    refresh = true
  } catch (e) {
    const described = await handle(e, isActive ? '启用失败，请稍后重试。' : '停用失败，请稍后重试。')
    ElMessage.error(described.message)
    if (described.status === 404) refresh = true
  } finally {
    busy[row.id] = false
  }
  if (refresh) await load()
}

async function disable(row: AdminUser): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定停用账号“${row.username}”（${row.display_name}）吗？该账号的登录会话会立即失效。`,
      '确认停用',
      { type: 'warning', confirmButtonText: '确认停用', cancelButtonText: '取消', autofocus: false },
    )
  } catch {
    return
  }
  await toggleActive(row, false, '账号已停用，其登录会话已失效')
}

function enable(row: AdminUser): Promise<void> {
  return toggleActive(row, true, '账号已启用')
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

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0 8px;
}

.self-tag {
  margin-left: 6px;
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
