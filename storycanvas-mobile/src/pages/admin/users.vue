<template>
  <view class="admin-users">
    <view class="admin-users__content">
      <!-- 搜索 -->
      <lv-input v-model="searchQuery" placeholder="搜索用户名、邮箱、套餐..." clearable />

      <!-- 用户列表 -->
      <lv-loading v-if="loading" />

      <view v-else class="admin-users__list">
        <view
          v-for="user in filteredUsers"
          :key="user.id"
          :class="['admin-users__item', { 'admin-users__item--active': selectedUser?.id === user.id }]"
          @tap="selectUser(user)"
        >
          <view class="admin-users__item-info">
            <text class="admin-users__item-name">{{ user.name }}</text>
            <text class="admin-users__item-email">{{ user.email }}</text>
            <view class="admin-users__item-tags">
              <lv-tag :type="user.role === 'admin' ? 'primary' : 'default'" :text="user.role === 'admin' ? '管理员' : '用户'" size="sm" />
              <lv-tag :type="user.status === 'active' ? 'success' : 'danger'" :text="user.status === 'active' ? '启用' : '停用'" size="sm" />
              <lv-tag v-if="user.plan_name" type="default" :text="user.plan_name" size="sm" />
            </view>
          </view>
          <ChevronRight :size="14" color="#94a3b8" />
        </view>
      </view>

      <!-- 新建用户 -->
      <view class="admin-users__section">
        <lv-button size="sm" @tap="showCreateForm = !showCreateForm">
          {{ showCreateForm ? '收起' : '新建用户' }}
        </lv-button>
      </view>

      <view v-if="showCreateForm" class="admin-users__form">
        <lv-input v-model="newUser.name" placeholder="姓名" />
        <lv-input v-model="newUser.email" placeholder="邮箱" />
        <lv-input v-model="newUser.password" placeholder="初始密码" type="password" />
        <view class="admin-users__form-row">
          <text class="admin-users__form-label">角色：</text>
          <lv-tag
            :type="newUser.role === 'admin' ? 'primary' : 'default'"
            text="管理员"
            size="sm"
            @tap="newUser.role = 'admin'"
          />
          <lv-tag
            :type="newUser.role === 'user' ? 'primary' : 'default'"
            text="普通用户"
            size="sm"
            @tap="newUser.role = 'user'"
          />
        </view>
        <lv-button :loading="creating" @tap="handleCreate" block>创建用户</lv-button>
      </view>

      <!-- 用户详情 -->
      <view v-if="selectedUser && !showCreateForm" class="admin-users__detail">
        <text class="admin-users__detail-title">账号信息</text>
        <lv-input v-model="editUser.name" placeholder="姓名" />
        <lv-input v-model="editUser.email" placeholder="邮箱" />
        <view class="admin-users__form-row">
          <text class="admin-users__form-label">角色：</text>
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
        <view class="admin-users__form-row">
          <text class="admin-users__form-label">状态：</text>
          <lv-tag
            :type="editUser.status === 'active' ? 'success' : 'danger'"
            :text="editUser.status === 'active' ? '启用' : '停用'"
            size="sm"
            @tap="editUser.status = editUser.status === 'active' ? 'disabled' : 'active'"
          />
        </view>
        <view class="admin-users__form-actions">
          <lv-button :loading="saving" @tap="handleSaveUser">保存账号信息</lv-button>
          <lv-button type="danger" @tap="handleDeleteUser">停用账号</lv-button>
        </view>

        <!-- 套餐调整 -->
        <view class="admin-users__section-divider" />
        <text class="admin-users__detail-title">套餐调整</text>
        <view class="admin-users__plan-list">
          <view
            v-for="plan in plans"
            :key="plan.id"
            :class="['admin-users__plan-item', { 'admin-users__plan-item--active': selectedPlanId === plan.id }]"
            @tap="selectedPlanId = plan.id"
          >
            <text>{{ plan.name }}</text>
          </view>
        </view>
        <lv-button :loading="applyingPlan" @tap="handleApplyPlan" block>应用选中套餐</lv-button>

        <!-- 额度补发 -->
        <view class="admin-users__section-divider" />
        <text class="admin-users__detail-title">额度补发</text>
        <view class="admin-users__grant-form">
          <lv-input v-model="grantFeatureKey" placeholder="功能项 Key（如 framework.generate.monthly_limit）" />
          <lv-input v-model="grantAmount" placeholder="补发数量" type="number" />
          <lv-button :loading="granting" @tap="handleGrant" block>发放额度</lv-button>
        </view>

        <!-- 额度进度 -->
        <view v-if="entitlements" class="admin-users__section-divider" />
        <view v-if="entitlements" class="admin-users__entitlements">
          <text class="admin-users__detail-title">额度进度</text>
          <view v-for="item in entitlements.usage" :key="item.feature_key" class="admin-users__usage-item">
            <view class="admin-users__usage-header">
              <text class="admin-users__usage-name">{{ getFeatureLabel(item.feature_key) }}</text>
              <text class="admin-users__usage-count">{{ item.remaining }} / {{ item.limit }}</text>
            </view>
            <lv-progress :percentage="item.limit > 0 ? Math.round((item.used / item.limit) * 100) : 0" />
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { adminApi } from '@/api'
import type { AdminUserItem, AdminUserEntitlements, AdminPlan } from '@/api/admin'
import { FEATURE_LABELS } from '@/utils/constants'
import LvInput from '@/components/lv-input/lv-input.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvTag from '@/components/lv-tag/lv-tag.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvProgress from '@/components/lv-progress/lv-progress.vue'
import { ChevronRight } from '@lucide/vue'

