export function formatBytes(bytes: number): string {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function formatDateTime(value: string | number): string {
  if (!value) return '-'
  return new Date(typeof value === 'number' ? value * 1000 : value).toLocaleString('zh-CN', { hour12: false })
}
