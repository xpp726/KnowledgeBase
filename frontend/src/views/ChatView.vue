<script setup lang="ts">
import { onMounted } from 'vue'
import { useChatStore } from '../stores/chat'
import ConversationSidebar from '../components/chat/ConversationSidebar.vue'
import MessageList from '../components/chat/MessageList.vue'
import ChatInput from '../components/chat/ChatInput.vue'

const store = useChatStore()

onMounted(() => {
  void store.loadConversations()
})
</script>

<template>
  <div class="chat-view">
    <ConversationSidebar />
    <div class="chat-main">
      <MessageList />
      <ChatInput />
    </div>
  </div>
</template>

<style scoped>
.chat-view {
  flex: 1;
  display: flex;
  min-height: 0;
}

.chat-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
</style>
