<template>
  <div class="users-page">
    <div class="page-header">
      <h2>用户管理</h2>
      <el-button type="primary" @click="openCreateDialog">
        <el-icon><Plus /></el-icon>
        新建用户
      </el-button>
    </div>

    <el-table :data="users" v-loading="loading" stripe style="width: 100%">
      <el-table-column prop="username" label="用户名" width="140" />
      <el-table-column prop="display_name" label="姓名" width="140" />
      <el-table-column label="角色" width="100">
        <template #default="{ row }">
          <el-tag :type="roleTagType(row.role)" size="small">{{ roleLabel(row.role) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '启用' : '禁用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="最后登录" width="170">
        <template #default="{ row }">
          {{ row.last_login_at ? formatTime(row.last_login_at) : '从未登录' }}
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="170">
        <template #default="{ row }">
          {{ formatTime(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openEditDialog(row)">编辑</el-button>
          <el-button size="small" @click="openResetPassword(row)">重置密码</el-button>
          <el-button
            size="small"
            :type="row.is_active ? 'warning' : 'success'"
            :disabled="row.id === auth.currentUser?.id"
            @click="toggleActive(row)"
          >
            {{ row.is_active ? '禁用' : '启用' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建/编辑用户弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingUser ? '编辑用户' : '新建用户'"
      width="420px"
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" :disabled="!!editingUser" placeholder="登录用户名" />
        </el-form-item>
        <el-form-item label="姓名" prop="display_name">
          <el-input v-model="form.display_name" placeholder="显示姓名" />
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
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSubmit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 重置密码弹窗 -->
    <el-dialog v-model="resetDialogVisible" title="重置密码" width="380px">
      <el-form :model="resetForm" label-width="80px">
        <el-form-item label="用户">
          <span>{{ resetTarget?.display_name }}（{{ resetTarget?.username }}）</span>
        </el-form-item>
        <el-form-item label="新密码" prop="newPassword">
          <el-input v-model="resetForm.newPassword" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resetDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleResetPassword">确认重置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import * as usersApi from '../api/users'
import { useAuthStore } from '../stores/auth'
import type { User, UserRole } from '../types/api'

const auth = useAuthStore()
const users = ref<User[]>([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const resetDialogVisible = ref(false)
const editingUser = ref<User | null>(null)
const resetTarget = ref<User | null>(null)
const formRef = ref<FormInstance>()

const form = reactive({
  username: '',
  display_name: '',
  password: '',
  role: 'viewer' as UserRole,
})

const resetForm = reactive({
  newPassword: '',
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  display_name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
  ],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
}

function roleLabel(role: string): string {
  return { admin: '管理员', editor: '编辑者', viewer: '普通用户' }[role] || role
}

function roleTagType(role: string): 'danger' | 'warning' | 'info' {
  const map: Record<string, 'danger' | 'warning' | 'info'> = { admin: 'danger', editor: 'warning', viewer: 'info' }
  return map[role] || 'info'
}

function formatTime(ts: number): string {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  return d.toLocaleString('zh-CN', { hour12: false })
}

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
  form.username = ''
  form.display_name = ''
  form.password = ''
  form.role = 'viewer'
  editingUser.value = null
}

function openCreateDialog() {
  resetFormData()
  dialogVisible.value = true
}

function openEditDialog(user: User) {
  editingUser.value = user
  form.username = user.username
  form.display_name = user.display_name
  form.role = user.role
  dialogVisible.value = true
}

async function handleSubmit() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    saving.value = true
    try {
      if (editingUser.value) {
        await usersApi.updateUser(editingUser.value.id, {
          display_name: form.display_name,
          role: form.role,
        })
        ElMessage.success('用户已更新')
      } else {
        await usersApi.createUser({
          username: form.username,
          password: form.password,
          display_name: form.display_name,
          role: form.role,
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
  })
}

function openResetPassword(user: User) {
  resetTarget.value = user
  resetForm.newPassword = ''
  resetDialogVisible.value = true
}

async function handleResetPassword() {
  if (!resetTarget.value) return
  if (resetForm.newPassword.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  saving.value = true
  try {
    await usersApi.updateUser(resetTarget.value.id, { reset_password: resetForm.newPassword })
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
