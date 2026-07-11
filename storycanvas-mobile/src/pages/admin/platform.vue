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
          <lv-input v-model="settings.api.image_size" placeholder="默认尺寸，如 1024x1024；留空不覆盖" />
          <lv-input v-model="settings.api.image_quality" placeholder="quality，如 auto / high / medium / low" />
          <lv-input v-model="settings.api.image_background" placeholder="background，如 auto / transparent / opaque" />
          <lv-input v-model="settings.api.image_moderation" placeholder="moderation，如 auto / low" />
          <lv-input v-model="settings.api.image_output_format" placeholder="output_format，如 png / jpeg / webp" />
          <lv-input v-model="settings.api.image_output_compression" placeholder="output_compression，0-100" />
          <lv-input v-model="settings.api.image_input_fidelity" placeholder="edits input_fidelity，如 high / low" />

          <text class="admin-platform__section-title">视频模型服务</text>
          <lv-input v-model="settings.api.video_base_url" placeholder="视频服务 Base URL" />
          <lv-input v-model="settings.api.video_model" placeholder="视频模型名称" />
          <lv-input v-model="settings.api.video_api_key" placeholder="视频 API Key" type="password" />

          <text class="admin-platform__section-title">云存储 OSS</text>
          <view class="admin-platform__checkboxes">
            <view class="admin-platform__checkbox" @tap="settings.api.oss_enabled = !settings.api.oss_enabled">
              <lv-icon :name="settings.api.oss_enabled ? 'CheckSquare' : 'Square'" :size="18" :color="settings.api.oss_enabled ? '#2563eb' : '#94a3b8'" />
              <text>启用 OSS 云存储</text>
            </view>
          </view>
          <lv-input :model-value="settings.api.oss_access_key_id || ''" placeholder="Access Key ID" @update:model-value="settings.api.oss_access_key_id = $event" />
          <lv-input :model-value="settings.api.oss_access_key_secret || ''" placeholder="Access Key Secret" type="password" @update:model-value="settings.api.oss_access_key_secret = $event" />
          <lv-input :model-value="settings.api.oss_endpoint || ''" placeholder="Endpoint，如 oss-cn-hangzhou.aliyuncs.com" @update:model-value="settings.api.oss_endpoint = $event" />
          <lv-input :model-value="settings.api.oss_bucket || ''" placeholder="Bucket 名称" @update:model-value="settings.api.oss_bucket = $event" />
          <lv-input :model-value="settings.api.oss_public_url_base || ''" placeholder="公网域名（可选），如 https://cdn.yourdomain.com" @update:model-value="settings.api.oss_public_url_base = $event" />

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
          <lv-input :model-value="String(settings.auth.email_code_expire_minutes)" placeholder="验证码有效期（分钟）" type="number" @update:model-value="settings.auth.email_code_expire_minutes = Number($event)" />
          <lv-input :model-value="String(settings.auth.email_code_length)" placeholder="验证码位数" type="number" @update:model-value="settings.auth.email_code_length = Number($event)" />

          <text class="admin-platform__section-title">SMTP 配置</text>
          <view class="admin-platform__checkbox" @tap="settings.email.smtp_enabled = !settings.email.smtp_enabled">
            <lv-icon :name="settings.email.smtp_enabled ? 'CheckSquare' : 'Square'" :size="18" :color="settings.email.smtp_enabled ? '#2563eb' : '#94a3b8'" />
            <text>启用 SMTP</text>
          </view>
          <lv-input v-model="settings.email.smtp_host" placeholder="SMTP Host" />
          <lv-input :model-value="String(settings.email.smtp_port)" placeholder="SMTP Port" type="number" @update:model-value="settings.email.smtp_port = Number($event)" />
          <lv-input v-model="settings.email.smtp_username" placeholder="SMTP 用户名" />
          <lv-input v-model="settings.email.smtp_password" placeholder="SMTP 密码" type="password" />
          <lv-input v-model="settings.email.smtp_from_email" placeholder="发件邮箱" />
          <lv-input v-model="settings.email.smtp_from_name" placeholder="发件人名称" />
        </view>

        <!-- 支付配置 -->
        <view v-if="activeTab === 3" class="admin-platform__section">
          <text class="admin-platform__section-title">支付方式</text>
          <view class="admin-platform__checkboxes">
            <view class="admin-platform__checkbox" @tap="settings.payment.enabled = !settings.payment.enabled">
              <lv-icon :name="settings.payment.enabled ? 'CheckSquare' : 'Square'" :size="18" :color="settings.payment.enabled ? '#2563eb' : '#94a3b8'" />
              <text>启用支付</text>
            </view>
          </view>
          <picker :range="paymentMethodOptions" range-key="label" :value="activePaymentIndex" @change="handlePaymentMethodChange">
            <view class="admin-platform__picker">
              <text>{{ paymentMethodOptions[activePaymentIndex]?.label || '关闭' }}</text>
              <lv-icon name="ChevronDown" :size="16" color="#64748b" />
            </view>
          </picker>
          <lv-input v-model="settings.payment.order_expire_minutes" placeholder="订单超时（分钟）" type="number" />
          <lv-textarea v-model="settings.payment.instructions" placeholder="支付说明" />

          <template v-if="settings.payment.mapay_enabled">
            <text class="admin-platform__section-title">码支付参数</text>
            <lv-input v-model="settings.payment.mapay_gateway" placeholder="网关地址 https://pay.21lili.cn" />
            <lv-input v-model="settings.payment.mapay_pid" placeholder="商户ID" />
            <lv-input v-model="settings.payment.mapay_key" placeholder="商户密钥" type="password" />
            <lv-input v-model="settings.payment.mapay_type" placeholder="开放通道，如 alipay,wxpay,qqpay,usdt" />
            <lv-input v-model="settings.payment.mapay_notify_url" placeholder="异步通知地址" />
            <lv-input v-model="settings.payment.mapay_return_url" placeholder="同步跳转地址" />
          </template>
        </view>
      </template>

      <view class="admin-platform__footer">
        <lv-button :loading="saving" @tap="handleSave" block>保存平台配置</lv-button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
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

