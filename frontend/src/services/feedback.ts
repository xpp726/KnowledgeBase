import { ElMessage, ElMessageBox } from 'element-plus'

/** UI feedback boundary used by stores and business composables. */
export const notify = {
  success: (message: string) => ElMessage.success(message),
  error: (message: string) => ElMessage.error(message),
  warning: (message: string) => ElMessage.warning(message),
  info: (message: string) => ElMessage.info(message),
}

export function confirmDialog(...args: Parameters<typeof ElMessageBox.confirm>) {
  return ElMessageBox.confirm(...args)
}

export function promptDialog(...args: Parameters<typeof ElMessageBox.prompt>) {
  return ElMessageBox.prompt(...args)
}
