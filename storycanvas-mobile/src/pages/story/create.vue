<template>
  <view class="create-story">
    <lv-navbar title="新建故事" show-back />

    <view class="create-story__content">
      <lv-input
        v-model="title"
        label="故事标题"
        placeholder="输入故事标题"
        :error="titleError"
      />
      <lv-input
        v-model="description"
        placeholder="故事描述 (可选)"
      />

      <view v-if="errorMsg" class="create-story__error">
        <text class="create-story__error-text">{{ errorMsg }}</text>
      </view>

      <lv-button
        block
        :loading="loading"
        @tap="handleCreate"
      >
        创建故事
      </lv-button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useStoriesStore } from '@/stores/stories'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvInput from '@/components/lv-input/lv-input.vue'
import LvButton from '@/components/lv-button/lv-button.vue'

const storyStore = useStoriesStore()

const title = ref('')
const description = ref('')
const titleError = ref('')
const errorMsg = ref('')
const loading = ref(false)

function validate(): boolean {
  titleError.value = ''
  errorMsg.value = ''

  if (!title.value.trim()) {
    titleError.value = '请输入故事标题'
    return false
  }
  return true
}

async function handleCreate() {
  if (!validate()) return

  loading.value = true
  try {
    const story = await storyStore.createStory(title.value.trim(), description.value.trim() || undefined)
    uni.showToast({ title: '创建成功', icon: 'success' })
    setTimeout(() => {
      uni.redirectTo({ url: `/pages/story/onboarding?storyId=${story.id}` })
    }, 1500)
  } catch (e: any) {
    errorMsg.value = e.message || '创建失败'
  } finally {
    loading.value = false
  }
}
</script>

<style lang="scss" scoped>
.create-story {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding $lv-page-padding;
  }

  &__error {
    margin-bottom: 24rpx;
    text-align: center;
  }

  &__error-text {
    font-size: $lv-font-sm;
    color: $lv-error;
  }
}
</style>
