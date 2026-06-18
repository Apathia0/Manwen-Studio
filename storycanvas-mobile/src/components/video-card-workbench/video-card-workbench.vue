<template>
  <!-- 视频卡片工作台 - 全屏弹窗 -->
  <view v-if="visible" class="vwb">
    <!-- 遮罩层 -->
    <view class="vwb__mask" @tap="handleClose" />

    <!-- 主体容器 -->
    <view class="vwb__container" @tap.stop>
      <!-- 顶部栏：镜头标题 + 关闭按钮 -->
      <view class="vwb__header">
        <view class="vwb__header-left">
          <text class="vwb__header-icon">🛠</text>
          <text class="vwb__header-title">镜头 {{ shotIndex }} 工作台</text>
        </view>
        <view class="vwb__header-close" @tap="handleClose">
          <text class="vwb__close-icon">✕</text>
        </view>
      </view>

      <!-- 4 类卡片导航标签栏 -->
      <scroll-view scroll-x class="vwb__tabs-scroll" show-scrollbar="false">
        <view class="vwb__tabs">
          <view
            v-for="tab in tabs"
            :key="tab.key"
            :class="['vwb__tab', { 'vwb__tab--active': currentType === tab.key }]"
            @tap="switchTab(tab.key)"
          >
            <text class="vwb__tab-icon">{{ tab.icon }}</text>
            <text class="vwb__tab-label">{{ tab.label }}</text>
          </view>
        </view>
      </scroll-view>

      <!-- 内容区域 - 按卡片类型显示占位内容 -->
      <scroll-view scroll-y class="vwb__content">
        <!-- 角色卡片 -->
        <view v-if="currentType === 'character'" class="vwb__card-content">
          <view class="vwb__placeholder">
            <text class="vwb__placeholder-icon">👤</text>
            <text class="vwb__placeholder-title">角色资产</text>
            <text class="vwb__placeholder-desc">管理本镜头的角色参考图和外观设定</text>
            <!-- TODO: T12 将实现角色卡片完整内容 -->
            <text class="vwb__placeholder-todo">🚧 T12 - 角色卡片功能开发中</text>
          </view>
        </view>

        <!-- 故事版卡片 -->
        <view v-else-if="currentType === 'storyboard'" class="vwb__card-content">
          <view v-if="shotData?.storyboard_image_url" class="vwb__preview-section">
            <image
              :src="assetUrl(shotData.storyboard_image_url)"
              class="vwb__preview-image"
              mode="aspectFit"
            />
          </view>
          <view class="vwb__info-section">
            <view class="vwb__info-row">
              <text class="vwb__info-label">状态</text>
              <view :class="['vwb__badge', `vwb__badge--${statusBadge(shotData)}`]">
                <text>{{ statusLabel(shotData) }}</text>
              </view>
            </view>
            <view v-if="shotData?.storyboard_prompt" class="vwb__info-row">
              <text class="vwb__info-label">故事版提示词</text>
              <text class="vwb__info-text vwb__info-text--prompt">{{ shotData.storyboard_prompt }}</text>
            </view>
            <view v-if="!shotData?.storyboard_image_url" class="vwb__placeholder">
              <text class="vwb__placeholder-icon">🎬</text>
              <text class="vwb__placeholder-title">暂无故事版</text>
              <text class="vwb__placeholder-desc">点击下方"重新生成"创建故事版图片</text>
            </view>
          </view>
        </view>

        <!-- 场景卡片 -->
        <view v-else-if="currentType === 'scene'" class="vwb__card-content">
          <view class="vwb__info-section">
            <view v-if="shotData?.scene_location" class="vwb__info-row">
              <text class="vwb__info-label">场景位置</text>
              <text class="vwb__info-text">{{ shotData.scene_location }}</text>
            </view>
            <view v-if="shotData?.time_of_day" class="vwb__info-row">
              <text class="vwb__info-label">时间</text>
              <text class="vwb__info-text">{{ shotData.time_of_day }}</text>
            </view>
            <view v-if="shotData?.scene_prompt" class="vwb__info-row">
              <text class="vwb__info-label">场景提示词</text>
              <text class="vwb__info-text vwb__info-text--prompt">{{ shotData.scene_prompt }}</text>
            </view>
            <view v-if="!shotData?.scene_location && !shotData?.scene_prompt" class="vwb__placeholder">
              <text class="vwb__placeholder-icon">🏞</text>
              <text class="vwb__placeholder-title">暂无场景详情</text>
              <text class="vwb__placeholder-desc">先生成镜头详情以获取场景信息</text>
            </view>
          </view>
        </view>

        <!-- 视频卡片 -->
        <view v-else-if="currentType === 'video'" class="vwb__card-content">
          <view v-if="shotData?.video_url" class="vwb__preview-section">
            <video
              :src="assetUrl(shotData.video_url)"
              class="vwb__preview-video"
              controls
            />
          </view>
          <view class="vwb__info-section">
            <view class="vwb__info-row">
              <text class="vwb__info-label">状态</text>
              <view :class="['vwb__badge', `vwb__badge--${statusBadge(shotData)}`]">
                <text>{{ statusLabel(shotData) }}</text>
              </view>
            </view>
            <view v-if="shotData?.video_prompt" class="vwb__info-row">
              <text class="vwb__info-label">视频提示词</text>
              <text class="vwb__info-text vwb__info-text--prompt">{{ shotData.video_prompt }}</text>
            </view>
            <view v-if="!shotData?.video_url" class="vwb__placeholder">
              <text class="vwb__placeholder-icon">▶</text>
              <text class="vwb__placeholder-title">暂无视频</text>
              <text class="vwb__placeholder-desc">点击下方"重新生成"生成视频</text>
            </view>
          </view>
        </view>
      </scroll-view>

      <!-- 底部操作栏：6 个功能按钮 -->
      <view class="vwb__actions">
        <!-- 第一行：主要操作 -->
        <view class="vwb__actions-row">
          <view
            :class="['vwb__action-btn', 'vwb__action-btn--primary', { 'vwb__action-btn--disabled': busy || !currentResource }]"
            @tap="handleRegenerate"
          >
            <text v-if="busy === 'regenerate'" class="vwb__action-spinner">⟳</text>
            <text v-else class="vwb__action-icon">🔄</text>
            <text class="vwb__action-label">{{ busy === 'regenerate' ? '生成中...' : '重新生成' }}</text>
          </view>

          <view
            :class="['vwb__action-btn', 'vwb__action-btn--primary', { 'vwb__action-btn--disabled': busy || !currentResource }]"
            @tap="handleUploadReplace"
          >
            <text class="vwb__action-icon">📤</text>
            <text class="vwb__action-label">上传替换</text>
          </view>

          <view
            :class="['vwb__action-btn', 'vwb__action-btn--primary', { 'vwb__action-btn--disabled': busy || !currentResource }]"
            @tap="handleRedraw"
          >
            <text class="vwb__action-icon">🎨</text>
            <text class="vwb__action-label">重绘</text>
          </view>
        </view>

        <!-- 第二行：辅助操作 -->
        <view class="vwb__actions-row">
          <view
            :class="['vwb__action-btn', 'vwb__action-btn--secondary', { 'vwb__action-btn--disabled': busy || !currentResource }]"
            @tap="handleReanalyzePrompt"
          >
            <text class="vwb__action-icon">🔍</text>
            <text class="vwb__action-label">分析提示词</text>
          </view>

          <view
            :class="['vwb__action-btn', 'vwb__action-btn--secondary', { 'vwb__action-btn--disabled': busy || !currentResource }]"
            @tap="handlePromptSave"
          >
            <text class="vwb__action-icon">💾</text>
            <text class="vwb__action-label">保存提示词</text>
          </view>

          <view
            :class="['vwb__action-btn', 'vwb__action-btn--danger', { 'vwb__action-btn--disabled': busy }]"
            @tap="handleDelete"
          >
            <text class="vwb__action-icon">🗑</text>
            <text class="vwb__action-label">删除</text>
          </view>
        </view>
      </view>
    </view>

    <!-- 隐藏的文件选择器（用于上传替换） -->
    <!-- uni-app 中通过 uni.chooseImage/uni.chooseVideo 实现，此处不需要 DOM input -->
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { videoApi } from '@/api'
import { BASE_URL } from '@/utils/constants'
import type { ChapterVideoShot } from '@/api/types'

