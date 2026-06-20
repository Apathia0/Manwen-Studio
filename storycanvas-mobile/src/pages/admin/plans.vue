<template>
  <view class="admin-plans">
    <view class="admin-plans__content">
      <!-- 顶部工具栏:标题 + 新建 -->
      <view class="admin-plans__toolbar">
        <text class="admin-plans__toolbar-title">套餐列表</text>
        <lv-button size="sm" @tap="showCreateForm = !showCreateForm">
          {{ showCreateForm ? '收起' : '新建套餐' }}
        </lv-button>
      </view>

      <!-- 新建套餐表单 -->
      <view v-if="showCreateForm" class="admin-plans__form">
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

      <!-- 套餐列表 -->
      <lv-loading v-if="loading" />

      <view v-else-if="plans.length === 0" class="admin-plans__empty">
        <lv-empty title="暂无套餐" />
      </view>

      <view v-else class="admin-plans__cards">
        <view
          v-for="plan in plans"
          :key="plan.id"
          class="admin-plans__card"
          @tap="goDetail(plan.id)"
        >
          <view class="admin-plans__card-info">
            <text class="admin-plans__card-name">{{ plan.name }}</text>
            <text class="admin-plans__card-price">¥{{ plan.monthly_price }}/月</text>
          </view>
          <view class="admin-plans__card-tags">
            <lv-tag v-if="plan.is_recommended" type="primary" text="推荐" size="sm" />
            <lv-tag v-if="!plan.is_visible" type="default" text="隐藏" size="sm" />
          </view>
          <ChevronRight :size="14" color="#94a3b8" />
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { adminApi } from '@/api'
import type { AdminPlan } from '@/api/admin'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvInput from '@/components/lv-input/lv-input.vue'
import LvTextarea from '@/components/lv-textarea/lv-textarea.vue'
import LvTag from '@/components/lv-tag/lv-tag.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import { ChevronRight } from '@lucide/vue'

const loading = ref(false)
const plans = ref<AdminPlan[]>([])
const showCreateForm = ref(false)
const creating = ref(false)

const newPlan = ref({ code: '', name: '', description: '', monthly_price: '', yearly_price: '' })

function goDetail(planId: number) {
  uni.navigateTo({ url: `/pages/admin/plan-detail?planId=${planId}` })
}

onMounted(async () => {
  await loadData()
})

async function loadData() {
  loading.value = true
  try {
    plans.value = await adminApi.getAdminPlans()
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
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
</script>

<style lang="scss" scoped>
.admin-plans {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: $lv-page-padding;
  }

  &__toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 20rpx;
  }

  &__toolbar-title {
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

    &:active {
      background: $lv-primary-lighter;
    }
  }

  &__card-info {
    flex: 1;
  }

  &__card-name {
    display: block;
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__card-price {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    margin-top: 4rpx;
  }

  &__card-tags {
    display: flex;
    gap: 8rpx;
  }

  &__form {
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: 32rpx;
    margin-bottom: $lv-section-gap;
    box-shadow: $lv-shadow-sm;
    display: flex;
    flex-direction: column;
    gap: 16rpx;
  }

  &__form-row {
    display: flex;
    gap: 16rpx;
  }

  &__form-actions {
    display: flex;
    gap: 16rpx;
    margin-top: 12rpx;
  }

  &__empty {
    padding: 60rpx 0;
  }
}
</style>
