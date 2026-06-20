<template>
  <view class="manga-page">
    <lv-navbar title="漫画生成" show-back />

    <view class="manga-page__content">
      <view class="manga-page__settings">
        <text class="manga-page__label">色彩:</text>
        <picker :value="colorModeIndex" :range="['彩色', '黑白']" @change="handleColorModeChange">
          <text class="manga-page__picker">{{ ['彩色', '黑白'][colorModeIndex] }}</text>
        </picker>
        <text class="manga-page__label">张数:</text>
        <picker :value="imageCountIndex" :range="imageCountOptions.map(o => o.label)" @change="handleImageCountChange">
          <text class="manga-page__picker">{{ imageCountOptions[imageCountIndex].label }}</text>
        </picker>
      </view>

      <view class="manga-page__ratio-row">
        <text class="manga-page__label">比例:</text>
        <picker :value="aspectRatioIndex" :range="aspectRatioOptions.map(o => o.label)" @change="handleAspectRatioChange">
          <text class="manga-page__picker">{{ mangaStore.aspectRatio }}</text>
        </picker>
      </view>

      <view class="manga-page__preset-row" @tap="handleOpenStylePreset">
        <text class="manga-page__preset-label">风格预设</text>
        <view class="manga-page__preset-value">
          <text>{{ mangaStore.stylePresetName || '未选择' }}</text>
          <lv-icon name="ChevronRight" :size="14" color="#94a3b8" />
        </view>
      </view>

      <view class="manga-page__tools-row">
        <lv-button secondary block @tap="goCharacterRefs">角色参考图</lv-button>
        <lv-button secondary block @tap="goCharacters">角色外观</lv-button>
        <lv-button secondary block @tap="goRefImages">参考图</lv-button>
      </view>

      <lv-button block :loading="mangaStore.isGenerating || isPolling" @tap="handleGenerate">
        <template v-if="mangaStore.isGenerating || isPolling">生成中...</template>
        <template v-else>
          <lv-icon name="ImagePlus" :size="16" style="margin-right: 8rpx;" />生成漫画
        </template>
      </lv-button>

      <view v-if="mangaStore.isGenerating || isPolling" class="manga-page__progress">
        <lv-progress :percentage="mangaStore.progressPercent" show-info />
        <text class="manga-page__status">{{ mangaStore.progress.statusMsg }}</text>
      </view>

      <view v-if="mangaStore.scenes.length > 0" class="manga-page__scenes">
        <view class="manga-page__scenes-header">
          <text class="manga-page__section-title">分镜脚本 ({{ mangaStore.scenes.length }})</text>
          <view class="manga-page__scenes-actions">
            <lv-button size="sm" secondary @tap="handleAddScene">
              <lv-icon name="Plus" :size="12" />新增
            </lv-button>
            <lv-button size="sm" secondary @tap="handleRegenerateScenes" :loading="regeneratingScenes">重生成</lv-button>
          </view>
        </view>
        <view v-for="(scene, i) in mangaStore.scenes" :key="i" class="manga-page__scene-item">
          <template v-if="editingSceneIndex === i">
            <view class="manga-page__scene-edit">
              <textarea class="manga-page__scene-textarea" v-model="editingSceneDraft" />
              <view class="manga-page__scene-edit-actions">
                <lv-button size="sm" secondary @tap="cancelSceneEdit">取消</lv-button>
                <lv-button size="sm" @tap="saveSceneEdit(i)">保存</lv-button>
              </view>
            </view>
          </template>
          <template v-else>
            <text class="manga-page__scene-num">{{ i + 1 }}.</text>
            <text class="manga-page__scene-text" @tap="startSceneEdit(i, scene)">{{ scene }}</text>
            <view class="manga-page__scene-row-actions">
              <view class="manga-page__scene-btn" @tap="startSceneEdit(i, scene)"><lv-icon name="Pencil" :size="12" color="#2563eb" /></view>
              <view class="manga-page__scene-btn" @tap="handleDeleteScene(i)"><lv-icon name="Trash2" :size="12" color="#ef4444" /></view>
            </view>
          </template>
        </view>
      </view>

      <view class="manga-page__grid">
        <manga-image-card
          v-for="img in mangaStore.images"
          :key="img.id"
          :image-path="img.image_path"
          :image-number="img.image_number"
          @tap="goGallery(img.image_number)"
        />
      </view>

      <lv-empty v-if="!mangaStore.isGenerating && !isPolling && mangaStore.images.length === 0" title="暂无漫画" description="点击生成按钮开始创作" />

      <StyleSelector
        v-if="showStylePreset"
        :presets="stylePresets"
        :selected-name="mangaStore.stylePresetName"
        :style-ref-url="mangaStore.styleReferenceImageUrl"
        :chapter-id="chapterId"
        @update:selected-name="mangaStore.saveStylePreset(chapterId, $event)"
        @update:style-ref-url="mangaStore.setStyleReferenceImageUrl"
        @close="showStylePreset = false"
      />

    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { useMangaStore } from '@/stores/manga'
