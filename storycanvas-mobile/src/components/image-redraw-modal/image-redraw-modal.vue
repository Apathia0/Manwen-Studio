<template>
  <view v-if="visible" class="img-redraw-overlay" @tap="onMaskTap">
    <view class="img-redraw-modal" @tap.stop>
      <!-- 标题栏 -->
      <view class="img-redraw-modal__header">
        <text class="img-redraw-modal__title">图片重绘</text>
        <view class="img-redraw-modal__close" @tap="handleClose">
          <text class="img-redraw-modal__close-icon">✕</text>
        </view>
      </view>

      <scroll-view scroll-y class="img-redraw-modal__body">
        <!-- 图片显示区 -->
        <view class="img-redraw-modal__image-section">
          <view class="img-redraw-modal__image-wrap">
            <image
              :src="imageUrl"
              mode="aspectFit"
              class="img-redraw-modal__display-img"
              @load="onImageLoad"
            />
            <!-- 局部重绘：Canvas 蒙版层 -->
            <canvas
              v-if="mode === 'partial' && canvasReady"
              canvas-id="redrawCanvas"
              id="redrawCanvas"
              class="img-redraw-modal__canvas"
              :style="canvasStyle"
              @touchstart="onTouchStart"
              @touchmove="onTouchMove"
              @touchend="onTouchEnd"
            />
          </view>
        </view>

        <!-- 重绘模式选择 -->
        <view class="img-redraw-modal__section">
          <text class="img-redraw-modal__section-title">重绘方式</text>
          <view class="img-redraw-modal__mode-row">
            <view
              v-for="m in modeOptions"
              :key="m.value"
              :class="[
                'img-redraw-modal__mode-tab',
                { 'img-redraw-modal__mode-tab--active': mode === m.value },
              ]"
              @tap="mode = m.value"
            >
              {{ m.label }}
            </view>
          </view>
        </view>

        <!-- 画笔控制（局部重绘） -->
        <view v-if="mode === 'partial'" class="img-redraw-modal__section">
          <view class="img-redraw-modal__brush-header">
            <text class="img-redraw-modal__section-title">画笔大小</text>
            <text class="img-redraw-modal__brush-value">{{ brushSize }}px</text>
          </view>
          <slider
            :min="10"
            :max="50"
            :value="brushSize"
            activeColor="#2563eb"
            blockColor="#2563eb"
            @change="onBrushSizeChange"
          />
          <view class="img-redraw-modal__brush-actions">
            <view
              class="img-redraw-modal__brush-btn"
              :class="{ 'img-redraw-modal__brush-btn--disabled': strokes.length === 0 }"
              @tap="undoStroke"
            >
              撤销
            </view>
            <view
              class="img-redraw-modal__brush-btn"
              :class="{ 'img-redraw-modal__brush-btn--disabled': strokes.length === 0 }"
              @tap="clearAll"
            >
              清空
            </view>
          </view>
        </view>

        <!-- 提示词输入 -->
        <view class="img-redraw-modal__section">
          <text class="img-redraw-modal__section-title">修改提示</text>
          <textarea
            v-model="prompt"
            class="img-redraw-modal__textarea"
            placeholder="描述你想调整的局部或整图效果…"
            :maxlength="500"
          />
        </view>
      </scroll-view>

      <!-- 底部按钮 -->
      <view class="img-redraw-modal__footer">
        <view class="img-redraw-modal__btn img-redraw-modal__btn--cancel" @tap="handleClose">
          取消
        </view>
        <view
          class="img-redraw-modal__btn img-redraw-modal__btn--confirm"
          :class="{ 'img-redraw-modal__btn--disabled': submitting }"
          @tap="handleSubmit"
        >
          {{ submitting ? '处理中...' : '开始重绘' }}
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch, getCurrentInstance, nextTick } from 'vue'
import { mangaApi } from '@/api'
import { useUiStore } from '@/stores/ui'
import type { ImageRedrawMode } from '@/api/types'