const loading = ref(false)
const users = ref<AdminUserItem[]>([])
const plans = ref<AdminPlan[]>([])
const searchQuery = ref('')
const selectedUser = ref<AdminUserItem | null>(null)
const showCreateForm = ref(false)
const creating = ref(false)
const saving = ref(false)
const applyingPlan = ref(false)
const granting = ref(false)
const selectedPlanId = ref<number | null>(null)
const grantFeatureKey = ref('')
const grantAmount = ref('')
const entitlements = ref<AdminUserEntitlements | null>(null)

const newUser = ref({ name: '', email: '', password: '', role: 'user' as string })
const editUser = ref({ name: '', email: '', role: '' as string, status: '' as string })

const filteredUsers = computed(() => {
  const q = searchQuery.value.toLowerCase()
  if (!q) return users.value
  return users.value.filter(u =>
    u.name.toLowerCase().includes(q) ||
    u.email.toLowerCase().includes(q) ||
    u.plan_name?.toLowerCase().includes(q)
  )
})

function getFeatureLabel(key: string): string {
  return FEATURE_LABELS[key]?.label || key
}

onMounted(async () => {
  loading.value = true
  try {
    const [usersData, plansData] = await Promise.all([
      adminApi.getAdminUsers(),
      adminApi.getAdminPlans(),
    ])
    users.value = usersData
    plans.value = plansData
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
})

async function selectUser(user: AdminUserItem) {
  selectedUser.value = user
  showCreateForm.value = false
  editUser.value = { name: user.name, email: user.email, role: user.role, status: user.status }
  selectedPlanId.value = null
  entitlements.value = null
  try {
    entitlements.value = await adminApi.getAdminUserEntitlements(user.id)
    selectedPlanId.value = entitlements.value.plan.id
  } catch {
    // 忽略
  }
}

async function handleCreate() {
  if (!newUser.value.name.trim() || !newUser.value.email.trim() || !newUser.value.password.trim()) {
    uni.showToast({ title: '请填写完整信息', icon: 'none' })
    return
  }
  creating.value = true
  try {
    await adminApi.createAdminUser(newUser.value)
    showCreateForm.value = false
    newUser.value = { name: '', email: '', password: '', role: 'user' }
    uni.showToast({ title: '创建成功', icon: 'success' })
    users.value = await adminApi.getAdminUsers()
  } catch (e: any) {
    uni.showToast({ title: e.message || '创建失败', icon: 'none' })
  } finally {
    creating.value = false
  }
}

async function handleSaveUser() {
  if (!selectedUser.value) return
  saving.value = true
  try {
    await adminApi.updateAdminUser(selectedUser.value.id, {
      name: editUser.value.name,
      email: editUser.value.email,
      role: editUser.value.role as any,
      status: editUser.value.status as any,
    })
    uni.showToast({ title: '保存成功', icon: 'success' })
    users.value = await adminApi.getAdminUsers()
  } catch (e: any) {
    uni.showToast({ title: e.message || '保存失败', icon: 'none' })
  } finally {
    saving.value = false
  }
}

async function handleDeleteUser() {
  if (!selectedUser.value) return
  uni.showModal({
    title: '确认停用',
    content: `确定停用用户「${selectedUser.value.name}」？`,
    confirmColor: '#be123c',
    success: async (res) => {
      if (res.confirm && selectedUser.value) {
        try {
          await adminApi.deleteAdminUser(selectedUser.value.id)
          selectedUser.value = null
          uni.showToast({ title: '已停用', icon: 'success' })
          users.value = await adminApi.getAdminUsers()
        } catch (e: any) {
          uni.showToast({ title: e.message || '操作失败', icon: 'none' })
        }
      }
    }
  })
}

async function handleApplyPlan() {
  if (!selectedUser.value || !selectedPlanId.value) return
  applyingPlan.value = true
  try {
    await adminApi.adminUpdateUserSubscription(selectedUser.value.id, selectedPlanId.value)
    uni.showToast({ title: '套餐已更新', icon: 'success' })
    entitlements.value = await adminApi.getAdminUserEntitlements(selectedUser.value.id)
    users.value = await adminApi.getAdminUsers()
  } catch (e: any) {
    uni.showToast({ title: e.message || '操作失败', icon: 'none' })
  } finally {
    applyingPlan.value = false
  }
}

async function handleGrant() {
  if (!selectedUser.value || !grantFeatureKey.value.trim() || !grantAmount.value) return
  granting.value = true
  try {
    const res = await adminApi.adminGrantUserQuota(selectedUser.value.id, grantFeatureKey.value, Number(grantAmount.value))
    uni.showToast({ title: `已补发 ${res.granted_amount}`, icon: 'success' })
    entitlements.value = await adminApi.getAdminUserEntitlements(selectedUser.value.id)
    grantFeatureKey.value = ''
    grantAmount.value = ''
  } catch (e: any) {
    uni.showToast({ title: e.message || '补发失败', icon: 'none' })
  } finally {
    granting.value = false
  }
}
</script>

<style lang="scss" scoped>
.admin-users {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: $lv-page-padding;
  }

  &__list {
    margin: 20rpx 0;
    display: flex;
    flex-direction: column;
    gap: 12rpx;
  }

  &__item {
    display: flex;
    align-items: center;
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
    padding: 24rpx;
    border: 2rpx solid transparent;

    &--active {
      border-color: $lv-primary;
      background: $lv-primary-lighter;
    }
  }

  &__item-info {
    flex: 1;
  }

  &__item-name {
    display: block;
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__item-email {
    display: block;
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    margin-top: 4rpx;
  }

  &__item-tags {
    display: flex;
    gap: 8rpx;
    margin-top: 8rpx;
    flex-wrap: wrap;
  }

  &__section {
    margin: 24rpx 0;
  }

  &__form,
  &__detail {
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: 32rpx;
    margin-top: 20rpx;
    box-shadow: $lv-shadow-sm;
  }

  &__detail-title {
    display: block;
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 16rpx;
    margin-top: 8rpx;
  }

  &__form-row {
    display: flex;
    align-items: center;
    gap: 12rpx;
    margin: 12rpx 0;
    flex-wrap: wrap;
  }

  &__form-label {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__form-actions {
    display: flex;
    gap: 16rpx;
    margin-top: 20rpx;
  }

  &__section-divider {
    height: 1rpx;
    background: $lv-border-light;
    margin: 24rpx 0;
  }

  &__plan-list {
    display: flex;
    flex-wrap: wrap;
    gap: 12rpx;
    margin-bottom: 16rpx;
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

  &__entitlements {
    margin-top: 8rpx;
  }

  &__usage-item {
    margin-bottom: 16rpx;
  }

  &__usage-header {
    display: flex;
    justify-content: space-between;
    margin-bottom: 8rpx;
  }

  &__usage-name {
    font-size: $lv-font-xs;
    color: $lv-text-secondary;
  }

  &__usage-count {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }
}
</style>
