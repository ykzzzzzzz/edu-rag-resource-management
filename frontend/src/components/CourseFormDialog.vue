<template>
  <el-dialog
    :model-value="modelValue"
    :title="isCreate ? '新建课程' : '编辑课程'"
    width="520px"
    destroy-on-close
    :close-on-click-modal="false"
    :close-on-press-escape="!submitting"
    :show-close="!submitting"
    :before-close="beforeClose"
    @open="onOpen"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-alert v-if="errorMessage" class="form-alert" type="error" show-icon :closable="false" :title="errorMessage" />

    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="submit">
      <el-form-item label="课程名称" prop="name">
        <el-input
          v-model="form.name"
          :maxlength="COURSE_NAME_MAX_LENGTH"
          show-word-limit
          placeholder="请输入课程名称"
          @input="errorMessage = ''"
        />
      </el-form-item>
      <el-form-item label="描述（可选）" prop="description">
        <el-input
          v-model="form.description"
          type="textarea"
          :rows="4"
          :maxlength="COURSE_DESCRIPTION_MAX_LENGTH"
          show-word-limit
          placeholder="简要说明课程内容"
        />
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
import type { Course, CourseUpdatePayload } from '../api'
import { useApiError } from '../composables/useApiError'
import { COURSE_DESCRIPTION_MAX_LENGTH, COURSE_NAME_MAX_LENGTH, charLength } from '../utils/admin'

const props = defineProps<{
  modelValue: boolean
  mode: 'create' | 'edit'
  course?: Course | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  /** 保存成功，参数为后端返回的最新课程。 */
  saved: [course: Course]
  /** 课程已不存在（404），父组件应刷新列表。 */
  stale: []
}>()

const { handle } = useApiError()

const formRef = ref<FormInstance>()
const submitting = ref(false)
const errorMessage = ref('')
const form = reactive({ name: '', description: '' })

const isCreate = computed(() => props.mode === 'create')

const rules: FormRules = {
  name: [
    {
      validator: (_rule, value: string, callback) => {
        const text = (value ?? '').trim()
        if (!text) callback(new Error('请输入课程名称'))
        else if (charLength(text) > COURSE_NAME_MAX_LENGTH) {
          callback(new Error(`课程名称不能超过 ${COURSE_NAME_MAX_LENGTH} 个字符`))
        } else callback()
      },
      trigger: ['blur', 'change'],
    },
  ],
  description: [
    {
      validator: (_rule, value: string, callback) => {
        if (charLength((value ?? '').trim()) > COURSE_DESCRIPTION_MAX_LENGTH) {
          callback(new Error(`描述不能超过 ${COURSE_DESCRIPTION_MAX_LENGTH} 个字符`))
        } else callback()
      },
      trigger: ['blur', 'change'],
    },
  ],
}

function onOpen(): void {
  errorMessage.value = ''
  if (props.mode === 'edit' && props.course) {
    form.name = props.course.name
    form.description = props.course.description ?? ''
  } else {
    form.name = ''
    form.description = ''
  }
  formRef.value?.clearValidate()
}

function beforeClose(done: () => void): void {
  if (!submitting.value) done()
}

async function submit(): Promise<void> {
  if (submitting.value) return
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  const name = form.name.trim()
  const description = form.description.trim()

  submitting.value = true
  errorMessage.value = ''
  try {
    let saved: Course
    if (isCreate.value) {
      saved = await api.createCourse({ name, description: description || null })
      ElMessage.success(`课程“${saved.name}”已创建`)
    } else if (props.course) {
      const changes: CourseUpdatePayload = {}
      if (name !== props.course.name) changes.name = name
      if (description !== (props.course.description ?? '')) changes.description = description || null
      if (Object.keys(changes).length === 0) {
        ElMessage.info('没有需要保存的修改')
        emit('update:modelValue', false)
        return
      }
      saved = await api.updateCourse(props.course.id, changes)
      ElMessage.success('课程已保存')
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
</style>