// ── 卡片类型定义 ──
type CardType = 'character' | 'storyboard' | 'scene' | 'video'

// ── Props ──
interface WorkbenchProps {
  /** 控制弹窗显隐 */
  visible: boolean
  /** 镜头 ID */
  shotId: number
  /** 镜头完整数据 */
  shotData: ChapterVideoShot | null
  /** 工作流 ID */
  workflowId: number
  /** 章节 ID */
  chapterId: number
  /** 初始激活的卡片类型 */
  initialType?: CardType
}

const props = withDefaults(defineProps<WorkbenchProps>(), {
  initialType: 'storyboard',
})

// ── Emits ──
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'updated', result?: unknown): void
}>()

// ── 状态 ──
/** 当前激活的卡片类型 */
const currentType = ref<CardType>(props.initialType || 'storyboard')
/** 忙碌标识：null = 空闲，字符串 = 当前操作名 */
const busy = ref<string | null>(null)

/** 监听 initialType 变化，同步到 currentType */
watch(
  () => props.initialType,
  (val) => {
    if (val) currentType.value = val
  }
)

/** 标签栏配置 */
interface TabConfig {
  key: CardType
  label: string
  icon: string
}

const tabs: TabConfig[] = [
  { key: 'character', label: '角色', icon: '👤' },
  { key: 'storyboard', label: '故事版', icon: '🎬' },
  { key: 'scene', label: '场景', icon: '🏞' },
  { key: 'video', label: '视频', icon: '▶' },
]

