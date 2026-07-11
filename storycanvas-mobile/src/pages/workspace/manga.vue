<template>
  <view class="manga-workbench">
    <lv-navbar :title="chapterTitle" show-back>
      <template #right>
        <text class="manga-workbench__nav-meta">{{ mangaStore.scenes.length }} 格</text>
      </template>
    </lv-navbar>

    <view class="manga-workbench__steps">
      <view
        v-for="(step, index) in flowSteps"
        :key="step.key"
        :class="[
          'manga-workbench__step',
          {
            'manga-workbench__step--active': activeFlow === step.key,
            'manga-workbench__step--done': activeFlowIndex > index
          }
        ]"
        @tap="switchFlow(step.key)"
      >
        <view class="manga-workbench__step-number">
          <lv-icon v-if="activeFlowIndex > index" name="Check" :size="13" color="#15803d" />
          <text v-else>{{ index + 1 }}</text>
        </view>
        <text>{{ step.label }}</text>
      </view>
    </view>

    <scroll-view scroll-y class="manga-workbench__scroll">
      <view v-if="activeFlow === 'materials'" class="manga-workbench__panel">
        <view class="manga-workbench__intro">
          <text class="manga-workbench__title">素材准备</text>
          <text class="manga-workbench__description">先完成必要素材，再进入分镜确认，生成时无需反复返回配置。</text>
        </view>

        <view class="manga-workbench__summary-list">
          <view class="manga-workbench__summary-row" @tap="handleOpenStylePreset">
            <text :class="['manga-workbench__status', mangaStore.stylePresetName || mangaStore.styleReferenceImageUrl ? 'is-ready' : 'is-pending']">
              {{ mangaStore.stylePresetName || mangaStore.styleReferenceImageUrl ? '已配置' : '待配置' }}
            </text>
            <view class="manga-workbench__summary-main">
              <text class="manga-workbench__summary-title">漫画风格</text>
              <text class="manga-workbench__summary-desc">{{ styleSummary }}</text>
            </view>
            <lv-icon name="ChevronRight" :size="17" color="#94a3b8" />
          </view>

          <view class="manga-workbench__summary-row" @tap="goCharacterRefs">
            <text class="manga-workbench__status is-info">独立页</text>
            <view class="manga-workbench__summary-main">
              <text class="manga-workbench__summary-title">角色参考</text>
              <text class="manga-workbench__summary-desc">配置角色形象与一致性参考图</text>
            </view>
            <lv-icon name="ChevronRight" :size="17" color="#94a3b8" />
          </view>

          <view class="manga-workbench__summary-row" @tap="goRefImages">
            <text class="manga-workbench__status is-info">素材</text>
            <view class="manga-workbench__summary-main">
              <text class="manga-workbench__summary-title">章节参考图</text>
              <text class="manga-workbench__summary-desc">管理场景、构图与章节专属参考</text>
            </view>
            <lv-icon name="ChevronRight" :size="17" color="#94a3b8" />
          </view>

          <view class="manga-workbench__summary-row" @tap="settingsVisible = true">
            <text class="manga-workbench__status is-info">{{ mangaStore.imageCount }} 格</text>
            <view class="manga-workbench__summary-main">
              <text class="manga-workbench__summary-title">生成设置</text>
              <text class="manga-workbench__summary-desc">{{ settingsSummary }}</text>
            </view>
            <lv-icon name="ChevronRight" :size="17" color="#94a3b8" />
          </view>
        </view>

        <view class="manga-workbench__secondary-entry" @tap="goCharacters">
          <lv-icon name="Users" :size="18" color="#475569" />
          <text>查看并调整角色外观描述</text>
          <lv-icon name="ChevronRight" :size="16" color="#94a3b8" />
        </view>
      </view>

      <view v-else-if="activeFlow === 'storyboard'" class="manga-workbench__panel">
        <view class="manga-workbench__intro">
          <text class="manga-workbench__title">检查分镜</text>
          <text class="manga-workbench__description">逐格确认画面内容。点击正文即可编辑，确认后再统一生成图片。</text>
        </view>

        <view v-if="mangaStore.scenes.length" class="manga-workbench__section-head">
          <text>共 {{ mangaStore.scenes.length }} 格</text>
          <view class="manga-workbench__head-actions">
            <view class="manga-workbench__text-action" @tap="handleAddScene">
              <lv-icon name="Plus" :size="14" color="#2563eb" />
              <text>新增</text>
            </view>
            <view class="manga-workbench__text-action" @tap="handleRegenerateScenes">
              <lv-icon name="RefreshCw" :size="14" color="#2563eb" />
              <text>{{ regeneratingScenes ? '生成中' : '重新生成' }}</text>
            </view>
          </view>
        </view>

        <view v-if="mangaStore.scenes.length" class="manga-workbench__scene-list">
          <view v-for="(scene, index) in mangaStore.scenes" :key="index" class="manga-workbench__scene-card">
            <view class="manga-workbench__scene-top">
              <text class="manga-workbench__scene-title">第 {{ index + 1 }} 格</text>
              <view class="manga-workbench__scene-actions">
                <view class="manga-workbench__icon-action" @tap="startSceneEdit(index, scene)">
                  <lv-icon name="Pencil" :size="15" color="#475569" />
                </view>
                <view class="manga-workbench__icon-action" @tap="handleDeleteScene(index)">
                  <lv-icon name="Trash2" :size="15" color="#dc2626" />
                </view>
              </view>
            </view>
            <template v-if="editingSceneIndex === index">
              <textarea
                v-model="editingSceneDraft"
                class="manga-workbench__scene-editor"
                :maxlength="-1"
                auto-height
                placeholder="描述这一格的画面、角色与镜头"
              />
              <view class="manga-workbench__edit-actions">
                <lv-button size="sm" secondary @tap="cancelSceneEdit">取消</lv-button>
                <lv-button size="sm" @tap="saveSceneEdit(index)">保存</lv-button>
              </view>
            </template>
            <text v-else class="manga-workbench__scene-copy" @tap="startSceneEdit(index, scene)">
              {{ scene || '点击补充分镜画面描述' }}
            </text>
          </view>
        </view>

        <view v-else class="manga-workbench__empty-state">
          <view class="manga-workbench__empty-icon">
            <lv-icon name="Clapperboard" :size="28" color="#64748b" />
          </view>
          <text class="manga-workbench__empty-title">还没有分镜</text>
          <text class="manga-workbench__empty-desc">AI 会根据当前章节生成 {{ mangaStore.imageCount }} 格漫画分镜。</text>
        </view>
      </view>

      <view v-else class="manga-workbench__panel">
        <view class="manga-workbench__intro">
          <text class="manga-workbench__title">漫画图片</text>
          <text class="manga-workbench__description">生成任务可在后台继续，未生成或失败的图片可以单独补充。</text>
        </view>

        <view v-if="mangaStore.isGenerating || isPolling" class="manga-workbench__task-card">
          <view class="manga-workbench__task-top">
            <view>
              <text class="manga-workbench__task-title">正在生成漫画</text>
              <text class="manga-workbench__task-desc">{{ mangaStore.progress.statusMsg || '后台处理中' }}</text>
            </view>
            <text class="manga-workbench__task-percent">{{ mangaStore.progressPercent }}%</text>
          </view>
          <lv-progress :percentage="mangaStore.progressPercent" />
          <view class="manga-workbench__cancel-action" @tap="cancelGeneration">取消生成</view>
        </view>

        <view v-if="mangaStore.scenes.length" class="manga-workbench__image-grid">
          <view v-for="(scene, index) in mangaStore.scenes" :key="index" class="manga-workbench__image-card">
            <view class="manga-workbench__image-head">
              <text>第 {{ index + 1 }} 格</text>
              <text :class="['manga-workbench__image-status', getImage(index + 1) ? 'is-ready' : 'is-pending']">
                {{ getImage(index + 1) ? '已完成' : generatingSingle === index + 1 ? '生成中' : '待生成' }}
              </text>
            </view>
            <manga-image-card
              v-if="getImage(index + 1)"
              :image-path="getImage(index + 1)!.image_path"
              :image-number="index + 1"
              :cache-bust="mangaStore.imageCacheBust"
              aspect-ratio="3:4"
              @tap="goGallery(index + 1)"
            />
            <view v-else class="manga-workbench__image-placeholder">
              <lv-icon name="Image" :size="24" color="#94a3b8" />
              <text>{{ generatingSingle === index + 1 ? '正在生成此格' : '等待生成' }}</text>
              <lv-button
                v-if="!mangaStore.isGenerating && !isPolling"
                size="sm"
                secondary
                :loading="generatingSingle === index + 1"
                @tap="generateSingle(index + 1, scene)"
              >
                生成此格
              </lv-button>
            </view>
          </view>
        </view>

        <view v-else class="manga-workbench__empty-state">
          <view class="manga-workbench__empty-icon">
            <lv-icon name="Images" :size="28" color="#64748b" />
          </view>
          <text class="manga-workbench__empty-title">请先生成分镜</text>
          <text class="manga-workbench__empty-desc">完成素材准备和分镜确认后，即可开始生成漫画图片。</text>
        </view>

        <view
          v-if="mangaStore.images.length && !mangaStore.isGenerating && !isPolling"
          class="manga-workbench__danger-action"
          @tap="resetAndGenerate"
        >
          清空并重新生成全部图片
        </view>
      </view>
    </scroll-view>

    <view class="manga-workbench__bottom-bar">
      <lv-button secondary @tap="handleSecondaryAction">{{ secondaryActionText }}</lv-button>
      <lv-button
        class="manga-workbench__primary-action"
        :loading="primaryLoading"
        @tap="handlePrimaryAction"
      >
        {{ primaryActionText }}
      </lv-button>
    </view>

    <view v-if="settingsVisible" class="manga-workbench__backdrop" @tap="settingsVisible = false">
      <view class="manga-workbench__drawer" @tap.stop>
        <view class="manga-workbench__drawer-handle" />
        <text class="manga-workbench__drawer-title">漫画生成设置</text>

        <view class="manga-workbench__setting-group">
          <text class="manga-workbench__setting-label">画面比例</text>
          <view class="manga-workbench__option-grid">
            <view
              v-for="option in aspectRatioOptions"
              :key="option.value"
              :class="['manga-workbench__option', { 'is-active': mangaStore.aspectRatio === option.value }]"
              @tap="selectAspectRatio(option.value)"
            >
              {{ option.label }}
            </view>
          </view>
        </view>

        <view class="manga-workbench__setting-group">
          <text class="manga-workbench__setting-label">色彩模式</text>
          <view class="manga-workbench__option-grid is-compact">
            <view
              v-for="option in colorModeOptions"
              :key="option.value"
              :class="['manga-workbench__option', { 'is-active': mangaStore.colorMode === option.value }]"
              @tap="selectColorMode(option.value)"
            >
              {{ option.label }}
            </view>
          </view>
        </view>

        <view class="manga-workbench__setting-group">
          <text class="manga-workbench__setting-label">分镜数量</text>
          <view class="manga-workbench__option-grid">
            <view
              v-for="option in imageCountOptions"
              :key="option.value"
              :class="['manga-workbench__option', { 'is-active': mangaStore.imageCount === option.value }]"
              @tap="selectImageCount(option.value)"
            >
              {{ option.label }}
            </view>
          </view>
        </view>

        <lv-button block @tap="settingsVisible = false">完成设置</lv-button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import { chaptersApi, mangaApi } from '@/api'
