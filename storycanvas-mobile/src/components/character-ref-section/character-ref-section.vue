<template>
  <view class="crs">
    <!-- 头部标题 -->
    <view class="crs__header">
      <text class="crs__title">角色参考图</text>
      <text v-if="loading" class="crs__loading">加载中...</text>
    </view>

    <!-- 角色 TAB 横向滚动标签 -->
    <scroll-view
      v-if="!loading"
      scroll-x
      class="crs__tabs-scroll"
      show-scrollbar="false"
    >
      <view class="crs__tabs">
        <view
          :class="['crs__tab', { 'crs__tab--active': activeCharacter === '' }]"
          @tap="activeCharacter = ''"
        >
          <text>未分配</text>
        </view>
        <view
          v-for="char in characters"
          :key="char"
          :class="['crs__tab', { 'crs__tab--active': activeCharacter === char }]"
          @tap="activeCharacter = char"
        >
          <text>{{ char }}</text>
        </view>
      </view>
    </scroll-view>

    <!-- 内容区：图片网格 / 空状态 -->
    <view class="crs__content">
      <template v-if="loading">
        <lv-empty title="加载中..." description="正在获取参考图数据" />
      </template>
      <template v-else-if="currentImages.length > 0">
        <view class="crs__grid">
          <view
            v-for="img in currentImages"
            :key="img.filename"
            class="crs__item"
            @longpress="handleDelete(img.filename)"
          >
            <image
              :src="refImageUrl(img.image_path)"
              mode="aspectFill"
              class="crs__image"
              lazy-load
            />
            <view class="crs__delete-overlay">
              <view class="crs__delete-btn" @tap.stop="handleDelete(img.filename)">
                <lv-icon name="Trash2" :size="16" color="#fff" />
              </view>
            </view>
          </view>
        </view>
      </template>
      <template v-else>
        <lv-empty
          title="暂无参考图"
          description="上传角色参考图帮助 AI 保持一致形象"
        />
      </template>
    </view>

    <!-- 底部操作按钮 -->
    <view class="crs__footer">
      <!-- 生成参考图按钮：仅 story 模式且选中具体角色时显示 -->
      <lv-button
        v-if="props.sourceType === 'story' && activeCharacter !== ''"
        block
        :loading="generatingCharName === activeCharacter"
        :disabled="generatingCharName !== '' && generatingCharName !== activeCharacter"
        @tap="handleGenerateTap"
        style="margin-bottom: 16rpx"
      >
        {{ generatingCharName === activeCharacter ? '正在生成...' : `为「${activeCharacter}」生成参考图` }}
      </lv-button>
      <lv-button block :loading="uploading" @tap="handleUploadTap">
        上传参考图
      </lv-button>
    </view>

    <!-- 角色选择底部弹窗 -->
    <lv-action-sheet
      :visible="showActionSheet"
      title="选择角色标签"
      :actions="actionSheetActions"
      cancel-text="取消"
      mask-closable
      @select="handleActionSheetSelect"
      @update:visible="showActionSheet = $event"
    />
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { mangaApi, storiesApi } from '@/api'
import { post } from '@/utils/request'
import { refImageUrl } from '@/utils/url'
import { useImagePicker } from '@/composables/useImagePicker'
import { useSSE } from '@/composables/useSSE'
import { getToken } from '@/utils/storage'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import LvActionSheet from '@/components/lv-action-sheet/lv-action-sheet.vue'

// ── 类型 ──
interface RefImage {
  filename: string
  image_path: string
  size_kb: number
  label?: string
  kind?: string
}

interface RefImagesPayload {
  images: RefImage[]
  max: number
}

// ── Props ──
const props = defineProps<{
  storyId: number
  chapterId?: number | null
  sourceType: 'story' | 'chapter'
}>()

// ── Emits ──
const emit = defineEmits<{
  (e: 'change'): void
}>()

// ── Composables ──
const { chooseAndConvert } = useImagePicker()
const { streaming: generating, start: startSSE, stop: stopSSE } = useSSE()

