<template>
  <view class="admin-system-prompts">
    <view class="admin-system-prompts__header">
      <text class="admin-system-prompts__title">系统提示词</text>
    </view>

    <lv-loading v-if="loading" />

    <lv-empty v-else-if="prompts.length === 0" title="暂无系统提示词" />

    <view v-else class="admin-system-prompts__list">
      <view
        v-for="prompt in prompts"
        :key="prompt.key"
        class="admin-system-prompts__card"
      >
        <text class="admin-system-prompts__card-title">{{ prompt.name }}</text>
        <text class="admin-system-prompts__card-key">{{ prompt.key }}</text>
        <textarea
          v-model="prompt.content"
          class="admin-system-prompts__card-textarea"
          placeholder="输入提示词内容"
        />
        <view class="admin-system-prompts__card-footer">
          <lv-button
            size="sm"
            :loading="savingKeys[prompt.key]"
            @tap="handleSave(prompt)"
          >保存</lv-button>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive } from 'vue'
import { adminApi } from '@/api'
import type { AdminSystemPrompt } from '@/api/admin'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import LvButton from '@/components/lv-button/lv-button.vue'

const loading = ref(false)
const prompts = ref<AdminSystemPrompt[]>([])
const savingKeys = reactive<Record<string, boolean>>({})

onMounted(async () => {
  await loadPrompts()
})

async function loadPrompts() {
  loading.value = true
  try {
    const res = await adminApi.getAdminSystemPrompts()
    prompts.value = Object.values(res)
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

async function handleSave(prompt: AdminSystemPrompt) {
  savingKeys[prompt.key] = true
  try {
    await adminApi.updateAdminSystemPrompts({ [prompt.key]: prompt.content })
    uni.showToast({ title: '保存成功', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '保存失败', icon: 'none' })
  } finally {
    savingKeys[prompt.key] = false
  }
}
</script>

<style lang="scss" scoped>
.admin-system-prompts {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: $lv-page-padding;
    padding-bottom: 0;
  }

  &__title {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__list {
    padding: $lv-page-padding;
    display: flex;
    flex-direction: column;
    gap: 20rpx;
  }

  &__card {
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: 24rpx;
    box-shadow: $lv-shadow-sm;
  }

  &__card-title {
    display: block;
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 4rpx;
  }

  &__card-key {
    display: block;
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    margin-bottom: 16rpx;
    font-family: monospace;
  }

  &__card-textarea {
    width: 100%;
    min-height: 200rpx;
    padding: 16rpx;
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    background: $lv-bg-end;
    border: 1rpx solid $lv-border;
    border-radius: $lv-radius-sm;
    line-height: 1.5;
    box-sizing: border-box;
    resize: none;
  }

  &__card-footer {
    display: flex;
    justify-content: flex-end;
    margin-top: 16rpx;
  }
}
</style>
