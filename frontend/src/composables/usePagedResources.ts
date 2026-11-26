import { ref } from 'vue'
import type { Resource, ResourceList } from '../api'
import { useApiError } from './useApiError'

export const PAGE_SIZE_OPTIONS = [10, 20, 50, 100]

/**
 * 分页资源列表的加载状态。fetcher 由页面提供并带上当前筛选条件。
 * 并发请求以最后一次为准；页码超出范围（如筛选后变少）时自动回到最后一页。
 */
export function usePagedResources(fetcher: (page: number, pageSize: number) => Promise<ResourceList>) {
  const { handle } = useApiError()
  const items = ref<Resource[]>([])
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

  /** 筛选条件变化后从第一页重新查询。 */
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
