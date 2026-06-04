<template>
  <view class="admin-plans">
    <view class="admin-plans__content">
      <!-- 套餐列表 -->
      <view class="admin-plans__list">
        <view class="admin-plans__list-header">
          <text class="admin-plans__list-title">套餐列表</text>
          <lv-button size="sm" @tap="showCreateForm = true">新建套餐</lv-button>
        </view>

        <lv-loading v-if="loading" />

        <view v-else-if="plans.length === 0" class="admin-plans__empty">
          <lv-empty title="暂无套餐" />
        </view>

        <view v-else class="admin-plans__cards">
          <view
            v-for="plan in plans"
            :key="plan.id"
            :class="['admin-plans__card', { 'admin-plans__card--active': selectedPlan?.id === plan.id }]"
            @tap="selectPlan(plan)"
          >
            <text class="admin-plans__card-name">{{ plan.name }}</text>
            <text class="admin-plans__card-price">¥{{ plan.monthly_price }}/月</text>
            <lv-tag v-if="plan.is_recommended" type="primary" text="推荐" size="sm" />
          </view>
        </view>
      </view>

      <!-- 新建套餐表单 -->
      <view v-if="showCreateForm" class="admin-plans__form">
        <text class="admin-plans__form-title">新建套餐</text>
        <lv-input v-model="newPlan.code" placeholder="套餐编码（如 enterprise）" />
        <lv-input v-model="newPlan.name" placeholder="套餐名称" />
        <lv-textarea v-model="newPlan.description" placeholder="套餐描述" />
        <view class="admin-plans__form-row">
          <lv-input v-model="newPlan.monthly_price" placeholder="月费" type="number" />
          <lv-input v-model="newPlan.yearly_price" placeholder="年费" type="number" />
        </view>
        <view class="admin-plans__form-actions">
          <lv-button secondary @tap="showCreateForm = false">取消</lv-button>
          <lv-button :loading="creating" @tap="handleCreate">创建套餐</lv-button>
        </view>
      </view>

      <!-- 选中套餐详情 -->
      <view v-if="selectedPlan && !showCreateForm" class="admin-plans__detail">
        <text class="admin-plans__detail-title">套餐信息</text>
        <lv-input v-model="editPlan.name" placeholder="套餐名称" />
        <lv-input v-model="editPlan.monthly_price" placeholder="月费" type="number" />
        <lv-input v-model="editPlan.yearly_price" placeholder="年费" type="number" />
        <lv-textarea v-model="editPlan.description" placeholder="套餐描述" />
        <view class="admin-plans__checkboxes">
          <view class="admin-plans__checkbox" @tap="editPlan.is_visible = !editPlan.is_visible">
            <lv-icon :name="editPlan.is_visible ? 'CheckSquare' : 'Square'" :size="18" :color="editPlan.is_visible ? '#2563eb' : '#94a3b8'" />
            <text>前台展示</text>
          </view>
          <view class="admin-plans__checkbox" @tap="editPlan.is_recommended = !editPlan.is_recommended">
            <lv-icon :name="editPlan.is_recommended ? 'CheckSquare' : 'Square'" :size="18" :color="editPlan.is_recommended ? '#2563eb' : '#94a3b8'" />
            <text>推荐套餐</text>
          </view>
        </view>
        <view class="admin-plans__form-actions">
          <lv-button :loading="saving" @tap="handleSavePlan">保存套餐信息</lv-button>
          <lv-button type="danger" @tap="handleDeletePlan">删除套餐</lv-button>
        </view>

        <!-- 功能配置 -->
        <view v-if="features.length > 0" class="admin-plans__features">
          <text class="admin-plans__features-title">功能配置</text>
          <view v-for="feat in features" :key="feat.feature_key" class="admin-plans__feature-item">
            <view class="admin-plans__feature-info">
              <text class="admin-plans__feature-name">{{ getFeatureName(feat.feature_key) }}</text>
              <text class="admin-plans__feature-desc">{{ getFeatureDesc(feat.feature_key) }}</text>
            </view>
            <view class="admin-plans__feature-input">
              <lv-input
                v-if="getFeatureType(feat.feature_key) !== 'boolean'"
                v-model="feat.value"
                :placeholder="getFeatureType(feat.feature_key) === 'number' ? '数量' : '值'"
                type="number"
                size="sm"
              />
              <view v-else class="admin-plans__checkbox" @tap="feat.value = feat.value ? false : true">
                <lv-icon :name="feat.value ? 'CheckSquare' : 'Square'" :size="18" :color="feat.value ? '#2563eb' : '#94a3b8'" />
                <text>{{ feat.value ? '开启' : '关闭' }}</text>
              </view>
            </view>
          </view>
          <lv-button :loading="savingFeatures" @tap="handleSaveFeatures" block>保存套餐能力</lv-button>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { adminApi } from '@/api'
