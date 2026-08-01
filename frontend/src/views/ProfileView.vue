<script setup lang="ts">
// ============================================================
// ProfileView — 个人中心
// 功能：编辑头像 / 修改用户名 / 修改密码
// ============================================================
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules, UploadRequestOptions } from 'element-plus'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import { useAuthStore } from '@/stores'

const router = useRouter()
const auth = useAuthStore()

/** 提取后端返回的错误信息（避免显示 axios 的通用状态码文案） */
function getErrorMessage(e: any, fallback: string): string {
  return e?.response?.data?.detail || e?.message || fallback
}

// ========== 资料编辑 ==========
const profileFormRef = ref<FormInstance>()
const profileForm = reactive({ username: '', avatar: '' })
const savingProfile = ref(false)
const uploadingAvatar = ref(false)

const profileRules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { pattern: /^[a-zA-Z][a-zA-Z0-9_]{2,19}$/, message: '3-20位，字母开头，仅含字母、数字、下划线', trigger: 'blur' },
  ],
}

// 选图前置校验（返回 false 取消上传）
function beforeAvatarUpload(file: File): boolean {
  if (!/^image\/(png|jpe?g|gif|webp)$/.test(file.type)) {
    ElMessage.error('请上传 png/jpg/gif/webp 格式图片')
    return false
  }
  if (file.size > 2 * 1024 * 1024) {
    ElMessage.error('图片大小不能超过 2MB')
    return false
  }
  return true
}

// 自定义上传：直接把图片文件传给后端，后端上传 OSS 后返回 URL
async function handleAvatarUpload(options: UploadRequestOptions) {
  uploadingAvatar.value = true
  try {
    await auth.uploadAvatar(options.file as File)
    // 上传成功后，用最新的头像 URL 更新预览
    profileForm.avatar = auth.avatar || ''
    ElMessage.success('头像已更新')
    options.onSuccess?.({})
  } catch (e: any) {
    ElMessage.error(getErrorMessage(e, '头像上传失败，请稍后重试'))
    options.onError?.(e as Error)
  } finally {
    uploadingAvatar.value = false
  }
}

async function handleSaveProfile() {
  const valid = await profileFormRef.value?.validate().catch(() => false)
  if (!valid) return
  savingProfile.value = true
  try {
    const payload: { username?: string } = {}
    if (profileForm.username !== auth.username) payload.username = profileForm.username
    if (Object.keys(payload).length === 0) {
      ElMessage.info('没有需要保存的修改')
      return
    }
    await auth.updateProfile(payload)
    ElMessage.success('资料已更新')
  } catch (e: any) {
    ElMessage.error(getErrorMessage(e, '保存失败，请稍后重试'))
  } finally {
    savingProfile.value = false
  }
}

// ========== 修改密码 ==========
const pwdFormRef = ref<FormInstance>()
const pwdForm = reactive({ oldPassword: '', newPassword: '', confirmPassword: '' })
const changingPwd = ref(false)

/** 新密码安全要求：8-20 位，含字母和数字 */
const newPasswordValidator = (_rule: any, value: string, cb: (err?: Error) => void) => {
  if (!value) {
    cb(new Error('请输入新密码'))
    return
  }
  if (value.length < 8 || value.length > 20) {
    cb(new Error('新密码长度需为 8-20 位'))
    return
  }
  if (!/[A-Za-z]/.test(value) || !/\d/.test(value)) {
    cb(new Error('新密码必须同时包含字母和数字'))
    return
  }
  cb()
}

const pwdRules: FormRules = {
  oldPassword: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  newPassword: [{ validator: newPasswordValidator, trigger: 'blur' }],
  confirmPassword: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    { validator: (_rule, value, cb) => {
        if (value !== pwdForm.newPassword) cb(new Error('两次输入的新密码不一致'))
        else cb()
      }, trigger: 'blur' },
  ],
}

async function handleChangePassword() {
  const valid = await pwdFormRef.value?.validate().catch(() => false)
  if (!valid) return
  changingPwd.value = true
  try {
    await auth.changePassword({
      old_password: pwdForm.oldPassword,
      new_password: pwdForm.newPassword,
      confirm_password: pwdForm.confirmPassword,
    })
    ElMessage.success('密码修改成功，请重新登录')
    pwdFormRef.value?.resetFields()
    pwdForm.oldPassword = ''
    pwdForm.newPassword = ''
    pwdForm.confirmPassword = ''
    auth.logout()
    router.push('/login')
  } catch (e: any) {
    ElMessage.error(getErrorMessage(e, '修改密码失败，请稍后重试'))
  } finally {
    changingPwd.value = false
  }
}

onMounted(() => {
  profileForm.username = auth.username
  profileForm.avatar = auth.avatar || ''
})
</script>

