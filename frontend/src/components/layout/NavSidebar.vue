<script setup lang="ts">
import {
  ChatDotRound,
  DataAnalysis,
  Document,
  FolderOpened,
  Setting,
} from '@element-plus/icons-vue'
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
      <el-menu-item index="/settings">
        <el-icon><Setting /></el-icon>
        <span>系统设置</span>
      </el-menu-item>
    </el-menu>
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
</style>
