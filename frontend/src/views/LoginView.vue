<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores'
import BlankLayout from '@/layouts/BlankLayout.vue'
import type { FormInstance, FormRules } from 'element-plus'

const router = useRouter()
const authStore = useAuthStore()

const activeTab = ref<'login' | 'register'>('login')
const loading = ref(false)

// ========== 登录 ==========
const loginFormRef = ref<FormInstance>()
const loginForm = reactive({ username: '', password: '' })
const loginRules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function handleLogin() {
  const valid = await loginFormRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    await authStore.login({ username: loginForm.username, password: loginForm.password })
    router.push('/dashboard')
  } catch (e: any) {
    ElMessage.error(e.message || '登录失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

// ========== 注册 ==========
const registerFormRef = ref<FormInstance>()
const registerForm = reactive({ username: '', password: '', confirmPassword: '' })

/** 密码规则：8-20 位，且必须同时包含字母和数字 */
const passwordValidator = (_rule: any, value: string, cb: (err?: Error) => void) => {
  if (!value) { cb(new Error('请输入密码')); return }
  if (value.length < 8 || value.length > 20) { cb(new Error('密码长度需为 8-20 位')); return }
  if (!/[A-Za-z]/.test(value) || !/\d/.test(value)) { cb(new Error('密码必须同时包含字母和数字')); return }
  cb()
}

const registerRules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ validator: passwordValidator, trigger: 'blur' }],
  confirmPassword: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    { validator: (_rule, value, cb) => {
        if (value !== registerForm.password) cb(new Error('两次输入的密码不一致'))
        else cb()
      }, trigger: 'blur' },
  ],
}