import { useMangaStore } from '@/stores/manga'
import { useStoriesStore } from '@/stores/stories'
import { useUiStore } from '@/stores/ui'
import { useMangaGenerationStatus } from '@/composables/useMangaGenerationStatus'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvProgress from '@/components/lv-progress/lv-progress.vue'
import MangaImageCard from '@/components/manga-image-card/manga-image-card.vue'

type FlowKey = 'materials' | 'storyboard' | 'images'

const mangaStore = useMangaStore()
const storyStore = useStoriesStore()
const uiStore = useUiStore()

const chapterId = ref(0)
const storyId = ref(0)
const chapterTitle = ref('章节漫画')
const activeFlow = ref<FlowKey>('materials')
const settingsVisible = ref(false)
const editingSceneIndex = ref(-1)
const editingSceneDraft = ref('')
const regeneratingScenes = ref(false)
const generatingSingle = ref(0)
const initialized = ref(false)

const { isPolling, stopPolling, checkAndResume } = useMangaGenerationStatus(chapterId)

const flowSteps: Array<{ key: FlowKey; label: string }> = [
  { key: 'materials', label: '素材准备' },
  { key: 'storyboard', label: '分镜确认' },
  { key: 'images', label: '图片生成' }
]

const colorModeOptions = [
  { label: '彩色', value: 'color' as const },
  { label: '黑白', value: 'bw' as const }
]

