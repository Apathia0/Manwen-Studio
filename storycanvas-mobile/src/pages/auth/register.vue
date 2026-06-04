<template>
  <view class="register-page">
    <view class="register-page__header">
      <text class="register-page__title">注册账号</text>
      <text class="register-page__subtitle">创建账号开始创作之旅</text>
    </view>

    <view class="register-page__form">
      <lv-input
        v-model="name"
        placeholder="用户名"
        :error="nameError"
      />
      <lv-input
        v-model="email"
        type="email"
        placeholder="邮箱"
        :error="emailError"
      />
      <lv-input
        v-model="password"
        type="password"
        placeholder="密码 (至少 6 位)"
        show-password-toggle
        :error="passwordError"
      />

      <view v-if="errorMsg" class="register-page__error">
        <text class="register-page__error-text">{{ errorMsg }}</text>
      </view>

      <lv-button
        block
        :loading="loading"
        @tap="handleRegister"
      >
        注册
      </lv-button>

      <view class="register-page__link">
        <text class="register-page__link-text" @tap="goLogin">已有账号？立即登录</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import LvInput from '@/components/lv-input/lv-input.vue'
import LvButton from '@/components/lv-button/lv-button.vue'

const authStore = useAuthStore()

const name = ref('')
const email = ref('')
const password = ref('')
const nameError = ref('')
const emailError = ref('')
const passwordError = ref('')
const errorMsg = ref('')
const loading = ref(false)

function validate(): boolean {
  let valid = true
  nameError.value = ''
  emailError.value = ''
  passwordError.value = ''
  errorMsg.value = ''

  if (!name.value) {
    nameError.value = '请输入用户名'
    valid = false
  }

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

async function handleRegister() {
  if (!validate()) return

  loading.value = true
  try {
    await authStore.register(name.value, email.value, password.value)
    uni.switchTab({ url: '/pages/index/index' })
  } catch (e: any) {
    errorMsg.value = e.message || '注册失败，请重试'
  } finally {
    loading.value = false
  }
}

function goLogin() {
  uni.navigateBack()
}
</script>

<style lang="scss" scoped>
.register-page {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);
  padding: $lv-page-padding;

  &__header {
    margin-top: 120rpx;
    margin-bottom: 64rpx;
  }

  &__title {
    display: block;
    font-size: $lv-font-3xl;
    font-weight: 700;
    color: $lv-text-primary;
    margin-bottom: 12rpx;
  }

  &__subtitle {
    display: block;
    font-size: $lv-font-base;
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

  &__link {
    margin-top: 32rpx;
    text-align: center;
  }

  &__link-text {
    font-size: $lv-font-sm;
    color: $lv-primary;

    &:active {
      opacity: 0.7;
    }
  }
}
</style>
