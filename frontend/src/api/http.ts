import type { ApiErrorBody } from './types'

/** 后端返回的业务错误，或网络层失败（status 为 0）。 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId: string | null

  constructor(status: number, code: string, message: string, requestId: string | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
  }
}

const API_PREFIX = '/api/v1'

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== 'object' || value === null || !('error' in value)) {
    return false
  }
  const error = (value as { error: unknown }).error
  return typeof error === 'object' && error !== null && 'code' in error && 'message' in error
}

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body: unknown = await response.json()
    if (isApiErrorBody(body)) {
      const { code, message, request_id } = body.error
      return new ApiError(response.status, code, message, request_id ?? null)
    }
  } catch {
    // 响应体不是 JSON 时使用下面的通用提示。
  }
  return new ApiError(response.status, 'http_error', `请求失败（HTTP ${response.status}）`)
}

export async function request<T>(method: 'GET' | 'POST' | 'PATCH', path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const init: RequestInit = { method, credentials: 'include', headers }
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }

  let response: Response
  try {
    response = await fetch(`${API_PREFIX}${path}`, init)
  } catch {
    throw new ApiError(0, 'network_error', '无法连接服务器，请确认后端已启动。')
  }

  if (!response.ok) {
    throw await toApiError(response)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}
