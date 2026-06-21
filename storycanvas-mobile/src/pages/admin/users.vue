<template>
  <view class="admin-users">
    <view class="admin-users__content">
      <!-- 顶部工具栏:搜索 + 新建 -->
      <view class="admin-users__toolbar">
        <lv-input v-model="searchQuery" placeholder="搜索用户名、邮箱、套餐..." clearable class="admin-users__search" />
        <lv-button size="sm" @tap="showCreateForm = !showCreateForm">
          {{ showCreateForm ? '收起' : '新建用户' }}
        </lv-button>
      </view>

      <!-- 新建用户表单 -->
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

      <!-- 用户列表 -->
      <lv-loading v-if="loading" />

      <view v-else class="admin-users__list">
        <view
          v-for="user in filteredUsers"
          :key="user.id"
          class="admin-users__item"
          @tap="goDetail(user.id)"
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
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { adminApi } from '@/api'
import type { AdminUserItem } from '@/api/admin'
import LvInput from '@/components/lv-input/lv-input.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvTag from '@/components/lv-tag/lv-tag.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import { ChevronRight } from '@lucide/vue'

const loading = ref(false)
const users = ref<AdminUserItem[]>([])
const searchQuery = ref('')
const showCreateForm = ref(false)
const creating = ref(false)

const newUser = ref({ name: '', email: '', password: '', role: 'user' as string })

const filteredUsers = computed(() => {
  const q = searchQuery.value.toLowerCase()
  if (!q) return users.value
  return users.value.filter(u =>
    u.name.toLowerCase().includes(q) ||
    u.email.toLowerCase().includes(q) ||
    u.plan_name?.toLowerCase().includes(q)
  )
})

function goDetail(userId: number) {
  uni.navigateTo({ url: `/pages/admin/user-detail?userId=${userId}` })
}

onMounted(async () => {
  loading.value = true
  try {
    users.value = await adminApi.getAdminUsers()
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
})

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
</script>

<style lang="scss" scoped>
.admin-users {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: $lv-page-padding;
  }

  &__toolbar {
    display: flex;
    align-items: center;
    gap: 16rpx;
    margin-bottom: 20rpx;
  }

  &__search {
    flex: 1;
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

    &:active {
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

  &__form {
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: 32rpx;
    margin-top: 20rpx;
    box-shadow: $lv-shadow-sm;
    display: flex;
    flex-direction: column;
    gap: 16rpx;
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
}
</style>