const imageCountOptions = [
  { label: '4 格', value: 4 },
  { label: '6 格', value: 6 },
  { label: '8 格', value: 8 },
  { label: '10 格', value: 10 },
  { label: '12 格', value: 12 },
  { label: '15 格', value: 15 },
  { label: '20 格', value: 20 }
]

const aspectRatioOptions = [
  { label: '9:16', value: '9:16' },
  { label: '3:4', value: '3:4' },
  { label: '2:3', value: '2:3' },
  { label: '1:1', value: '1:1' },
  { label: '3:2', value: '3:2' },
  { label: '4:3', value: '4:3' },
  { label: '16:9', value: '16:9' }
]

const activeFlowIndex = computed(() => flowSteps.findIndex(step => step.key === activeFlow.value))
const styleSummary = computed(() => {
  const style = mangaStore.stylePresetName || (mangaStore.styleReferenceImageUrl ? '自定义参考图' : '选择预设或上传风格参考图')
  return `${style} · ${mangaStore.colorMode === 'bw' ? '黑白' : '彩色'}`
})
const settingsSummary = computed(() =>
  `${mangaStore.aspectRatio} · ${mangaStore.colorMode === 'bw' ? '黑白' : '彩色'} · ${mangaStore.imageCount} 格`
)
const primaryLoading = computed(() =>
  regeneratingScenes.value || mangaStore.isGenerating || isPolling.value
)
const primaryActionText = computed(() => {
  if (activeFlow.value === 'materials') return mangaStore.scenes.length ? '查看并确认分镜' : '生成分镜'
  if (activeFlow.value === 'storyboard') return mangaStore.images.length ? '继续生成缺失图片' : '确认分镜并生成图片'
  return mangaStore.images.length ? '继续生成缺失图片' : '开始生成漫画图片'
})
const secondaryActionText = computed(() => {
  if (activeFlow.value === 'materials') return '退出'
  return '上一步'
})

