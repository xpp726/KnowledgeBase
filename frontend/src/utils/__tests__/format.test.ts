import { describe, expect, it } from 'vitest'
import { formatBytes, formatDateTime } from '../format'

describe('format utilities', () => {
  it('formats byte sizes for the common units', () => {
    expect(formatBytes(0)).toBe('-')
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2.0 KB')
    expect(formatBytes(2 * 1024 * 1024)).toBe('2.0 MB')
  })

  it('formats unix timestamps and ISO timestamps consistently', () => {
    expect(formatDateTime(0)).toBe('-')
    expect(formatDateTime('2026-01-02T03:04:05Z')).toContain('2026')
    expect(formatDateTime(0.001)).toContain('1970')
  })
})
