import { describe, expect, it } from 'vitest'
import { ApiError, errorMessage } from '../errors'

describe('api/errors', () => {
  it('ApiError 保留请求类型和 HTTP 状态码', () => {
    const error = new ApiError('无权限', 'http', 403)
    expect(error).toBeInstanceOf(Error)
    expect(error.name).toBe('ApiError')
    expect(error.kind).toBe('http')
    expect(error.status).toBe(403)
  })

  it('errorMessage 优先使用 Error 文案', () => {
    expect(errorMessage(new Error('请求失败'), '默认文案')).toBe('请求失败')
    expect(errorMessage({ message: '非 Error 对象' }, '默认文案')).toBe('默认文案')
  })
})