/** 镜头序号（从 shotData 中读取） */
const shotIndex = computed(() => props.shotData?.shot_index ?? props.shotId)

/** 当前资源（根据卡片类型从 shotData 派生） */
const currentResource = computed(() => {
  if (!props.shotData) return null
  const shot = props.shotData

  switch (currentType.value) {
    case 'character':
      // 角色资源：从 shot.characters 和 character_prompts 派生
      return {
        id: shot.id,
        type: 'character' as const,
        characters: shot.characters || [],
        prompts: shot.character_prompts || [],
      }
    case 'storyboard':
      // 故事版资源：图片 URL + 提示词
      return {
        id: shot.id,
        type: 'storyboard' as const,
        url: shot.storyboard_image_url || null,
        prompt: shot.storyboard_prompt || null,
        hasAsset: !!shot.storyboard_image_url,
      }
    case 'scene':
      // 场景资源：位置 + 时间 + 场景提示词
      return {
        id: shot.id,
        type: 'scene' as const,
        location: shot.scene_location || null,
        timeOfDay: shot.time_of_day || null,
        prompt: shot.scene_prompt || null,
      }
    case 'video':
      // 视频资源：URL + 提示词
      return {
        id: shot.id,
        type: 'video' as const,
        url: shot.video_url || null,
        prompt: shot.video_prompt || null,
        hasAsset: !!shot.video_url,
      }
    default:
      return null
  }
})

// ── 工具方法 ──

/** 生成静态资源完整 URL */
function assetUrl(path?: string | null): string {
  if (!path) return ''
  if (path.startsWith('http://') || path.startsWith('https://') || path.startsWith('/static/')) return path
  return `${BASE_URL}/static/video/${path.replace(/^video_outputs[/\\]/, '')}`
}

/** 状态徽标样式类名 */
function statusBadge(shot: ChapterVideoShot | null): string {
  if (!shot) return 'pending'
  if (shot.status === 'failed') return 'failed'
  if (shot.status === 'video_ready') return 'success'
  if (shot.status === 'storyboard_ready') return 'info'
  return 'pending'
}

