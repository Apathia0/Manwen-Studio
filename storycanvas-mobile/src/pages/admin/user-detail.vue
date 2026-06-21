<template>
  <view class="user-detail">
    <lv-navbar :title="user?.name || '用户详情'" show-back />

    <view class="user-detail__content">
      <lv-loading v-if="loading" />

      <template v-else-if="user">
        <!-- 账号信息 -->
        <view class="user-detail__section">
          <text class="user-detail__section-title">账号信息</text>
          <lv-input v-model="editUser.name" placeholder="姓名" />
          <lv-input v-model="editUser.email" placeholder="邮箱" />
          <view class="user-detail__row">
            <text class="user-detail__row-label">角色：</text>
            <view class="user-detail__tag-group">
              <lv-tag
                :type="editUser.role === 'admin' ? 'primary' : 'default'"
                text="管理员"
                size="sm"
                @tap="editUser.role = 'admin'"
              />
              <lv-tag
                :type="editUser.role === 'user' ? 'primary' : 'default'"
                text="普通用户"
                size="sm"
                @tap="editUser.role = 'user'"
              />
            </view>
          </view>
          <view class="user-detail__row">
            <text class="user-detail__row-label">状态：</text>
            <view class="user-detail__tag-group">
              <lv-tag
                :type="editUser.status === 'active' ? 'success' : 'danger'"
                :text="editUser.status === 'active' ? '启用' : '停用'"
                size="sm"
                @tap="editUser.status = editUser.status === 'active' ? 'disabled' : 'active'"
              />
            </view>
          </view>
          <view class="user-detail__actions">
            <lv-button :loading="saving" @tap="handleSaveUser">保存账号信息</lv-button>
            <lv-button type="danger" @tap="handleDeleteUser">停用账号</lv-button>
          </view>
        </view>

        <!-- 套餐调整 -->
        <view class="user-detail__section">
          <text class="user-detail__section-title">套餐调整</text>
          <view class="user-detail__plan-list">
            <view
              v-for="plan in plans"
              :key="plan.id"
              :class="['user-detail__plan-item', { 'user-detail__plan-item--active': selectedPlanId === plan.id }]"
              @tap="selectedPlanId = plan.id"
            >
              <text>{{ plan.name }}</text>
            </view>
          </view>
          <lv-button :loading="applyingPlan" @tap="handleApplyPlan" block>应用选中套餐</lv-button>
        </view>

        <!-- 额度补发 -->
        <view class="user-detail__section">
          <text class="user-detail__section-title">额度补发</text>
          <view class="user-detail__grant-form">
            <view class="user-detail__grant-picker">
              <text class="user-detail__grant-label">功能项</text>
              <picker
                v-if="catalog.length > 0"
                :value="grantFeatureIndex"
                :range="catalog"
                range-key="name"
                @change="handleFeaturePickerChange"
              >
                <view class="user-detail__picker-display">
                  <text>{{ catalog[grantFeatureIndex]?.name || '请选择功能项' }}</text>
                  <ChevronRight :size="14" color="#94a3b8" style="transform: rotate(90deg);" />
                </view>
              </picker>
              <view v-else class="user-detail__picker-display">
                <text>加载功能项中...</text>
              </view>
            </view>
            <lv-input v-model="grantAmount" placeholder="补发数量" type="number" />
            <text v-if="catalog[grantFeatureIndex]" class="user-detail__grant-desc">{{ catalog[grantFeatureIndex].description }}</text>
            <lv-button :loading="granting" @tap="handleGrant" block>发放额度</lv-button>
            <view v-if="grantFeedback" class="user-detail__grant-feedback">
              <text class="user-detail__grant-feedback-text">
                已补发 {{ grantFeedback.granted_amount }}，累计补发从 {{ grantFeedback.before_granted }} 提升到 {{ grantFeedback.after_granted }}。
              </text>
            </view>
          </view>
        </view>

        <!-- 额度进度 -->
        <view v-if="entitlements" class="user-detail__section">
          <text class="user-detail__section-title">额度进度</text>
          <view v-for="item in entitlements.usage" :key="item.feature_key" class="user-detail__usage-item">
            <view class="user-detail__usage-header">
              <view class="user-detail__usage-name-block">
                <text class="user-detail__usage-name">{{ catalogFeatureName(item.feature_key) }}</text>
                <text class="user-detail__usage-key">{{ item.feature_key }}</text>
              </view>
              <text class="user-detail__usage-count">{{ item.remaining }} / {{ item.limit }}</text>
            </view>
            <lv-progress :percentage="item.limit > 0 ? Math.round((item.used / item.limit) * 100) : 0" />
            <view class="user-detail__usage-detail">
              <text class="user-detail__usage-detail-item">基础: {{ item.base_limit ?? item.limit }}</text>
              <text class="user-detail__usage-detail-item">补发: {{ item.granted ?? 0 }}</text>
              <text class="user-detail__usage-detail-item">已用: {{ item.used }}</text>
              <text class="user-detail__usage-detail-item">剩余: {{ item.remaining }}</text>
            </view>
          </view>
        </view>
      </template>

      <lv-empty v-else title="用户未找到" />
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { adminApi } from '@/api'
import type { AdminUserItem, AdminUserEntitlements, AdminPlan, AdminFeatureCatalogItem } from '@/api/admin'
import { FEATURE_LABELS } from '@/utils/constants'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvInput from '@/components/lv-input/lv-input.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvTag from '@/components/lv-tag/lv-tag.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvProgress from '@/components/lv-progress/lv-progress.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import { ChevronRight } from '@lucide/vue'

