<template>
  <view v-if="visible" class="redraw-modal" @tap="handleMaskTap">
    <view class="redraw-modal__mask" />
    <view class="redraw-modal__container" @tap.stop>
      <!-- 头部 -->
      <view class="redraw-modal__header">
        <text class="redraw-modal__title">图片重绘</text>
        <view class="redraw-modal__close" @tap="handleClose">
          <text class="redraw-modal__close-icon">✕</text>
        </view>
      </view>

      <!-- 模式切换标签 -->
      <view class="redraw-modal__tabs">
        <view
          v-for="tab in tabs"
          :key="tab.value"
          class="redraw-modal__tab"
          :class="{ 'redraw-modal__tab--active': mode === tab.value }"
          @tap="switchMode(tab.value)"
        >
          <text class="redraw-modal__tab-text">{{ tab.label }}</text>
        </view>
      </view>

      <!-- 图片 + 蒙版区域 -->
      <view class="redraw-modal__image-area">
        <image
          :src="imageUrl"
          class="redraw-modal__image"
          mode="aspectFit"
          @load="onImageLoad"
          @error="onImageError"
        />
        <!-- 局部重绘模式：Canvas 蒙版覆盖层 -->
        <!-- #ifndef MP-WEIXIN -->
        <canvas
          v-if="mode === 'partial'"
          ref="canvasRef"
          class="redraw-modal__canvas"
          @touchstart="handleTouchStart"
          @touchmove="handleTouchMove"
          @touchend="handleTouchEnd"
        />
        <!-- #endif -->
        <!-- #ifdef MP-WEIXIN -->
        <canvas
          v-if="mode === 'partial'"
          canvas-id="redrawCanvas"
          class="redraw-modal__canvas"
          @touchstart="handleTouchStart"
          @touchmove="handleTouchMove"
          @touchend="handleTouchEnd"
        />
        <!-- #endif -->
      </view>

      <!-- 蒙版工具栏（仅局部重绘模式） -->
      <view v-if="mode === 'partial'" class="redraw-modal__tools">
        <view class="redraw-modal__tool" @tap="undoStroke">
          <text class="redraw-modal__tool-text">撤销</text>
        </view>
        <view class="redraw-modal__tool" @tap="clearCanvas">
          <text class="redraw-modal__tool-text">清除</text>
        </view>
        <view class="redraw-modal__brush">
          <text class="redraw-modal__brush-label">画笔</text>
          <slider
            class="redraw-modal__slider"
            :value="brushSize"
            :min="10"
            :max="50"
            :step="2"
            @change="onBrushSizeChange"
          />
          <text class="redraw-modal__brush-value">{{ brushSize }}px</text>
        </view>
      </view>

      <!-- 提示词输入 -->
      <view class="redraw-modal__prompt">
        <textarea
          v-model="prompt"
          class="redraw-modal__textarea"
          placeholder="输入重绘提示词（可选）"
          :maxlength="500"
          :auto-height="true"
        />
      </view>

      <!-- 底部按钮 -->
      <view class="redraw-modal__footer">
        <view class="redraw-modal__btn redraw-modal__btn--cancel" @tap="handleClose">
          <text class="redraw-modal__btn-text">取消</text>
        </view>
        <view class="redraw-modal__btn redraw-modal__btn--confirm" @tap="handleConfirm">
          <text class="redraw-modal__btn-text">确定</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'

/** 重绘模式 */
type RedrawMode = 'full' | 'partial' | 'regenerate'

/** 笔触：记录一系列触摸点 */
interface Stroke {
  points: Array<{ x: number; y: number }>
}

interface Props {
  visible: boolean
  imageUrl: string
  imageNumber?: number
  chapterId?: number
}

const props = withDefaults(defineProps<Props>(), {
  imageNumber: 0,
  chapterId: 0,
})

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'success', result: Record<string, unknown>): void
}>()

// ========== 模式标签 ==========
const tabs: Array<{ label: string; value: RedrawMode }> = [
  { label: '整图重绘', value: 'full' },
  { label: '局部重绘', value: 'partial' },
  { label: '重新生成', value: 'regenerate' },
]