/** 状态文本标签 */
function statusLabel(shot: ChapterVideoShot | null): string {
  if (!shot) return '未知'
  const labels: Record<string, string> = {
    pending: '待处理',
    storyboard_generating: '故事版生成中',
    storyboard_ready: '故事版已完成',
    video_generating: '视频生成中',
    video_ready: '视频已完成',
    failed: '失败',
  }
  return labels[shot.status] || shot.status
}

// ── 标签切换 ──

/** 切换当前激活的卡片类型 */
function switchTab(type: CardType) {
  currentType.value = type
}

// ── 关闭弹窗 ──

/** 关闭工作台 */
function handleClose() {
  busy.value = null
  emit('close')
}

// ── 6 个操作 Handler（骨架 + 保护逻辑 + TODO 注释）──

/**
 * 1. 重新生成
 * 根据 currentType 调用对应的重新生成 API
 */
async function handleRegenerate() {
  if (busy.value || !currentResource.value) return
  busy.value = 'regenerate'
  try {
    // TODO: T12-T15 将根据卡片类型实现完整的重新生成逻辑
    //   character  → regenerateVideoAsset (T12)
    //   storyboard → regenerateChapterWorkflowStoryboard (T13)
    //   scene      → reanalyzeChapterShotPrompts (T14)
    //   video      → regenerateChapterWorkflowVideo (T15)
    const type = currentType.value
    switch (type) {
      case 'storyboard':
        await videoApi.regenerateChapterWorkflowStoryboard(props.shotId)
        break
      case 'video':
        await videoApi.regenerateChapterWorkflowVideo(props.shotId)
        break
      default:
        uni.showToast({ title: `${currentType.value} 重新生成功能即将实现`, icon: 'none' })
        break
    }
    emit('updated')
  } catch (e: any) {
    uni.showToast({ title: e?.message || '操作失败', icon: 'none' })
  } finally {
    busy.value = null
  }
}

/**
 * 2. 上传替换
 * 根据 currentType 上传文件替换当前资源
 */
async function handleUploadReplace() {
  if (busy.value || !currentResource.value) return
  busy.value = 'upload'
  try {
    // TODO: T12-T15 将根据卡片类型实现完整的上传替换逻辑
    //   character  → replaceVideoAsset (T12)
    //   storyboard → uploadShotStoryboard (T13)
    //   video      → uploadShotVideo (T15)
    //   scene      → 场景类型不支持上传替换，但保留入口

    // uni-app 中使用 uni.chooseImage / uni.chooseVideo 选择文件
    const type = currentType.value
    if (type === 'storyboard' || type === 'character') {
      const res = await uni.chooseImage({ count: 1, sizeType: ['compressed'] })
      if (res.tempFilePaths.length > 0) {
        if (type === 'storyboard') {
          await videoApi.uploadShotStoryboard(props.shotId, res.tempFilePaths[0])
        }
        emit('updated')
      }
    } else if (type === 'video') {
      const res = await uni.chooseVideo({ sourceType: ['album'] })
      if (res.tempFilePath) {
        await videoApi.uploadShotVideo(props.shotId, res.tempFilePath)
        emit('updated')
      }
    } else {
      uni.showToast({ title: '场景类型暂不支持上传', icon: 'none' })
    }
  } catch (e: any) {
    uni.showToast({ title: e?.message || '上传替换失败', icon: 'none' })
  } finally {
    busy.value = null
  }
}

/**
 * 3. 重绘
 * 根据 currentType 调用对应的重绘/重新生成 API
 */
