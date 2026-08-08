<script setup lang="ts">
// 默认布局：顶部导航栏(桌面) + 底部Tab栏(移动端) + 主内容区
import { ref } from 'vue'
import { useAuthStore } from '@/stores'
import { useRouter, useRoute } from 'vue-router'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const navItems = [
  { name: 'dashboard', label: '工作台', icon: 'Grid' },
  { name: 'chat', label: 'AI对话', icon: 'ChatDotRound' },
  { name: 'knowledge', label: '知识库', icon: 'FolderOpened' },
  { name: 'profile', label: '我的', icon: 'User' },
]

// 底部Tab按钮（仅移动端显示，4入口）
const tabItems = [
  { name: 'dashboard', label: '工作台', icon: 'Grid' },
  { name: 'chat', label: 'AI对话', icon: 'ChatDotRound' },
  { name: 'knowledge', label: '知识库', icon: 'FolderOpened' },
  { name: 'profile', label: '我的', icon: 'User' },
]

const showLogoutConfirm = ref(false)
const mobileMenuOpen = ref(false)

function handleLogout() {
  showLogoutConfirm.value = true
}

function confirmLogout() {
  showLogoutConfirm.value = false
  auth.logout()
  router.push('/login')
}

function handleNavClick(item: { name: string }) {
  mobileMenuOpen.value = false
  router.push({ name: item.name })
}

function handleTabClick(item: { name: string }) {
  router.push({ name: item.name })
}

function handleHomeClick() {
  mobileMenuOpen.value = false
  router.push('/dashboard')
}
</script>

<template>
  <div class="default-layout">
    <!-- 顶部导航栏 -->
    <header class="topbar">
      <div class="topbar-brand" @click="handleHomeClick">
        <img src="/icon.svg" alt="Meetily AI" class="topbar-logo" />
        <span class="topbar-name">Meetily AI</span>
      </div>

      <!-- 桌面端导航 -->
      <nav class="topbar-nav desktop-nav">
        <button
          v-for="item in navItems"
          :key="item.label"
          class="nav-btn"
          :class="{ active: route.name?.toString().startsWith(item.name) }"
          @click="handleNavClick(item)"
        >
          <el-icon class="nav-icon" :size="17">
            <component :is="item.icon" />
          </el-icon>
          <span>{{ item.label }}</span>
        </button>
      </nav>

      <!-- 移动端汉堡按钮 -->
      <button
        class="hamburger-btn"
        :class="{ open: mobileMenuOpen }"
        @click="mobileMenuOpen = !mobileMenuOpen"
        aria-label="切换导航菜单"
      >
        <span></span>
        <span></span>
        <span></span>
      </button>

      <div class="topbar-user">
        <div class="user-avatar-wrap" title="个人中心" @click="router.push('/profile')">
          <img v-if="auth.avatar" :src="auth.avatar" class="user-avatar-img" alt="头像" />
          <div v-else class="user-avatar-text">{{ auth.username?.charAt(0) || '?' }}</div>
          <span class="user-name">{{ auth.username || '用户' }}</span>
        </div>
        <button class="logout-btn" title="退出登录" @click="handleLogout">
          <el-icon><SwitchButton /></el-icon>
          <span class="logout-text">退出</span>
        </button>
      </div>
    </header>

    <!-- 移动端侧滑菜单 -->
    <Teleport to="body">
      <Transition name="drawer-fade">
        <div v-if="mobileMenuOpen" class="mobile-drawer-overlay" @click="mobileMenuOpen = false" />
      </Transition>
      <Transition name="drawer-slide">
        <nav v-if="mobileMenuOpen" class="mobile-drawer" @click.stop>
          <div class="drawer-header">
            <div class="topbar-brand" @click="handleHomeClick">
              <img src="/icon.svg" alt="Meetily AI" class="topbar-logo" />
              <span class="topbar-name">Meetily AI</span>
            </div>
          </div>
          <div class="drawer-nav">
            <button
              v-for="item in navItems"
              :key="item.label"
              class="drawer-nav-btn"
              :class="{ active: route.name?.toString().startsWith(item.name) }"
              @click="handleNavClick(item)"
            >
              <el-icon :size="20"><component :is="item.icon" /></el-icon>
              <span>{{ item.label }}</span>
            </button>
          </div>
          <div class="drawer-footer">
            <button class="drawer-nav-btn logout" @click="confirmLogout">
              <el-icon :size="20"><SwitchButton /></el-icon>
              <span>退出登录</span>
            </button>
          </div>
        </nav>
      </Transition>
    </Teleport>

    <!-- 主内容区 -->
    <main class="main-content">
      <slot />
    </main>

    <!-- 移动端底部Tab导航 -->
    <nav class="bottom-tabs">
      <button
        v-for="item in tabItems"
        :key="item.label"
        class="tab-item"
        :class="{ active: route.name?.toString().startsWith(item.name) }"
        @click="handleTabClick(item)"
      >
        <el-icon :size="22"><component :is="item.icon" /></el-icon>
        <span>{{ item.label }}</span>
      </button>
    </nav>

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
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  padding-bottom: var(--safe-area-bottom);
}

