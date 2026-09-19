import type { App } from 'vue'
import {
  ElAvatar,
  ElButton,
  ElDialog,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElMenu,
  ElMenuItem,
  ElOption,
  ElPopconfirm,
  ElPopover,
  ElProgress,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag,
  ElTooltip,
  ElTreeSelect,
  ElUpload,
  ElLoadingDirective,
} from 'element-plus'

/** Register only the Element Plus components used by the application templates. */
export function installElementPlus(app: App) {
  app
    .component('ElAvatar', ElAvatar)
    .component('ElButton', ElButton)
    .component('ElDialog', ElDialog)
    .component('ElEmpty', ElEmpty)
    .component('ElForm', ElForm)
    .component('ElFormItem', ElFormItem)
    .component('ElIcon', ElIcon)
    .component('ElInput', ElInput)
    .component('ElInputNumber', ElInputNumber)
    .component('ElMenu', ElMenu)
    .component('ElMenuItem', ElMenuItem)
    .component('ElOption', ElOption)
    .component('ElPopconfirm', ElPopconfirm)
    .component('ElPopover', ElPopover)
    .component('ElProgress', ElProgress)
    .component('ElSelect', ElSelect)
    .component('ElTable', ElTable)
    .component('ElTableColumn', ElTableColumn)
    .component('ElTag', ElTag)
    .component('ElTooltip', ElTooltip)
    .component('ElTreeSelect', ElTreeSelect)
    .component('ElUpload', ElUpload)
    .directive('loading', ElLoadingDirective)
}
