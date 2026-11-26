export type Role = 'student' | 'teacher' | 'admin'

export type QaMode = 'demo' | 'cloud'

export interface CurrentUser {
  id: string
  username: string
  display_name: string
  role: Role
}

export interface LoginRequest {
  username: string
  password: string
}

export interface SystemMode {
  qa_mode: QaMode
}

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    request_id: string
  }
}