import type { AdminPlan, AdminFeatureCatalogItem, AdminFeatureItem, AdminQuotaRule } from '@/api/admin'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvInput from '@/components/lv-input/lv-input.vue'
import LvTextarea from '@/components/lv-textarea/lv-textarea.vue'
import LvTag from '@/components/lv-tag/lv-tag.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'

const loading = ref(false)
const plans = ref<AdminPlan[]>([])
const selectedPlan = ref<AdminPlan | null>(null)
const showCreateForm = ref(false)
const creating = ref(false)
const saving = ref(false)
const savingFeatures = ref(false)

const newPlan = ref({ code: '', name: '', description: '', monthly_price: '', yearly_price: '' })
const editPlan = ref({ name: '', monthly_price: '', yearly_price: '', description: '', is_visible: true, is_recommended: false })

const catalog = ref<AdminFeatureCatalogItem[]>([])
const features = ref<AdminFeatureItem[]>([])
const quotaRules = ref<AdminQuotaRule[]>([])

onMounted(async () => {
  await loadData()
})

async function loadData() {
  loading.value = true
  try {
    const [plansData, catalogData] = await Promise.all([
      adminApi.getAdminPlans(),
      adminApi.getAdminFeatureCatalog(),
    ])
    plans.value = plansData
    catalog.value = catalogData
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

async function selectPlan(plan: AdminPlan) {
  selectedPlan.value = plan
  editPlan.value = {
    name: plan.name,
    monthly_price: String(plan.monthly_price),
    yearly_price: String(plan.yearly_price || ''),
    description: plan.description || '',
    is_visible: plan.is_visible,
    is_recommended: plan.is_recommended,
  }
  try {
    const [featuresData, rulesData] = await Promise.all([
      adminApi.getAdminPlanFeatures(plan.id),
      adminApi.getAdminQuotaRules(plan.id),
    ])
    features.value = featuresData
    quotaRules.value = rulesData
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载功能配置失败', icon: 'none' })
  }
}

function getFeatureName(key: string): string {
  return catalog.value.find(c => c.key === key)?.name || key
}

function getFeatureDesc(key: string): string {
  return catalog.value.find(c => c.key === key)?.description || ''
}

function getFeatureType(key: string): string {
  return catalog.value.find(c => c.key === key)?.value_type || 'text'
}

async function handleCreate() {
  if (!newPlan.value.code.trim() || !newPlan.value.name.trim()) {
    uni.showToast({ title: '请填写编码和名称', icon: 'none' })
    return
  }
  creating.value = true
  try {
    await adminApi.createAdminPlan({
      code: newPlan.value.code.trim(),
      name: newPlan.value.name.trim(),
      description: newPlan.value.description.trim(),
      monthly_price: Number(newPlan.value.monthly_price) || 0,
      yearly_price: Number(newPlan.value.yearly_price) || 0,
    })
    showCreateForm.value = false
    newPlan.value = { code: '', name: '', description: '', monthly_price: '', yearly_price: '' }
    uni.showToast({ title: '创建成功', icon: 'success' })
    await loadData()
  } catch (e: any) {
    uni.showToast({ title: e.message || '创建失败', icon: 'none' })
  } finally {
    creating.value = false
  }
}

async function handleSavePlan() {
  if (!selectedPlan.value) return
  saving.value = true
  try {
    await adminApi.updateAdminPlan(selectedPlan.value.id, {
      name: editPlan.value.name,
      monthly_price: Number(editPlan.value.monthly_price) || 0,
      yearly_price: Number(editPlan.value.yearly_price) || null,
      description: editPlan.value.description,
      is_visible: editPlan.value.is_visible,
      is_recommended: editPlan.value.is_recommended,
    })
    uni.showToast({ title: '保存成功', icon: 'success' })
    await loadData()
  } catch (e: any) {
    uni.showToast({ title: e.message || '保存失败', icon: 'none' })
  } finally {
    saving.value = false
  }
}

async function handleDeletePlan() {
  if (!selectedPlan.value) return
  uni.showModal({
    title: '确认删除',
    content: `确定删除套餐「${selectedPlan.value.name}」？`,
    confirmColor: '#be123c',
    success: async (res) => {
      if (res.confirm && selectedPlan.value) {
        try {
          await adminApi.deleteAdminPlan(selectedPlan.value.id)
          selectedPlan.value = null
          uni.showToast({ title: '已删除', icon: 'success' })
          await loadData()
        } catch (e: any) {
          uni.showToast({ title: e.message || '删除失败', icon: 'none' })
        }
      }
    }
  })
}

async function handleSaveFeatures() {
  if (!selectedPlan.value) return
  savingFeatures.value = true
  try {
    await adminApi.saveAdminPlanFeatures(selectedPlan.value.id, features.value)
    await adminApi.saveAdminQuotaRules(selectedPlan.value.id, quotaRules.value)
    uni.showToast({ title: '保存成功', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '保存失败', icon: 'none' })
  } finally {
    savingFeatures.value = false
  }
}
</script>

<style lang="scss" scoped>
.admin-plans {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: $lv-page-padding;
  }

  &__list {
    margin-bottom: $lv-section-gap;
  }

  &__list-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 20rpx;
  }

  &__list-title {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__cards {
    display: flex;
    flex-direction: column;
    gap: 16rpx;
  }

  &__card {
    display: flex;
    align-items: center;
    gap: 16rpx;
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
    padding: 24rpx;
    border: 2rpx solid transparent;

    &--active {
      border-color: $lv-primary;
      background: $lv-primary-lighter;
    }
  }

  &__card-name {
    flex: 1;
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__card-price {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__form,
  &__detail {
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: 32rpx;
    margin-bottom: $lv-section-gap;
    box-shadow: $lv-shadow-sm;
  }

  &__form-title,
  &__detail-title {
    display: block;
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 20rpx;
  }

  &__form-row {
    display: flex;
    gap: 16rpx;
  }

  &__form-actions {
    display: flex;
    gap: 16rpx;
    margin-top: 20rpx;
  }

  &__checkboxes {
    display: flex;
    gap: 32rpx;
    margin-top: 16rpx;
  }

  &__checkbox {
    display: flex;
    align-items: center;
    gap: 8rpx;
  }

  &__features {
    margin-top: 32rpx;
    padding-top: 24rpx;
    border-top: 1rpx solid $lv-border-light;
  }

  &__features-title {
    display: block;
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 20rpx;
  }

  &__feature-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16rpx 0;
    border-bottom: 1rpx solid $lv-border-light;
  }

  &__feature-info {
    flex: 1;
    margin-right: 16rpx;
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

  &__feature-input {
    width: 200rpx;
    flex-shrink: 0;
  }

  &__empty {
    padding: 60rpx 0;
  }
}
</style>
