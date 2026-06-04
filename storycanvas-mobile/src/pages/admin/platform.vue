<template>
  <view class="admin-platform">
    <view class="admin-platform__content">
      <lv-swiper-tabs
        :tabs="['基础信息', 'AI API', '认证邮箱', '支付配置']"
        v-model:current="activeTab"
      />

      <lv-loading v-if="loading" />

      <template v-else-if="settings">
        <!-- 基础信息 -->
        <view v-if="activeTab === 0" class="admin-platform__section">
          <lv-input v-model="settings.basic.site_name" placeholder="平台名称" />
          <lv-input v-model="settings.basic.site_slogan" placeholder="平台副标题" />
          <lv-input v-model="settings.basic.support_email" placeholder="客服邮箱" />
          <lv-input v-model="settings.basic.icp" placeholder="ICP 备案号" />
          <lv-input v-model="settings.basic.copyright" placeholder="版权信息" />
          <lv-textarea v-model="settings.basic.notice" placeholder="运营公告/首页提示" />
        </view>

        <!-- AI API -->
        <view v-if="activeTab === 1" class="admin-platform__section">
          <text class="admin-platform__section-title">文本模型服务</text>
          <lv-input v-model="settings.api.deepseek_base_url" placeholder="DeepSeek Base URL" />
          <lv-input v-model="settings.api.deepseek_model" placeholder="DeepSeek 模型名称" />
          <lv-input v-model="settings.api.deepseek_api_key" placeholder="DeepSeek API Key" type="password" />

          <text class="admin-platform__section-title">图片模型服务</text>
          <lv-input v-model="settings.api.image_base_url" placeholder="图片服务 Base URL" />
          <lv-input v-model="settings.api.image_model" placeholder="图片模型名称" />
          <lv-input v-model="settings.api.image_api_key" placeholder="图片 API Key" type="password" />

          <view class="admin-platform__checkboxes">
            <view class="admin-platform__checkbox" @tap="settings.api.enable_user_override = !settings.api.enable_user_override">
              <lv-icon :name="settings.api.enable_user_override ? 'CheckSquare' : 'Square'" :size="18" :color="settings.api.enable_user_override ? '#2563eb' : '#94a3b8'" />
              <text>允许用户覆盖 API Key</text>
            </view>
            <view class="admin-platform__checkbox" @tap="settings.api.enable_user_url_override = !settings.api.enable_user_url_override">
              <lv-icon :name="settings.api.enable_user_url_override ? 'CheckSquare' : 'Square'" :size="18" :color="settings.api.enable_user_url_override ? '#2563eb' : '#94a3b8'" />
              <text>允许用户覆盖 URL/模型</text>
            </view>
          </view>
        </view>

        <!-- 认证邮箱 -->
        <view v-if="activeTab === 2" class="admin-platform__section">
          <text class="admin-platform__section-title">登录注册验证</text>
          <view class="admin-platform__checkboxes">
            <view class="admin-platform__checkbox" @tap="settings.auth.require_email_code_for_register = !settings.auth.require_email_code_for_register">
              <lv-icon :name="settings.auth.require_email_code_for_register ? 'CheckSquare' : 'Square'" :size="18" :color="settings.auth.require_email_code_for_register ? '#2563eb' : '#94a3b8'" />
              <text>注册必须验证邮箱</text>
            </view>
            <view class="admin-platform__checkbox" @tap="settings.auth.require_email_code_for_login = !settings.auth.require_email_code_for_login">
              <lv-icon :name="settings.auth.require_email_code_for_login ? 'CheckSquare' : 'Square'" :size="18" :color="settings.auth.require_email_code_for_login ? '#2563eb' : '#94a3b8'" />
              <text>登录必须验证邮箱</text>
            </view>
          </view>
          <lv-input v-model="settings.auth.email_code_expire_minutes" placeholder="验证码有效期（分钟）" type="number" />
          <lv-input v-model="settings.auth.email_code_length" placeholder="验证码位数" type="number" />

          <text class="admin-platform__section-title">SMTP 配置</text>
          <view class="admin-platform__checkbox" @tap="settings.email.smtp_enabled = !settings.email.smtp_enabled">
            <lv-icon :name="settings.email.smtp_enabled ? 'CheckSquare' : 'Square'" :size="18" :color="settings.email.smtp_enabled ? '#2563eb' : '#94a3b8'" />
            <text>启用 SMTP</text>
          </view>
          <lv-input v-model="settings.email.smtp_host" placeholder="SMTP Host" />
          <lv-input v-model="settings.email.smtp_port" placeholder="SMTP Port" type="number" />
          <lv-input v-model="settings.email.smtp_username" placeholder="SMTP 用户名" />
          <lv-input v-model="settings.email.smtp_password" placeholder="SMTP 密码" type="password" />
          <lv-input v-model="settings.email.smtp_from_email" placeholder="发件邮箱" />
          <lv-input v-model="settings.email.smtp_from_name" placeholder="发件人名称" />
        </view>

        <!-- 支付配置 -->
        <view v-if="activeTab === 3" class="admin-platform__section">
          <view class="admin-platform__checkboxes">
            <view class="admin-platform__checkbox" @tap="settings.payment.enabled = !settings.payment.enabled">
              <lv-icon :name="settings.payment.enabled ? 'CheckSquare' : 'Square'" :size="18" :color="settings.payment.enabled ? '#2563eb' : '#94a3b8'" />
              <text>启用支付</text>
            </view>
            <view class="admin-platform__checkbox" @tap="settings.payment.mock_enabled = !settings.payment.mock_enabled">
              <lv-icon :name="settings.payment.mock_enabled ? 'CheckSquare' : 'Square'" :size="18" :color="settings.payment.mock_enabled ? '#2563eb' : '#94a3b8'" />
              <text>模拟支付</text>
            </view>
          </view>
          <lv-input v-model="settings.payment.order_expire_minutes" placeholder="订单超时（分钟）" type="number" />
          <lv-textarea v-model="settings.payment.instructions" placeholder="支付说明" />
        </view>
      </template>

      <view class="admin-platform__footer">
        <lv-button :loading="saving" @tap="handleSave" block>保存平台配置</lv-button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { adminApi } from '@/api'