async function handleRegister() {
  const valid = await registerFormRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    await authStore.register({ username: registerForm.username, password: registerForm.password, confirmPassword: registerForm.confirmPassword })
    ElMessage.success('注册成功，请登录')
    registerForm.username = ''
    registerForm.password = ''
    registerForm.confirmPassword = ''
    registerFormRef.value?.resetFields()
    activeTab.value = 'login'
  } catch (e: any) {
    ElMessage.error(e.message || '注册失败，请稍后重试')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <BlankLayout>
    <div class="login-page">
      <!-- ===== 左侧品牌面板 ===== -->
      <aside class="brand-panel">
        <div class="brand-inner">
          <div class="brand-logo">
            <img src="/icon.svg" alt="Meetily AI" class="brand-logo-img" />
            <span class="brand-logo-text">Meetily AI</span>
          </div>
          <div class="brand-tagline">
            <h1>每一次会议<br />都值得被记住</h1>
            <p>AI 驱动的会议助手，提供实时转写、智能摘要与知识库检索。</p>
          </div>
          <div class="brand-features">
            <div class="brand-feature">
              <span class="brand-feature-dot"></span> 实时语音转写，支持多人会议
            </div>
            <div class="brand-feature">
              <span class="brand-feature-dot"></span> AI 自动生成会议摘要与行动项
            </div>
            <div class="brand-feature">
              <span class="brand-feature-dot"></span> 知识库检索，随时查阅会议上下文
            </div>
          </div>
        </div>
      </aside>

      <!-- ===== 右侧表单面板 ===== -->
      <main class="form-panel">
        <!-- 移动端：表单上方 logo（桌面端隐藏） -->
        <div class="mobile-brand">
          <img src="/icon.svg" alt="Meetily AI" class="mobile-brand-img" />
          <span class="mobile-brand-text">Meetily AI</span>
        </div>

        <div class="form-card">
          <!-- 登录 -->
          <section v-show="activeTab === 'login'" class="form-section">
            <div class="form-header">
              <h2>欢迎回来</h2>
              <p>登录以继续</p>
            </div>
            <el-form ref="loginFormRef" :model="loginForm" :rules="loginRules" label-position="top" @keyup.enter="handleLogin">
              <el-form-item prop="username">
                <template #label><span class="custom-label">用户名</span></template>
                <el-input v-model="loginForm.username" placeholder="输入您的用户名" size="large" />
              </el-form-item>
              <el-form-item prop="password">
                <template #label><span class="custom-label">密码</span></template>
                <el-input v-model="loginForm.password" type="password" placeholder="输入您的密码" size="large" show-password />
              </el-form-item>
              <button type="button" class="login-submit-btn" :disabled="loading" @click="handleLogin">
                <span v-if="loading" class="btn-spinner"></span>
                {{ loading ? '登录中...' : '登 录' }}
              </button>
            </el-form>
            <div class="form-switch">
              <p>还没有账号？<a @click="activeTab = 'register'">立即注册</a></p>
            </div>
          </section>

          <!-- 注册 -->
          <section v-show="activeTab === 'register'" class="form-section">
            <div class="form-header">
              <h2>创建账号</h2>
              <p>加入 Meetily AI</p>
            </div>
            <el-form ref="registerFormRef" :model="registerForm" :rules="registerRules" label-position="top" @keyup.enter="handleRegister">
              <el-form-item prop="username">
                <template #label><span class="custom-label">用户名</span></template>
                <el-input v-model="registerForm.username" placeholder="3-20位，字母开头" size="large" />
              </el-form-item>
              <el-form-item prop="password">
                <template #label><span class="custom-label">密码</span></template>
                <el-input v-model="registerForm.password" type="password" placeholder="8-20位，含字母和数字" size="large" show-password />
              </el-form-item>
              <el-form-item prop="confirmPassword">
                <template #label><span class="custom-label">确认密码</span></template>
                <el-input v-model="registerForm.confirmPassword" type="password" placeholder="再次输入密码" size="large" show-password />
              </el-form-item>
              <button type="button" class="login-submit-btn" :disabled="loading" @click="handleRegister">
                <span v-if="loading" class="btn-spinner"></span>
                {{ loading ? '注册中...' : '注 册' }}
              </button>
            </el-form>
            <div class="form-switch">
              <p>已有账号？<a @click="activeTab = 'login'">立即登录</a></p>
            </div>
          </section>
        </div>
      </main>
    </div>
  </BlankLayout>
</template>

<style scoped lang="scss">
@use '@/styles/mixins.scss' as *;

// ---- 双栏布局 ----
.login-page {
  display: grid;
  grid-template-columns: 1fr 1fr;
  min-height: 100vh;
  overflow: hidden;
}

// ============================================================
// 左侧品牌面板
// ============================================================
.brand-panel {
  background: linear-gradient(160deg, #2c241b 0%, #1a1612 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;

  &::before {
    content: '';
    position: absolute;
    top: -120px;
    right: -120px;
    width: 400px;
    height: 400px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(245, 180, 0, 0.08) 0%, transparent 70%);
    pointer-events: none;
  }

  &::after {
    content: '';
    position: absolute;
    bottom: -80px;
    left: -80px;
    width: 260px;
    height: 260px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(245, 180, 0, 0.05) 0%, transparent 70%);
    pointer-events: none;
  }
}

.brand-inner {
  position: relative;
  z-index: 1;
  max-width: 380px;
}

.brand-logo {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 48px;
}

.brand-logo-img {
  width: 44px;
  height: 44px;
  object-fit: contain;
}

.brand-logo-text {
  font-family: var(--font-display);
  font-size: 26px;
  font-weight: 700;
  color: var(--color-stone-50);
  letter-spacing: 0.02em;
}

.brand-tagline {
  margin-bottom: 40px;

  h1 {
    font-family: var(--font-display);
    font-size: 48px;
    font-weight: 700;
    color: var(--color-stone-50);
    line-height: 1.25;
    margin-bottom: 24px;
    letter-spacing: -0.01em;
  }

  p {
    font-size: 17px;
    color: var(--color-stone-400);
    line-height: 1.7;
  }
}

.brand-features {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.brand-feature {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--color-stone-400);
  font-size: 14px;
}

.brand-feature-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-amber-400);
  flex-shrink: 0;
}

// ============================================================
// 右侧表单面板
// ============================================================
.form-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px;
  overflow-y: auto;
  background: var(--color-stone-50);
}

.form-card {
  width: 100%;
  max-width: 420px;
  background: white;
  border: 1px solid var(--color-stone-200);
  border-radius: 20px;
  padding: 48px 40px 40px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.04);
}

.form-section {
  animation: fadeSlideIn 0.35s ease-out;
}