onLoad(async options => {
  chapterId.value = Number(options?.chapterId || 0)
  storyId.value = Number(options?.storyId || 0) || storyStore.activeStoryId || 0
  if (!chapterId.value) {
    uiStore.error('未指定章节')
    return
  }
  await loadWorkbench()
  initialized.value = true
})

onShow(async () => {
  if (!initialized.value || !chapterId.value) return
  await Promise.all([
    mangaStore.loadStylePreset(chapterId.value),
    mangaStore.loadAspectRatio(chapterId.value),
    mangaStore.loadImages(chapterId.value)
  ])
  checkAndResume()
})

async function loadWorkbench() {
  try {
    mangaStore.setActiveChapterContext(chapterId.value)
    const [chapter] = await Promise.all([
      chaptersApi.getChapter(chapterId.value),
      mangaStore.loadChapterManga(chapterId.value),
      mangaStore.loadColorMode(chapterId.value),
      mangaStore.loadImageCount(chapterId.value),
      mangaStore.loadAspectRatio(chapterId.value),
      mangaStore.loadStylePreset(chapterId.value)
    ])
    chapterTitle.value = `第 ${chapter.chapter_number} 章漫画`
    if (mangaStore.images.length) activeFlow.value = 'images'
    else if (mangaStore.scenes.length) activeFlow.value = 'storyboard'
    checkAndResume()
  } catch (error) {
    console.error('加载漫画工作台失败:', error)
    uiStore.error('加载漫画工作台失败')
  }
}

function switchFlow(flow: FlowKey) {
  if (flow === 'images' && !mangaStore.scenes.length) {
    uiStore.error('请先生成并确认分镜')
    return
  }
  activeFlow.value = flow
}

async function handlePrimaryAction() {
  if (!chapterId.value || primaryLoading.value) return
  if (activeFlow.value === 'materials') {
    if (mangaStore.scenes.length) {
      activeFlow.value = 'storyboard'
      return
    }
    await generateScenes()
    return
  }
  if (!mangaStore.scenes.length) {
    activeFlow.value = 'materials'
    uiStore.error('请先生成分镜')
    return
  }
  try {
    if (editingSceneIndex.value >= 0) {
      await saveSceneEdit(editingSceneIndex.value)
      if (editingSceneIndex.value >= 0) return
    } else {
      await mangaStore.updateScenes(chapterId.value, [...mangaStore.scenes])
    }
    activeFlow.value = 'images'
    await mangaStore.startMangaGeneration(chapterId.value)
  } catch (error: any) {
    uiStore.error(error.message || '启动漫画生成失败')
  }
}

