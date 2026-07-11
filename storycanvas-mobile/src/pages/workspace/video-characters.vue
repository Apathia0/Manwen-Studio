<template>
  <view class="video-characters">
    <lv-navbar title="视频角色库" show-back />
    <view class="video-characters__content">
      <lv-button block :loading="generating" @tap="handleGenerate">生成角色</lv-button>

      <lv-loading v-if="loading" />

      <view v-else-if="characters.length > 0" class="video-characters__list">
        <view v-for="char in characters" :key="char.name" class="video-characters__card">
          <view class="video-characters__header">
            <text class="video-characters__name">{{ char.name }}</text>
            <lv-button size="sm" type="secondary" @tap="handleCreateVersion(char)">创建新版本</lv-button>
          </view>
          <text class="video-characters__version-count">{{ char.versions.length }} 个版本</text>
          <view
            v-for="ver in char.versions"
            :key="ver.id"
            class="video-characters__version"
            :class="{ 'video-characters__version--active': activeVersionId === ver.id }"
            @tap="handleVersionClick(ver)"
          >
            <image
              v-if="ver.ref_asset_url"
              class="video-characters__thumbnail"
              :src="ver.ref_asset_url"
              mode="aspectFill"
            />
            <view class="video-characters__version-body">
              <text class="video-characters__label">{{ ver.label }}</text>
              <text v-if="ver.created_at" class="video-characters__created-at">{{ formatTime(ver.created_at) }}</text>
              <text class="video-characters__appearance" @tap.stop="showDetail(ver)">{{ truncate(ver.appearance_card, 60) }}</text>
            </view>
            <view class="video-characters__version-actions">
              <text class="video-characters__action" @tap.stop="handleSetCurrent(ver)">设为当前</text>
              <text class="video-characters__action video-characters__action--danger" @tap.stop="handleDeleteVersion(char, ver)">删除</text>
            </view>
          </view>
        </view>
      </view>

      <lv-empty v-else title="暂无视频角色" description="点击上方按钮生成角色" />

      <lv-modal v-model:visible="detailVisible" title="角色描述">
        <scroll-view scroll-y class="video-characters__detail-scroll">
          <text class="video-characters__detail-text">{{ detailText }}</text>
        </scroll-view>
      </lv-modal>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { videoApi } from '@/api'
import type { VideoCharacter, CharacterVersion } from '@/api/types'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import LvModal from '@/components/lv-modal/lv-modal.vue'

const loading = ref(false)
const generating = ref(false)
const characters = ref<VideoCharacter[]>([])
const storyId = ref(0)
const activeVersionId = ref(0)

const detailVisible = ref(false)
const detailText = ref('')

onLoad((options) => {
  storyId.value = Number(options?.storyId || 0)
  loadCharacters()
})

async function loadCharacters() {
  loading.value = true
  try {
    const data = await videoApi.listVideoCharacters(storyId.value)
    characters.value = data.characters
    // 自动选中第一个默认版本
    for (const char of data.characters) {
      const defVer = char.versions.find((v) => v.is_default)
      if (defVer) {
        activeVersionId.value = defVer.id
        break
      }
    }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : '加载失败'
    uni.showToast({ title: msg, icon: 'none' })
  } finally {
    loading.value = false
  }
}

async function handleGenerate() {
  generating.value = true
  try {
    const data = await videoApi.generateVideoCharacters(storyId.value)
    characters.value = data.characters
    activeVersionId.value = 0
    uni.showToast({ title: '角色生成成功', icon: 'success' })
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : '生成失败'
    uni.showToast({ title: msg, icon: 'none' })
  } finally {
    generating.value = false
  }
}

async function handleCreateVersion(char: VideoCharacter) {
  uni.showModal({
    title: '创建新版本',
    content: '请输入版本标签',
    editable: true,
    placeholderText: '例如：现代装、古风版',
    success: async (res) => {
      if (!res.confirm || !res.content) return
      const label = res.content.trim()
      if (!label) return
      try {
        await videoApi.createCharacterVersion(storyId.value, char.name, { version_label: label })
        uni.showToast({ title: '版本创建成功', icon: 'success' })
        await loadCharacters()
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : '创建失败'
        uni.showToast({ title: msg, icon: 'none' })
      }
    },
  })
}

async function handleDeleteVersion(char: VideoCharacter, ver: CharacterVersion) {
  uni.showModal({
    title: '删除版本',
    content: `确定删除版本「${ver.label}」吗？此操作不可撤销。`,
    success: async (res) => {
      if (!res.confirm) return
      try {
        await videoApi.deleteCharacterVersion(storyId.value, char.name, ver.label)
        uni.showToast({ title: '版本已删除', icon: 'success' })
        if (activeVersionId.value === ver.id) {
          activeVersionId.value = 0
        }
        await loadCharacters()
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : '删除失败'
        uni.showToast({ title: msg, icon: 'none' })
      }
    },
  })
}

function handleVersionClick(ver: CharacterVersion) {
  activeVersionId.value = ver.id
  showDetail(ver)
}

function handleSetCurrent(ver: CharacterVersion) {
  activeVersionId.value = ver.id
}

function showDetail(ver: CharacterVersion) {
  detailText.value = ver.appearance_card
  detailVisible.value = true
}

function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max) + '...' : text
}

function formatTime(isoStr: string): string {
  const d = new Date(isoStr)
  if (isNaN(d.getTime())) return isoStr
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
</script>

<style lang="scss" scoped>
.video-characters {
  min-height: 100vh; background: $lv-bg-start;

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding;
  }

  &__list {
    margin-top: 24rpx;
  }

  &__card {
    background: #fff; border-radius: 24rpx; padding: 28rpx; margin-bottom: 16rpx;
  }

  &__header {
    display: flex; align-items: center; justify-content: space-between;
  }

  &__name {
    font-size: 32rpx; font-weight: 600; color: $lv-text-primary;
  }

  &__version-count {
    font-size: 24rpx; color: $lv-text-muted; display: block; margin-top: 4rpx; margin-bottom: 16rpx;
  }

  &__version {
    background: $lv-bg-start; border-radius: 16rpx; padding: 20rpx; margin-bottom: 12rpx;
    display: flex; align-items: flex-start; gap: 16rpx;
    border: 2rpx solid transparent;

    &--active {
      border-color: $lv-primary;
    }
  }

  &__thumbnail {
    width: 80rpx; height: 80rpx; border-radius: 12rpx; flex-shrink: 0; background: $lv-bg-mid;
  }

  &__version-body {
    flex: 1; min-width: 0;
  }

  &__label {
    font-size: 26rpx; font-weight: 500; color: $lv-primary; display: block; margin-bottom: 4rpx;
  }

  &__created-at {
    font-size: 22rpx; color: $lv-text-muted; display: block; margin-bottom: 6rpx;
  }

  &__appearance {
    font-size: 24rpx; color: $lv-text-secondary; display: block; line-height: 1.6;
  }

  &__version-actions {
    display: flex; flex-direction: column; gap: 8rpx; flex-shrink: 0; padding-top: 4rpx;
  }

  &__action {
    font-size: 22rpx; color: $lv-primary; padding: 4rpx 8rpx;

    &--danger {
      color: $lv-error;
    }
  }

  &__detail-scroll {
    max-height: 60vh;
  }

  &__detail-text {
    font-size: 28rpx; color: $lv-text-primary; line-height: 1.8; white-space: pre-wrap;
  }
}
</style>
