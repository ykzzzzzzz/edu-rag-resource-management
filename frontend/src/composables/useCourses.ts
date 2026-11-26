import { ref } from 'vue'
import { api } from '../api'
import type { Course } from '../api'
import { useApiError } from './useApiError'

/** 加载课程下拉所需的课程列表。 */
export function useCourses() {
  const { handle } = useApiError()
  const courses = ref<Course[]>([])
  const loading = ref(false)
  const error = ref('')
  const loaded = ref(false)

  async function loadCourses(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      courses.value = (await api.listCourses()).items
      loaded.value = true
    } catch (e) {
      error.value = (await handle(e, '课程列表加载失败，请稍后重试。')).message
    } finally {
      loading.value = false
    }
  }

  return { courses, loading, error, loaded, loadCourses }
}
