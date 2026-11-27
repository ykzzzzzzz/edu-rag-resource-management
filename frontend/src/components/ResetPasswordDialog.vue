<template>
  <el-dialog
    :model-value="modelValue"
    title="重置密码"
    width="480px"
    destroy-on-close
    :close-on-click-modal="false"
    :close-on-press-escape="!submitting"
    :show-close="!submitting"
    :before-close="beforeClose"
    @open="onOpen"
    @closed="onClosed"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <p v-if="user" class="target">账号：{{ user.display_name }}（{{ user.username }}）</p>
    <el-alert
      class="form-alert"
      type="warning"
      show-icon
      :closable="false"
      title="重置后，该用户的所有登录会话会立即撤销，需要用新密码重新登录。"
    />
    <el-alert v-if="errorMessage" class="form-alert" type="error" show-icon :closable="false" :title="errorMessage" />

    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="submit">
      <el-form-item label="新密码" prop="newPassword">
        <el-input
          v-model="form.newPassword"
          type="password"
          show-password
          autocomplete="new-password"
          placeholder="请输入新密码"
          @input="revalidateConfirm"
        />
        <div class="field-hint">{{ PASSWORD_RULE_TEXT }}</div>
      </el-form-item>
      <el-form-item label="确认新密码" prop="confirm">
        <el-input
          v-model="form.confirm"
          type="password"
          show-password
          autocomplete="new-password"
          placeholder="请再次输入新密码"
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button :disabled="submitting" @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" :disabled="submitting" @click="submit">确认重置</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { api } from '../api'
import type { AdminUser } from '../api'
import { useApiError } from '../composables/useApiError'
import { PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH, PASSWORD_RULE_TEXT, charLength } from '../utils/admin'

const props = defineProps<{
  modelValue: boolean
  user: AdminUser | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  /** 重置成功。 */
  done: []
  /** 目标用户已不存在（404），父组件应刷新列表。 */
  stale: []
}>()

const { handle } = useApiError()

const formRef = ref<FormInstance>()
const submitting = ref(false)
const errorMessage = ref('')
const form = reactive({ newPassword: '', confirm: '' })

const rules: FormRules = {
  newPassword: [
    {
      validator: (_rule, value: string, callback) => {
        const length = charLength(value ?? '')
        if (length === 0) callback(new Error('请输入新密码'))
        else if (length < PASSWORD_MIN_LENGTH || length > PASSWORD_MAX_LENGTH) {
          callback(new Error(`密码长度需为 ${PASSWORD_MIN_LENGTH}–${PASSWORD_MAX_LENGTH} 个字符`))
        } else callback()
      },
      trigger: ['blur', 'change'],
    },
  ],
  confirm: [
    {
      validator: (_rule, value: string, callback) => {
        if (!value) callback(new Error('请再次输入新密码'))
        else if (value !== form.newPassword) callback(new Error('两次输入的密码不一致'))
        else callback()
      },
      trigger: ['blur', 'change'],
    },
  ],
}

function onOpen(): void {
  errorMessage.value = ''
  form.newPassword = ''
  form.confirm = ''
}

/** 关闭后立即清掉明文密码。 */
function onClosed(): void {
  form.newPassword = ''
  form.confirm = ''
}

/** 新密码改动后，若确认框已有内容则重新比对。 */
function revalidateConfirm(): void {
  if (form.confirm) void formRef.value?.validateField('confirm').catch(() => undefined)
}

function beforeClose(done: () => void): void {
  if (!submitting.value) done()
}

async function submit(): Promise<void> {
  if (submitting.value || !props.user) return
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  errorMessage.value = ''
  try {
    await api.resetUserPassword(props.user.id, { new_password: form.newPassword })
    ElMessage.success('已重置，该用户的所有会话已撤销')
    emit('update:modelValue', false)
    emit('done')
  } catch (e) {
    const described = await handle(e, '重置失败，请稍后重试。')
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
.target {
  margin: 0 0 12px;
  overflow-wrap: anywhere;
}

.form-alert {
  margin-bottom: 12px;
}

.field-hint {
  width: 100%;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-secondary);
}
</style>