function handleSecondaryAction() {
  if (activeFlow.value === 'materials') {
    uni.navigateBack()
    return
  }
  activeFlow.value = activeFlow.value === 'images' ? 'storyboard' : 'materials'
}

async function generateScenes() {
  regeneratingScenes.value = true
  try {
    await mangaStore.generateScenes(chapterId.value)
    activeFlow.value = 'storyboard'
    uiStore.success('分镜已生成，请逐格确认')
  } catch (error: any) {
    uiStore.error(error.message || '生成分镜失败')
  } finally {
    regeneratingScenes.value = false
  }
}

function startSceneEdit(index: number, text: string) {
  editingSceneIndex.value = index
  editingSceneDraft.value = text
}

function cancelSceneEdit() {
  editingSceneIndex.value = -1
  editingSceneDraft.value = ''
}

async function saveSceneEdit(index: number) {
  const scenes = [...mangaStore.scenes]
  scenes[index] = editingSceneDraft.value.trim()
  try {
    await mangaStore.updateScenes(chapterId.value, scenes)
    cancelSceneEdit()
    uiStore.success('分镜已保存')
  } catch (error: any) {
    uiStore.error(error.message || '保存分镜失败')
  }
}

function handleAddScene() {
  const scenes = [...mangaStore.scenes, '']
  mangaStore.scenes = scenes
  startSceneEdit(scenes.length - 1, '')
}

function handleDeleteScene(index: number) {
  uni.showModal({
    title: '删除分镜',
    content: mangaStore.images.length ? '删除分镜会清空现有漫画图片，确定继续？' : '确定删除此分镜？',
    confirmText: '删除',
    success: async result => {
      if (!result.confirm) return
      try {
        if (mangaStore.images.length) {
          await mangaApi.clearMangaImages(chapterId.value)
          mangaStore.images = []
        }
        const scenes = mangaStore.scenes.filter((_, currentIndex) => currentIndex !== index)
        await mangaStore.updateScenes(chapterId.value, scenes)
        cancelSceneEdit()
        uiStore.success('分镜已删除')
      } catch (error: any) {
        uiStore.error(error.message || '删除分镜失败')
      }
    }
  })
}

async function handleRegenerateScenes() {
  if (regeneratingScenes.value) return
  const run = async () => {
    regeneratingScenes.value = true
    try {
      if (mangaStore.images.length) {
        await mangaApi.clearMangaImages(chapterId.value)
        mangaStore.images = []
      }
      await mangaStore.generateScenes(chapterId.value)
      uiStore.success('分镜已重新生成')
    } catch (error: any) {
      uiStore.error(error.message || '重新生成分镜失败')
    } finally {
      regeneratingScenes.value = false
    }
  }
  if (!mangaStore.images.length) {
    await run()
    return
  }
  uni.showModal({
    title: '重新生成分镜',
    content: '重新生成会清空现有漫画图片，确定继续？',
    confirmText: '清空并生成',
    success: result => {
      if (result.confirm) run()
    }
  })
}

function selectAspectRatio(ratio: string) {
  mangaStore.saveAspectRatio(chapterId.value, ratio)
}

function selectColorMode(mode: 'color' | 'bw') {
  mangaStore.saveColorMode(chapterId.value, mode)
}

async function selectImageCount(count: number) {
  if (count === mangaStore.imageCount) return
  if (!mangaStore.scenes.length) {
    try {
      await mangaStore.saveImageCount(chapterId.value, count)
    } catch (error: any) {
      uiStore.error(error.message || '保存分镜数量失败')
    }
    return
  }
  uni.showModal({
    title: '调整分镜数量',
    content: `当前已有 ${mangaStore.scenes.length} 格分镜。调整为 ${count} 格后，需要重新生成分镜，现有漫画图片也会被清空。`,
    confirmText: '调整并重生成',
    success: async result => {
      if (!result.confirm) return
      regeneratingScenes.value = true
      try {
        if (mangaStore.images.length) {
          await mangaApi.clearMangaImages(chapterId.value)
          mangaStore.images = []
        }
        await mangaStore.saveImageCount(chapterId.value, count)
        await mangaStore.generateScenes(chapterId.value)
        activeFlow.value = 'storyboard'
        settingsVisible.value = false
        uiStore.success(`已重新生成 ${count} 格分镜`)
      } catch (error: any) {
        uiStore.error(error.message || '调整分镜数量失败')
      } finally {
        regeneratingScenes.value = false
      }
    }
  })
}