<template>
  <DefaultLayout>
    <div class="profile-page">
      <!-- ========== 页头 ========== -->
      <div class="page-header">
        <div>
          <h1 class="page-title">个人中心</h1>
          <p class="page-subtitle">管理您的头像、用户名与密码</p>
        </div>
        <div class="quick-actions">
          <el-button text @click="router.push('/dashboard')">
            <el-icon><ArrowLeft /></el-icon>&nbsp;返回工作台
          </el-button>
        </div>
      </div>

      <!-- ========== 主体卡片 ========== -->
      <div class="profile-card">
        <!-- ===== 基础资料 ===== -->
        <div class="section">
          <h2 class="section-title">基础资料</h2>
          <el-form ref="profileFormRef" :model="profileForm" :rules="profileRules" label-position="top">
            <!-- 头像 -->
            <div class="avatar-row">
              <div class="avatar-preview">
                <img v-if="profileForm.avatar" :src="profileForm.avatar" class="avatar-img" alt="头像" />
                <div v-else class="avatar-placeholder">{{ (profileForm.username || '?').charAt(0) }}</div>
              </div>
              <div class="avatar-actions">
                <el-upload
                  :show-file-list="false"
                  :auto-upload="true"
                  accept=".png,.jpg,.jpeg,.gif,.webp"
                  :before-upload="beforeAvatarUpload"
                  :http-request="handleAvatarUpload"
                >
                  <el-button :loading="uploadingAvatar">更换头像</el-button>
                </el-upload>
                <p class="avatar-tip">支持 png/jpg/gif/webp，大小不超过 2MB</p>
              </div>
            </div>

            <!-- 用户名 -->
            <el-form-item prop="username">
              <template #label><span class="form-label">用户名</span></template>
              <el-input v-model="profileForm.username" placeholder="3-20位，字母开头" />
            </el-form-item>

            <div class="form-actions">
              <el-button type="primary" :loading="savingProfile" @click="handleSaveProfile">
                保存资料
              </el-button>
            </div>
          </el-form>
        </div>

        <!-- ===== 修改密码 ===== -->
        <div class="section">
          <h2 class="section-title">修改密码</h2>
          <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-position="top">
            <el-form-item prop="oldPassword">
              <template #label><span class="form-label">原密码</span></template>
              <el-input v-model="pwdForm.oldPassword" type="password" show-password placeholder="请输入原密码" />
            </el-form-item>
            <el-form-item prop="newPassword">
              <template #label><span class="form-label">新密码</span></template>
              <el-input v-model="pwdForm.newPassword" type="password" show-password placeholder="8-20位，含字母和数字" />
            </el-form-item>
            <el-form-item prop="confirmPassword">
              <template #label><span class="form-label">确认新密码</span></template>
              <el-input v-model="pwdForm.confirmPassword" type="password" show-password placeholder="再次输入新密码" @keyup.enter="handleChangePassword" />
            </el-form-item>

            <div class="form-actions">
              <el-button type="primary" :loading="changingPwd" @click="handleChangePassword">
                确认修改
              </el-button>
            </div>
          </el-form>
        </div>
      </div>
    </div>
  </DefaultLayout>
</template>

<style scoped lang="scss">
@use '@/styles/mixins.scss' as *;

.profile-page {
  max-width: 720px;
  margin: 0 auto;
  padding: $space-8;
}

// ============================================================
// 页头 — 与 Dashboard 等页面保持一致的 page-header 规范
// ============================================================
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: $space-8;
}

.page-title {
  font-size: 28px;
  font-weight: 700;
  color: var(--color-stone-800);
  font-family: var(--font-display);
}

.page-subtitle {
  font-size: 14px;
  color: var(--color-stone-500);
  margin-top: 4px;
}

.quick-actions {
  display: flex;
  gap: $space-3;
}

// ============================================================
// 主体卡片
// ============================================================
.profile-card {
  background: white;
  border: 1px solid var(--color-stone-200);
  border-radius: var(--radius-xl);
  padding: $space-8;
  box-shadow: var(--shadow-md);
  @include card-hover;
}

// 分区
.section {
  margin-bottom: $space-8;

  &:last-child {
    margin-bottom: 0;
  }
}

.section-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--color-stone-800);
  font-family: var(--font-display);
  margin-bottom: $space-6;
  padding-bottom: $space-3;
  border-bottom: 1px solid var(--color-stone-100);
  position: relative;

  &::after {
    content: '';
    position: absolute;
    left: 0;
    bottom: -1px;
    width: 48px;
    height: 2px;
    background: var(--color-amber-400);
    border-radius: $radius-full;
  }
}

.form-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-stone-600);
  letter-spacing: 0.02em;
}

// ============================================================
// 头像
// ============================================================
.avatar-row {
  display: flex;
  align-items: center;
  gap: $space-6;
  margin-bottom: $space-6;
}

.avatar-preview {
  width: 88px;
  height: 88px;
  border-radius: 50%;
  overflow: hidden;
  flex-shrink: 0;
  border: 2px solid var(--color-amber-200);
  background: var(--color-stone-50);
}

.avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.avatar-placeholder {
  width: 100%;
  height: 100%;
  background: var(--color-stone-100);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32px;
  font-weight: 700;
  color: var(--color-stone-500);
  font-family: var(--font-display);
}

.avatar-tip {
  font-size: 12px;
  color: var(--color-stone-400);
  margin-top: $space-2;
}

.form-actions {
  margin-top: $space-2;
  padding-top: $space-4;
  border-top: 1px solid var(--color-stone-100);
}

// ============================================================
// Element Plus 覆盖 — 与登录页表单风格一致
// ============================================================
::deep(.el-form-item) {
  margin-bottom: $space-6;
}

::deep(.el-form-item__label) {
  margin-bottom: 6px;
  padding-bottom: 0;
}

::deep(.el-input__wrapper) {
  border-radius: var(--radius-lg) !important;
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

::deep(.el-input__inner) {
  font-size: 14px !important;
  font-family: var(--font-body) !important;
  color: var(--color-stone-800) !important;
  height: 42px !important;
  line-height: 42px !important;

  &::placeholder {
    color: var(--color-stone-400) !important;
  }
}

::deep(.el-form-item__error) {
  font-size: 12px;
  padding-top: 4px;
}

// ============================================================
// 响应式
// ============================================================
@include respond-to(md) {
  .profile-page {
    padding: $space-4;
  }

  .page-header {
    flex-direction: column;
    align-items: flex-start;
    gap: $space-4;
  }

  .profile-card {
    padding: $space-6;
  }
}
</style>
