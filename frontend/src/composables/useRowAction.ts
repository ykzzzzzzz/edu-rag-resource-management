import { reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { useApiError } from './useApiError'

export type RowActionResult = 'ok' | 'stale' | 'error'

/**
 * 针对列表行的写操作：按行 id 防重复点击，成功后提示并刷新列表。
 * 404/409 说明资源状态已变化，同样刷新列表并返回 'stale'。
 */
export function useRowAction(reload: () => Promise<unknown>) {
  const { handle } = useApiError()
  const busy = reactive<Record<string, boolean>>({})

  async function run(
    id: string,
    task: () => Promise<unknown>,
    successText: string,
    failText: string,
  ): Promise<RowActionResult> {
    if (busy[id]) return 'error'
    busy[id] = true
    let result: RowActionResult = 'ok'
    try {
      await task()
      ElMessage.success(successText)
    } catch (e) {
      const described = await handle(e, failText)
      const stale = described.status === 404 || described.status === 409
      result = stale ? 'stale' : 'error'
      ElMessage.error(stale ? `${described.message}（列表已刷新）` : described.message)
    } finally {
      busy[id] = false
    }
    if (result !== 'error') {
      await reload()
    }
    return result
  }

  return { busy, run }
}
