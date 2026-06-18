<template>
  <view class="video-characters">
    <lv-navbar title="视频角色库" show-back />
    <view class="video-characters__content">
      <lv-button block :loading="generating" @tap="handleGenerate">生成角色</lv-button>

      <lv-loading v-if="loading" />

      <view v-else-if="characters.length > 0" class="video-characters__list">
        <view v-for="char in characters" :key="char.name" class="video-characters__card">
          <text class="video-characters__name">{{ char.name }}</text>
          <text class="video-characters__version-count">{{ char.versions.length }} 个版本</text>
          <view
            v-for="ver in char.versions"
            :key="ver.id"
            class="video-characters__version"
          >
            <view class="video-characters__version-header" @tap="showDetail(ver)">
              <text class="video-characters__label">{{ ver.label }}</text>
              <text class="video-characters__appearance">{{ truncate(ver.appearance_card, 60) }}</text>
            </view>
            <!-- 参考图缩略图 -->
            <image
              v-if="getRefImageUrl(char.name, ver.id)"
              :src="getRefImageUrl(char.name, ver.id)!"
              mode="aspectFill"
              class="video-characters__ref-thumb"
            />
            <!-- 参考图操作按钮 -->
            <view class="video-characters__ref-actions">
              <lv-button
                v-if="!getRefImageUrl(char.name, ver.id)"
                size="sm"
                :loading="isRefGenLoading(char.name, ver.id)"
                @tap="handleGenRefImage(char.name, ver.id)"
              >生成参考图</lv-button>
              <template v-else>
                <lv-button
                  size="sm"
                  type="secondary"
                  :loading="isRefGenLoading(char.name, ver.id)"
                  @tap="handleRedrawRefImage(char.name, ver.id)"
                >重绘参考图</lv-button>
                <lv-button
                  size="sm"
                  type="danger"
                  :loading="isRefGenLoading(char.name, ver.id)"
                  @tap="handleDeleteRefImage(char.name, ver.id)"
                >删除参考图</lv-button>
              </template>
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
import type { StoryVideoCharacter } from '@/api/types'
import { videoAssetUrl } from '@/utils/url'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import LvModal from '@/components/lv-modal/lv-modal.vue'

const loading = ref(false)
const generating = ref(false)
const characters = ref<StoryVideoCharacter[]>([])
const storyId = ref(0)

const detailVisible = ref(false)
const detailText = ref('')

/* ── 参考图管理状态 ── */
/** 记录每个版本 ref 请求的加载状态，key 为 `${charName}::${verId}` */
const refGenLoading = ref<Record<string, boolean>>({})
/** 记录每个角色/版本的 ref 图片 URL 缓存 */
const refImageCache = ref<Record<string, string | null>>({})

onLoad((options) => {
  storyId.value = Number(options?.storyId || 0)
  loadCharacters()
})

async function loadCharacters() {
  loading.value = true
  try {
    const data = await videoApi.listStoryVideoCharacters(storyId.value)
    characters.value = data.characters
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

async function handleGenerate() {
  generating.value = true
  try {
    const data = await videoApi.generateStoryVideoCharacters(storyId.value)
    characters.value = data.characters
    uni.showToast({ title: '角色生成成功', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '生成失败', icon: 'none' })
  } finally {
    generating.value = false
  }
}

function showDetail(ver: StoryVideoCharacter['versions'][number]) {
  detailText.value = ver.appearance_card
  detailVisible.value = true
}

function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max) + '...' : text
}

/* ── 参考图管理 ── */

/** 获取缓存的参考图 URL */
function getRefImageUrl(charName: string, verId: number): string | null {
  const key = `${charName}::${verId}`
  const cached = refImageCache.value[key]
  if (cached !== undefined) return cached
  const char = characters.value.find(c => c.name === charName)
  const ver = char?.versions.find(v => v.id === verId)
  const url = ver?.ref_asset_url ?? null
  refImageCache.value[key] = url
  return url
}

/** 设置参考图加载状态 */
function setRefGenLoading(charName: string, verId: number, loading: boolean): void {
  refGenLoading.value[`${charName}::${verId}`] = loading
}

