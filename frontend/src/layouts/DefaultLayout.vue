<script setup lang="ts">
// 默认布局：顶部导航栏 + 主内容区
import { ref } from 'vue'
import { useAuthStore } from '@/stores'
import { useRouter, useRoute } from 'vue-router'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const navItems = [
  { name: 'dashboard', label: '会议', icon: 'Calendar' },
  { name: 'knowledge', label: '知识库', icon: 'FolderOpened' },
  { name: 'chat', label: 'AI 对话', icon: 'ChatDotRound' },
]

const showLogoutConfirm = ref(false)

function handleLogout() {
  showLogoutConfirm.value = true
}

function confirmLogout() {
  showLogoutConfirm.value = false
  auth.logout()
  router.push('/login')
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
          <el-icon class="nav-icon" :size="17">
            <component :is="item.icon" />
          </el-icon>
          <span>{{ item.label }}</span>
        </button>
      </nav>

      <div class="topbar-user">
        <div class="user-avatar-wrap" title="个人中心" @click="router.push('/profile')">
          <img v-if="auth.avatar" :src="auth.avatar" class="user-avatar-img" alt="头像" />
          <div v-else class="user-avatar">{{ auth.username?.charAt(0) || '?' }}</div>
          <span class="user-name">{{ auth.username || '用户' }}</span>
        </div>
        <button class="logout-btn" title="退出登录" @click="handleLogout">
          <el-icon><SwitchButton /></el-icon>
          <span class="logout-text">退出</span>
        </button>
      </div>
    </header>

    <main class="main-content">
      <slot />
    </main>

    <!-- 退出登录确认弹窗 -->
    <ConfirmDialog
      :visible="showLogoutConfirm"
      title="退出登录"
      message="确定要退出登录吗？"
      confirm-text="退出"
      cancel-text="取消"
      type="warning"
      @close="showLogoutConfirm = false"
      @confirm="confirmLogout"
    />
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
  margin-right: $space-6;
}

.topbar-logo {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--color-amber-400), var(--color-amber-500));
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  color: var(--color-stone-900);
  font-weight: 700;
  font-family: var(--font-display);
  box-shadow: 0 2px 6px rgba(245, 158, 11, 0.35);
}

.topbar-name {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 20px;
  color: var(--color-stone-800);
  letter-spacing: 0.01em;
}

// ============================================================
// 导航 — 置于品牌与用户区之间，自动居中留白
// ============================================================
.topbar-nav {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: $space-4;
  height: 100%;
}

.nav-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 14px;
  border: none;
  background: transparent;
  color: var(--color-stone-500);
  font-size: 15px;
  font-weight: 500;
  font-family: var(--font-body);
  cursor: pointer;
  height: 100%;
  position: relative;
  transition: color var(--transition-fast);

  // 底部激活指示条
  &::after {
    content: '';
    position: absolute;
    left: 14px;
    right: 14px;
    bottom: 0;
    height: 3px;
    border-radius: $radius-full;
    background: var(--color-amber-400);
    transform: scaleX(0);
    transform-origin: center;
    transition: transform var(--transition-normal);
  }

  .nav-icon {
    transition: transform var(--transition-fast);
  }

  &:hover {
    color: var(--color-stone-800);

    .nav-icon {
      transform: translateY(-1px);
    }
  }

  &.active {
    color: var(--color-amber-600);
    font-weight: 600;

    &::after {
      transform: scaleX(1);
    }
  }
}

// ============================================================
// 用户区
// ============================================================
.topbar-user {
  display: flex;
  align-items: center;
  gap: $space-2;
  margin-left: auto;
}

.user-avatar-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  padding: 6px 12px 6px 6px;
  border-radius: $radius-full;
  border: 1.5px solid transparent;
  transition: all var(--transition-fast);

  &:hover {
    background: var(--color-stone-50);
    border-color: var(--color-amber-200);
  }
}

.user-avatar,
.user-avatar-img {
  width: 34px;
  height: 34px;
  border-radius: 50%;
}

.user-avatar {
  background: linear-gradient(135deg, var(--color-stone-200), var(--color-stone-300));
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-stone-600);
  font-family: var(--font-display);
}

.user-avatar-img {
  object-fit: cover;
  display: block;
}

.user-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-stone-800);
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.logout-btn {
  height: 34px;
  padding: 0 14px;
  border: none;
  background: transparent;
  color: var(--color-stone-400);
  cursor: pointer;
  border-radius: $radius-full;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  font-family: var(--font-body);
  transition: all var(--transition-fast);

  .logout-text {
    display: none;
  }

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

  .user-avatar-wrap {
    .user-name {
      display: none;
    }
  }

  .logout-btn {
    .logout-text {
      display: none;
    }
  }

  .nav-btn {
    padding: 0 12px;
  }
}

@include respond-to(sm) {
  .topbar-brand .topbar-name {
    display: none;
  }

  .topbar-nav {
    position: static;
    transform: none;
    margin: 0 auto;
  }
}
</style>