const paymentMethodOptions = [
  { value: 'closed', label: '关闭' },
  { value: 'wechat', label: '微信支付' },
  { value: 'alipay', label: '支付宝' },
  { value: 'epay', label: '易支付' },
  { value: 'mapay', label: '码支付' }
]

const activePaymentMethod = computed(() => {
  const pm = settings.value?.payment
  if (!pm?.enabled) return 'closed'
  if (pm.wechat_enabled) return 'wechat'
  if (pm.alipay_enabled) return 'alipay'
  if (pm.epay_enabled) return 'epay'
  if (pm.mapay_enabled) return 'mapay'
  return 'closed'
})

const activePaymentIndex = computed(() => {
  const index = paymentMethodOptions.findIndex((item) => item.value === activePaymentMethod.value)
  return index >= 0 ? index : 0
})

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

function handlePaymentMethodChange(event: any) {
  if (!settings.value) return
  const option = paymentMethodOptions[Number(event.detail?.value || 0)] || paymentMethodOptions[0]
  const pm = settings.value.payment
  pm.enabled = option.value !== 'closed'
  pm.wechat_enabled = option.value === 'wechat'
  pm.alipay_enabled = option.value === 'alipay'
  pm.epay_enabled = option.value === 'epay'
  pm.mapay_enabled = option.value === 'mapay'
  if (option.value === 'wechat') pm.default_method = 'wechat_qr'
  else if (option.value === 'alipay') pm.default_method = 'alipay_qr'
  else if (option.value === 'epay') pm.default_method = 'epay_qr'
  else if (option.value === 'mapay') {
    pm.default_method = 'mapay_qr'
    pm.mapay_gateway = pm.mapay_gateway || 'https://pay.21lili.cn'
    pm.mapay_type = pm.mapay_type || 'alipay'
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

  &__picker {
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: 88rpx;
    padding: 0 24rpx;
    margin-bottom: 16rpx;
    border: 1rpx solid $lv-border-light;
    border-radius: $lv-radius-md;
    color: $lv-text-primary;
    background: $lv-surface-solid;
  }

  &__footer {
    margin-top: 32rpx;
  }
}
</style>