const uiStore = useUiStore()
const instance = getCurrentInstance()

interface DrawPoint {
  x: number
  y: number
}

interface DrawStroke {
  points: DrawPoint[]
  brushSize: number
}

// ── Props ──
interface Props {
  visible: boolean
  imageUrl: string
  imageNumber?: number | null
  chapterId?: number | null
  storyId?: number | null
  filename?: string
  refType?: 'manga' | 'story-ref' | 'chapter-ref'
}

const props = withDefaults(defineProps<Props>(), {
  visible: false,
  imageNumber: undefined,
  chapterId: undefined,
  storyId: undefined,
  filename: '',
  refType: 'manga',
})

// ── Emits ──
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'success', result: any): void
}>()

// ── 状态 ──
const mode = ref<ImageRedrawMode>('full')
const prompt = ref('')
const submitting = ref(false)
const brushSize = ref(30)
const strokes = ref<DrawStroke[]>([])
const currentPoints = ref<DrawPoint[]>([])
const isDrawing = ref(false)
const imageLoaded = ref(false)
const canvasReady = ref(false)
const canvasWidth = ref(0)
const canvasHeight = ref(0)
const imageNaturalWidth = ref(0)
const imageNaturalHeight = ref(0)

// ── 内部 Canvas 引用 ──
let canvasEl: any = null
let canvasCtx: any = null

// ── 模式选项 ──
const modeOptions = [
  { label: '整图重绘', value: 'full' as ImageRedrawMode },
  { label: '局部重绘', value: 'partial' as ImageRedrawMode },
  { label: '重新生成', value: 'regenerate' as ImageRedrawMode },
]

// ── Canvas 样式 ──
const canvasStyle = computed(() => ({
  width: canvasWidth.value + 'px',
  height: canvasHeight.value + 'px',
}))

// ── 重置状态 ──
watch(
  () => [props.visible, props.imageUrl],
  () => {
    if (props.visible) {
      mode.value = 'full'
      prompt.value = ''
      submitting.value = false
      strokes.value = []
      currentPoints.value = []
      isDrawing.value = false
      imageLoaded.value = false
      canvasReady.value = false
      canvasEl = null
      canvasCtx = null
      nextTick(() => {
        setTimeout(initCanvas, 100)
      })
    }
  }
)

// ── 初始化 Canvas ──
function initCanvas() {
  if (!imageLoaded.value || mode.value !== 'partial') return
  try {
    const query = uni.createSelectorQuery().in(instance)
    query.select('.img-redraw-modal__image-wrap').boundingClientRect((rect: any) => {
      if (!rect) return
      canvasWidth.value = Math.round(rect.width)
      canvasHeight.value = Math.round(rect.height)
      nextTick(() => initCanvasNode())
    }).exec()
  } catch (e) {
    console.error('Canvas 初始化失败:', e)
  }
}

function initCanvasNode() {
  // #ifndef MP-WEIXIN
  try {
    const query = uni.createSelectorQuery().in(instance)
    query.select('#redrawCanvas').node((res: any) => {
      if (!res || !res.node) return
      canvasEl = res.node
      canvasEl.width = canvasWidth.value
      canvasEl.height = canvasHeight.value
      canvasCtx = canvasEl.getContext('2d')
      if (canvasCtx) {
        canvasCtx.lineCap = 'round'
        canvasCtx.lineJoin = 'round'
      }
      canvasReady.value = true
    }).exec()
  } catch (e) {
    console.error('H5 Canvas 初始化失败:', e)
  }
  // #endif

  // #ifdef MP-WEIXIN
  canvasCtx = uni.createCanvasContext('redrawCanvas', instance)
  if (canvasCtx) {
    canvasCtx.setLineCap('round')
    canvasCtx.setLineJoin('round')
  }
  canvasReady.value = true
  // #endif
}