const mode = ref<RedrawMode>('full')
const prompt = ref('')

// ========== Canvas 引用（H5/App 平台） ==========
// #ifndef MP-WEIXIN
const canvasRef = ref<HTMLCanvasElement | null>(null)
let canvasCtx: CanvasRenderingContext2D | null = null
// #endif

// ========== 绘画状态 ==========
const brushSize = ref(24)
const strokes = ref<Stroke[]>([])
const currentStroke = ref<Stroke | null>(null)
const isDrawing = ref(false)
const imageLoaded = ref(false)

// ========== 切换模式时重置 ==========
function switchMode(newMode: RedrawMode) {
  mode.value = newMode
  if (newMode === 'partial') {
    // 延迟初始化 Canvas，等待 DOM 更新
    nextTick(() => {
      initCanvas()
    })
  }
}

// ========== 初始化 Canvas ==========
function initCanvas() {
  // #ifdef MP-WEIXIN
  // 微信小程序使用 uni.createCanvasContext
  const ctx = uni.createCanvasContext('redrawCanvas')
  if (ctx) {
    // 设置画笔样式
    ctx.setStrokeStyle('#ff0000')
    ctx.setLineWidth(brushSize.value)
    ctx.setLineCap('round')
    ctx.setLineJoin('round')
    ctx.draw()
  }
  // #endif
  // #ifndef MP-WEIXIN
  if (!canvasRef.value) return
  canvasCtx = canvasRef.value.getContext('2d')
  if (!canvasCtx) return

  // 设置 Canvas 尺寸匹配图片容器
  const container = canvasRef.value.parentElement
  if (container) {
    const rect = container.getBoundingClientRect()
    canvasRef.value.width = rect.width
    canvasRef.value.height = rect.height
  }

  // 设置画笔样式
  canvasCtx.strokeStyle = 'rgba(255, 0, 0, 0.6)'
  canvasCtx.lineWidth = brushSize.value
  canvasCtx.lineCap = 'round'
  canvasCtx.lineJoin = 'round'
  // #endif
}

// ========== 触摸事件处理 ==========
/** uni-app Canvas 触摸事件（兼容各平台） */
interface UniCanvasTouch {
  x: number
  y: number
}

interface UniCanvasTouchEvent {
  touches: UniCanvasTouch[]
  changedTouches: UniCanvasTouch[]
  detail?: Record<string, unknown>
  preventDefault?: () => void
  stopPropagation?: () => void
}

