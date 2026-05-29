<template>
  <view class="login-page">
    <view class="login-page__header">
      <lv-icon name="PenLine" :size="48" />
      <text class="login-page__title">漫文工坊</text>
      <text class="login-page__subtitle">AI 创作 · 漫画生成</text>
    </view>

    <view class="login-page__carousel">
      <swiper class="login-page__swiper" autoplay circular indicator-dots indicator-color="rgba(37, 99, 235, 0.3)" indicator-active-color="#2563eb">
        <swiper-item v-for="(feature, index) in features" :key="index">
          <view class="login-page__feature">
            <view class="login-page__feature-icon">
              <lv-icon :name="feature.icon" :size="32" color="#2563eb" />
            </view>
            <text class="login-page__feature-title">{{ feature.title }}</text>
            <text class="login-page__feature-desc">{{ feature.desc }}</text>
          </view>
        </swiper-item>
      </swiper>
    </view>

    <view class="login-page__form">
      <lv-input
        v-model="email"
        type="email"
        placeholder="邮箱"
        :error="emailError"
      />
      <lv-input
        v-model="password"
        type="password"
        placeholder="密码"
        show-password-toggle
        :error="passwordError"
      />

      <view v-if="errorMsg" class="login-page__error">
        <text class="login-page__error-text">{{ errorMsg }}</text>
      </view>

      <lv-button
        block
        :loading="loading"
        @tap="handleLogin"
      >
        登录
      </lv-button>

      <view class="login-page__links">
        <text class="login-page__link" @tap="goRegister">还没有账号？立即注册</text>
        <text class="login-page__link" @tap="goForgotPassword">忘记密码？</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import LvInput from '@/components/lv-input/lv-input.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'

const authStore = useAuthStore()

const email = ref('')
const password = ref('')
const emailError = ref('')
const passwordError = ref('')
const errorMsg = ref('')
const loading = ref(false)

const features = [
  { icon: 'Sparkles', title: 'AI 智能写作', desc: '基于 DeepSeek 的强大 AI 能力' },
  { icon: 'Palette', title: '一键漫画生成', desc: '自动分镜，生成精美漫画' },
  { icon: 'BookOpen', title: '专业故事框架', desc: '三幕结构，角色塑造' }
]

function validate(): boolean {
  let valid = true
  emailError.value = ''
  passwordError.value = ''
  errorMsg.value = ''

  if (!email.value) {
    emailError.value = '请输入邮箱'
    valid = false
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value)) {
    emailError.value = '邮箱格式不正确'
    valid = false
  }

  if (!password.value) {
    passwordError.value = '请输入密码'
    valid = false
  } else if (password.value.length < 6) {
    passwordError.value = '密码至少 6 位'
    valid = false
  }

  return valid
}

async function handleLogin() {
  if (!validate()) return

  loading.value = true
  try {
    await authStore.login(email.value, password.value)
    uni.switchTab({ url: '/pages/index/index' })
  } catch (e: any) {
    errorMsg.value = e.message || '登录失败，请重试'
  } finally {
    loading.value = false
  }
}

function goRegister() {
  uni.navigateTo({ url: '/pages/auth/register' })
}

function goForgotPassword() {
  uni.navigateTo({ url: '/pages/auth/forgot-password' })
}
</script>

<style lang="scss" scoped>
.login-page {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);
  padding: $lv-page-padding;

  &__header {
    display: flex;
    flex-direction: column;
    align-items: center;
    margin-top: 80rpx;
    margin-bottom: 48rpx;
  }

  &__logo {
    margin-bottom: 16rpx;
  }

  &__title {
    font-size: $lv-font-3xl;
    font-weight: 700;
    color: $lv-text-primary;
    margin-bottom: 8rpx;
  }

  &__subtitle {
    font-size: $lv-font-base;
    color: $lv-text-secondary;
  }

  &__carousel {
    margin-bottom: 48rpx;
  }

  &__swiper {
    height: 240rpx;
  }

  &__feature {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: $lv-card-padding;
    box-shadow: $lv-shadow-sm;
  }

  &__feature-icon {
    margin-bottom: 16rpx;
    display: flex;
    justify-content: center;
  }

  &__feature-title {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 8rpx;
  }

  &__feature-desc {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__form {
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: 40rpx 32rpx;
    box-shadow: $lv-shadow-sm;
  }

  &__error {
    margin-bottom: 24rpx;
    text-align: center;
  }

  &__error-text {
    font-size: $lv-font-sm;
    color: $lv-error;
  }

  &__links {
    display: flex;
    justify-content: space-between;
    margin-top: 32rpx;
  }

  &__link {
    font-size: $lv-font-sm;
    color: $lv-primary;

    &:active {
      opacity: 0.7;
    }
  }
}
</style>