function handleOpenStylePreset() {
  uni.navigateTo({ url: `/pages/workspace/manga-style?chapterId=${chapterId.value}` })
}

function goCharacterRefs() {
  uni.navigateTo({ url: `/pages/workspace/character-refs?storyId=${storyId.value}&chapterId=${chapterId.value}` })
}

function goCharacters() {
  uni.navigateTo({ url: `/pages/workspace/character-profiles?storyId=${storyId.value}` })
}

function goRefImages() {
  uni.navigateTo({ url: `/pages/workspace/ref-images?chapterId=${chapterId.value}` })
}

function goGallery(imageNumber: number) {
  uni.navigateTo({ url: `/pages/workspace/manga-gallery?chapterId=${chapterId.value}&imageNumber=${imageNumber}` })
}

function getImage(imageNumber: number) {
  return mangaStore.images.find(image => image.image_number === imageNumber)
}

async function generateSingle(imageNumber: number, scene: string) {
  if (!chapterId.value || generatingSingle.value) return
  generatingSingle.value = imageNumber
  try {
    const image = await mangaApi.regenerateImage(chapterId.value, imageNumber, scene, 'regenerate', {
      size: aspectRatioToSize(mangaStore.aspectRatio),
      stylePresetName: mangaStore.stylePresetName || undefined,
      styleRefUrl: mangaStore.styleReferenceImageUrl || undefined
    })
    const existingIndex = mangaStore.images.findIndex(item => item.image_number === imageNumber)
    if (existingIndex >= 0) mangaStore.images[existingIndex] = image
    else mangaStore.images.push(image)
    mangaStore.images.sort((left, right) => left.image_number - right.image_number)
    mangaStore.refreshImageCache()
    uiStore.success(`第 ${imageNumber} 格已生成`)
  } catch (error: any) {
    uiStore.error(error.message || '单格生成失败')
  } finally {
    generatingSingle.value = 0
  }
}

function resetAndGenerate() {
  uni.showModal({
    title: '重新生成全部',
    content: '将清空本章现有漫画图片，分镜脚本会保留。',
    confirmText: '清空并生成',
    success: async result => {
      if (!result.confirm) return
      try {
        await mangaApi.clearMangaImages(chapterId.value)
        mangaStore.images = []
        await mangaStore.startMangaGeneration(chapterId.value)
      } catch (error: any) {
        uiStore.error(error.message || '重新生成失败')
      }
    }
  })
}

async function cancelGeneration() {
  stopPolling()
  try {
    await mangaStore.stopGeneration(chapterId.value)
    uiStore.success('已取消生成')
  } catch (error: any) {
    uiStore.error(error.message || '取消失败')
  }
}

function aspectRatioToSize(ratio: string) {
  return ({
    '9:16': '1024x1792',
    '3:4': '1024x1365',
    '2:3': '1024x1536',
    '1:1': '1024x1024',
    '3:2': '1536x1024',
    '4:3': '1365x1024',
    '16:9': '1792x1024'
  } as Record<string, string>)[ratio]
}
</script>