// ── 图片加载 ──
function onImageLoad(e: any) {
  imageLoaded.value = true
  if (e.detail) {
    imageNaturalWidth.value = e.detail.width || 0
    imageNaturalHeight.value = e.detail.height || 0
  }
  if (mode.value === 'partial') {
    setTimeout(initCanvas, 50)
  }
}

// ── 更新 Canvas 偏移量（计算相对坐标） ──
let canvasOffsetX = 0
let canvasOffsetY = 0

function updateCanvasOffset() {
  try {
    const query = uni.createSelectorQuery().in(instance)
    query.select('#redrawCanvas').boundingClientRect((rect: any) => {
      if (rect) {
        canvasOffsetX = rect.left
        canvasOffsetY = rect.top
      }
    }).exec()
  } catch (e) {
    // ignore
  }
}

function computeRelativePoint(e: any): { x: number; y: number } | null {
  const touch = e.touches?.[0] || e.changedTouches?.[0]
  if (!touch) return null
  // #ifndef MP-WEIXIN
  return {
    x: touch.clientX - canvasOffsetX,
    y: touch.clientY - canvasOffsetY,
  }
  // #endif
  // #ifdef MP-WEIXIN
  return {
    x: touch.x - canvasOffsetX,
    y: touch.y - canvasOffsetY,
  }
  // #endif
}

// ── 触摸事件处理 ──
function onTouchStart(e: any) {
  if (!canvasReady.value) return
  isDrawing.value = true
  currentPoints.value = []
  updateCanvasOffset()
  const point = computeRelativePoint(e)
  if (!point) return
  currentPoints.value.push(point)
  drawPoint(point)
}

function onTouchMove(e: any) {
  if (!isDrawing.value || !canvasReady.value) return
  const point = computeRelativePoint(e)
  if (!point) return
  point.x = Math.max(0, Math.min(canvasWidth.value, point.x))
  point.y = Math.max(0, Math.min(canvasHeight.value, point.y))
  const last = currentPoints.value[currentPoints.value.length - 1]
  if (last) {
    drawSegment(last, point)
  } else {
    drawPoint(point)
  }
  currentPoints.value.push(point)
}

function onTouchEnd() {
  if (!isDrawing.value) return
  isDrawing.value = false
  if (currentPoints.value.length > 0) {
    strokes.value.push({
      points: [...currentPoints.value],
      brushSize: brushSize.value,
    })
  }
  currentPoints.value = []
}

// ── Canvas 绘制 ──
function drawPoint(point: DrawPoint) {
  // #ifndef MP-WEIXIN
  if (!canvasCtx) return
  canvasCtx.fillStyle = 'rgba(239, 68, 68, 0.45)'
  canvasCtx.beginPath()
  canvasCtx.arc(point.x, point.y, brushSize.value / 2, 0, Math.PI * 2)
  canvasCtx.fill()
  // #endif

  // #ifdef MP-WEIXIN
  if (!canvasCtx) return
  canvasCtx.setFillStyle('rgba(239, 68, 68, 0.45)')
  canvasCtx.beginPath()
  canvasCtx.arc(point.x, point.y, brushSize.value / 2, 0, Math.PI * 2)
  canvasCtx.fill()
  canvasCtx.draw(true)
  // #endif
}

