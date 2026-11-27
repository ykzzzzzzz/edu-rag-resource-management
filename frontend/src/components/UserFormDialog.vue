<template>
  <el-dialog
    :model-value="modelValue"
    :title="isCreate ? '新建账号' : '编辑账号'"
    width="520px"
    class="user-form-dialog"
    destroy-on-close
    :close-on-click-modal="false"
    :close-on-press-escape="!submitting"
    :show-close="!submitting"
    :before-close="beforeClose"
    @open="onOpen"
    @closed="onClosed"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-alert v-if="errorMessage" class="form-alert" type="error" show-icon :closable="false" :title="errorMessage" />

    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="submit">
      <el-form-item v-if="isCreate" label="用户名" prop="username">
        <el-input
          v-model="form.username"
          :maxlength="USERNAME_MAX_LENGTH"
          show-word-limit
          autocomplete="off"
          placeholder="例如 teacher02"
        />
        <div class="field-hint">
          {{ USERNAME_MIN_LENGTH }}–{{ USERNAME_MAX_LENGTH }} 位，只能使用小写字母、数字、下划线、点和连字符，且以字母或数字开头。创建后不可修改。
        </div>
      </el-form-item>
      <el-form-item v-else label="用户名">
        <span class="static-value">{{ user?.username }}</span>
      </el-form-item>

      <el-form-item label="显示名" prop="displayName">
        <el-input
          v-model="form.displayName"
          :maxlength="DISPLAY_NAME_MAX_LENGTH"
          show-word-limit
          autocomplete="off"
          placeholder="请输入显示名"
        />
      </el-form-item>

      <el-form-item label="角色" prop="role">
        <el-select v-model="form.role" placeholder="请选择角色" class="full-width">
          <el-option v-for="option in ROLE_OPTIONS" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
      </el-form-item>

      <el-form-item v-if="isCreate" label="初始密码" prop="password">
        <el-input
          v-model="form.password"
          type="password"
          show-password
          autocomplete="new-password"
          placeholder="请输入初始密码"
        />
        <div class="field-hint">{{ PASSWORD_RULE_TEXT }}</div>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button :disabled="submitting" @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" :disabled="submitting" @click="submit">
        {{ isCreate ? '创建' : '保存' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { api } from '../api'
import type { AdminUser, AdminUserUpdatePayload, Role } from '../api'
import { useApiError } from '../composables/useApiError'
import {
  DISPLAY_NAME_MAX_LENGTH,
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  PASSWORD_RULE_TEXT,
  ROLE_OPTIONS,
  USERNAME_MAX_LENGTH,
  USERNAME_MIN_LENGTH,
  USERNAME_PATTERN,
  charLength,
} from '../utils/admin'

const props = defineProps<{
  modelValue: boolean
  /** create：新建账号；edit：修改显示名和角色。 */
  mode: 'create' | 'edit'
  user?: AdminUser | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  /** 保存成功，参数为后端返回的最新用户。 */
  saved: [user: AdminUser]
  /** 目标用户已不存在（404），父组件应刷新列表。 */
  stale: []
}>()

const { handle } = useApiError()

const formRef = ref<FormInstance>()
const submitting = ref(false)
const errorMessage = ref('')
const form = reactive({
  username: '',
  displayName: '',
  role: '' as Role | '',
  password: '',
})

const isCreate = computed(() => props.mode === 'create')

const rules = computed<FormRules>(() => ({
  username: [
    {
      validator: (_rule, value: string, callback) => {
        const text = (value ?? '').trim()
        const length = charLength(text)
        if (!text) callback(new Error('请输入用户名'))
        else if (length < USERNAME_MIN_LENGTH || length > USERNAME_MAX_LENGTH) {
          callback(new Error(`用户名需为 ${USERNAME_MIN_LENGTH}–${USERNAME_MAX_LENGTH} 个字符`))
        } else if (!USERNAME_PATTERN.test(text)) {
          callback(new Error('只能使用小写字母、数字、下划线、点和连字符，且以字母或数字开头'))
        } else callback()
      },
      trigger: ['blur', 'change'],
    },
  ],
  displayName: [
    {
      validator: (_rule, value: string, callback) => {
        const text = (value ?? '').trim()
        if (!text) callback(new Error('请输入显示名'))
        else if (charLength(text) > DISPLAY_NAME_MAX_LENGTH) {
          callback(new Error(`显示名不能超过 ${DISPLAY_NAME_MAX_LENGTH} 个字符`))
        } else callback()
      },
      trigger: ['blur', 'change'],
    },
  ],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
  password: isCreate.value
    ? [
        {
          validator: (_rule, value: string, callback) => {
            const length = charLength(value ?? '')
            if (length === 0) callback(new Error('请输入初始密码'))
            else if (length < PASSWORD_MIN_LENGTH || length > PASSWORD_MAX_LENGTH) {
              callback(new Error(`密码长度需为 ${PASSWORD_MIN_LENGTH}–${PASSWORD_MAX_LENGTH} 个字符`))
            } else callback()
          },
          trigger: ['blur', 'change'],
        },
      ]
    : [],
}))

function onOpen(): void {
  errorMessage.value = ''
  form.password = ''
  if (props.mode === 'edit' && props.user) {
    form.username = props.user.username
    form.displayName = props.user.display_name
    form.role = props.user.role
  } else {
    form.username = ''
    form.displayName = ''
    form.role = ''
  }
}

/** 关闭后立即清掉密码，避免明文留在组件状态里。 */
function onClosed(): void {
  form.password = ''
}

function beforeClose(done: () => void): void {
  if (!submitting.value) done()
}

async function submit(): Promise<void> {
  if (submitting.value) return
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid || form.role === '') return

  const displayName = form.displayName.trim()
  const role = form.role

  submitting.value = true
  errorMessage.value = ''
  try {
    let saved: AdminUser
    if (isCreate.value) {
      saved = await api.createUser({
        username: form.username.trim(),
        display_name: displayName,
        password: form.password,
        role,
      })
      ElMessage.success(`账号“${saved.username}”已创建`)
    } else if (props.user) {
      const changes: AdminUserUpdatePayload = {}
      if (displayName !== props.user.display_name) changes.display_name = displayName
      if (role !== props.user.role) changes.role = role
      if (Object.keys(changes).length === 0) {
        ElMessage.info('没有需要保存的修改')
        emit('update:modelValue', false)
        return
      }
      saved = await api.updateUser(props.user.id, changes)
      ElMessage.success('账号信息已保存')
    } else {
      return
    }
    emit('update:modelValue', false)
    emit('saved', saved)
  } catch (e) {
    const described = await handle(e, isCreate.value ? '创建失败，请稍后重试。' : '保存失败，请稍后重试。')
    errorMessage.value = described.message
    if (described.status === 404) {
      emit('stale')
    }
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.form-alert {
  margin-bottom: 12px;
}

.full-width {
  width: 100%;
}

.field-hint {
  width: 100%;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-secondary);
}

.static-value {
  overflow-wrap: anywhere;
}
</style>