/** 检查参考图是否正在加载 */
function isRefGenLoading(charName: string, verId: number): boolean {
  return !!refGenLoading.value[`${charName}::${verId}`]
}

/** 生成角色参考图 */
async function handleGenRefImage(charName: string, verId: number): Promise<void> {
  setRefGenLoading(charName, verId, true)
  try {
    const asset = await videoApi.generateCharacterRefImage(storyId.value, charName, {
      version_id: verId,
    })
    const url = videoAssetUrl(asset.file_path)
    refImageCache.value[`${charName}::${verId}`] = url
    const char = characters.value.find(c => c.name === charName)
    const ver = char?.versions.find(v => v.id === verId)
    if (ver && url) {
      ver.ref_asset_url = url
    }
    uni.showToast({ title: '参考图生成成功', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '生成参考图失败', icon: 'none' })
  } finally {
    setRefGenLoading(charName, verId, false)
  }
}

/** 重绘角色参考图 */
async function handleRedrawRefImage(charName: string, verId: number): Promise<void> {
  uni.showModal({
    title: '重绘参考图',
    content: '请输入重绘提示词（可留空，默认使用完整重绘）',
    editable: true,
    placeholderText: '（可选）描述希望如何修改参考图',
    success: async (res) => {
      if (!res.confirm) return
      const prompt = res.content?.trim() || ''
      setRefGenLoading(charName, verId, true)
      try {
        const asset = await videoApi.redrawCharacterRefImage(storyId.value, charName, {
          version_id: verId,
          prompt: prompt || '',
          mode: 'full',
        })
        const url = videoAssetUrl(asset.file_path)
        refImageCache.value[`${charName}::${verId}`] = url
        const char = characters.value.find(c => c.name === charName)
        const ver = char?.versions.find(v => v.id === verId)
        if (ver && url) {
          ver.ref_asset_url = url
        }
        uni.showToast({ title: '参考图重绘成功', icon: 'success' })
      } catch (e: any) {
        uni.showToast({ title: e.message || '重绘参考图失败', icon: 'none' })
      } finally {
        setRefGenLoading(charName, verId, false)
      }
    },
  })
}

/** 删除角色参考图 */
async function handleDeleteRefImage(charName: string, verId: number): Promise<void> {
  const res = await new Promise<UniApp.ShowModalRes>((resolve) => {
    uni.showModal({
      title: '删除参考图',
      content: `确定要删除 ${charName} 的参考图吗？此操作不可恢复。`,
      success: resolve,
    })
  })
  if (!res.confirm) return
  setRefGenLoading(charName, verId, true)
  try {
    await videoApi.deleteVideoCharacterRefImage(storyId.value, charName)
    refImageCache.value[`${charName}::${verId}`] = null
    const char = characters.value.find(c => c.name === charName)
    const ver = char?.versions.find(v => v.id === verId)
    if (ver) {
      ver.ref_asset_url = null
    }
    uni.showToast({ title: '参考图已删除', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '删除参考图失败', icon: 'none' })
  } finally {
    setRefGenLoading(charName, verId, false)
  }
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

  &__name {
    font-size: 32rpx; font-weight: 600; color: $lv-text-primary; display: block;
  }

  &__version-count {
    font-size: 24rpx; color: $lv-text-muted; display: block; margin-top: 4rpx; margin-bottom: 16rpx;
  }

  &__version {
    background: $lv-bg-start; border-radius: 16rpx; padding: 20rpx; margin-bottom: 12rpx;
  }

  &__version-header {
    // clickable area for version detail
  }

  &__label {
    font-size: 26rpx; font-weight: 500; color: $lv-primary; display: block; margin-bottom: 8rpx;
  }

  &__appearance {
    font-size: 24rpx; color: $lv-text-secondary; display: block; line-height: 1.6;
  }

  &__ref-thumb {
    width: 100%; height: 240rpx; border-radius: 12rpx; margin-top: 16rpx; background: #e5e5e5;
  }

  &__ref-actions {
    display: flex; gap: 12rpx; margin-top: 16rpx;
  }

  &__detail-scroll {
    max-height: 60vh;
  }

  &__detail-text {
    font-size: 28rpx; color: $lv-text-primary; line-height: 1.8; white-space: pre-wrap;
  }
}
</style>
