<template>
  <view class="editor-page">
    <view class="editor-page__navbar">
      <view class="editor-page__back" @tap="handleBack">
        <ArrowLeft :size="20" color="#0f172a" />
      </view>
      <text class="editor-page__navbar-title">编辑 Ch.{{ chapterNumber }}</text>
      <lv-button size="sm" @tap="handleSave">保存</lv-button>
    </view>

    <view class="editor-page__body">
      <textarea
        v-model="content"
        class="editor-page__textarea"
        placeholder="开始写作..."
        :auto-height="true"
        @input="handleInput"
      />
    </view>

    <view class="editor-page__status">
      <text class="editor-page__word-count">字数: {{ wordCount }}</text>
      <text :class="['editor-page__save-status', saveStatusClass]">{{ saveStatusText }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onBeforeUnmount } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { get, put } from '@/utils/request'
import type { Chapter } from '@/api/types'
import LvButton from '@/components/lv-button/lv-button.vue'
import { ArrowLeft } from '@lucide/vue'

const chapterId = ref(0)
const chapterNumber = ref(0)
const content = ref('')
const lastSavedContent = ref('')
const saveStatus = ref<'saved' | 'saving' | 'unsaved'>('saved')
let saveTimer: ReturnType<typeof setTimeout> | null = null

const wordCount = computed(() => content.value.length)
const saveStatusClass = computed(() => `editor-page__${saveStatus.value}`)
const saveStatusText = computed(() => {
  switch (saveStatus.value) {
    case 'saved': return '已保存'
    case 'saving': return '保存中...'
    case 'unsaved': return '未保存'
  }
})

onLoad((options) => {
  chapterId.value = parseInt(options?.chapterId || '0')
  if (chapterId.value) {
    loadContent()
  }
})

onBeforeUnmount(() => {
  if (saveTimer) clearTimeout(saveTimer)
  autoSave()
})

async function loadContent() {
  try {
    const chapter = await get<Chapter>(`/api/chapters/${chapterId.value}`)
    content.value = chapter.novel_content || ''
    chapterNumber.value = chapter.chapter_number
    lastSavedContent.value = content.value
  } catch (e) {
    uni.showToast({ title: '加载失败', icon: 'none' })
  }
}

function handleInput() {
  saveStatus.value = 'unsaved'
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(autoSave, 3000)
}

async function autoSave() {
  if (content.value === lastSavedContent.value) return
  saveStatus.value = 'saving'
  try {
    await put(`/api/chapters/${chapterId.value}/content`, { content: content.value })
    lastSavedContent.value = content.value
    saveStatus.value = 'saved'
  } catch (e) {
    saveStatus.value = 'unsaved'
  }
}

async function handleSave() {
  await autoSave()
  if (saveStatus.value === 'saved') {
    uni.showToast({ title: '已保存', icon: 'success' })
  }
}

function handleBack() {
  if (content.value !== lastSavedContent.value) {
    uni.showModal({
      title: '提示',
      content: '有未保存的修改，是否保存？',
      success: async (res) => {
        if (res.confirm) {
          await autoSave()
        }
        uni.navigateBack()
      }
    })
  } else {
    uni.navigateBack()
  }
}
</script>

<style lang="scss" scoped>
.editor-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #ffffff;

  &__navbar {
    display: flex;
    align-items: center;
    gap: 16rpx;
    padding: 16rpx $lv-page-padding;
    padding-top: calc(var(--status-bar-height) + 16rpx);
    border-bottom: 1rpx solid $lv-border-light;
  }

  &__back {
    width: 48rpx;
    height: 48rpx;
    @include flex-center;
  }

  &__navbar-title {
    flex: 1;
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__body {
    flex: 1;
    overflow: hidden;
  }

  &__textarea {
    width: 100%;
    height: 100%;
    padding: 32rpx;
    font-size: 32rpx;
    line-height: 1.8;
    color: $lv-text-primary;
    background: transparent;
    border: none;
    outline: none;
  }

  &__status {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16rpx $lv-page-padding;
    background: $lv-primary-lighter;
    border-top: 1rpx solid $lv-border-light;
  }

  &__word-count {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__save-status {
    font-size: $lv-font-sm;

    &.editor-page__saved { color: $lv-success; }
    &.editor-page__saving { color: $lv-warning; }
    &.editor-page__unsaved { color: $lv-text-muted; }
  }
}
</style>