function getTouchPos(e: UniCanvasTouchEvent): { x: number; y: number } {
  if (e.touches && e.touches.length > 0) {
    return { x: e.touches[0].x, y: e.touches[0].y }
  }
  return { x: 0, y: 0 }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function handleTouchStart(e: any) {
  if (mode.value !== 'partial') return
  isDrawing.value = true
  const pos = getTouchPos(e)
  currentStroke.value = { points: [pos] }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function handleTouchMove(e: any) {
  if (!isDrawing.value || !currentStroke.value) return
  const pos = getTouchPos(e)
  const lastPos = currentStroke.value.points[currentStroke.value.points.length - 1]
  currentStroke.value.points.push(pos)

  // 绘制线段
  // #ifdef MP-WEIXIN
  const ctx = uni.createCanvasContext('redrawCanvas')
  ctx.setStrokeStyle('#ff0000')
  ctx.setLineWidth(brushSize.value)
  ctx.setLineCap('round')
  ctx.setLineJoin('round')
  ctx.beginPath()
  ctx.moveTo(lastPos.x, lastPos.y)
  ctx.lineTo(pos.x, pos.y)
  ctx.stroke()
  ctx.draw(true)
  // #endif
  // #ifndef MP-WEIXIN
  if (!canvasCtx) return
  canvasCtx.beginPath()
  canvasCtx.moveTo(lastPos.x, lastPos.y)
  canvasCtx.lineTo(pos.x, pos.y)
  canvasCtx.stroke()
  // #endif
}

function handleTouchEnd() {
  if (!isDrawing.value || !currentStroke.value) return
  isDrawing.value = false
  // 保存笔触
  if (currentStroke.value.points.length > 1) {
    strokes.value.push(currentStroke.value)
  }
  currentStroke.value = null
}

// ========== 撤销 ==========
function undoStroke() {
  if (strokes.value.length === 0) return
  strokes.value.pop()
  redrawAll()
}

// ========== 清除 ==========
function clearCanvas() {
  strokes.value = []
  redrawAll()
}

// ========== 重绘所有笔触 ==========
function redrawAll() {
  // #ifdef MP-WEIXIN
  const ctx = uni.createCanvasContext('redrawCanvas')
  // 先清空
  ctx.clearRect(0, 0, 9999, 9999)
  // 重绘所有已保存的笔触
  ctx.setStrokeStyle('#ff0000')
  ctx.setLineWidth(brushSize.value)
  ctx.setLineCap('round')
  ctx.setLineJoin('round')
  for (const stroke of strokes.value) {
    if (stroke.points.length < 2) continue
    ctx.beginPath()
    ctx.moveTo(stroke.points[0].x, stroke.points[0].y)
    for (let i = 1; i < stroke.points.length; i++) {
      ctx.lineTo(stroke.points[i].x, stroke.points[i].y)
    }
    ctx.stroke()
  }
  ctx.draw()
  // #endif
  // #ifndef MP-WEIXIN
  if (!canvasCtx || !canvasRef.value) return
  canvasCtx.clearRect(0, 0, canvasRef.value.width, canvasRef.value.height)
  for (const stroke of strokes.value) {
    if (stroke.points.length < 2) continue
    canvasCtx.beginPath()
    canvasCtx.moveTo(stroke.points[0].x, stroke.points[0].y)
    for (let i = 1; i < stroke.points.length; i++) {
      canvasCtx.lineTo(stroke.points[i].x, stroke.points[i].y)
    }
    canvasCtx.stroke()
  }
  // #endif
}

// ========== 画笔大小变化 ==========
function onBrushSizeChange(e: { detail: { value: number } }) {
  brushSize.value = e.detail.value
  // 更新画笔宽度
  // #ifndef MP-WEIXIN
  if (canvasCtx) {
    canvasCtx.lineWidth = brushSize.value
  }
  // #endif
}

// ========== 获取蒙版 base64 数据 ==========
function getMaskDataUrl(): Promise<string> {
  return new Promise((resolve, reject) => {
    // #ifdef MP-WEIXIN
    uni.canvasToTempFilePath({
      canvasId: 'redrawCanvas',
      success: (res) => {
        resolve(res.tempFilePath)
      },
      fail: (err) => {
        reject(err)
      },
    })
    // #endif
    // #ifndef MP-WEIXIN
    if (!canvasRef.value) {
      reject(new Error('Canvas 未初始化'))
      return
    }
    try {
      const dataUrl = canvasRef.value.toDataURL('image/png')
      resolve(dataUrl)
    } catch (err) {
      reject(err)
    }
    // #endif
  })
}

// ========== 图片加载 ==========
function onImageLoad() {
  imageLoaded.value = true
}

function onImageError() {
  imageLoaded.value = false
}

// ========== Modal 交互 ==========
function handleMaskTap() {
  emit('close')
}

function handleClose() {
  emit('close')
}

// ========== 确认重绘 ==========
async function handleConfirm() {
  if (!props.chapterId || !props.imageNumber) {
    emit('close')
    return
  }

  try {
    // 动态导入 API，避免循环依赖
    const { mangaApi } = await import('@/api')

    let mask: string | undefined
    if (mode.value === 'partial' && strokes.value.length > 0) {
      mask = await getMaskDataUrl()
    }

    const result = await mangaApi.regenerateImage(
      props.chapterId,
      props.imageNumber,
      prompt.value || '',
      mode.value,
      { mask },
    )

    emit('success', result as unknown as Record<string, unknown>)
    emit('close')
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : '重绘失败'
    uni.showToast({ title: message, icon: 'error' })
  }
}

// ========== 监听 visible 变化，初始化 Canvas ==========
watch(
  () => props.visible,
  (val) => {
    if (val && mode.value === 'partial') {
      // 组件显示时如果已是局部模式，初始化 Canvas
      nextTick(() => {
        initCanvas()
      })
    }
  },
)
</script>

<style lang="scss" scoped>
.redraw-modal {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 1000;
  display: flex;
  justify-content: center;
  align-items: flex-end;

  &__mask {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.5);
  }

  &__container {
    position: relative;
    width: 100%;
    max-height: 90vh;
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg $lv-radius-lg 0 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    animation: redraw-modal-slide-up 0.3s ease;
  }

  // ===== 头部 =====
  &__header {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 32rpx;
    padding-top: 40rpx;
    border-bottom: 1rpx solid $lv-border-light;
    position: relative;
  }

  &__title {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__close {
    position: absolute;
    right: 32rpx;
    top: 50%;
    transform: translateY(-50%);
    width: 64rpx;
    height: 64rpx;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  &__close-icon {
    font-size: 36rpx;
    color: $lv-text-secondary;
  }

  // ===== 模式标签 =====
  &__tabs {
    display: flex;
    padding: 24rpx 32rpx;
    gap: 16rpx;
  }

  &__tab {
    flex: 1;
    height: 72rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: $lv-radius-sm;
    background: $lv-primary-lighter;
    transition: all 0.2s;

    &--active {
      background: $lv-primary;
    }
  }

  &__tab-text {
    font-size: $lv-font-sm;
    font-weight: 500;
    color: $lv-text-secondary;
    transition: color 0.2s;

    .redraw-modal__tab--active & {
      color: $lv-text-on-primary;
    }
  }

  // ===== 图片区域 =====
  &__image-area {
    position: relative;
    width: 100%;
    background: #f0f0f0;
  }

  &__image {
    width: 100%;
    height: 500rpx;
  }

  &__canvas {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 500rpx;
  }

  // ===== 蒙版工具栏 =====
  &__tools {
    display: flex;
    align-items: center;
    padding: 16rpx 32rpx;
    gap: 16rpx;
    border-bottom: 1rpx solid $lv-border-light;
  }

  &__tool {
    height: 64rpx;
    padding: 0 24rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: $lv-radius-xs;
    border: 1rpx solid $lv-border;
    background: $lv-surface-solid;

    &:active {
      background: $lv-primary-lighter;
    }
  }

  &__tool-text {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__brush {
    flex: 1;
    display: flex;
    align-items: center;
    gap: 8rpx;
  }

  &__brush-label {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    flex-shrink: 0;
  }

  &__slider {
    flex: 1;
  }

  &__brush-value {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    flex-shrink: 0;
    width: 60rpx;
    text-align: center;
  }

  // ===== 提示词 =====
  &__prompt {
    padding: 24rpx 32rpx;
  }

  &__textarea {
    width: 100%;
    min-height: 120rpx;
    padding: 20rpx 24rpx;
    font-size: $lv-font-base;
    color: $lv-text-primary;
    background: $lv-primary-lighter;
    border-radius: $lv-radius-sm;
    border: 1rpx solid $lv-border-light;
    box-sizing: border-box;

    &:focus {
      border-color: $lv-border-focus;
    }
  }

  // ===== 底部按钮 =====
  &__footer {
    display: flex;
    border-top: 1rpx solid $lv-border-light;
    margin-top: 16rpx;
  }

  &__btn {
    flex: 1;
    height: 96rpx;
    display: flex;
    align-items: center;
    justify-content: center;

    &:active {
      background: $lv-primary-lighter;
    }

    &--cancel {
      border-right: 1rpx solid $lv-border-light;
    }

    &--confirm {
      .redraw-modal__btn-text {
        color: $lv-primary;
      }
    }
  }

  &__btn-text {
    font-size: $lv-font-base;
    font-weight: 500;
    color: $lv-text-secondary;
  }
}

@keyframes redraw-modal-slide-up {
  from {
    transform: translateY(100%);
  }
  to {
    transform: translateY(0);
  }
}
</style>
