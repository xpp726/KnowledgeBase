<script setup lang="ts">
// 会话侧栏：列表 / 新建 / 改名（就地编辑）/ 删除（确认弹窗）/ 切换
import { ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useChatStore } from '../../stores/chat'

const store = useChatStore()
const { conversations, currentId } = storeToRefs(store)

const editingId = ref<string | null>(null)
const editingTitle = ref('')

function startEdit(id: string, title: string) {
  editingId.value = id
  editingTitle.value = title || '新会话'
}

function confirmEdit() {
  const title = editingTitle.value.trim()
  if (title && editingId.value) void store.renameConversation(editingId.value, title)
  editingId.value = null
}

function remove(id: string) {
  void store.removeConversation(id)
}

function select(id: string) {
  if (editingId.value) return
  void store.switchConversation(id)
}

function newConv() {
  store.newConversation()
}
</script>

<template>
  <aside class="conv-sidebar">
    <div class="conv-toolbar">
      <span class="conv-toolbar-title">会话</span>
      <el-button size="small" type="primary" plain @click="newConv">
        <el-icon><Plus /></el-icon>
        <span>新建</span>
      </el-button>
    </div>

    <div class="conv-list">
      <!-- 未选会话时的"新会话"占位项 -->
      <div class="conv-item" :class="{ active: !currentId }" @click="newConv">
        <span class="conv-title">新会话</span>
      </div>

      <div v-if="!conversations.length" class="conv-empty">
        暂无历史会话，提问将自动创建
      </div>

      <el-popover
        v-for="conv in conversations"
        :key="conv.id"
        :visible="editingId === conv.id"
        placement="left"
        width="220"
        trigger="manual"
        @hide="editingId = null"
      >
        <template #reference>
          <div
            class="conv-item"
            :class="{ active: conv.id === currentId }"
            @click="select(conv.id)"
          >
            <span class="conv-title">{{ conv.title || '新会话' }}</span>
            <span class="conv-actions" @click.stop>
              <el-button link size="small" @click="startEdit(conv.id, conv.title)">
                <el-icon><EditPen /></el-icon>
              </el-button>
              <el-popconfirm
                title="删除该会话？"
                confirm-button-text="删除"
                cancel-button-text="取消"
                width="180"
                @confirm="remove(conv.id)"
              >
                <template #reference>
                  <el-button link size="small">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </template>
              </el-popconfirm>
            </span>
          </div>
        </template>

        <div class="conv-edit">
          <el-input
            v-model="editingTitle"
            size="small"
            autofocus
            @keyup.enter="confirmEdit"
          />
          <div class="conv-edit-actions">
            <el-button size="small" type="primary" @click="confirmEdit">确定</el-button>
            <el-button size="small" @click="editingId = null">取消</el-button>
          </div>
        </div>
      </el-popover>
    </div>
  </aside>
</template>

<style scoped>
.conv-sidebar {
  width: 240px;
  flex-shrink: 0;
  border-right: 1px solid var(--border);
  background: var(--card);
  display: flex;
  flex-direction: column;
}

.conv-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
}

.conv-toolbar-title {
  font-size: 14px;
  font-weight: 600;
}

.conv-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.conv-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  margin-bottom: 2px;
  transition: background 0.15s;
}

.conv-item:hover {
  background: rgba(139, 200, 234, 0.1);
}

.conv-item.active {
  background: rgba(139, 200, 234, 0.22);
  font-weight: 500;
}

.conv-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-actions {
  display: none;
  align-items: center;
  gap: 0;
}

.conv-item:hover .conv-actions {
  display: flex;
}

.conv-empty {
  padding: 12px 10px;
  font-size: 12px;
  color: var(--text-secondary);
  text-align: center;
}

.conv-edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}
</style>
