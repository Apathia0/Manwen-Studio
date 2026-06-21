<template>
  <view class="ref-images">
    <lv-navbar title="参考图" show-back />

    <!-- 级别切换 -->
    <view class="ref-images__tabs">
      <view
        :class="['ref-images__tab', { 'ref-images__tab--active': level === 'chapter' }]"
        @tap="switchLevel('chapter')"
      >章节参考图</view>
      <view
        :class="['ref-images__tab', { 'ref-images__tab--active': level === 'story' }]"
        @tap="switchLevel('story')"
      >故事参考图</view>
    </view>

    <view class="ref-images__content">
      <lv-button block :loading="uploading" @tap="handleAdd">
        <lv-icon name="Plus" :size="14" color="#fff" style="margin-right: 8rpx;" />
        添加参考图
      </lv-button>

      <view v-if="images.length > 0" class="ref-images__grid">
        <view
          v-for="(img, i) in images"
          :key="img.filename || i"
          class="ref-images__item"
        >
          <image :src="refImageUrl(img.image_path)" mode="aspectFill" class="ref-images__img" />
          <view class="ref-images__actions">
            <view
              class="ref-images__action ref-images__action--redraw"
              @tap.stop="handleRedraw(i, img)"
            >
              <lv-icon name="Wand2" :size="14" color="#fff" />
            </view>
            <view class="ref-images__action ref-images__action--delete" @tap.stop="handleDelete(i, img.filename)">
              <lv-icon name="X" :size="14" color="#fff" />
            </view>
          </view>
          <text v-if="img.label" class="ref-images__label">{{ img.label }}</text>
        </view>
      </view>

      <lv-empty
        v-else
        title="暂无参考图"
        description="上传角色参考图帮助 AI 保持一致形象"
      />

      <text v-if="maxRef > 0" class="ref-images__count">最多 {{ maxRef }} 张</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { mangaApi } from '@/api'
import { redrawStoryRefImage, redrawChapterRefImage } from '@/api/manga'
import type { ImageRedrawMode } from '@/api/types'
import { useImagePicker } from '@/composables/useImagePicker'
import { refImageUrl } from '@/utils/url'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'

interface RefImage {
  filename: string
  image_path: string
  size_kb: number
  label?: string
  kind?: string
}

const images = ref<RefImage[]>([])
const maxRef = ref(0)
const uploading = ref(false)
const redrawing = ref(false)
const level = ref<'chapter' | 'story'>('chapter')
const chapterId = ref(0)
const storyId = ref(0)
const { chooseAndConvert } = useImagePicker()

onMounted(async () => {
  const pages = getCurrentPages()
  const page = pages[pages.length - 1] as any
  chapterId.value = Number(page.options?.chapterId || 0)
  storyId.value = Number(page.options?.storyId || 0)
  await loadImages()
})

async function loadImages() {
  try {
    if (level.value === 'chapter' && chapterId.value) {
      const res = await mangaApi.getChapterRefImages(chapterId.value)
      images.value = res.images || []
      maxRef.value = res.max || 0
    } else if (level.value === 'story' && storyId.value) {
      const res = await mangaApi.getStoryRefImages(storyId.value)
      images.value = res.images || []
      maxRef.value = res.max || 0
    }
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  }
}

function switchLevel(lv: 'chapter' | 'story') {
  if (level.value === lv) return
  level.value = lv
  loadImages()
}

async function handleAdd() {
  if (uploading.value) return
  uploading.value = true
  try {
    const base64List = await chooseAndConvert({ count: 1 })
    if (!base64List || base64List.length === 0) {
      uploading.value = false
      return
    }
    const base64 = base64List[0]
    let res
    if (level.value === 'chapter' && chapterId.value) {
      res = await mangaApi.uploadChapterRefImage(chapterId.value, base64)
    } else if (level.value === 'story' && storyId.value) {
      res = await mangaApi.uploadStoryRefImage(storyId.value, base64)
    } else {
      uni.showToast({ title: '缺少故事或章节 ID', icon: 'none' })
      uploading.value = false
      return
    }
    images.value = res.images || []
    maxRef.value = res.max || 0
    uni.showToast({ title: '上传成功', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '上传失败', icon: 'none' })
  } finally {
    uploading.value = false
  }
}

