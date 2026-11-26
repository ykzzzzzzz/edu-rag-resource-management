<template>
  <el-dialog
    :model-value="modelValue"
    :title="isCreate ? '上传资源' : '编辑草稿'"
    width="560px"
    class="resource-form-dialog"
    :close-on-click-modal="false"
    :close-on-press-escape="!submitting"
    :show-close="!submitting"
    :before-close="beforeClose"
    @open="onOpen"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-alert
      v-if="coursesError"
      class="form-alert"
      type="error"
      show-icon
      :closable="false"
      :title="coursesError"
    />
    <el-alert
      v-else-if="courses.length === 0"
      class="form-alert"
      type="warning"
      show-icon
      :closable="false"
      title="暂无课程，请联系管理员先创建课程"
    />
    <el-alert v-if="errorMessage" class="form-alert" type="error" show-icon :closable="false" :title="errorMessage" />

    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="submit">
      <el-form-item label="标题" prop="title">
        <el-input v-model="form.title" :maxlength="TITLE_MAX_LENGTH" show-word-limit placeholder="请输入资源标题" />
      </el-form-item>
      <el-form-item label="课程" prop="courseId">
        <el-select v-model="form.courseId" filterable placeholder="请选择课程" class="full-width">
          <el-option v-for="course in courses" :key="course.id" :label="course.name" :value="course.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="描述（可选）" prop="description">
        <el-input
          v-model="form.description"
          type="textarea"
          :rows="3"
          :maxlength="DESCRIPTION_MAX_LENGTH"
          show-word-limit
          placeholder="简要说明资源内容"
        />
      </el-form-item>
      <el-form-item v-if="isCreate" label="文件" prop="file" required>
        <div class="file-row">
          <input
            ref="fileInput"
            class="file-input"
            type="file"
            :accept="ALLOWED_EXTENSIONS.join(',')"
            :disabled="submitting"
            @change="onFileChange"
          />
        </div>
        <div class="file-hint">
          支持 .pdf（需含文本层）、.docx、.txt（UTF-8），单个文件不超过 20 MiB。
        </div>
        <div v-if="form.file" class="file-meta">
          已选择：{{ form.file.name }}（{{ formatSize(form.file.size) }}）
        </div>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button :disabled="submitting" @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" :disabled="submitting || courses.length === 0" @click="submit">
        {{ isCreate ? '上传' : '保存' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { api } from '../api'
import type { Course, Resource } from '../api'
import { useApiError } from '../composables/useApiError'
import {
  ALLOWED_EXTENSIONS,
  DESCRIPTION_MAX_LENGTH,
  TITLE_MAX_LENGTH,
  formatSize,
  validateUploadFile,
} from '../utils/resource'

const props = defineProps<{
  modelValue: boolean
  /** create：上传新资源；edit：修改草稿的标题、课程、描述。 */
  mode: 'create' | 'edit'
  resource?: Resource | null
  courses: Course[]
  coursesError?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  /** 保存成功。 */
  saved: [resource: Resource]
  /** 服务端提示资源状态已变化（404/409），父组件应刷新列表。 */
  stale: []
}>()

const { handle } = useApiError()

const formRef = ref<FormInstance>()
const fileInput = ref<HTMLInputElement>()
const submitting = ref(false)
const errorMessage = ref('')
const form = reactive({
  title: '',
  courseId: '',
  description: '',
  file: null as File | null,
})

const isCreate = computed(() => props.mode === 'create')

const rules = computed<FormRules>(() => ({
  title: [
    {
      validator: (_rule, value: string, callback) => {
        const text = (value ?? '').trim()
        if (!text) callback(new Error('请输入标题'))
        else if (text.length > TITLE_MAX_LENGTH) callback(new Error(`标题不能超过 ${TITLE_MAX_LENGTH} 个字符`))
        else callback()
      },
      trigger: ['blur', 'change'],
    },
  ],
  courseId: [{ required: true, message: '请选择课程', trigger: 'change' }],
  description: [
    {
      validator: (_rule, value: string, callback) => {
        if ((value ?? '').trim().length > DESCRIPTION_MAX_LENGTH) {
          callback(new Error(`描述不能超过 ${DESCRIPTION_MAX_LENGTH} 个字符`))
        } else callback()
      },
      trigger: 'blur',
    },
  ],
  file: isCreate.value
    ? [
        {
          validator: (_rule, _value: unknown, callback) => {
            if (!form.file) callback(new Error('请选择要上传的文件'))
            else {
              const problem = validateUploadFile(form.file)
              if (problem) callback(new Error(problem))
              else callback()
            }
          },
          trigger: 'change',
        },
      ]
    : [],
}))

function onOpen(): void {
  errorMessage.value = ''
  form.file = null
  if (fileInput.value) fileInput.value.value = ''
  if (props.mode === 'edit' && props.resource) {
    form.title = props.resource.title
    form.courseId = props.resource.course_id
    form.description = props.resource.description ?? ''
  } else {
    form.title = ''
    form.courseId = ''
    form.description = ''
  }
  formRef.value?.clearValidate()
}

function onFileChange(event: Event): void {
  const input = event.target as HTMLInputElement
  form.file = input.files && input.files.length > 0 ? input.files[0] : null
  errorMessage.value = ''
  void formRef.value?.validateField('file').catch(() => undefined)
}

function beforeClose(done: () => void): void {
  if (!submitting.value) done()
}

async function submit(): Promise<void> {
  if (submitting.value) return
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  errorMessage.value = ''
  try {
    const title = form.title.trim()
    const description = form.description.trim()
    let saved: Resource
    if (isCreate.value && form.file) {
      saved = await api.uploadResource({
        title,
        course_id: form.courseId,
        description: description || undefined,
        file: form.file,
      })
      ElMessage.success('上传成功，已保存为草稿')
    } else if (props.resource) {
      saved = await api.updateResource(props.resource.id, {
        title,
        course_id: form.courseId,
        description: description || null,
      })
      ElMessage.success('草稿已保存')
    } else {
      return
    }
    emit('update:modelValue', false)
    emit('saved', saved)
  } catch (e) {
    const described = await handle(e, isCreate.value ? '上传失败，请稍后重试。' : '保存失败，请稍后重试。')
    errorMessage.value = described.message
    if (described.status === 404 || described.status === 409) {
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

.file-row {
  width: 100%;
}

.file-input {
  max-width: 100%;
}

.file-hint {
  width: 100%;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-secondary);
}

.file-meta {
  width: 100%;
  font-size: 13px;
  overflow-wrap: anywhere;
}
</style>