const loading = ref(false)
const saving = ref(false)
const applyingPlan = ref(false)
const granting = ref(false)
const userId = ref(0)
const user = ref<AdminUserItem | null>(null)
const plans = ref<AdminPlan[]>([])
const catalog = ref<AdminFeatureCatalogItem[]>([])
const entitlements = ref<AdminUserEntitlements | null>(null)
const selectedPlanId = ref<number | null>(null)
const grantFeatureIndex = ref(0)
const grantAmount = ref('10')
const grantFeedback = ref<{ feature_key: string; granted_amount: number; before_granted: number; after_granted: number } | null>(null)

const editUser = ref({ name: '', email: '', role: '' as string, status: '' as string })

onLoad((options) => {
  userId.value = Number(options?.userId || 0)
  if (!userId.value) {
    uni.showToast({ title: '缺少用户 ID', icon: 'none' })
    return
  }
})

onMounted(async () => {
  if (!userId.value) return
  loading.value = true
  try {
    const [usersData, plansData, catalogData, entitlementsData] = await Promise.all([
      adminApi.getAdminUsers(),
      adminApi.getAdminPlans(),
      adminApi.getAdminFeatureCatalog(),
      adminApi.getAdminUserEntitlements(userId.value),
    ])
    user.value = usersData.find(u => u.id === userId.value) || null
    plans.value = plansData
    catalog.value = catalogData
    entitlements.value = entitlementsData
    selectedPlanId.value = entitlementsData.plan?.id || null
    if (user.value) {
      editUser.value = {
        name: user.value.name,
        email: user.value.email,
        role: user.value.role,
        status: user.value.status,
      }
    }
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
})

function catalogFeatureName(key: string): string {
  const item = catalog.value.find(c => c.key === key)
  if (item) return item.name
  if (FEATURE_LABELS[key]) return FEATURE_LABELS[key].label
  return key
}

function handleFeaturePickerChange(e: any) {
  grantFeatureIndex.value = e.detail.value
}

async function handleSaveUser() {
  if (!user.value) return
  saving.value = true
  try {
    await adminApi.updateAdminUser(user.value.id, {
      name: editUser.value.name,
      email: editUser.value.email,
      role: editUser.value.role as any,
      status: editUser.value.status as any,
    })
    uni.showToast({ title: '保存成功', icon: 'success' })
    // 返回列表页并刷新
    setTimeout(() => uni.navigateBack(), 800)
  } catch (e: any) {
    uni.showToast({ title: e.message || '保存失败', icon: 'none' })
  } finally {
    saving.value = false
  }
}

async function handleDeleteUser() {
  if (!user.value) return
  uni.showModal({
    title: '确认停用',
    content: `确定停用用户「${user.value.name}」？`,
    confirmColor: '#be123c',
    success: async (res) => {
      if (!res.confirm || !user.value) return
      try {
        await adminApi.deleteAdminUser(user.value.id)
        uni.showToast({ title: '已停用', icon: 'success' })
        setTimeout(() => uni.navigateBack(), 800)
      } catch (e: any) {
        uni.showToast({ title: e.message || '操作失败', icon: 'none' })
      }
    },
  })
}

async function handleApplyPlan() {
  if (!user.value || !selectedPlanId.value) return
  applyingPlan.value = true
  try {
    await adminApi.adminUpdateUserSubscription(user.value.id, selectedPlanId.value)
    uni.showToast({ title: '套餐已更新', icon: 'success' })
    entitlements.value = await adminApi.getAdminUserEntitlements(user.value.id)
  } catch (e: any) {
    uni.showToast({ title: e.message || '操作失败', icon: 'none' })
  } finally {
    applyingPlan.value = false
  }
}

async function handleGrant() {
  if (!user.value) return
  const featureItem = catalog.value[grantFeatureIndex.value]
  if (!featureItem || !grantAmount.value) return
  granting.value = true
  try {
    const res = await adminApi.adminGrantUserQuota(user.value.id, featureItem.key, Number(grantAmount.value))
    grantFeedback.value = res
    uni.showToast({ title: `已补发 ${res.granted_amount}`, icon: 'success' })
    entitlements.value = await adminApi.getAdminUserEntitlements(user.value.id)
    grantAmount.value = ''
  } catch (e: any) {
    uni.showToast({ title: e.message || '补发失败', icon: 'none' })
  } finally {
    granting.value = false
  }
}
</script>

<style lang="scss" scoped>
.user-detail {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding $lv-page-padding;
  }

  &__section {
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: 32rpx;
    margin-bottom: $lv-section-gap;
    box-shadow: $lv-shadow-sm;
  }

  &__section-title {
    display: block;
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 20rpx;
  }

  &__row {
    display: flex;
    align-items: center;
    gap: 12rpx;
    margin: 16rpx 0;
    flex-wrap: wrap;
  }

  &__row-label {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__tag-group {
    display: flex;
    gap: 8rpx;
  }

  &__actions {
    display: flex;
    gap: 16rpx;
    margin-top: 24rpx;
  }

  &__plan-list {
    display: flex;
    flex-wrap: wrap;
    gap: 12rpx;
    margin-bottom: 20rpx;
  }

  &__plan-item {
    padding: 12rpx 24rpx;
    border-radius: $lv-radius-full;
    border: 1rpx solid $lv-border-light;
    font-size: $lv-font-sm;

    &--active {
      background: $lv-primary;
      color: #fff;
      border-color: $lv-primary;
    }
  }

  &__grant-form {
    display: flex;
    flex-direction: column;
    gap: 16rpx;
  }

  &__grant-picker {
    display: flex;
    flex-direction: column;
    gap: 8rpx;
  }

  &__grant-label {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__picker-display {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #fff;
    border: 1rpx solid $lv-border;
    border-radius: $lv-radius-sm;
    padding: 20rpx 24rpx;
    font-size: $lv-font-sm;
    color: $lv-text-primary;
  }

  &__grant-desc {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    line-height: 1.5;
  }

  &__grant-feedback {
    background: #ecfdf5;
    border: 1rpx solid #a7f3d0;
    border-radius: $lv-radius-sm;
    padding: 16rpx 20rpx;
  }

  &__grant-feedback-text {
    font-size: $lv-font-xs;
    color: #065f46;
    line-height: 1.5;
  }

  &__usage-item {
    margin-bottom: 20rpx;
  }

  &__usage-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 8rpx;
  }

  &__usage-name-block {
    flex: 1;
  }

  &__usage-name {
    display: block;
    font-size: $lv-font-sm;
    font-weight: 500;
    color: $lv-text-primary;
  }

  &__usage-key {
    display: block;
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    margin-top: 2rpx;
  }

  &__usage-count {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__usage-detail {
    display: flex;
    flex-wrap: wrap;
    gap: 12rpx;
    margin-top: 12rpx;
  }

  &__usage-detail-item {
    font-size: $lv-font-xs;
    color: $lv-text-secondary;
    background: $lv-primary-lighter;
    padding: 6rpx 16rpx;
    border-radius: $lv-radius-full;
  }
}
</style>
