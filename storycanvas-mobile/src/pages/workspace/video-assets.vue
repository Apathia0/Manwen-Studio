<template>
  <view class="video-assets">
    <lv-navbar title="视频资产管理" show-back />

    <view class="video-assets__content">
      <lv-loading v-if="loading" text="加载中..." vertical class="video-assets__loading" />

      <template v-else>
        <!-- 资产类型筛选标签 -->
        <scroll-view v-if="assetTypes.length > 0" scroll-x class="video-assets__filter-scroll" show-scrollbar="false">
          <view class="video-assets__filter-tabs">
            <view
              v-for="t in assetTypes"
              :key="t.value"
              :class="['video-assets__filter-tab', { 'video-assets__filter-tab--active': activeFilter === t.value }]"
              @tap="activeFilter = t.value"
            >
              <text>{{ t.label }} ({{ t.count }})</text>
            </view>
          </view>
        </scroll-view>

        <!-- 资产列表 -->
        <view v-if="filteredAssets.length > 0" class="video-assets__list">
          <view v-for="asset in filteredAssets" :key="asset.id" class="video-assets__card">
            <!-- 缩略图 -->
            <view class="video-assets__card-thumb" @tap="previewAsset(asset)">
              <image
                v-if="thumbnailUrl(asset)"
                :src="thumbnailUrl(asset) || ''"
                class="video-assets__card-img"
                mode="aspectFill"
              />
              <view v-else class="video-assets__card-thumb-placeholder">
                <lv-icon :name="typeIcon(asset.asset_type)" :size="28" color="#94a3b8" />
              </view>
            </view>

            <!-- 信息区 -->
            <view class="video-assets__card-info">
              <view class="video-assets__card-header">
                <text class="video-assets__card-name">{{ asset.name || '未命名资产' }}</text>
                <view class="video-assets__card-badges">
                  <text :class="['video-assets__badge', `video-assets__badge--${asset.asset_type}`]">
                    {{ typeLabel(asset.asset_type) }}
                  </text>
                  <text :class="['video-assets__badge', `video-assets__badge--scope`]">
                    {{ scopeLabel(asset.usage_scope) }}
                  </text>
                </view>
              </view>
              <text class="video-assets__card-meta">ID: {{ asset.id }} | 版本: {{ asset.revision }} | {{ formatTime(asset.created_at) }}</text>
              <text v-if="asset.provider" class="video-assets__card-meta">提供商: {{ asset.provider }}</text>
            </view>

            <!-- 操作区 -->
            <view class="video-assets__card-actions">
              <view class="video-assets__card-action-btn video-assets__card-action-btn--scope" @tap="openScopeDialog(asset)">
                <text>范围</text>
              </view>
              <view class="video-assets__card-action-btn video-assets__card-action-btn--promote" @tap="handlePromote(asset)">
                <text>提升</text>
              </view>
              <view class="video-assets__card-action-btn video-assets__card-action-btn--delete" @tap="handleDelete(asset)">
                <text>删除</text>
              </view>
            </view>
          </view>
        </view>

        <lv-empty v-else title="暂无视频资产" description="此章节暂无视频资产" />

        <!-- 刷新按钮 -->
        <view class="video-assets__refresh-bar">
          <lv-button size="sm" secondary @tap="loadAssets" :loading="loading">刷新</lv-button>
        </view>
      </template>
    </view>

    <!-- 修改范围弹窗 -->
    <lv-modal
      v-model:show="scopeDialogVisible"
      title="修改资产范围"
      @confirm="handleScopeConfirm"
      :confirm-loading="scopeSaving"
    >
      <view class="video-assets__modal-content">
        <view class="video-assets__modal-hint">
          <text>当前资产: {{ scopeTarget?.name || '未命名' }}</text>
        </view>
        <view class="video-assets__scope-list">
          <view
            v-for="opt in scopeOptions"
            :key="opt.value"
            :class="['video-assets__scope-item', { 'video-assets__scope-item--active': scopeDraft === opt.value }]"
            @tap="scopeDraft = opt.value"
          >
            <text>{{ opt.label }}</text>
            <text class="video-assets__scope-item-desc">{{ opt.desc }}</text>
          </view>
        </view>
      </view>
    </lv-modal>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { videoApi, adminApi } from '@/api'
import type { VideoAsset } from '@/api/types'
import { videoAssetUrl } from '@/utils/url'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import LvModal from '@/components/lv-modal/lv-modal.vue'

const chapterId = ref(0)
const loading = ref(false)
const assets = ref<VideoAsset[]>([])
const activeFilter = ref('all')