@keyframes fadeSlideIn {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

.form-header {
  margin-bottom: 32px;

  h2 {
    font-family: var(--font-display);
    font-size: 26px;
    font-weight: 700;
    color: var(--color-stone-800);
    margin-bottom: 6px;
  }

  p {
    font-size: 14px;
    color: var(--color-stone-500);
  }
}

.custom-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-stone-600);
  letter-spacing: 0.04em;
}

// ---- Element Plus 表单覆盖 ----
::deep(.el-form-item) { margin-bottom: 20px; }
::deep(.el-form-item__label) { margin-bottom: 6px; padding-bottom: 0; }

::deep(.el-input__wrapper) {
  border-radius: 12px !important;
  border: 1.5px solid var(--color-stone-200) !important;
  background: var(--color-stone-50) !important;
  box-shadow: none !important;
  padding: 4px 16px !important;
  transition: all 0.2s;
}
::deep(.el-input.is-focus .el-input__wrapper) {
  border-color: var(--color-amber-400) !important;
  background: white !important;
  box-shadow: 0 0 0 3px rgba(245, 180, 0, 0.08) !important;
}
::deep(.el-input.is-error .el-input__wrapper) { border-color: var(--color-error) !important; }
::deep(.el-input__inner) {
  font-size: 14px !important;
  font-family: var(--font-body) !important;
  color: var(--color-stone-800) !important;
  height: 42px !important;
  line-height: 42px !important;
  &::placeholder { color: var(--color-stone-400) !important; }
}
::deep(.el-input__suffix) { color: var(--color-stone-400); }
::deep(.el-input__suffix-inner) { font-size: 16px; }
::deep(.el-form-item__error) { font-size: 12px; padding-top: 4px; }

// ---- 提交按钮 ----
.login-submit-btn {
  width: 100%;
  margin-top: 12px;
  padding: 14px 0;
  border: none;
  border-radius: 12px;
  background: linear-gradient(135deg, var(--color-amber-400), var(--color-amber-500));
  color: white;
  font-size: 15px;
  font-weight: 600;
  font-family: var(--font-body);
  cursor: pointer;
  letter-spacing: 0.08em;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;

  &:hover:not(:disabled) {
    transform: translateY(-1px);
    box-shadow: 0 4px 16px rgba(245, 180, 0, 0.3);
  }
  &:active:not(:disabled) { transform: translateY(0); }
  &:disabled { opacity: 0.6; cursor: not-allowed; }
}

.btn-spinner {
  display: inline-block;
  width: 15px;
  height: 15px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

// ---- 移动端 Logo 头（默认隐藏，仅小屏显示） ----
.mobile-brand {
  display: none;
}

// ---- 切换提示 ----
.form-switch {
  text-align: center;
  margin-top: 24px;

  p { font-size: 14px; color: var(--color-stone-500); }

  a {
    color: var(--color-amber-600);
    font-weight: 600;
    cursor: pointer;
    transition: color 0.15s;
    &:hover { color: var(--color-amber-500); }
  }
}

// ---- 响应式 ----
@include respond-to(md) {
  .login-page {
    grid-template-columns: 1fr;
  }
  .brand-panel { display: none; }
  .form-panel {
    padding: 32px 24px;
    flex-direction: column;
    gap: 28px;
  }

  .mobile-brand {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
  }

  .mobile-brand-img {
    width: 44px;
    height: 44px;
    object-fit: contain;
  }

  .mobile-brand-text {
    font-family: var(--font-display);
    font-size: 24px;
    font-weight: 700;
    color: var(--color-stone-800);
  }

  .form-card { padding: 36px 28px; }
}

@include respond-to(sm) {
  .form-panel {
    padding: 24px 16px;
    flex-direction: column;
    gap: 24px;
  }

  .mobile-brand {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
  }

  .mobile-brand-img {
    width: 40px;
    height: 40px;
    object-fit: contain;
  }

  .mobile-brand-text {
    font-family: var(--font-display);
    font-size: 22px;
    font-weight: 700;
    color: var(--color-stone-800);
  }

  .form-card {
    padding: 28px 20px;
    border-radius: 16px;
  }

  .form-header {
    margin-bottom: 24px;
    h2 { font-size: 22px; }
  }

  .login-submit-btn {
    padding: 12px 0;
    font-size: 14px;
  }
}
</style>