import { useUiStore } from '@/stores/ui'
import { useStoriesStore } from '@/stores/stories'
import { useMangaGenerationStatus } from '@/composables/useMangaGenerationStatus'
import { mangaApi, adminApi } from '@/api'
import type { VideoStylePreset } from '@/api/admin'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import LvProgress from '@/components/lv-progress/lv-progress.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import MangaImageCard from '@/components/manga-image-card/manga-image-card.vue'
import StyleSelector from '@/components/style-selector/style-selector.vue'

const mangaStore = useMangaStore()
const uiStore = useUiStore()
const storyStore = useStoriesStore()

const chapterId = ref(0)
let storyId = 0
const { isPolling, startPolling, stopPolling, checkAndResume } = useMangaGenerationStatus(chapterId)

const colorModeIndex = ref(0)
const imageCountIndex = ref(1)
const editingSceneIndex = ref(-1)
const editingSceneDraft = ref('')
const regeneratingScenes = ref(false)

const imageCountOptions = [
  { label: '4张', value: 4 },
  { label: '6张', value: 6 },
  { label: '8张', value: 8 },
  { label: '10张', value: 10 },
  { label: '12张', value: 12 },
  { label: '15张', value: 15 },
  { label: '20张', value: 20 }
]

const aspectRatioOptions = [
  { label: '9:16', value: '9:16' },
  { label: '3:4', value: '3:4' },
  { label: '2:3', value: '2:3' },
  { label: '1:1', value: '1:1' },
  { label: '3:2', value: '3:2' },
  { label: '4:3', value: '4:3' },
  { label: '16:9', value: '16:9' },
]

const showStylePreset = ref(false)
const stylePresets = ref<VideoStylePreset[]>([])

onLoad(async (options) => {
  chapterId.value = parseInt(options?.chapterId || '0')
  storyId = parseInt(options?.storyId || '0') || storyStore.activeStoryId || 0

  if (!chapterId.value) {
    uiStore.error('未指定章节')
    return
  }

  try {
    await Promise.all([
      mangaStore.loadScenes(chapterId.value),
      mangaStore.loadColorMode(chapterId.value),
      mangaStore.loadImageCount(chapterId.value)
    ])

    colorModeIndex.value = mangaStore.colorMode === 'bw' ? 1 : 0
    const countIdx = imageCountOptions.findIndex(o => o.value === mangaStore.imageCount)
    if (countIdx !== -1) imageCountIndex.value = countIdx

    mangaStore.loadAspectRatio(chapterId.value)
    mangaStore.loadStylePreset(chapterId.value)
    const res = await adminApi.listStylePresets()
    stylePresets.value = res.presets || []

    // 检查是否有后台运行中的任务（断点续传）
    checkAndResume()
  } catch (e) {
    console.error('加载漫画数据失败:', e)
  }
})

function startSceneEdit(index: number, text: string) {
  editingSceneIndex.value = index
  editingSceneDraft.value = text
}

function cancelSceneEdit() {
  editingSceneIndex.value = -1
  editingSceneDraft.value = ''
}

async function saveSceneEdit(index: number) {
  const newScenes = [...mangaStore.scenes]
  newScenes[index] = editingSceneDraft.value
  try {
    await mangaStore.updateScenes(chapterId.value, newScenes)
    editingSceneIndex.value = -1
    editingSceneDraft.value = ''
    uiStore.success('已保存')
  } catch (e: any) {
    uiStore.error(e.message || '保存失败')
  }
}

function handleAddScene() {
  const newScenes = [...mangaStore.scenes, '']
  mangaStore.scenes = newScenes
  editingSceneIndex.value = newScenes.length - 1
  editingSceneDraft.value = ''
}

function handleDeleteScene(index: number) {
  uni.showModal({
    title: '确认删除',
    content: '确定删除此分镜？',
    success: async (res) => {
      if (!res.confirm) return
      const newScenes = mangaStore.scenes.filter((_: any, i: number) => i !== index)
      try {
        await mangaStore.updateScenes(chapterId.value, newScenes)
        mangaStore.scenes = newScenes
        uiStore.success('已删除')
      } catch (e: any) {
        uiStore.error(e.message || '删除失败')
      }
    }
  })
}

async function handleRegenerateScenes() {
  if (regeneratingScenes.value) return
  regeneratingScenes.value = true
  try {
    await mangaStore.generateScenes(chapterId.value)
    uiStore.success('分镜已重新生成')
  } catch (e: any) {
    uiStore.error(e.message || '重生成失败')
  } finally {
    regeneratingScenes.value = false
  }
}

