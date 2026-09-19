<script setup lang="ts">
import type { User } from '../../types/auth'
import { formatDateTime } from '../../utils/format'

defineProps<{
  users: User[]
  loading: boolean
  currentUserId?: string
}>()

const emit = defineEmits<{
  (event: 'edit', user: User): void
  (event: 'reset-password', user: User): void
  (event: 'toggle-active', user: User): void
}>()

function roleLabel(role: string): string {
  return { admin: '管理员', editor: '编辑者', viewer: '普通用户' }[role] || role
}

function roleTagType(role: string): 'danger' | 'warning' | 'info' {
  const map: Record<string, 'danger' | 'warning' | 'info'> = { admin: 'danger', editor: 'warning', viewer: 'info' }
  return map[role] || 'info'
}

</script>

<template>
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
      <template #default="{ row }">{{ row.last_login_at ? formatDateTime(row.last_login_at) : '从未登录' }}</template>
    </el-table-column>
    <el-table-column label="创建时间" width="170">
      <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
    </el-table-column>
    <el-table-column label="操作" width="220" fixed="right">
      <template #default="{ row }">
        <el-button size="small" @click="emit('edit', row)">编辑</el-button>
        <el-button size="small" @click="emit('reset-password', row)">重置密码</el-button>
        <el-button
          size="small"
          :type="row.is_active ? 'warning' : 'success'"
          :disabled="row.id === currentUserId"
          @click="emit('toggle-active', row)"
        >
          {{ row.is_active ? '禁用' : '启用' }}
        </el-button>
      </template>
    </el-table-column>
  </el-table>
</template>