<style lang="scss" scoped>
.manga-workbench {
  min-height: 100vh;
  background: #f4f7fb;
  color: #0f172a;

  &__nav-meta {
    font-size: 22rpx;
    color: #64748b;
  }

  &__steps {
    position: fixed;
    z-index: 20;
    top: calc(var(--status-bar-height) + 88rpx);
    left: 0;
    right: 0;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    height: 104rpx;
    padding: 0 24rpx;
    background: #fff;
    border-bottom: 1rpx solid #e2e8f0;
  }

  &__step {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10rpx;
    min-width: 0;
    font-size: 22rpx;
    color: #94a3b8;

    &::after {
      position: absolute;
      top: 51rpx;
      right: -18rpx;
      width: 36rpx;
      height: 2rpx;
      background: #dbe3ee;
      content: '';
    }

    &:last-child::after {
      display: none;
    }

    &--active {
      color: #1d4ed8;
      font-weight: 700;
    }

    &--done {
      color: #15803d;
    }
  }

  &__step-number {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36rpx;
    height: 36rpx;
    flex: 0 0 36rpx;
    border-radius: 50%;
    background: #eef2f7;
    font-size: 20rpx;
    font-weight: 700;
    color: #64748b;
  }

  &__step--active &__step-number {
    background: #2563eb;
    color: #fff;
  }

  &__step--done &__step-number {
    background: #dcfce7;
  }

  &__scroll {
    height: 100vh;
    box-sizing: border-box;
    padding: calc(var(--status-bar-height) + 212rpx) 24rpx calc(148rpx + env(safe-area-inset-bottom));
  }

  &__panel {
    width: 100%;
    max-width: 1080rpx;
    margin: 0 auto;
    padding-bottom: 28rpx;
  }

  &__intro {
    padding: 28rpx 4rpx 24rpx;
  }

  &__title {
    display: block;
    font-size: 38rpx;
    line-height: 1.25;
    font-weight: 800;
  }

  &__description {
    display: block;
    margin-top: 12rpx;
    font-size: 24rpx;
    line-height: 1.6;
    color: #64748b;
  }

  &__summary-list {
    overflow: hidden;
    background: #fff;
    border: 1rpx solid #e2e8f0;
    border-radius: 8rpx;
  }

  &__summary-row {
    display: flex;
    align-items: center;
    gap: 18rpx;
    min-height: 112rpx;
    padding: 18rpx 22rpx;
    border-bottom: 1rpx solid #edf1f5;

    &:last-child {
      border-bottom: 0;
    }
  }

  &__status,
  &__image-status {
    flex: 0 0 auto;
    padding: 7rpx 12rpx;
    border-radius: 6rpx;
    font-size: 20rpx;
    font-weight: 700;

    &.is-ready {
      background: #dcfce7;
      color: #15803d;
    }

    &.is-pending {
      background: #fff7ed;
      color: #c2410c;
    }

    &.is-info {
      background: #eff6ff;
      color: #1d4ed8;
    }
  }

  &__summary-main {
    min-width: 0;
    flex: 1;
  }

  &__summary-title {
    display: block;
    font-size: 28rpx;
    font-weight: 700;
  }

  &__summary-desc {
    display: block;
    overflow: hidden;
    margin-top: 7rpx;
    font-size: 22rpx;
    color: #64748b;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__secondary-entry {
    display: flex;
    align-items: center;
    gap: 14rpx;
    margin-top: 18rpx;
    padding: 22rpx;
    background: #fff;
    border: 1rpx solid #e2e8f0;
    border-radius: 8rpx;
    font-size: 24rpx;
    color: #475569;

    text {
      flex: 1;
    }
  }

  &__section-head,
  &__task-top,
  &__image-head,
  &__scene-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  &__section-head {
    margin-bottom: 16rpx;
    font-size: 24rpx;
    font-weight: 700;
    color: #475569;
  }

  &__head-actions,
  &__scene-actions,
  &__edit-actions {
    display: flex;
    align-items: center;
    gap: 12rpx;
  }

  &__text-action {
    display: flex;
    align-items: center;
    gap: 5rpx;
    padding: 10rpx 4rpx;
    font-size: 22rpx;
    color: #2563eb;
  }

  &__scene-list {
    display: flex;
    flex-direction: column;
    gap: 16rpx;
  }

  &__scene-card,
  &__image-card,
  &__task-card {
    padding: 22rpx;
    background: #fff;
    border: 1rpx solid #e2e8f0;
    border-radius: 8rpx;
  }

  &__scene-title {
    font-size: 27rpx;
    font-weight: 700;
  }

  &__icon-action {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 54rpx;
    height: 54rpx;
    border-radius: 6rpx;
    background: #f8fafc;
  }

  &__scene-copy {
    display: block;
    margin-top: 16rpx;
    font-size: 25rpx;
    line-height: 1.65;
    color: #475569;
  }

  &__scene-editor {
    width: 100%;
    min-height: 150rpx;
    box-sizing: border-box;
    margin-top: 16rpx;
    padding: 18rpx;
    background: #f8fafc;
    border: 1rpx solid #cbd5e1;
    border-radius: 6rpx;
    font-size: 25rpx;
    line-height: 1.6;
  }

  &__edit-actions {
    justify-content: flex-end;
    margin-top: 14rpx;
  }

  &__empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 84rpx 36rpx;
    text-align: center;
  }

  &__empty-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 88rpx;
    height: 88rpx;
    margin-bottom: 20rpx;
    border-radius: 50%;
    background: #e8eef6;
  }

  &__empty-title {
    font-size: 28rpx;
    font-weight: 700;
  }

  &__empty-desc {
    margin-top: 10rpx;
    font-size: 23rpx;
    line-height: 1.6;
    color: #64748b;
  }

  &__task-card {
    margin-bottom: 18rpx;
    border-color: #bfdbfe;
    background: #f8fbff;
  }

  &__task-title {
    display: block;
    font-size: 27rpx;
    font-weight: 700;
  }

  &__task-desc {
    display: block;
    margin: 7rpx 0 18rpx;
    font-size: 22rpx;
    color: #64748b;
  }

  &__task-percent {
    font-size: 26rpx;
    font-weight: 800;
    color: #2563eb;
  }

  &__cancel-action,
  &__danger-action {
    padding: 20rpx 0 4rpx;
    text-align: center;
    font-size: 23rpx;
    color: #dc2626;
  }

  &__image-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16rpx;
  }

  &__image-card {
    min-width: 0;
    padding: 14rpx;
  }

  &__image-head {
    gap: 8rpx;
    margin-bottom: 12rpx;
    font-size: 23rpx;
    font-weight: 700;
  }

  &__image-status {
    padding: 5rpx 8rpx;
    font-size: 18rpx;
  }

  &__image-placeholder {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 14rpx;
    min-height: 0;
    aspect-ratio: 3 / 4;
    padding: 18rpx;
    background: #f8fafc;
    border: 1rpx dashed #cbd5e1;
    border-radius: 6rpx;
    text-align: center;
    font-size: 21rpx;
    color: #64748b;
  }

  @media (min-width: 768px) {
    &__scroll {
      padding-right: 32px;
      padding-left: 32px;
    }

    &__panel {
      max-width: 960px;
    }

    &__image-grid {
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
    }
  }

  &__bottom-bar {
    position: fixed;
    z-index: 30;
    right: 0;
    bottom: 0;
    left: 0;
    display: flex;
    gap: 14rpx;
    padding: 18rpx 24rpx calc(18rpx + env(safe-area-inset-bottom));
    background: rgba(255, 255, 255, 0.98);
    border-top: 1rpx solid #e2e8f0;
    box-shadow: 0 -8rpx 24rpx rgba(15, 23, 42, 0.06);
  }

  &__primary-action {
    flex: 1;
  }

  &__backdrop {
    position: fixed;
    z-index: 100;
    inset: 0;
    display: flex;
    align-items: flex-end;
    background: rgba(15, 23, 42, 0.48);
  }

  &__drawer {
    width: 100%;
    max-height: 82vh;
    box-sizing: border-box;
    padding: 16rpx 24rpx calc(30rpx + env(safe-area-inset-bottom));
    overflow-y: auto;
    background: #fff;
    border-radius: 8rpx 8rpx 0 0;
  }

  &__drawer-handle {
    width: 72rpx;
    height: 8rpx;
    margin: 0 auto 24rpx;
    border-radius: 8rpx;
    background: #cbd5e1;
  }

  &__drawer-title {
    display: block;
    margin-bottom: 28rpx;
    font-size: 32rpx;
    font-weight: 800;
  }

  &__setting-group {
    margin-bottom: 28rpx;
  }

  &__setting-label {
    display: block;
    margin-bottom: 14rpx;
    font-size: 23rpx;
    font-weight: 700;
    color: #475569;
  }

  &__option-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10rpx;

    &.is-compact {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  &__option {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 68rpx;
    padding: 6rpx;
    background: #f8fafc;
    border: 1rpx solid #e2e8f0;
    border-radius: 6rpx;
    font-size: 22rpx;
    color: #475569;

    &.is-active {
      background: #eff6ff;
      border-color: #2563eb;
      color: #1d4ed8;
      font-weight: 700;
    }
  }
}
</style>