function drawSegment(from: DrawPoint, to: DrawPoint) {
  const size = brushSize.value
  // #ifndef MP-WEIXIN
  if (!canvasCtx) return
  canvasCtx.fillStyle = 'rgba(239, 68, 68, 0.45)'
  canvasCtx.lineCap = 'round'
  canvasCtx.lineJoin = 'round'
  canvasCtx.lineWidth = size
  canvasCtx.beginPath()
  canvasCtx.moveTo(from.x, from.y)
  canvasCtx.lineTo(to.x, to.y)
  canvasCtx.stroke()
  canvasCtx.beginPath()
  canvasCtx.arc(to.x, to.y, size / 2, 0, Math.PI * 2)
  canvasCtx.fill()
  // #endif

  // #ifdef MP-WEIXIN
  if (!canvasCtx) return
  canvasCtx.setFillStyle('rgba(239, 68, 68, 0.45)')
  canvasCtx.setLineCap('round')
  canvasCtx.setLineJoin('round')
  canvasCtx.setLineWidth(size)
  canvasCtx.beginPath()
  canvasCtx.moveTo(from.x, from.y)
  canvasCtx.lineTo(to.x, to.y)
  canvasCtx.stroke()
  canvasCtx.beginPath()
  canvasCtx.arc(to.x, to.y, size / 2, 0, Math.PI * 2)
  canvasCtx.fill()
  canvasCtx.draw(true)
  // #endif
}

function redrawAllStrokes() {
  // #ifndef MP-WEIXIN
  if (!canvasCtx || !canvasEl) return
  canvasCtx.clearRect(0, 0, canvasEl.width, canvasEl.height)
  for (const stroke of strokes.value) {
    const savedSize = brushSize.value
    brushSize.value = stroke.brushSize
    for (let i = 0; i < stroke.points.length; i++) {
      const p = stroke.points[i]
      if (i === 0) {
        drawPoint(p)
      } else {
        drawSegment(stroke.points[i - 1], p)
      }
    }
    brushSize.value = savedSize
  }
  // #endif

  // #ifdef MP-WEIXIN
  if (!canvasCtx) return
  canvasCtx.setFillStyle('rgba(0,0,0,0)')
  canvasCtx.fillRect(0, 0, canvasWidth.value, canvasHeight.value)
  canvasCtx.draw(true)
  for (const stroke of strokes.value) {
    const savedSize = brushSize.value
    brushSize.value = stroke.brushSize
    for (let i = 0; i < stroke.points.length; i++) {
      const p = stroke.points[i]
      if (i === 0) {
        drawPoint(p)
      } else {
        drawSegment(stroke.points[i - 1], p)
      }
    }
    brushSize.value = savedSize
  }
  // #endif
}

// ── 画笔控制 ──
function onBrushSizeChange(e: any) {
  brushSize.value = e.detail.value
}

function undoStroke() {
  if (strokes.value.length === 0) return
  strokes.value.pop()
  redrawAllStrokes()
}

function clearAll() {
  strokes.value = []
  // #ifndef MP-WEIXIN
  if (canvasCtx && canvasEl) {
    canvasCtx.clearRect(0, 0, canvasEl.width, canvasEl.height)
  }
  // #endif

  // #ifdef MP-WEIXIN
  if (canvasCtx) {
    canvasCtx.setFillStyle('rgba(0,0,0,0)')
    canvasCtx.fillRect(0, 0, canvasWidth.value, canvasHeight.value)
    canvasCtx.draw(true)
  }
  // #endif
}

