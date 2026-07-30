<script setup lang="ts">
// ============================================================
// ConfirmDialog — 通用确认弹窗，与系统"温暖工作室"风格一致
// ============================================================
import { watch, onUnmounted } from 'vue'

const props = withDefaults(defineProps<{
  visible: boolean
  title?: string
  subtitle?: string
  message?: string
  highlightText?: string
  confirmText?: string
  cancelText?: string
  type?: 'warning' | 'danger'
  icon?: string
}>(), {
  title: '提示',
  subtitle: '',
  message: '',
  confirmText: '确认',
  cancelText: '取消',
  type: 'warning',
  icon: '⚠',
})

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'confirm'): void
}>()

function handleOverlayClick() {
  emit('close')
}

function handleCancel() {
  emit('close')
}

function handleConfirm() {
  emit('confirm')
}

// ESC 关闭
function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.visible) {
    emit('close')
  }
}

watch(() => props.visible, (val) => {
  if (val) {
    document.addEventListener('keydown', handleKeydown)
  } else {
    document.removeEventListener('keydown', handleKeydown)
  }
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="confirm-overlay" @click.self="handleOverlayClick">
      <div class="confirm-modal">
        <!-- 头部 -->
        <div class="confirm-header">
          <div>
            <h2 class="confirm-title">{{ title }}</h2>
            <p class="confirm-subtitle">{{ subtitle || '此操作不可恢复，请确认' }}</p>
          </div>
          <button class="confirm-close" @click="handleCancel">✕</button>
        </div>

        <!-- 内容 -->
        <div class="confirm-body">
          <div class="confirm-content" :class="`confirm-type-${type}`">
            <div class="confirm-icon">{{ icon }}</div>
            <p class="confirm-message">
              <template v-if="highlightText">
                {{ message.split(highlightText)[0] }}<span class="confirm-highlight">{{ highlightText }}</span>{{ message.split(highlightText)[1] || '' }}
              </template>
              <template v-else>
                {{ message }}
              </template>
            </p>
          </div>
        </div>

        <!-- 底部按钮 -->
        <div class="confirm-footer">
          <button class="cfm-btn-cancel" @click="handleCancel">{{ cancelText }}</button>
          <button
            class="cfm-btn-confirm"
            :class="`cfm-btn-${type}`"
            @click="handleConfirm"
          >
            {{ confirmText }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped lang="scss">
// ---- 遮罩层 ----
.confirm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  backdrop-filter: blur(3px);
}

// ---- 弹窗主体 ----
.confirm-modal {
  background: white;
  border-radius: 20px;
  padding: 0;
  width: 100%;
  max-width: 400px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12);
  animation: confirmIn 0.25s ease-out;
  overflow: hidden;
}

@keyframes confirmIn {
  from { opacity: 0; transform: scale(0.95) translateY(10px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

// ---- 头部 ----
.confirm-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24px 28px 16px;
}

.confirm-title {
  font-family: var(--font-display, 'Noto Serif SC', serif);
  font-size: 20px;
  font-weight: 700;
  color: var(--color-stone-800);
}

.confirm-subtitle {
  font-size: 13px;
  color: var(--color-stone-500);
  margin-top: 4px;
}

.confirm-close {
  width: 32px;
  height: 32px;
  border: none;
  background: var(--color-stone-100);
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-stone-500);
  transition: all 0.15s;
  font-size: 14px;

  &:hover {
    background: var(--color-stone-200);
    color: var(--color-stone-700);
  }
}

// ---- 内容 ----
.confirm-body {
  padding: 0 28px 24px;
}

.confirm-content {
  text-align: center;
  padding: 20px 0;
}

.confirm-icon {
  font-size: 40px;
  margin-bottom: 12px;
  opacity: 0.6;
}

.confirm-message {
  font-size: 14px;
  color: var(--color-stone-600);
  line-height: 1.6;
}

.confirm-highlight {
  font-weight: 600;
  color: var(--color-stone-800);
}

// 类型色彩
.confirm-type-warning .confirm-icon {
  color: var(--color-warning, #f59e0b);
}

.confirm-type-danger .confirm-icon {
  color: var(--color-error, #ef4444);
}

// ---- 底部 ----
.confirm-footer {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  padding: 16px 28px;
  border-top: 1px solid var(--color-stone-100);
  background: var(--color-stone-50);
}

// 取消按钮
.cfm-btn-cancel {
  padding: 10px 20px;
  border: 1.5px solid var(--color-stone-200);
  border-radius: 8px;
  background: white;
  color: var(--color-stone-700);
  font-size: 14px;
  font-weight: 500;
  font-family: var(--font-body, 'Inter', 'PingFang SC', sans-serif);
  cursor: pointer;
  transition: all 0.15s;

  &:hover {
    background: var(--color-stone-50);
    border-color: var(--color-stone-300);
  }
}

// 确认按钮
.cfm-btn-confirm {
  padding: 10px 24px;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  font-family: var(--font-body, 'Inter', 'PingFang SC', sans-serif);
  cursor: pointer;
  transition: all 0.2s;

  &:hover {
    transform: translateY(-1px);
  }
}

.cfm-btn-warning {
  background: var(--color-warning, #f59e0b);
  color: white;

  &:hover {
    background: #d97706;
    box-shadow: 0 4px 12px rgba(245, 158, 11, 0.25);
  }
}

.cfm-btn-danger {
  background: var(--color-error, #ef4444);
  color: white;

  &:hover {
    background: #dc2626;
    box-shadow: 0 4px 12px rgba(220, 38, 38, 0.25);
  }
}
</style>
