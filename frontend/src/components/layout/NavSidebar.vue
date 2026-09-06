<script setup lang="ts">
import { computed } from 'vue'
import {
  ChatDotRound,
  DataAnalysis,
  Document,
  FolderOpened,
  Setting,
  User,
  SwitchButton,
} from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useAuthStore } from '../../stores/auth'

const auth = useAuthStore()
const router = useRouter()

const roleLabel = computed(() => {
  const map: Record<string, string> = { admin: '管理员', editor: '编辑者', viewer: '普通用户' }
  return map[auth.currentUser?.role || ''] || ''
})

async function handleLogout() {
  try {
    await ElMessageBox.confirm('确定要退出登录吗？', '退出确认', {
      confirmButtonText: '退出',
      cancelButtonText: '取消',
      type: 'warning',
    })
    auth.logout()
    router.push('/login')
  } catch {
    // 用户取消
  }
}
</script>

<template>
  <aside class="nav-sidebar">
    <div class="brand">知识库问答</div>
    <el-menu :default-active="$route.path" router class="nav-menu">
      <el-menu-item index="/">
        <el-icon><ChatDotRound /></el-icon>
        <span>问答</span>
      </el-menu-item>
      <el-menu-item index="/documents">
        <el-icon><FolderOpened /></el-icon>
        <span>文档管理</span>
      </el-menu-item>
      <el-menu-item index="/logs">
        <el-icon><Document /></el-icon>
        <span>运行日志</span>
      </el-menu-item>
      <el-menu-item index="/stats">
        <el-icon><DataAnalysis /></el-icon>
        <span>数据统计</span>
      </el-menu-item>
      <el-menu-item v-if="auth.isAdmin()" index="/users">
        <el-icon><User /></el-icon>
        <span>用户管理</span>
      </el-menu-item>
      <el-menu-item v-if="auth.isAdmin()" index="/settings">
        <el-icon><Setting /></el-icon>
        <span>系统设置</span>
      </el-menu-item>
    </el-menu>
    <div class="user-info" v-if="auth.currentUser">
      <div class="user-detail">
        <el-avatar :size="32" class="user-avatar">
          {{ auth.currentUser.display_name.charAt(0) }}
        </el-avatar>
        <div class="user-meta">
          <div class="user-name">{{ auth.currentUser.display_name }}</div>
          <div class="user-role">{{ roleLabel }}</div>
        </div>
      </div>
      <el-button
        text
        size="small"
        class="logout-btn"
        @click="handleLogout"
      >
        <el-icon><SwitchButton /></el-icon>
        退出
      </el-button>
    </div>
  </aside>
</template>

<style scoped>
.nav-sidebar {
  width: 180px;
  flex-shrink: 0;
  background: var(--card);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
}

.brand {
  padding: 16px 20px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

.nav-menu {
  border-right: none;
  flex: 1;
}

.user-info {
  padding: 12px 16px;
  border-top: 1px solid var(--border);
}

.user-detail {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.user-avatar {
  background: var(--accent, #409eff);
  color: #fff;
  flex-shrink: 0;
}

.user-meta {
  min-width: 0;
}

.user-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-role {
  font-size: 11px;
  color: var(--text-secondary);
}

.logout-btn {
  width: 100%;
  justify-content: center;
  color: var(--text-secondary);
}
</style>
