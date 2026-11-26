import { ref } from 'vue'
import type { Ref } from 'vue'
import { useApiError } from './useApiError'

export interface PagedResult<T> {
  items: T[]
  total: number
}

/**
 * 通用分页列表状态，行为与 usePagedResources 一致（并发以最后一次为准、页码越界回到最后一页），
 * 但不限定为资源类型，供问答日志等页面使用。
 */
export function usePagedList<T>(fetcher: (page: number, pageSize: number) => Promise<PagedResult<T>>) {
  const { handle } = useApiError()
  const items = ref<T[]>([]) as Ref<T[]>
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(20)
  const loading = ref(false)
  const error = ref('')
  let token = 0

  async function load(): Promise<void> {
    const mine = ++token
    loading.value = true
    error.value = ''
    try {
      const result = await fetcher(page.value, pageSize.value)
      if (mine !== token) return
      if (result.items.length === 0 && result.total > 0 && page.value > 1) {
        page.value = Math.max(1, Math.ceil(result.total / pageSize.value))
        await load()
        return
      }
      items.value = result.items
      total.value = result.total
    } catch (e) {
      const described = await handle(e, '列表加载失败，请稍后重试。')
      if (mine !== token) return
      items.value = []
      total.value = 0
      error.value = described.message
    } finally {
      if (mine === token) loading.value = false
    }
  }

  function search(): Promise<void> {
    page.value = 1
    return load()
  }

  function changePage(value: number): Promise<void> {
    page.value = value
    return load()
  }

  function changePageSize(value: number): Promise<void> {
    pageSize.value = value
    page.value = 1
    return load()
  }

  return { items, total, page, pageSize, loading, error, load, search, changePage, changePageSize }
}