async function handleRedraw() {
  if (busy.value || !currentResource.value) return
  busy.value = 'redraw'
  try {
    // TODO: T12-T15 将根据卡片类型实现完整的重绘逻辑
    //   character  → regenerateVideoAsset（支持 mask 局部重绘）(T12)
    //   storyboard → regenerateChapterWorkflowStoryboard (T13)
    //   video      → regenerateChapterWorkflowVideo (T15)
    //   scene      → 场景类型通过重新分析提示词实现 (T14)
    const type = currentType.value
    switch (type) {
      case 'storyboard':
        await videoApi.regenerateChapterWorkflowStoryboard(props.shotId)
        break
      case 'video':
        await videoApi.regenerateChapterWorkflowVideo(props.shotId)
        break
      default:
        uni.showToast({ title: `${currentType.value} 重绘功能即将实现`, icon: 'none' })
        break
    }
    emit('updated')
  } catch (e: any) {
    uni.showToast({ title: e?.message || '重绘失败', icon: 'none' })
  } finally {
    busy.value = null
  }
}

/**
 * 4. 删除
 * 删除当前卡片资源（需确认）
 */
async function handleDelete() {
  if (busy.value) return
  // uni-app 确认对话框
  const confirmRes = await uni.showModal({
    title: '确认删除',
    content: `确定要删除当前${getTypeLabel(currentType.value)}资源吗？此操作不可撤销。`,
  })
  if (!confirmRes.confirm) return

  busy.value = 'delete'
  try {
    // TODO: T12-T15 将根据卡片类型实现完整的删除逻辑
    //   character  → deleteVideoAsset (T12)
    //   storyboard → clearShotStoryboard (T13)
    //   video      → clearShotVideo (T15)
    //   scene      → 场景类型不支持删除
    const type = currentType.value
    switch (type) {
      case 'storyboard':
        await videoApi.clearShotStoryboard(props.shotId)
        break
      case 'video':
        await videoApi.clearShotVideo(props.shotId)
        break
      default:
        uni.showToast({ title: `${currentType.value} 删除功能即将实现`, icon: 'none' })
        break
    }
    emit('updated')
  } catch (e: any) {
    uni.showToast({ title: e?.message || '删除失败', icon: 'none' })
  } finally {
    busy.value = null
  }
}

/**
 * 5. 重新分析提示词
 * 调用 AI 重新分析并生成当前镜头提示词
 */
async function handleReanalyzePrompt() {
  if (busy.value || !currentResource.value) return
  busy.value = 'reanalyze'
  try {
    // TODO: T12-T15 将根据卡片类型实现完整分析提示词逻辑
    //   character  → 角色提示词分析 (T12)
    //   storyboard → reanalyzeChapterWorkflowStoryboardPrompt (T13)
    //   scene      → reanalyzeChapterShotPrompts (T14)
    //   video      → reanalyzeChapterShotPrompts (T15)
    await videoApi.reanalyzeChapterShotPrompts(props.shotId)
    emit('updated')
  } catch (e: any) {
    uni.showToast({ title: e?.message || '分析提示词失败', icon: 'none' })
  } finally {
    busy.value = null
  }
}

/**
 * 6. 保存提示词
 * 保存当前编辑的提示词到后端
 */
async function handlePromptSave() {
  if (busy.value || !currentResource.value) return
  busy.value = 'savePrompt'
  try {
    // TODO: T12-T15 将根据卡片类型实现完整的保存提示词逻辑
    //   character  → 保存角色提示词 (T12)
    //   storyboard → saveChapterShotPrompts (storyboard_prompt) (T13)
    //   scene      → saveChapterShotPrompts (scene_prompt) (T14)
    //   video      → saveChapterShotPrompts (video_prompt) (T15)
    const prompts: Record<string, string | null> = {}
    if (currentType.value === 'storyboard') prompts.storyboard_prompt = currentResource.value.prompt
    if (currentType.value === 'video') prompts.video_prompt = currentResource.value.prompt
    if (currentType.value === 'scene') prompts.scene_prompt = currentResource.value.prompt

    if (Object.keys(prompts).length > 0) {
      await videoApi.saveChapterShotPrompts(props.shotId, prompts)
      uni.showToast({ title: '提示词已保存', icon: 'success' })
    } else {
      uni.showToast({ title: '暂无提示词可保存', icon: 'none' })
    }
    emit('updated')
  } catch (e: any) {
    uni.showToast({ title: e?.message || '保存失败', icon: 'none' })
  } finally {
    busy.value = null
  }
}

