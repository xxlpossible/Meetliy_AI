<script setup lang="ts">
// 登录/注册页面
import { ref, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { useAuthStore } from '@/stores'
import BlankLayout from '@/layouts/BlankLayout.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const activeTab = ref<'login' | 'register'>('login')
const loading = ref(false)

const loginFormRef = ref<FormInstance>()
const registerFormRef = ref<FormInstance>()

const loginForm = reactive({ username: '', password: '' })
const registerForm = reactive({ username: '', password: '', confirmPassword: '' })

const loginRules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const registerRules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 20, message: '3-20位字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 20, message: '6-20位字符', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== registerForm.password) callback(new Error('两次密码不一致'))
        else callback()
      },
      trigger: 'blur',
    },
  ],
}

async function handleLogin() {
  if (!loginFormRef.value) return
  await loginFormRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      await auth.login({ username: loginForm.username, password: loginForm.password })
      ElMessage.success('登录成功')
      const redirect = (route.query.redirect as string) || '/dashboard'
      router.push(redirect)
    } catch (e: any) {
      ElMessage.error(e.message || '登录失败')
    } finally {
      loading.value = false
    }
  })
}

async function handleRegister() {
  if (!registerFormRef.value) return
  await registerFormRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      await auth.register({
        username: registerForm.username,
        password: registerForm.password,
        confirmPassword: registerForm.confirmPassword,
      })
      ElMessage.success('注册成功，请登录')
      activeTab.value = 'login'
      loginForm.username = registerForm.username
    } catch (e: any) {
      ElMessage.error(e.message || '注册失败')
    } finally {
      loading.value = false
    }
  })
}
</script>

<template>
  <BlankLayout>
    <div class="login-page">
      <aside class="brand-panel">
        <div class="brand-logo">
          <div class="brand-logo-icon">会</div>
          <span class="brand-logo-text">Meetily</span>
        </div>
        <div class="brand-tagline">
          <h1>让每次会议<br />都有回响</h1>
          <p>智能语音识别、实时转写、AI 纪要提取。从对话到知识，一步到位。</p>
        </div>
        <div class="brand-features">
          <div class="brand-feature"><div class="brand-feature-dot"></div><span>多人实时会议，≤4 人浏览器直连</span></div>
          <div class="brand-feature"><div class="brand-feature-dot"></div><span>录音文件上传，离线也能生成纪要</span></div>
          <div class="brand-feature"><div class="brand-feature-dot"></div><span>知识库关联，AI 深度对话</span></div>
          <div class="brand-feature"><div class="brand-feature-dot"></div><span>自动归档，所有会议一目了然</span></div>
        </div>
      </aside>

      <main class="form-panel">
        <div class="form-wrapper">
          <!-- 登录 -->
          <section v-show="activeTab === 'login'" class="form-section">
            <div class="form-header">
              <h2>欢迎回来</h2>
              <p>登录以继续您的会议工作空间</p>
            </div>
            <el-form ref="loginFormRef" :model="loginForm" :rules="loginRules" label-position="top">
              <el-form-item label="用户名" prop="username">
                <el-input v-model="loginForm.username" placeholder="输入您的用户名" size="large" />
              </el-form-item>
              <el-form-item label="密码" prop="password">
                <el-input v-model="loginForm.password" type="password" placeholder="输入您的密码" size="large" show-password @keyup.enter="handleLogin" />
              </el-form-item>
              <el-button type="primary" size="large" class="submit-btn" :loading="loading" @click="handleLogin">登 录</el-button>
            </el-form>
            <div class="form-switch">
              <p>还没有账号？<a @click="activeTab = 'register'">立即注册</a></p>
            </div>
          </section>

          <!-- 注册 -->
          <section v-show="activeTab === 'register'" class="form-section">
            <div class="form-header">
              <h2>创建账号</h2>
              <p>加入 Meetily，让会议更高效</p>
            </div>
            <el-form ref="registerFormRef" :model="registerForm" :rules="registerRules" label-position="top">
              <el-form-item label="用户名" prop="username">
                <el-input v-model="registerForm.username" placeholder="3-20位，字母开头" size="large" />
              </el-form-item>
              <el-form-item label="密码" prop="password">
                <el-input v-model="registerForm.password" type="password" placeholder="6-20位，含字母和数字" size="large" show-password />
              </el-form-item>
              <el-form-item label="确认密码" prop="confirmPassword">
                <el-input v-model="registerForm.confirmPassword" type="password" placeholder="再次输入密码" size="large" show-password @keyup.enter="handleRegister" />
              </el-form-item>
              <el-button type="primary" size="large" class="submit-btn" :loading="loading" @click="handleRegister">注 册</el-button>
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

.login-page {
  display: grid;
  grid-template-columns: 1fr 1fr;
  min-height: 100vh;
  overflow: hidden;
}

.brand-panel {
  background: linear-gradient(160deg, #2c241b 0%, #1a1612 100%);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 56px 48px;
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
}

.brand-logo {
  display: flex;
  align-items: center;
  gap: 14px;
  position: relative;
  z-index: 1;
}

.brand-logo-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--color-amber-400), var(--color-amber-500));
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  color: var(--color-stone-900);
  font-weight: 700;
  font-family: var(--font-display);
}

.brand-logo-text {
  font-family: var(--font-display);
  font-size: 26px;
  font-weight: 700;
  color: var(--color-stone-50);
  letter-spacing: 0.02em;
}

.brand-tagline {
  position: relative;
  z-index: 1;

  h1 {
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
    max-width: 360px;
  }
}

.brand-features {
  display: flex;
  flex-direction: column;
  gap: 16px;
  position: relative;
  z-index: 1;
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

.form-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px;
  overflow-y: auto;
}

.form-wrapper {
  width: 100%;
  max-width: 380px;
}

.form-section {
  animation: fadeSlideIn 0.35s ease-out;
}

@keyframes fadeSlideIn {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

.form-header {
  margin-bottom: 36px;

  h2 {
    font-size: 28px;
    font-weight: 700;
    color: var(--color-stone-800);
    margin-bottom: 8px;
  }

  p {
    font-size: 15px;
    color: var(--color-stone-500);
  }
}

:deep(.el-form-item__label) {
  font-size: 13px !important;
  font-weight: 600 !important;
  color: var(--color-stone-600) !important;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.submit-btn {
  width: 100%;
  margin-top: 8px;
  font-size: 15px;
  font-weight: 600;
}

.form-switch {
  text-align: center;
  margin-top: 24px;

  p {
    font-size: 14px;
    color: var(--color-stone-500);
  }

  a {
    color: var(--color-amber-600);
    font-weight: 600;
    cursor: pointer;
    transition: color var(--transition-fast);

    &:hover {
      color: var(--color-amber-500);
    }
  }
}

@include respond-to(md) {
  .login-page {
    grid-template-columns: 1fr;
  }
  .brand-panel {
    display: none;
  }
  .form-panel {
    padding: 32px 24px;
  }
}
</style>
