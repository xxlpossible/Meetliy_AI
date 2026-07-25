<script setup lang="ts">
// 默认布局：顶部导航栏 + 主内容区
import { useAuthStore } from '@/stores'
import { useRouter, useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const navItems = [
  { name: 'dashboard', label: '会议', icon: 'Calendar' },
  { name: 'knowledge', label: '知识库', icon: 'FolderOpened' },
  { name: 'chat', label: 'AI 对话', icon: 'ChatDotRound' },
]

async function handleLogout() {
  try {
    await ElMessageBox.confirm('确定要退出登录吗？', '提示', {
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
  <div class="default-layout">
    <header class="topbar">
      <div class="topbar-brand" @click="router.push('/dashboard')">
        <div class="topbar-logo">会</div>
        <span class="topbar-name">Meetily</span>
      </div>

      <nav class="topbar-nav">
        <button
          v-for="item in navItems"
          :key="item.name"
          class="nav-btn"
          :class="{ active: route.name?.toString().startsWith(item.name) }"
          @click="router.push({ name: item.name })"
        >
          <span>{{ item.label }}</span>
        </button>
      </nav>

      <div class="topbar-user">
        <div class="user-info">
          <div class="user-name">{{ auth.username || '用户' }}</div>
          <div class="user-role">会议参与者</div>
        </div>
        <div class="user-avatar">{{ auth.username?.charAt(0) || '?' }}</div>
        <button class="logout-btn" title="退出登录" @click="handleLogout">
          <el-icon><SwitchButton /></el-icon>
        </button>
      </div>
    </header>

    <main class="main-content">
      <slot />
    </main>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/mixins.scss' as *;

.default-layout {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.topbar {
  background: white;
  border-bottom: 1px solid var(--color-stone-200);
  padding: 0 $space-8;
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 100;
}

.topbar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
}

.topbar-logo {
  width: 36px;
  height: 36px;
  border-radius: 9px;
  background: linear-gradient(135deg, var(--color-amber-400), var(--color-amber-500));
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  color: var(--color-stone-900);
  font-weight: 700;
  font-family: var(--font-display);
}

.topbar-name {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 20px;
  color: var(--color-stone-800);
}

.topbar-nav {
  display: flex;
  align-items: center;
  gap: 8px;
}

.nav-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border: none;
  background: transparent;
  color: var(--color-stone-600);
  font-size: 14px;
  font-weight: 500;
  font-family: var(--font-body);
  cursor: pointer;
  border-radius: var(--radius-md);
  transition: all var(--transition-fast);

  &:hover {
    background: var(--color-stone-100);
    color: var(--color-stone-800);
  }

  &.active {
    background: var(--color-amber-50);
    color: var(--color-amber-600);
  }
}

.topbar-user {
  display: flex;
  align-items: center;
  gap: 12px;
}

.user-info {
  line-height: 1.3;
  text-align: right;
}

.user-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-stone-800);
}

.user-role {
  font-size: 12px;
  color: var(--color-stone-400);
}

.user-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--color-stone-200);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-stone-600);
}

.logout-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  color: var(--color-stone-400);
  cursor: pointer;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--transition-fast);

  &:hover {
    background: #fef2f2;
    color: var(--color-error);
  }
}

.main-content {
  flex: 1;
}

@include respond-to(md) {
  .topbar {
    padding: 0 $space-4;
  }
  .user-info {
    display: none;
  }
}
</style>