import type { PlatformSettings } from '@/api/admin'
import LvSwiperTabs from '@/components/lv-swiper-tabs/lv-swiper-tabs.vue'
import LvInput from '@/components/lv-input/lv-input.vue'
import LvTextarea from '@/components/lv-textarea/lv-textarea.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'

const loading = ref(false)
const saving = ref(false)
const activeTab = ref(0)
const settings = ref<PlatformSettings | null>(null)

onMounted(async () => {
  loading.value = true
  try {
    settings.value = await adminApi.getAdminPlatformSettings()
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
})

async function handleSave() {
  if (!settings.value) return
  saving.value = true
  try {
    settings.value = await adminApi.updateAdminPlatformSettings(settings.value)
    uni.showToast({ title: '保存成功', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '保存失败', icon: 'none' })
  } finally {
    saving.value = false
  }
}
</script>

<style lang="scss" scoped>
.admin-platform {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: $lv-page-padding;
  }

  &__section {
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: 32rpx;
    margin-top: 20rpx;
    box-shadow: $lv-shadow-sm;
  }

  &__section-title {
    display: block;
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
    margin-top: 24rpx;
    margin-bottom: 16rpx;

    &:first-child {
      margin-top: 0;
    }
  }

  &__checkboxes {
    display: flex;
    flex-wrap: wrap;
    gap: 24rpx;
    margin: 16rpx 0;
  }

  &__checkbox {
    display: flex;
    align-items: center;
    gap: 8rpx;
  }

  &__footer {
    margin-top: 32rpx;
  }
}
</style>