function handleColorModeChange(e: any) {
  colorModeIndex.value = e.detail.value
  const mode = colorModeIndex.value === 0 ? 'color' : 'bw'
  mangaStore.saveColorMode(chapterId.value, mode as 'color' | 'bw')
}

function handleImageCountChange(e: any) {
  imageCountIndex.value = e.detail.value
  const count = imageCountOptions[imageCountIndex.value].value
  mangaStore.saveImageCount(chapterId.value, count)
}

const aspectRatioIndex = computed(() =>
  aspectRatioOptions.findIndex(o => o.value === mangaStore.aspectRatio)
)

function handleAspectRatioChange(e: any) {
  const ratio = aspectRatioOptions[e.detail.value].value
  mangaStore.saveAspectRatio(chapterId.value, ratio)
}

async function handleOpenStylePreset() {
  if (stylePresets.value.length === 0) {
    try {
      const res = await adminApi.listStylePresets()
      stylePresets.value = res.presets || []
    } catch (e: any) {
      uiStore.error(e.message || '加载风格预设失败')
      return
    }
  }
  showStylePreset.value = true
}

async function handleGenerate() {
  if (!chapterId.value) return
  await mangaStore.startMangaGeneration(chapterId.value)
}

function goCharacterRefs() {
  uni.navigateTo({ url: `/pages/workspace/character-refs?storyId=${storyId}&chapterId=${chapterId.value}` })
}

function goGallery(imageNumber: number) {
  uni.navigateTo({ url: `/pages/workspace/manga-gallery?chapterId=${chapterId.value}&imageNumber=${imageNumber}` })
}

function goCharacters() {
  uni.navigateTo({ url: `/pages/workspace/character-profiles?storyId=${chapterId.value}` })
}

function goRefImages() {
  uni.navigateTo({ url: `/pages/workspace/ref-images?chapterId=${chapterId.value}` })
}
</script>

<style lang="scss" scoped>
.manga-page {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx) $lv-page-padding $lv-page-padding;
  }

  &__settings {
    display: flex;
    align-items: center;
    gap: 12rpx;
    margin-bottom: 16rpx;
  }

  &__label {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__picker {
    font-size: $lv-font-sm;
    color: $lv-primary;
    background: $lv-primary-light;
    padding: 8rpx 20rpx;
    border-radius: $lv-radius-full;
  }

  &__progress {
    margin: 16rpx 0;
    padding: 24rpx;
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
    box-shadow: $lv-shadow-sm;
  }

  &__status {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    margin-top: 12rpx;
  }

  &__scenes {
    margin: 24rpx 0;
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
    padding: 24rpx;
    box-shadow: $lv-shadow-sm;
  }

  &__section-title {
    display: block;
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 16rpx;
  }

  &__scene-item {
    display: flex;
    gap: 12rpx;
    padding: 12rpx 0;
    border-bottom: 1rpx solid $lv-border-light;

    &:last-child {
      border-bottom: none;
    }
  }

  &__scene-num {
    font-size: $lv-font-sm;
    color: $lv-primary;
    font-weight: 600;
    flex-shrink: 0;
  }

  &__scene-text {
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    line-height: 1.6;
    flex: 1;
  }
  &__scenes-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16rpx;
  }
  &__scenes-actions {
    display: flex;
    gap: 8rpx;
  }
  &__scene-edit {
    width: 100%;
  }
  &__scene-textarea {
    width: 100%;
    min-height: 120rpx;
    padding: 16rpx;
    background: $lv-bg-start;
    border-radius: $lv-radius-sm;
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    line-height: 1.6;
  }
  &__scene-edit-actions {
    display: flex;
    gap: 8rpx;
    justify-content: flex-end;
    margin-top: 8rpx;
  }
  &__scene-row-actions {
    display: flex;
    gap: 8rpx;
    flex-shrink: 0;
    margin-left: auto;
  }
  &__scene-btn {
    padding: 4rpx 8rpx;
  }

  &__grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16rpx;
    margin: 16rpx 0;
  }

  &__ratio-row {
    display: flex;
    align-items: center;
    gap: 12rpx;
    margin-bottom: 12rpx;
  }
  &__preset-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16rpx;
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
    margin-bottom: 16rpx;
  }
  &__preset-label {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }
  &__preset-value {
    display: flex;
    align-items: center;
    gap: 8rpx;
    font-size: $lv-font-sm;
    color: $lv-text-primary;
  }
  &__tools-row {
    display: flex;
    gap: 16rpx;
    margin-top: 16rpx;
  }
}
</style>
