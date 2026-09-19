<template>
  <div class="users-page">
    <div class="page-header">
      <h2>用户管理</h2>
      <el-button type="primary" @click="openCreateDialog">
        <el-icon><Plus /></el-icon>
        新建用户
      </el-button>
    </div>

    <UserTable
      :users="users"
      :loading="loading"
      :current-user-id="auth.currentUser?.id"
      @edit="openEditDialog"
      @reset-password="openResetPassword"
      @toggle-active="toggleActive"
    />

    <UserDialogs
      :visible="dialogVisible"
      :reset-visible="resetDialogVisible"
      :editing-user="editingUser"
      :reset-target="resetTarget"
      :saving="saving"
      @update:visible="dialogVisible = $event"
      @update:reset-visible="resetDialogVisible = $event"
      @save="handleSave"
      @reset-password="handleResetPassword"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as usersApi from '../api/users'
import { useAuthStore } from '../stores/auth'
import type { User } from '../types/auth'
import UserTable from '../components/users/UserTable.vue'
import UserDialogs, {
  type UserDialogSavePayload,
  type UserPasswordResetPayload,
} from '../components/users/UserDialogs.vue'

const auth = useAuthStore()
const users = ref<User[]>([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const resetDialogVisible = ref(false)
const editingUser = ref<User | null>(null)
const resetTarget = ref<User | null>(null)
async function loadUsers() {
  loading.value = true
  try {
    users.value = await usersApi.listUsers()
  } catch (e) {
    ElMessage.error((e as Error).message || '加载用户列表失败')
  } finally {
    loading.value = false
  }
}

function resetFormData() {
  editingUser.value = null
}

function openCreateDialog() {
  resetFormData()
  dialogVisible.value = true
}

function openEditDialog(user: User) {
  editingUser.value = user
  dialogVisible.value = true
}

async function handleSave(payload: UserDialogSavePayload) {
  saving.value = true
  try {
    if (editingUser.value) {
      await usersApi.updateUser(editingUser.value.id, {
        display_name: payload.displayName,
        role: payload.role,
      })
      ElMessage.success('用户已更新')
    } else {
      await usersApi.createUser({
        username: payload.username,
        password: payload.password,
        display_name: payload.displayName,
        role: payload.role,
      })
      ElMessage.success('用户已创建')
    }
    dialogVisible.value = false
    await loadUsers()
  } catch (e) {
    ElMessage.error((e as Error).message || '保存失败')
  } finally {
    saving.value = false
  }
}

function openResetPassword(user: User) {
  resetTarget.value = user
  resetDialogVisible.value = true
}

async function handleResetPassword(payload: UserPasswordResetPayload) {
  saving.value = true
  try {
    await usersApi.updateUser(payload.userId, { reset_password: payload.password })
    ElMessage.success('密码已重置')
    resetDialogVisible.value = false
  } catch (e) {
    ElMessage.error((e as Error).message || '重置失败')
  } finally {
    saving.value = false
  }
}

async function toggleActive(user: User) {
  const action = user.is_active ? '禁用' : '启用'
  try {
    await ElMessageBox.confirm(`确定要${action}用户「${user.display_name}」吗？`, '确认', {
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await usersApi.updateUser(user.id, { is_active: !user.is_active })
    ElMessage.success(`已${action}`)
    await loadUsers()
  } catch (e) {
    ElMessage.error((e as Error).message || '操作失败')
  }
}

onMounted(loadUsers)
</script>

<style scoped>
.users-page {
  padding: 24px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-header h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}
</style>
