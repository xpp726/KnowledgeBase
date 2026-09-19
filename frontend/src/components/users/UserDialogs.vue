<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import type { User, UserRole } from '../../types/auth'

export interface UserDialogSavePayload {
  username: string
  displayName: string
  password: string
  role: UserRole
}

export interface UserPasswordResetPayload {
  userId: string
  password: string
}

const props = defineProps<{
  visible: boolean
  resetVisible: boolean
  editingUser: User | null
  resetTarget: User | null
  saving: boolean
}>()

const emit = defineEmits<{
  (event: 'update:visible', visible: boolean): void
  (event: 'update:reset-visible', visible: boolean): void
  (event: 'save', payload: UserDialogSavePayload): void
  (event: 'reset-password', payload: UserPasswordResetPayload): void
}>()

const formRef = ref<FormInstance>()
const form = reactive({ username: '', displayName: '', password: '', role: 'viewer' as UserRole })
const newPassword = ref('')

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  displayName: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
  ],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
}

function resetForm() {
  form.username = ''
  form.displayName = ''
  form.password = ''
  form.role = 'viewer'
  formRef.value?.clearValidate()
}

watch(
  () => [props.visible, props.editingUser?.id] as const,
  ([visible]) => {
    if (!visible) return
    form.username = props.editingUser?.username ?? ''
    form.displayName = props.editingUser?.display_name ?? ''
    form.password = ''
    form.role = props.editingUser?.role ?? 'viewer'
  },
  { immediate: true },
)

watch(
  () => [props.resetVisible, props.resetTarget?.id] as const,
  ([visible]) => {
    if (visible) newPassword.value = ''
  },
  { immediate: true },
)

async function submit() {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  emit('save', { ...form })
}

function submitPasswordReset() {
  if (!props.resetTarget) return
  if (newPassword.value.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  emit('reset-password', { userId: props.resetTarget.id, password: newPassword.value })
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="editingUser ? '编辑用户' : '新建用户'"
    width="420px"
    @update:model-value="emit('update:visible', $event)"
    @closed="resetForm"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
      <el-form-item label="用户名" prop="username">
        <el-input v-model="form.username" :disabled="!!editingUser" placeholder="登录用户名" />
      </el-form-item>
      <el-form-item label="姓名" prop="displayName">
        <el-input v-model="form.displayName" placeholder="显示姓名" />
      </el-form-item>
      <el-form-item v-if="!editingUser" label="密码" prop="password">
        <el-input v-model="form.password" type="password" show-password placeholder="至少 6 位" />
      </el-form-item>
      <el-form-item label="角色" prop="role">
        <el-select v-model="form.role" style="width: 100%">
          <el-option label="管理员（全部权限）" value="admin" />
          <el-option label="编辑者（文档管理+问答）" value="editor" />
          <el-option label="普通用户（仅问答）" value="viewer" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog
    :model-value="resetVisible"
    title="重置密码"
    width="380px"
    @update:model-value="emit('update:reset-visible', $event)"
  >
    <el-form label-width="80px">
      <el-form-item label="用户">
        <span>{{ resetTarget?.display_name }}（{{ resetTarget?.username }}）</span>
      </el-form-item>
      <el-form-item label="新密码">
        <el-input v-model="newPassword" type="password" show-password placeholder="至少 6 位" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:reset-visible', false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submitPasswordReset">确认重置</el-button>
    </template>
  </el-dialog>
</template>