// ============================================================
// 顶部导航栏
// ============================================================
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
  object-fit: contain;
  display: block;
  flex-shrink: 0;
}

.topbar-name {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 20px;
  color: var(--color-stone-800);
  letter-spacing: 0.01em;
  white-space: nowrap;
}

// 桌面导航
.topbar-nav {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: $space-8;
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

  &:hover {
    color: var(--color-stone-800);
  }

  &.active {
    color: var(--color-amber-600);
    font-weight: 600;

    &::after {
      transform: scaleX(1);
    }
  }
}

// 用户区
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

.user-avatar-text,
.user-avatar-img {
  width: 34px;
  height: 34px;
  border-radius: 50%;
}

.user-avatar-text {
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
  @include text-ellipsis;
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
  // 移动端为底部Tab留出空间
  padding-bottom: 0;
}

// ============================================================
// 汉堡按钮（移动端）
// ============================================================
.hamburger-btn {
  display: none;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  gap: 5px;
  width: 44px;
  height: 44px;
  border: none;
  background: transparent;
  cursor: pointer;
  padding: 10px;
  border-radius: $radius-md;
  transition: background 0.15s;
  @include touch-target;

  span {
    display: block;
    width: 20px;
    height: 2px;
    background: var(--color-stone-700);
    border-radius: 2px;
    transition: all 0.3s ease;
  }

  &:hover {
    background: var(--color-stone-100);
  }

  &.open {
    span:nth-child(1) { transform: translateY(7px) rotate(45deg); }
    span:nth-child(2) { opacity: 0; }
    span:nth-child(3) { transform: translateY(-7px) rotate(-45deg); }
  }
}

// ============================================================
// 移动端侧滑抽屉（左侧滑入）
// ============================================================
.mobile-drawer-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(3px);
  z-index: 200;
}

.drawer-fade-enter-active { transition: opacity 0.3s ease; }
.drawer-fade-leave-active { transition: opacity 0.25s ease; }
.drawer-fade-enter-from,
.drawer-fade-leave-to { opacity: 0; }

.mobile-drawer {
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  width: min(300px, 80vw);
  background: white;
  z-index: 201;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-xl);
}

.drawer-slide-enter-active { transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1); }
.drawer-slide-leave-active { transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1); }
.drawer-slide-enter-from,
.drawer-slide-leave-to { transform: translateX(-100%); }

.drawer-header {
  padding: 24px 20px 16px;
  border-bottom: 1px solid var(--color-stone-100);
}

.drawer-nav {
  flex: 1;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
}

.drawer-nav-btn {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 14px 16px;
  border: none;
  background: transparent;
  color: var(--color-stone-600);
  font-size: 15px;
  font-weight: 500;
  font-family: var(--font-body);
  cursor: pointer;
  border-radius: var(--radius-md);
  transition: all 0.15s;
  text-align: left;
  @include touch-target;

  &:active {
    background: var(--color-stone-100);
  }

  &.active {
    background: var(--color-amber-50);
    color: var(--color-amber-600);
    font-weight: 600;
  }

  &.logout {
    color: var(--color-error);

    &:active {
      background: #fef2f2;
    }
  }
}

.drawer-footer {
  padding: 16px 12px;
  border-top: 1px solid var(--color-stone-100);
}

// ============================================================
// 移动端底部Tab导航
// ============================================================
.bottom-tabs {
  display: none;
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 100;
  justify-content: space-around;
  align-items: center;
  @include glass-nav;
  padding: 6px 0 max(6px, var(--safe-area-bottom));
}

.tab-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 4px 10px;
  color: var(--color-stone-400);
  font-size: 10px;
  font-weight: 500;
  cursor: pointer;
  transition: color var(--transition-fast);
  border: none;
  background: none;
  font-family: var(--font-body);
  @include touch-target;

  &:active { opacity: 0.7; }

  &.active {
    color: var(--color-amber-500);

    :deep(.el-icon) {
      color: var(--color-amber-400);
    }
  }
}

// ============================================================
// 响应式
// ============================================================
@include respond-to(md) {
  .topbar {
    padding: 0 $space-4;
  }

  .user-avatar-wrap .user-name {
    display: none;
  }

  .topbar-nav {
    gap: $space-6;
  }

  .nav-btn {
    padding: 0 12px;

    span {
      display: none;
    }
  }
}

@include respond-to(sm) {
  .desktop-nav {
    display: none;
  }

  // 手机端去掉汉堡按钮（已有底部 Tab 导航）
  .hamburger-btn {
    display: none;
  }

  // 手机端头部同样显示 logo 文字（缩小字号适配窄屏）
  .topbar-brand .topbar-name {
    display: inline;
    font-size: 17px;
  }

  .topbar-user {
    gap: 0;
  }

  .logout-btn {
    padding: 0 8px;
  }

  // 显示底部Tab导航
  .bottom-tabs {
    display: flex;
  }

  // 主内容区为底部Tab留空间
  .main-content {
    padding-bottom: 68px;
  }
}
</style>