// ── 导出蒙版 ──
function exportMask(): Promise<string> {
  return new Promise((resolve) => {
    if (!canvasReady.value) {
      resolve('')
      return
    }

    // #ifndef MP-WEIXIN
    try {
      if (!canvasCtx || !canvasEl) {
        resolve('')
        return
      }
      const raw = canvasCtx.getImageData(0, 0, canvasEl.width, canvasEl.height)
      let hasPaint = false
      for (let i = 3; i < raw.data.length; i += 4) {
        if (raw.data[i] > 10) {
          hasPaint = true
          break
        }
      }
      if (!hasPaint) {
        resolve('')
        return
      }
      // 创建蒙版 Canvas：白色背景，涂抹区域透明
      const maskCanvas = document.createElement('canvas')
      maskCanvas.width = canvasEl.width
      maskCanvas.height = canvasEl.height
      const maskCtx = maskCanvas.getContext('2d')
      if (!maskCtx) {
        resolve('')
        return
      }
      maskCtx.fillStyle = '#ffffff'
      maskCtx.fillRect(0, 0, maskCanvas.width, maskCanvas.height)
      const maskData = maskCtx.getImageData(0, 0, maskCanvas.width, maskCanvas.height)
      for (let i = 0; i < raw.data.length; i += 4) {
        const alpha = raw.data[i + 3]
        maskData.data[i] = 255
        maskData.data[i + 1] = 255
        maskData.data[i + 2] = 255
        maskData.data[i + 3] = alpha > 10 ? 0 : 255
      }
      maskCtx.putImageData(maskData, 0, 0)
      // 缩放到图片原始尺寸
      if (
        imageNaturalWidth.value > 0 &&
        imageNaturalHeight.value > 0 &&
        (imageNaturalWidth.value !== canvasEl.width ||
          imageNaturalHeight.value !== canvasEl.height)
      ) {
        const scaledCanvas = document.createElement('canvas')
        scaledCanvas.width = imageNaturalWidth.value
        scaledCanvas.height = imageNaturalHeight.value
        const scaledCtx = scaledCanvas.getContext('2d')
        if (scaledCtx) {
          scaledCtx.drawImage(maskCanvas, 0, 0, scaledCanvas.width, scaledCanvas.height)
          resolve(scaledCanvas.toDataURL('image/png'))
          return
        }
      }
      resolve(maskCanvas.toDataURL('image/png'))
    } catch (e) {
      console.error('导出蒙版失败:', e)
      resolve('')
    }
    // #endif

    // #ifdef MP-WEIXIN
    try {
      uni.canvasToTempFilePath({
        canvasId: 'redrawCanvas',
        fileType: 'png',
        success: (res) => {
          uni.getFileSystemManager().readFile({
            filePath: res.tempFilePath,
            encoding: 'base64',
            success: (readRes) => {
              resolve('data:image/png;base64,' + readRes.data)
            },
            fail: () => resolve(''),
          })
        },
        fail: () => resolve(''),
      })
    } catch (e) {
      console.error('MP 导出蒙版失败:', e)
      resolve('')
    }
    // #endif
  })
}

// ── 提交重绘 ──
async function handleSubmit() {
  if (submitting.value) return
  submitting.value = true

  try {
    const currentMode = mode.value
    const p = prompt.value.trim()

    let maskData: string | undefined
    if (currentMode === 'partial') {
      maskData = await exportMask()
      if (!maskData) {
        uiStore.error('请先在图片上涂抹需要修改的区域')
        submitting.value = false
        return
      }
    }

    if (props.refType === 'manga') {
      if (!props.chapterId || !props.imageNumber) {
        uiStore.error('缺少章节或图片信息')
        submitting.value = false
        return
      }
      const result = await mangaApi.regenerateImage(
        props.chapterId,
        props.imageNumber,
        p,
        currentMode,
        { mask: maskData }
      )
      emit('success', result)
    } else if (props.refType === 'story-ref') {
      if (!props.storyId || !props.filename) {
        uiStore.error('缺少故事或文件名信息')
        submitting.value = false
        return
      }
      const result = await mangaApi.redrawStoryRefImage(props.storyId, props.filename, {
        prompt: p,
        mode: currentMode,
        mask: maskData,
      })
      emit('success', result)
    } else if (props.refType === 'chapter-ref') {
      if (!props.chapterId || !props.filename) {
        uiStore.error('缺少章节或文件名信息')
        submitting.value = false
        return
      }
      const result = await mangaApi.redrawChapterRefImage(props.chapterId, props.filename, {
        prompt: p,
        mode: currentMode,
        mask: maskData,
      })
      emit('success', result)
    }

    uiStore.success('重绘完成')
    emit('close')
  } catch (e: any) {
    uiStore.error(e.message || '重绘失败')
  } finally {
    submitting.value = false
  }
}

// ── 弹窗操作 ──
function handleClose() {
  emit('close')
}

