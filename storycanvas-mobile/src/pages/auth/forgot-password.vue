<template>
  <view class="forgot-page">
    <view class="forgot-page__header">
      <text class="forgot-page__title">重置密码</text>
      <text class="forgot-page__subtitle">输入邮箱获取验证码</text>
    </view>

    <view class="forgot-page__form">
      <lv-input
        v-model="email"
        type="email"
        placeholder="邮箱"
        :error="emailError"
      />
      <lv-input
        v-model="code"
        placeholder="验证码"
        :error="codeError"
      />
      <lv-input
        v-model="newPassword"
        type="password"
        placeholder="新密码 (至少 6 位)"
        show-password-toggle
        :error="passwordError"
      />

      <view v-if="errorMsg" class="forgot-page__error">
        <text class="forgot-page__error-text">{{ errorMsg }}</text>
      </view>

      <lv-button
        block
        :loading="sendingCode"
        @tap="handleSendCode"
      >
        {{ codeSent ? `已发送 (${countdown}s)` : '发送验证码' }}
      </lv-button>

      <view style="height: 24rpx" />

      <lv-button
        block
        :loading="loading"
        @tap="handleReset"
      >
        重置密码
      </lv-button>

      <view class="forgot-page__link">
        <text class="forgot-page__link-text" @tap="goLogin">返回登录</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { authApi } from '@/api'
import LvInput from '@/components/lv-input/lv-input.vue'
import LvButton from '@/components/lv-button/lv-button.vue'

const email = ref('')
const code = ref('')
const newPassword = ref('')
const emailError = ref('')
const codeError = ref('')
const passwordError = ref('')
const errorMsg = ref('')
const loading = ref(false)
const sendingCode = ref(false)
const codeSent = ref(false)
const countdown = ref(60)

function validateEmail(): boolean {
  if (!email.value) {
    emailError.value = '请输入邮箱'
    return false
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value)) {
    emailError.value = '邮箱格式不正确'
    return false
  }
  emailError.value = ''
  return true
}

async function handleSendCode() {
  if (!validateEmail()) return

  sendingCode.value = true
  try {
    await authApi.sendEmailCode(email.value)
    codeSent.value = true
    startCountdown()
  } catch (e: any) {
    errorMsg.value = e.message || '发送失败'
  } finally {
    sendingCode.value = false
  }
}

function startCountdown() {
  countdown.value = 60
  const timer = setInterval(() => {
    countdown.value--
    if (countdown.value <= 0) {
      clearInterval(timer)
      codeSent.value = false
    }
  }, 1000)
}

function validate(): boolean {
  let valid = true
  errorMsg.value = ''

  if (!code.value) {
    codeError.value = '请输入验证码'
    valid = false
  } else {
    codeError.value = ''
  }

  if (!newPassword.value) {
    passwordError.value = '请输入新密码'
    valid = false
  } else if (newPassword.value.length < 6) {
    passwordError.value = '密码至少 6 位'
    valid = false
  } else {
    passwordError.value = ''
  }

  return valid
}

async function handleReset() {
  if (!validateEmail() || !validate()) return

  loading.value = true
  try {
    await authApi.resetPassword(email.value, code.value, newPassword.value)
    uni.showToast({ title: '密码已重置', icon: 'success' })
    setTimeout(() => {
      uni.navigateBack()
    }, 1500)
  } catch (e: any) {
    errorMsg.value = e.message || '重置失败'
  } finally {
    loading.value = false
  }
}

function goLogin() {
  uni.navigateBack()
}
</script>

<style lang="scss" scoped>
.forgot-page {
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