/** 获取卡片类型中文标签 */
function getTypeLabel(type: CardType): string {
  const labels: Record<CardType, string> = {
    character: '角色',
    storyboard: '故事版',
    scene: '场景',
    video: '视频',
  }
  return labels[type] || type
}
</script>

<style lang="scss" scoped>
@use '@/styles/variables' as *;

// ── 工作台全屏弹窗 ──
.vwb {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 1100;
  display: flex;
  flex-direction: column;
}

// ── 遮罩 ──
.vwb__mask {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(15, 23, 42, 0.6);
}

// ── 主体容器 ──
.vwb__container {
  position: relative;
  flex: 1;
  display: flex;
  flex-direction: column;
  background: $lv-surface-solid;
  border-radius: $lv-radius-lg $lv-radius-lg 0 0;
  box-shadow: $lv-shadow-xl;
  margin-top: env(safe-area-inset-top);
  overflow: hidden;
  animation: vwb-slide-up 0.3s ease;
}

@keyframes vwb-slide-up {
  from {
    opacity: 0;
    transform: translateY(120rpx);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

// ── 顶部栏 ──
.vwb__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: $lv-card-padding;
  border-bottom: 1rpx solid $lv-border-light;
  background: linear-gradient(135deg, $lv-primary-lighter, $lv-bg-end);
  flex-shrink: 0;
}

.vwb__header-left {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.vwb__header-icon {
  font-size: $lv-font-xl;
}

.vwb__header-title {
  font-size: $lv-font-lg;
  font-weight: 600;
  color: $lv-text-primary;
}

.vwb__header-close {
  width: 64rpx;
  height: 64rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: $lv-radius-full;
  background: rgba(0, 0, 0, 0.06);
  transition: background 0.2s;

  &:active {
    background: rgba(0, 0, 0, 0.12);
  }
}

.vwb__close-icon {
  font-size: 32rpx;
  color: $lv-text-secondary;
  font-weight: 600;
}

// ── 标签栏 ──
.vwb__tabs-scroll {
  flex-shrink: 0;
  background: $lv-surface-solid;
  border-bottom: 1rpx solid $lv-border-light;
}

.vwb__tabs {
  display: flex;
  padding: 16rpx $lv-page-padding;
  gap: 12rpx;
}

.vwb__tab {
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding: 16rpx 28rpx;
  border-radius: $lv-radius-xl;
  background: $lv-bg-end;
  border: 1rpx solid $lv-border-light;
  transition: all 0.25s;
  white-space: nowrap;
  flex-shrink: 0;

  &--active {
    background: $lv-primary;
    border-color: $lv-primary;
    box-shadow: $lv-shadow-sm;

    .vwb__tab-label {
      color: $lv-text-on-primary;
      font-weight: 600;
    }
  }

  &:active {
    transform: scale(0.96);
  }
}

.vwb__tab-icon {
  font-size: $lv-font-base;
}

.vwb__tab-label {
  font-size: $lv-font-sm;
  color: $lv-text-secondary;
  transition: color 0.25s;
}

// ── 内容区 ──
.vwb__content {
  flex: 1;
  overflow-y: auto;
  padding: $lv-card-padding;
  background: $lv-bg-end;
}

.vwb__card-content {
  display: flex;
  flex-direction: column;
  gap: $lv-section-gap;
}

// ── 预览区 ──
.vwb__preview-section {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 360rpx;
  background: $lv-surface-solid;
  border-radius: $lv-radius-md;
  border: 1rpx solid $lv-border-light;
  overflow: hidden;
}

.vwb__preview-image {
  width: 100%;
  height: 480rpx;
  border-radius: $lv-radius-md;
}

.vwb__preview-video {
  width: 100%;
  height: 480rpx;
  border-radius: $lv-radius-md;
}

// ── 信息区 ──
.vwb__info-section {
  display: flex;
  flex-direction: column;
  gap: $lv-item-gap;
}

.vwb__info-row {
  display: flex;
  flex-direction: column;
  gap: 6rpx;
  padding: 16rpx 20rpx;
  background: $lv-surface-solid;
  border-radius: $lv-radius-sm;
  border: 1rpx solid $lv-border-light;
}

.vwb__info-label {
  font-size: $lv-font-xs;
  color: $lv-text-muted;
  font-weight: 500;
}

.vwb__info-text {
  font-size: $lv-font-base;
  color: $lv-text-primary;

  &--prompt {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    line-height: 1.6;
  }
}

// ── 状态徽标 ──
.vwb__badge {
  display: inline-flex;
  align-self: flex-start;
  padding: 4rpx 16rpx;
  border-radius: $lv-radius-full;
  font-size: $lv-font-xs;

  &--pending {
    background: $lv-warning-bg;
    color: $lv-warning;
  }

  &--info {
    background: $lv-primary-light;
    color: $lv-primary;
  }

  &--success {
    background: $lv-success-bg;
    color: $lv-success;
  }

  &--failed {
    background: $lv-error-bg;
    color: $lv-error;
  }
}

// ── 占位区 ──
.vwb__placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60rpx 40rpx;
  background: $lv-surface-solid;
  border-radius: $lv-radius-md;
  border: 2rpx dashed $lv-border-light;
  gap: 16rpx;
}

.vwb__placeholder-icon {
  font-size: 72rpx;
  opacity: 0.5;
}

.vwb__placeholder-title {
  font-size: $lv-font-lg;
  font-weight: 600;
  color: $lv-text-secondary;
}

.vwb__placeholder-desc {
  font-size: $lv-font-sm;
  color: $lv-text-muted;
  text-align: center;
}

.vwb__placeholder-todo {
  margin-top: 8rpx;
  font-size: $lv-font-xs;
  color: $lv-warning;
  background: $lv-warning-bg;
  padding: 8rpx 20rpx;
  border-radius: $lv-radius-full;
}

// ── 底部操作栏 ──
.vwb__actions {
  flex-shrink: 0;
  padding: $lv-card-padding;
  padding-bottom: calc($lv-card-padding + env(safe-area-inset-bottom));
  background: $lv-surface-solid;
  border-top: 1rpx solid $lv-border-light;
  display: flex;
  flex-direction: column;
  gap: 12rpx;
}

.vwb__actions-row {
  display: flex;
  gap: 10rpx;
}

.vwb__action-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  padding: 18rpx 12rpx;
  border-radius: $lv-radius-sm;
  border: 1rpx solid transparent;
  transition: all 0.2s;
  min-height: $lv-touch-min;

  &:active:not(&--disabled) {
    transform: scale(0.97);
  }

  // 主要操作（蓝色）
  &--primary {
    background: $lv-primary;
    border-color: $lv-primary;

    .vwb__action-label {
      color: $lv-text-on-primary;
      font-weight: 500;
    }

    &:active:not(&--disabled) {
      background: $lv-primary-dark;
    }
  }

  // 次要操作（浅色背景）
  &--secondary {
    background: $lv-bg-end;
    border-color: $lv-border-light;

    .vwb__action-label {
      color: $lv-text-secondary;
    }

    &:active:not(&--disabled) {
      background: $lv-primary-light;
    }
  }

  // 危险操作（红色）
  &--danger {
    background: $lv-error-bg;
    border-color: $lv-error-bg;

    .vwb__action-label {
      color: $lv-error;
    }

    &:active:not(&--disabled) {
      background: #fde2e7;
    }
  }

  // 禁用态
  &--disabled {
    opacity: 0.45;
    pointer-events: none;
  }
}

.vwb__action-icon {
  font-size: $lv-font-xl;
}

.vwb__action-spinner {
  font-size: $lv-font-xl;
  animation: vwb-spin 0.8s linear infinite;
}

@keyframes vwb-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.vwb__action-label {
  font-size: $lv-font-sm;
  white-space: nowrap;
}
</style>
