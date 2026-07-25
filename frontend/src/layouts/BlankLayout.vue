<script setup lang="ts">
// 空白布局（登录页等无导航页面）
</script>

<template>
  <div class="blank-layout">
    <slot />
  </div>
</template>

<style scoped>
.blank-layout {
  min-height: 100vh;
}
</style>
