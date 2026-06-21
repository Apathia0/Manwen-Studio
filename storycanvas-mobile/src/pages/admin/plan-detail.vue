<template>
  <view class="plan-detail">
    <lv-navbar :title="plan?.name || '套餐详情'" show-back />

    <view class="plan-detail__content">
      <lv-loading v-if="loading" />

      <template v-else-if="plan">
        <!-- 套餐信息 -->
        <view class="plan-detail__section">
          <text class="plan-detail__section-title">套餐信息</text>
          <lv-input v-model="editPlan.name" placeholder="套餐名称" />
          <view class="plan-detail__row">
            <lv-input v-model="editPlan.monthly_price" placeholder="月费" type="number" />
            <lv-input v-model="editPlan.yearly_price" placeholder="年费" type="number" />
          </view>
          <lv-textarea v-model="editPlan.description" placeholder="套餐描述" />
          <view class="plan-detail__checkboxes">
            <view class="plan-detail__checkbox" @tap="editPlan.is_visible = !editPlan.is_visible">
              <lv-icon :name="editPlan.is_visible ? 'CheckSquare' : 'Square'" :size="18" :color="editPlan.is_visible ? '#2563eb' : '#94a3b8'" />
              <text>前台展示</text>
            </view>
            <view class="plan-detail__checkbox" @tap="editPlan.is_recommended = !editPlan.is_recommended">
              <lv-icon :name="editPlan.is_recommended ? 'CheckSquare' : 'Square'" :size="18" :color="editPlan.is_recommended ? '#2563eb' : '#94a3b8'" />
              <text>推荐套餐</text>
            </view>
          </view>
          <view class="plan-detail__actions">
            <lv-button :loading="saving" @tap="handleSavePlan">保存套餐信息</lv-button>
            <lv-button type="danger" @tap="handleDeletePlan">删除套餐</lv-button>
          </view>
        </view>

        <!-- 功能配置 -->
        <view v-if="features.length > 0" class="plan-detail__section">
          <text class="plan-detail__section-title">功能配置</text>
          <view v-for="feat in features" :key="feat.feature_key" class="plan-detail__feature-item">
            <view class="plan-detail__feature-info">
              <text class="plan-detail__feature-name">{{ getFeatureName(feat.feature_key) }}</text>
              <text class="plan-detail__feature-desc">{{ getFeatureDesc(feat.feature_key) }}</text>
            </view>
            <view class="plan-detail__feature-controls">
              <!-- 套餐值 -->
              <view class="plan-detail__feature-field">
                <text class="plan-detail__feature-field-label">套餐值</text>
                <lv-input
                  v-if="getFeatureType(feat.feature_key) !== 'boolean'"
                  v-model="feat.value"
                  placeholder="数量"
                  type="number"
                  size="sm"
                />
                <view v-else class="plan-detail__checkbox" @tap="feat.value = feat.value ? false : true">
                  <lv-icon :name="feat.value ? 'CheckSquare' : 'Square'" :size="18" :color="feat.value ? '#2563eb' : '#94a3b8'" />
                  <text>{{ feat.value ? '开启' : '关闭' }}</text>
                </view>
              </view>

              <!-- 重置周期 -->
              <view class="plan-detail__feature-field">
                <text class="plan-detail__feature-field-label">重置周期</text>
                <picker
                  :value="getResetPeriodIndex(feat.feature_key)"
                  :range="resetPeriodOptions"
                  range-key="label"
                  @change="(e: any) => handleResetPeriodChange(feat.feature_key, e.detail.value)"
                >
                  <view class="plan-detail__picker-display">
                    <text>{{ resetPeriodOptions[getResetPeriodIndex(feat.feature_key)]?.label || '按月重置' }}</text>
                    <ChevronRight :size="12" color="#94a3b8" style="transform: rotate(90deg);" />
                  </view>
                </picker>
              </view>

              <!-- 扣减时机 -->
              <view class="plan-detail__feature-field">
                <text class="plan-detail__feature-field-label">扣减时机</text>
                <picker
                  :value="getDeductModeIndex(feat.feature_key)"
                  :range="deductModeOptions"
                  range-key="label"
                  @change="(e: any) => handleDeductModeChange(feat.feature_key, e.detail.value)"
                >
                  <view class="plan-detail__picker-display">
                    <text>{{ deductModeOptions[getDeductModeIndex(feat.feature_key)]?.label || '成功后扣减' }}</text>
                    <ChevronRight :size="12" color="#94a3b8" style="transform: rotate(90deg);" />
                  </view>
                </picker>
              </view>
            </view>
          </view>
          <lv-button :loading="savingFeatures" @tap="handleSaveFeatures" block>保存套餐能力</lv-button>
        </view>
      </template>

      <lv-empty v-else title="套餐未找到" />
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { adminApi } from '@/api'
import type { AdminPlan, AdminFeatureCatalogItem, AdminFeatureItem, AdminQuotaRule } from '@/api/admin'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvInput from '@/components/lv-input/lv-input.vue'
import LvTextarea from '@/components/lv-textarea/lv-textarea.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import { ChevronRight } from '@lucide/vue'