// 范围修改弹窗状态
const scopeDialogVisible = ref(false)
const scopeTarget = ref<VideoAsset | null>(null)
const scopeDraft = ref('')
const scopeSaving = ref(false)

const scopeOptions = [
  { value: 'shot_only', label: '仅本镜头', desc: '仅当前镜头可见' },
  { value: 'scene_shared', label: '场景共享', desc: '本场景所有镜头可见' },
  { value: 'chapter_global', label: '章节全局', desc: '本章所有场景可见' },
]

const promoteLevels = [
  { value: 'scene_shared', label: '场景共享' },
  { value: 'chapter_global', label: '章节全局' },
  { value: 'story_default', label: '作品默认' },
]

// 资产类型分组
const assetTypes = computed(() => {
  const counts: Record<string, number> = {}
  for (const a of assets.value) {
    const t = a.asset_type || 'other'
    counts[t] = (counts[t] || 0) + 1
  }
  const list: { value: string; label: string; count: number }[] = [
    { value: 'all', label: '全部', count: assets.value.length },
  ]
  for (const [key, count] of Object.entries(counts)) {
    list.push({ value: key, label: typeLabel(key), count })
  }
  return list
})

const filteredAssets = computed(() => {
  if (activeFilter.value === 'all') return assets.value
  return assets.value.filter((a) => a.asset_type === activeFilter.value)
})

function typeLabel(assetType: string): string {
  const map: Record<string, string> = {
    character: '角色图',
    storyboard: '故事版',
    scene: '场景图',
    video: '视频',
    shot: '镜头',
  }
  return map[assetType] || assetType
}

function typeIcon(assetType: string): string {
  const map: Record<string, string> = {
    character: 'User',
    storyboard: 'Layout',
    scene: 'Image',
    video: 'Video',
    shot: 'Camera',
  }
  return map[assetType] || 'File'
}

function scopeLabel(usageScope: string | null | undefined): string {
  const map: Record<string, string> = {
    shot_only: '镜头级',
    scene_shared: '场景级',
    chapter_global: '章节级',
  }
  return map[usageScope || ''] || '镜头级'
}

function thumbnailUrl(asset: VideoAsset): string | null {
  if (asset.asset_type === 'video') return null
  return videoAssetUrl(asset.file_path)
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  } catch {
    return iso
  }
}

function previewAsset(asset: VideoAsset) {
  const url = thumbnailUrl(asset)
  if (!url) {
    uni.showToast({ title: '此类型不支持预览', icon: 'none' })
    return
  }
  uni.previewImage({ urls: [url], current: url })
}

// ── 删除 ──

function handleDelete(asset: VideoAsset) {
  uni.showModal({
    title: '确认删除',
    content: `确定删除资产「${asset.name || '未命名'}」(ID: ${asset.id})？此操作不可撤销。`,
    success: async (res) => {
      if (!res.confirm) return
      try {
        await videoApi.deleteVideoAsset(asset.id)
        assets.value = assets.value.filter((a) => a.id !== asset.id)
        uni.showToast({ title: '已删除', icon: 'success' })
      } catch (e: any) {
        uni.showToast({ title: e?.message || '删除失败', icon: 'none' })
      }
    },
  })
}

// ── 修改范围 ──

function openScopeDialog(asset: VideoAsset) {
  scopeTarget.value = asset
  scopeDraft.value = asset.usage_scope || 'shot_only'
  scopeDialogVisible.value = true
}

async function handleScopeConfirm() {
  if (!scopeTarget.value || scopeSaving.value) return
  scopeSaving.value = true
  try {
    await adminApi.updateAssetScope(scopeTarget.value.id, {
      usage_scope: scopeDraft.value,
    })
    const idx = assets.value.findIndex((a) => a.id === scopeTarget.value!.id)
    if (idx >= 0) {
      assets.value[idx] = { ...assets.value[idx], usage_scope: scopeDraft.value }
    }
    uni.showToast({ title: '范围已更新', icon: 'success' })
    scopeDialogVisible.value = false
  } catch (e: any) {
    uni.showToast({ title: e?.message || '更新失败', icon: 'none' })
  } finally {
    scopeSaving.value = false
  }
}

// ── 提升资产 ──