async function handleDelete(index: number, filename: string) {
  if (!filename) {
    uni.showToast({ title: '无法删除: 缺少文件名', icon: 'none' })
    return
  }
  uni.showModal({
    title: '确认删除',
    content: '确定删除这张参考图吗?',
    success: async (res) => {
      if (!res.confirm) return
      try {
        let result
        if (level.value === 'chapter' && chapterId.value) {
          result = await mangaApi.deleteChapterRefImage(chapterId.value, filename)
        } else if (level.value === 'story' && storyId.value) {
          result = await mangaApi.deleteStoryRefImage(storyId.value, filename)
        }
        images.value = result?.images || []
        uni.showToast({ title: '已删除', icon: 'success' })
      } catch (e: any) {
        uni.showToast({ title: e.message || '删除失败', icon: 'none' })
      }
    },
  })
}
async function handleRedraw(index: number, img: RefImage) {
  if (redrawing.value) return
  const filename = img.filename
  if (!filename) {
    uni.showToast({ title: '无法重绘: 缺少文件名', icon: 'none' })
    return
  }

  // 弹出提示词输入对话框
  const [err, confirmResult] = await new Promise<[any, any]>((resolve) => {
    uni.showModal({
      title: '重绘参考图',
      content: '',
      editable: true,
      placeholderText: '输入重绘提示词（可选，描述想要的修改）',
      success: (res) => resolve([null, res]),
      fail: (err) => resolve([err, null]),
    })
  })

  if (err || !confirmResult?.confirm) return

  const prompt = (confirmResult.content as string) || ''
  redrawing.value = true

  try {
    let result
    if (level.value === 'story' && storyId.value) {
      result = await redrawStoryRefImage(storyId.value, filename, { prompt, mode: 'full' as ImageRedrawMode })
    } else if (level.value === 'chapter' && chapterId.value) {
      result = await redrawChapterRefImage(chapterId.value, filename, { prompt, mode: 'full' as ImageRedrawMode })
    } else {
      uni.showToast({ title: '缺少故事或章节 ID', icon: 'none' })
      return
    }

    images.value = result?.images || []
    uni.showToast({ title: '重绘成功', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '重绘失败', icon: 'none' })
  } finally {
    redrawing.value = false
  }
}

</script>

<style lang="scss" scoped>
.ref-images {
  min-height: 100vh;
  background: $lv-bg-start;

  &__tabs {
    display: flex;
    background: #fff;
    border-bottom: 1rpx solid $lv-border-light;
  }

  &__tab {
    flex: 1;
    text-align: center;
    padding: 24rpx 0;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    border-bottom: 4rpx solid transparent;

    &--active {
      color: $lv-primary;
      border-bottom-color: $lv-primary;
      font-weight: 600;
    }
  }

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding;
  }

  &__grid {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 16rpx;
    margin-top: 24rpx;
  }

  &__item {
    position: relative;
    aspect-ratio: 1;
    border-radius: $lv-radius-md;
    overflow: hidden;
    background: $lv-primary-lighter;
  }

  &__img {
    width: 100%;
    height: 100%;
  }

  &__actions {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    display: flex;
    justify-content: flex-end;
    padding: 12rpx;
    background: linear-gradient(transparent, rgba(0, 0, 0, 0.6));
  }

  &__action {
    width: 48rpx;
    height: 48rpx;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-left: 12rpx;

    &--redraw {
      background: rgba(255, 255, 255, 0.85);
    }

    &--delete {
      background: rgba(255, 70, 70, 0.85);
    }

    &:active {
      opacity: 0.7;
    }
  }

  &__label {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    background: rgba(0, 0, 0, 0.4);
    color: #fff;
    font-size: 20rpx;
    padding: 4rpx 8rpx;
    text-align: center;
  }

  &__count {
    display: block;
    text-align: center;
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    margin-top: 24rpx;
  }
}
</style>