const resetPeriodOptions = [
  { label: '按月重置', value: 'monthly' },
  { label: '按年重置', value: 'yearly' },
  { label: '不重置', value: 'never' },
]

const deductModeOptions = [
  { label: '成功后扣减', value: 'on_success' },
  { label: '提交即扣减', value: 'on_submit' },
  { label: '手动扣减', value: 'manual' },
]

const loading = ref(false)
const saving = ref(false)
const savingFeatures = ref(false)
const planId = ref(0)
const plan = ref<AdminPlan | null>(null)
const catalog = ref<AdminFeatureCatalogItem[]>([])
const features = ref<AdminFeatureItem[]>([])
const quotaRules = ref<AdminQuotaRule[]>([])

const editPlan = ref({
  name: '',
  monthly_price: '',
  yearly_price: '',
  description: '',
  is_visible: true,
  is_recommended: false,
})

onLoad((options) => {
  planId.value = Number(options?.planId || 0)
  if (!planId.value) {
    uni.showToast({ title: '缺少套餐 ID', icon: 'none' })
    return
  }
})

onMounted(async () => {
  if (!planId.value) return
  loading.value = true
  try {
    const [plansData, catalogData, featuresData, rulesData] = await Promise.all([
      adminApi.getAdminPlans(),
      adminApi.getAdminFeatureCatalog(),
      adminApi.getAdminPlanFeatures(planId.value),
      adminApi.getAdminQuotaRules(planId.value),
    ])
    plan.value = plansData.find(p => p.id === planId.value) || null
    catalog.value = catalogData
    features.value = featuresData
    quotaRules.value = rulesData
    if (plan.value) {
      editPlan.value = {
        name: plan.value.name,
        monthly_price: String(plan.value.monthly_price),
        yearly_price: String(plan.value.yearly_price || ''),
        description: plan.value.description || '',
        is_visible: plan.value.is_visible,
        is_recommended: plan.value.is_recommended,
      }
    }
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
})

function getFeatureName(key: string): string {
  return catalog.value.find(c => c.key === key)?.name || key
}

function getFeatureDesc(key: string): string {
  return catalog.value.find(c => c.key === key)?.description || ''
}

function getFeatureType(key: string): string {
  return catalog.value.find(c => c.key === key)?.value_type || 'text'
}

function getRule(featureKey: string): AdminQuotaRule {
  const existing = quotaRules.value.find(r => r.feature_key === featureKey)
  if (existing) return existing
  return {
    feature_key: featureKey,
    reset_period: 'monthly',
    deduct_mode: 'on_success',
    extra_config: {},
  }
}

function getResetPeriodIndex(featureKey: string): number {
  const rule = getRule(featureKey)
  const idx = resetPeriodOptions.findIndex(o => o.value === rule.reset_period)
  return idx >= 0 ? idx : 0
}

function getDeductModeIndex(featureKey: string): number {
  const rule = getRule(featureKey)
  const idx = deductModeOptions.findIndex(o => o.value === rule.deduct_mode)
  return idx >= 0 ? idx : 0
}

function handleResetPeriodChange(featureKey: string, index: number) {
  const value = resetPeriodOptions[index].value
  const existingIdx = quotaRules.value.findIndex(r => r.feature_key === featureKey)
  if (existingIdx >= 0) {
    quotaRules.value[existingIdx].reset_period = value
  } else {
    quotaRules.value.push({
      feature_key: featureKey,
      reset_period: value,
      deduct_mode: 'on_success',
      extra_config: {},
    })
  }
}

function handleDeductModeChange(featureKey: string, index: number) {
  const value = deductModeOptions[index].value
  const existingIdx = quotaRules.value.findIndex(r => r.feature_key === featureKey)
  if (existingIdx >= 0) {
    quotaRules.value[existingIdx].deduct_mode = value
  } else {
    quotaRules.value.push({
      feature_key: featureKey,
      reset_period: 'monthly',
      deduct_mode: value,
      extra_config: {},
    })
  }
}

async function handleSavePlan() {
  if (!plan.value) return
  saving.value = true
  try {
    await adminApi.updateAdminPlan(plan.value.id, {
      name: editPlan.value.name,
      monthly_price: Number(editPlan.value.monthly_price) || 0,
      yearly_price: Number(editPlan.value.yearly_price) || null,
      description: editPlan.value.description,
      is_visible: editPlan.value.is_visible,
      is_recommended: editPlan.value.is_recommended,
    })
    uni.showToast({ title: '保存成功', icon: 'success' })
    setTimeout(() => uni.navigateBack(), 800)
  } catch (e: any) {
    uni.showToast({ title: e.message || '保存失败', icon: 'none' })
  } finally {
    saving.value = false
  }
}

async function handleDeletePlan() {
  if (!plan.value) return
  uni.showModal({
    title: '确认删除',
    content: `确定删除套餐「${plan.value.name}」？`,
    confirmColor: '#be123c',
    success: async (res) => {
      if (!res.confirm || !plan.value) return
      try {
        await adminApi.deleteAdminPlan(plan.value.id)
        uni.showToast({ title: '已删除', icon: 'success' })
        setTimeout(() => uni.navigateBack(), 800)
      } catch (e: any) {
        uni.showToast({ title: e.message || '删除失败', icon: 'none' })
      }
    },
  })
}

async function handleSaveFeatures() {
  if (!plan.value) return
  savingFeatures.value = true
  try {
    await adminApi.saveAdminPlanFeatures(plan.value.id, features.value)
    await adminApi.saveAdminQuotaRules(plan.value.id, quotaRules.value)
    uni.showToast({ title: '保存成功', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '保存失败', icon: 'none' })
  } finally {
    savingFeatures.value = false
  }
}
</script>

<style lang="scss" scoped>
.plan-detail {
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
    gap: 16rpx;
  }

  &__checkboxes {
    display: flex;
    gap: 32rpx;
    margin-top: 20rpx;
  }

  &__checkbox {
    display: flex;
    align-items: center;
    gap: 8rpx;
  }

  &__actions {
    display: flex;
    gap: 16rpx;
    margin-top: 24rpx;
  }

  &__feature-item {
    display: flex;
    flex-direction: column;
    padding: 20rpx 0;
    border-bottom: 1rpx solid $lv-border-light;

    &:last-child {
      border-bottom: none;
    }
  }

  &__feature-info {
    margin-bottom: 16rpx;
  }

  &__feature-name {
    display: block;
    font-size: $lv-font-sm;
    font-weight: 500;
    color: $lv-text-primary;
  }

  &__feature-desc {
    display: block;
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    margin-top: 4rpx;
  }

  &__feature-controls {
    display: flex;
    gap: 16rpx;
    flex-wrap: wrap;
  }

  &__feature-field {
    flex: 1;
    min-width: 180rpx;
  }

  &__feature-field-label {
    display: block;
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    margin-bottom: 8rpx;
  }

  &__picker-display {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #fff;
    border: 1rpx solid $lv-border;
    border-radius: $lv-radius-sm;
    padding: 16rpx 20rpx;
    font-size: $lv-font-sm;
    color: $lv-text-primary;
  }
}
</style>
