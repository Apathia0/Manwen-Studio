<template>
  <view class="password-page">
    <lv-navbar title="修改密码" show-back />
    <view class="password-page__form">
      <lv-input v-model="oldPwd" label="原密码" type="password" placeholder="请输入原密码" />
      <lv-input v-model="newPwd" label="新密码" type="password" placeholder="请输入新密码" />
      <lv-input v-model="confirmPwd" label="确认密码" type="password" placeholder="再次输入新密码" />
      <lv-button block @tap="handleSubmit" style="margin-top: 48rpx;">确认修改</lv-button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { put } from '@/utils/request'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvInput from '@/components/lv-input/lv-input.vue'

const oldPwd = ref('')
const newPwd = ref('')
const confirmPwd = ref('')

async function handleSubmit() {
  if (!oldPwd.value || !newPwd.value || !confirmPwd.value) return uni.showToast({ title: '请填完所有字段', icon: 'none' })
  if (newPwd.value !== confirmPwd.value) return uni.showToast({ title: '两次密码不一致', icon: 'none' })
  if (newPwd.value.length < 6) return uni.showToast({ title: '密码至少6位', icon: 'none' })
  try {
    await put('/api/user/password', { old_password: oldPwd.value, new_password: newPwd.value })
    uni.showToast({ title: '修改成功', icon: 'success' })
    setTimeout(() => uni.navigateBack(), 1500)
  } catch (e: any) {
    uni.showToast({ title: e.message || '修改失败', icon: 'none' })
  }
}
</script>

<style lang="scss" scoped>
.password-page { min-height: 100vh; background: $lv-bg-start;
  &__form { padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding; }
}
</style>