// ── 状态 ──
const characters = ref<string[]>([])
const refImages = ref<RefImage[]>([])
const loading = ref(false)
const uploading = ref(false)
const deletingFilename = ref('')
const activeCharacter = ref('') // '' 表示"未分配"
const showActionSheet = ref(false)
const generatingCharName = ref('') // 正在生成的角色名，空串表示未在生成

// ── 计算属性 ──

/** 当前选中标签下的图片列表 */
const currentImages = computed<RefImage[]>(() => {
  if (activeCharacter.value === '') {
    // "未分配"：没有 label 或 label 为空
    return refImages.value.filter(img => !img.label)
  }
  return refImages.value.filter(img => img.label === activeCharacter.value)
})

/** 角色选择弹窗的选项列表 */
const actionSheetActions = computed(() => {
  const items: { text: string; danger?: boolean }[] = [
    { text: '不指定（通用参考图）' }
  ]
  for (const name of characters.value) {
    items.push({ text: name })
  }
  return items
})

// ── 初始化 ──

onMounted(() => {
  initData()
})

watch(() => [props.storyId, props.chapterId, props.sourceType], () => {
  initData()
})

async function initData() {
  if (!props.storyId) return
  if (props.sourceType === 'chapter' && !props.chapterId) return

  loading.value = true
  try {
    await Promise.all([loadCharacters(), loadRefImages()])
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载参考图数据失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

/** 从故事中提取角色名列表 */
async function loadCharacters() {
  try {
    const story = await storiesApi.getStory(props.storyId)
    if (story.characters && Array.isArray(story.characters)) {
      characters.value = story.characters
        .map(c => (c as Record<string, any>).name)
        .filter(Boolean) as string[]
    } else {
      characters.value = []
    }
  } catch {
    // 角色加载失败不影响参考图展示
    characters.value = []
  }
}

/** 根据 sourceType 加载参考图 */
async function loadRefImages() {
  try {
    let result: RefImagesPayload
    if (props.sourceType === 'story') {
      result = await mangaApi.getStoryRefImages(props.storyId)
    } else if (props.chapterId) {
      result = await mangaApi.getChapterRefImages(props.chapterId)
    } else {
      result = { images: [], max: 0 }
    }
    refImages.value = result.images || []
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载参考图失败', icon: 'none' })
    refImages.value = []
  }
}

// ── 操作 ──

/** 点击上传按钮：打开角色选择弹窗 */
function handleUploadTap() {
  if (uploading.value) return
  showActionSheet.value = true
}

/** 点击生成参考图按钮：通过 SSE 流式生成角色参考图 */
function handleGenerateTap() {
  if (generatingCharName.value) return // 正在生成中
  const charName = activeCharacter.value
  if (!charName || props.sourceType !== 'story') return

  generatingCharName.value = charName

  startSSE({
    url: mangaApi.characterRefImagesUrl(props.storyId),
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${getToken()}`
    },
    body: { character_name: charName, overwrite: false },
    onEvent: (event) => {
      switch (event.type) {
        case 'snapshot':
        case 'image':
          // 后端返回的 images 是最新列表，直接覆盖刷新
          if (event.data?.images) {
            refImages.value = event.data.images
          }
          break
        case 'done':
          if (event.data?.images) {
            refImages.value = event.data.images
          }
          generatingCharName.value = ''
          uni.showToast({ title: '生成完成', icon: 'success' })
          emit('change')
          break
        case 'error':
          uni.showToast({
            title: event.data?.error || '生成角色参考图失败',
            icon: 'none'
          })
          generatingCharName.value = ''
          break
      }
    },
    onError: () => {
      uni.showToast({ title: '生成请求失败', icon: 'none' })
      generatingCharName.value = ''
    },
    onComplete: () => {
      if (generatingCharName.value) generatingCharName.value = ''
    }
  })
}

/** 角色选择弹窗选中后的处理 */
async function handleActionSheetSelect(index: number) {
  let label: string | undefined
  if (index === 0) {
    // "不指定" — 不传入 label
    label = undefined
  } else {
    // 选中某个角色
    const charIndex = index - 1
    if (charIndex < characters.value.length) {
      label = characters.value[charIndex]
    }
  }
  await doUpload(label)
}

/** 执行上传：选择图片 → base64 → 上传API → 刷新列表 */
async function doUpload(label?: string) {
  if (uploading.value) return
  uploading.value = true
  try {
    const base64List = await chooseAndConvert({ count: 1 })
    if (!base64List || base64List.length === 0) {
      return
    }
    const base64 = base64List[0]

    const body: Record<string, any> = { image: base64 }
    if (label) {
      body.label = label
    }

    let result: RefImagesPayload
    if (props.sourceType === 'story' && label) {
      // 使用角色参考图专用上传端点
      result = await mangaApi.uploadCharacterRefImage(
        props.storyId,
        base64,
        label,
        /* replaceExisting */ false
      )
    } else if (props.sourceType === 'story') {
      result = await post<RefImagesPayload>(
        `/api/stories/${props.storyId}/ref-images`,
        body
      )
    } else if (props.chapterId) {
      result = await post<RefImagesPayload>(
        `/api/chapters/${props.chapterId}/ref-images`,
        body
      )
    } else {
      uni.showToast({ title: '缺少故事或章节 ID', icon: 'none' })
      return
    }

    refImages.value = result.images || []
    uni.showToast({ title: '上传成功', icon: 'success' })
    emit('change')
  } catch (e: any) {
    uni.showToast({ title: e.message || '上传失败', icon: 'none' })
  } finally {
    uploading.value = false
  }
}

/** 删除参考图 */
async function handleDelete(filename: string) {
  if (!filename || deletingFilename.value) return

  uni.showModal({
    title: '确认删除',
    content: '确定删除这张参考图吗？',
    success: async (res) => {
      if (!res.confirm) return

      deletingFilename.value = filename
      try {
        let result: RefImagesPayload | undefined
        if (props.sourceType === 'story') {
          result = await mangaApi.deleteCharacterRefImage(props.storyId, filename)
        } else if (props.chapterId) {
          result = await mangaApi.deleteChapterRefImage(props.chapterId, filename)
        }
        if (result) {
          refImages.value = result.images || []
        }
        uni.showToast({ title: '已删除', icon: 'success' })
        emit('change')
      } catch (e: any) {
        uni.showToast({ title: e.message || '删除失败', icon: 'none' })
      } finally {
        deletingFilename.value = ''
      }
    }
  })
}
</script>

<style lang="scss" scoped>
.crs {
  background: $lv-surface-solid;
  border-radius: $lv-radius-md;
  overflow: hidden;

  // ── 头部 ──
  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: $lv-card-padding $lv-card-padding 0;
  }

  &__title {
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__loading {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  // ── 角色 TAB ──
  &__tabs-scroll {
    white-space: nowrap;
    padding: 16rpx $lv-card-padding 0;
  }

  &__tabs {
    display: inline-flex;
    gap: 12rpx;
  }

  &__tab {
    display: inline-flex;
    padding: 8rpx 24rpx;
    border-radius: $lv-radius-full;
    background: $lv-primary-lighter;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    border: 2rpx solid transparent;

    &--active {
      background: $lv-primary;
      color: $lv-text-on-primary;
      border-color: transparent;
    }

    &:active {
      opacity: 0.8;
    }
  }

  // ── 内容区 ──
  &__content {
    padding: 16rpx $lv-card-padding;
    min-height: 200rpx;
  }

  // ── 图片网格 ──
  &__grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12rpx;
  }

  &__item {
    position: relative;
    aspect-ratio: 1;
    border-radius: $lv-radius-sm;
    overflow: hidden;
    background: $lv-primary-lighter;
  }

  &__image {
    width: 100%;
    height: 100%;
  }

  // 删除悬浮层（hover 态在移动端通过 active 模拟）
  &__delete-overlay {
    position: absolute;
    top: 0;
    right: 0;
    padding: 8rpx;
    opacity: 0;
    transition: opacity 0.2s ease;
  }

  &__item:active &__delete-overlay,
  &__item:hover &__delete-overlay {
    opacity: 1;
  }

  &__delete-btn {
    width: 48rpx;
    height: 48rpx;
    border-radius: 50%;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;

    &:active {
      background: rgba(0, 0, 0, 0.7);
    }
  }

  // ── 底部上传 ──
  &__footer {
    padding: 0 $lv-card-padding $lv-card-padding;
  }
}
</style>