function handlePromote(asset: VideoAsset) {
  const items = promoteLevels.map((l) => l.label)
  uni.showActionSheet({
    itemList: items,
    success: async (res) => {
      const level = promoteLevels[res.tapIndex]
      if (!level) return
      uni.showModal({
        title: '确认提升',
        content: `确定将资产「${asset.name || '未命名'}」提升为「${level.label}」？`,
        success: async (modalRes) => {
          if (!modalRes.confirm) return
          try {
            const result = await adminApi.promoteAsset(asset.id, { level: level.value })
            const idx = assets.value.findIndex((a) => a.id === asset.id)
            if (idx >= 0) {
              assets.value[idx] = {
                ...assets.value[idx],
                usage_scope: result.usage_scope || assets.value[idx].usage_scope,
              }
            }
            uni.showToast({ title: '已提升', icon: 'success' })
          } catch (e: any) {
            uni.showToast({ title: e?.message || '提升失败', icon: 'none' })
          }
        },
      })
    },
  })
}

// ── 数据加载 ──

async function loadAssets() {
  if (!chapterId.value) return
  loading.value = true
  try {
    const data = await videoApi.listVideoAssets(chapterId.value)
    assets.value = data.assets || []
  } catch (e: any) {
    uni.showToast({ title: e?.message || '加载资产失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

onLoad((options) => {
  chapterId.value = Number(options?.chapterId || 0)
  if (!chapterId.value) {
    uni.showToast({ title: '未指定章节', icon: 'none' })
  }
  loadAssets()
})
</script>

<style lang="scss" scoped>
.video-assets {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx) $lv-page-padding $lv-page-padding;
  }

  &__loading {
    display: flex;
    justify-content: center;
    padding-top: 200rpx;
  }

  &__filter-scroll {
    white-space: nowrap;
    margin-bottom: 16rpx;
  }

  &__filter-tabs {
    display: inline-flex;
    gap: 8rpx;
  }

  &__filter-tab {
    display: inline-flex;
    align-items: center;
    padding: 10rpx 20rpx;
    background: $lv-surface-solid;
    border-radius: $lv-radius-full;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    border: 1rpx solid $lv-border-light;

    &--active {
      background: $lv-primary;
      color: #fff;
      border-color: $lv-primary;
    }
  }

  &__list {
    display: flex;
    flex-direction: column;
    gap: 16rpx;
  }

  &__card {
    display: flex;
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
    padding: 20rpx;
    box-shadow: $lv-shadow-sm;
    gap: 16rpx;
  }

  &__card-thumb {
    width: 120rpx;
    height: 120rpx;
    border-radius: $lv-radius-sm;
    overflow: hidden;
    flex-shrink: 0;
    background: $lv-primary-lighter;
  }

  &__card-img {
    width: 100%;
    height: 100%;
  }

  &__card-thumb-placeholder {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: $lv-primary-lighter;
  }

  &__card-info {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 6rpx;
  }

  &__card-header {
    display: flex;
    align-items: center;
    gap: 8rpx;
    flex-wrap: wrap;
  }

  &__card-name {
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
    @include text-ellipsis;
    flex: 1;
    min-width: 0;
  }

  &__card-badges {
    display: flex;
    gap: 4rpx;
    flex-shrink: 0;
  }

  &__badge {
    font-size: 20rpx;
    padding: 2rpx 10rpx;
    border-radius: 8rpx;

    &--character {
      background: #dbeafe;
      color: #2563eb;
    }
    &--storyboard {
      background: #fef3c7;
      color: #92400e;
    }
    &--scene {
      background: #dcfce7;
      color: #15803d;
    }
    &--video {
      background: #fce7f3;
      color: #be185d;
    }
    &--shot {
      background: #e0e7ff;
      color: #4f46e5;
    }
    &--scope {
      background: #f1f5f9;
      color: #64748b;
    }
  }

  &__card-meta {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__card-actions {
    display: flex;
    flex-direction: column;
    gap: 6rpx;
    flex-shrink: 0;
    justify-content: center;
  }

  &__card-action-btn {
    padding: 6rpx 14rpx;
    border-radius: $lv-radius-sm;
    font-size: 20rpx;
    text-align: center;

    &--scope {
      background: #eff6ff;
      color: #2563eb;
    }
    &--promote {
      background: #fef3c7;
      color: #92400e;
    }
    &--delete {
      background: #fee2e2;
      color: #dc2626;
    }

    &:active {
      opacity: 0.6;
    }
  }

  &__refresh-bar {
    display: flex;
    justify-content: center;
    margin-top: 32rpx;
  }

  &__modal-content {
    padding: 16rpx 0;
  }

  &__modal-hint {
    margin-bottom: 16rpx;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__scope-list {
    display: flex;
    flex-direction: column;
    gap: 8rpx;
  }

  &__scope-item {
    padding: 20rpx;
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
    border: 2rpx solid $lv-border-light;

    &--active {
      border-color: $lv-primary;
      background: $lv-primary-light;
    }
  }

  &__scope-item-desc {
    display: block;
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    margin-top: 4rpx;
  }
}
</style>
