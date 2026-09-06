<script setup lang="ts">
import NavSidebar from './NavSidebar.vue'
</script>

<template>
  <div class="app-layout">
    <NavSidebar />
    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.app-layout {
  display: flex;
  height: 100%;
}

.app-main {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
</style>