function onMaskTap() {
  emit('close')
}
</script>

<style lang="scss" scoped>

.img-redraw-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 2000;
  background: rgba(15, 23, 42, 0.62);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32rpx;
}

.img-redraw-modal {
  width: 100%;
  max-width: 700rpx;
  max-height: 90vh;
  background: $lv-surface-solid;
  border-radius: $lv-radius-lg;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: $lv-shadow-xl;

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 24rpx 32rpx;
    border-bottom: 1rpx solid $lv-border-light;
    flex-shrink: 0;
  }

  &__title {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__close {
    width: 56rpx;
    height: 56rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    background: $lv-primary-lighter;

    &:active {
      background: $lv-primary-light;
    }
  }

  &__close-icon {
    font-size: 28rpx;
    color: $lv-text-secondary;
  }

  &__body {
    flex: 1;
    overflow: hidden;
  }

  // ── 图片显示区 ──
  &__image-section {
    padding: 0;
    background: linear-gradient(180deg, #0f172a 0%, #111827 100%);
  }

  &__image-wrap {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 300rpx;
    overflow: hidden;
  }

  &__display-img {
    max-width: 100%;
    max-height: 60vh;
  }

  &__canvas {
    position: absolute;
    top: 0;
    left: 0;
    touch-action: none;
  }

  // ── 控制区 ──
  &__section {
    padding: 24rpx 32rpx;
    border-bottom: 1rpx solid $lv-border-light;

    &:last-child {
      border-bottom: none;
    }
  }

  &__section-title {
    display: block;
    font-size: $lv-font-sm;
    font-weight: 600;
    color: $lv-text-secondary;
    margin-bottom: 12rpx;
  }

  // ── 模式选择 ──
  &__mode-row {
    display: flex;
    gap: 12rpx;
  }

  &__mode-tab {
    flex: 1;
    padding: 12rpx 16rpx;
    border-radius: $lv-radius-sm;
    font-size: $lv-font-sm;
    text-align: center;
    color: $lv-text-secondary;
    background: $lv-primary-lighter;
    border: 1rpx solid $lv-border;

    &:active {
      opacity: 0.7;
    }

    &--active {
      background: $lv-primary;
      color: $lv-text-on-primary;
      border-color: $lv-primary;
    }
  }

  // ── 画笔控制 ──
  &__brush-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8rpx;
  }

  &__brush-value {
    font-size: $lv-font-sm;
    color: $lv-primary;
    font-weight: 500;
  }

  &__brush-actions {
    display: flex;
    gap: 12rpx;
    margin-top: 12rpx;
  }

  &__brush-btn {
    padding: 8rpx 24rpx;
    border-radius: $lv-radius-sm;
    font-size: $lv-font-xs;
    color: $lv-text-secondary;
    background: $lv-primary-lighter;
    border: 1rpx solid $lv-border;

    &:active {
      opacity: 0.7;
    }

    &--disabled {
      opacity: 0.4;
      pointer-events: none;
    }
  }

  // ── 提示词 ──
  &__textarea {
    width: 100%;
    min-height: 120rpx;
    padding: 16rpx;
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    background: $lv-bg-start;
    border: 2rpx solid $lv-border;
    border-radius: $lv-radius-sm;
    line-height: 1.6;
    box-sizing: border-box;
  }

  // ── 底部按钮 ──
  &__footer {
    display: flex;
    border-top: 1rpx solid $lv-border-light;
    flex-shrink: 0;
  }

  &__btn {
    flex: 1;
    height: 88rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: $lv-font-base;
    font-weight: 500;

    &:active {
      opacity: 0.8;
    }

    &--cancel {
      color: $lv-text-secondary;
      border-right: 1rpx solid $lv-border-light;
    }

    &--confirm {
      color: $lv-text-on-primary;
      background: $lv-primary;
    }

    &--disabled {
      opacity: 0.5;
      pointer-events: none;
    }
  }
}
</style>
