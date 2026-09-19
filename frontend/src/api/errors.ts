/** 前端请求层统一错误模型。 */

export type RequestErrorKind = 'http' | 'network' | 'timeout' | 'aborted' | 'parse' | 'unknown'

export class ApiError extends Error {
  readonly kind: RequestErrorKind
  readonly status?: number

  constructor(message: string, kind: RequestErrorKind = 'unknown', status?: number) {
    super(message)
    this.name = 'ApiError'
    this.kind = kind
    this.status = status
  }
}

export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message
  return fallback
}
