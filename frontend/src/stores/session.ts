import { computed, reactive } from 'vue'
import { api, ApiError } from '../api'
import type { CurrentUser, LoginRequest, QaMode } from '../api/types'

const state = reactive({
  user: null as CurrentUser | null,
  /** 已完成首次 /auth/me 检查。 */
  restored: false,
  qaMode: null as QaMode | null,
  /** 恢复会话时的非 401 错误（如网络不通），显示在登录页。 */
  notice: '',
})

let restoring: Promise<void> | null = null

export const session = {
  user: computed(() => state.user),
  restored: computed(() => state.restored),
  qaMode: computed(() => state.qaMode),
  notice: computed(() => state.notice),

  /** 通过 /auth/me 恢复登录状态。并发调用共享同一个请求。 */
  restore(): Promise<void> {
    if (!restoring) {
      restoring = (async () => {
        try {
          state.user = await api.me()
          state.notice = ''
        } catch (error) {
          state.user = null
          if (!(error instanceof ApiError && error.status === 401)) {
            state.notice = error instanceof ApiError ? error.message : '无法确认登录状态。'
          }
        } finally {
          state.restored = true
          restoring = null
        }
      })()
    }
    return restoring
  },

  async login(payload: LoginRequest): Promise<CurrentUser> {
    const user = await api.login(payload)
    state.user = user
    state.notice = ''
    state.restored = true
    return user
  },

  /**
   * 退出登录。服务端返回 401 说明会话已失效，同样视为退出成功。
   * 其他错误会抛出，本地登录状态保持不变，避免服务端会话仍有效而界面显示已退出。
   */
  async logout(): Promise<void> {
    try {
      await api.logout()
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) {
        throw error
      }
    }
    state.user = null
  },

  /** 获取当前问答模式，失败时保持为 null 并由界面显示“模式未知”。 */
  async loadQaMode(): Promise<void> {
    try {
      const { qa_mode } = await api.systemMode()
      state.qaMode = qa_mode
    } catch {
      state.qaMode = null
    }
  },
}
