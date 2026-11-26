import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '../api'
import { session } from '../stores/session'

const STATUS_FALLBACKS: Record<number, string> = {
  401: '登录已失效，请重新登录。',
  403: '无权限执行该操作。',
  404: '资源不存在或无权查看。',
  409: '资源状态已发生变化，请刷新后重试。',
  413: '文件过大，请压缩后再上传。',
  415: '文件类型或内容不合法，仅支持含文本层的 PDF、DOCX 和 UTF-8 TXT。',
  422: '提交的参数不合法，请检查后重试。',
}

export interface DescribedError {
  status: number
  message: string
}

/** 优先使用后端 error.message，缺失时按状态码给出默认提示。 */
export function describeError(error: unknown, fallback: string): DescribedError {
  if (error instanceof ApiError) {
    return { status: error.status, message: error.message || STATUS_FALLBACKS[error.status] || fallback }
  }
  return { status: -1, message: fallback }
}

/**
 * 统一处理接口错误。401 时清除本地会话并跳转登录页（登录后回到当前页），
 * 其余情况只返回可展示的文本，由页面决定如何呈现。
 */
export function useApiError() {
  const router = useRouter()
  const route = useRoute()

  async function handle(error: unknown, fallback: string): Promise<DescribedError> {
    const described = describeError(error, fallback)
    if (described.status === 401) {
      try {
        // 服务端对已失效会话返回 401，session.logout 将其视为退出成功并清空本地用户。
        await session.logout()
      } catch {
        // 无法确认服务端状态时保持原样，只提示。
      }
      if (session.user.value === null) {
        await router.replace({ name: 'login', query: { redirect: route.fullPath } })
      }
    }
    return described
  }

  return { handle }
}
