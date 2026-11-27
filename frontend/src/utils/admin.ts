import { ROLE_LABELS } from '../config/navigation'
import type { Role } from '../api/types'

/**
 * 管理员页面的输入限制，取自后端 schemas.py。前端只做预检，最终以服务端返回为准。
 * 后端按字符（Unicode 码点）计长，这里同样用码点而不是 UTF-16 长度。
 */
export const USERNAME_MIN_LENGTH = 3
export const USERNAME_MAX_LENGTH = 64
/** 后端先校验该格式再转小写，所以这里要求输入时就是小写。 */
export const USERNAME_PATTERN = /^[a-z0-9][a-z0-9_.-]*$/
export const DISPLAY_NAME_MAX_LENGTH = 64
export const PASSWORD_MIN_LENGTH = 8
export const PASSWORD_MAX_LENGTH = 128
export const COURSE_NAME_MAX_LENGTH = 100
export const COURSE_DESCRIPTION_MAX_LENGTH = 500

export const PASSWORD_RULE_TEXT = `密码长度为 ${PASSWORD_MIN_LENGTH}–${PASSWORD_MAX_LENGTH} 个字符，除长度外没有其他要求。`

export const ROLE_OPTIONS = (Object.keys(ROLE_LABELS) as Role[]).map((value) => ({
  value,
  label: ROLE_LABELS[value],
}))

/** 按 Unicode 码点计长，与后端 Python 字符串长度一致。 */
export function charLength(value: string): number {
  return Array.from(value).length
}
