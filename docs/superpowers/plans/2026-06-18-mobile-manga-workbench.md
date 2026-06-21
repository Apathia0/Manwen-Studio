# 移动端漫画工作台对齐 Web 端 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 移动端漫画工作台功能对齐 Web 端，包括比例选择、风格预设、分镜编辑、角色参考图管理、重绘弹窗

**Architecture:** 基于现有 `manga.vue`/`chapter-view.vue` 模板 + `stores/manga.ts` store + `useSSE` composable，新增 3 个组件（style-selector/character-ref-section/image-redraw-modal），API 层扩展 `regenerateImage` 参数。4 个子项目按 A→C→B→D 顺序实施。

**Tech Stack:** Vue 3 + uni-app + Pinia + lv-ui kit + Lucide icons

**设计文档:** `docs/superpowers/specs/2026-06-18-mobile-manga-workbench-design.md`

---

## 子项目 A：比例选择 + 风格预设

### Task A1: 扩展 manga store（aspectRatio / stylePreset / styleRefUrl 状态）

**Files:**
- Modify: `storycanvas-mobile/src/stores/manga.ts` (全文件)
- Test: `npm run type-check` 验证

- [ ] **Step 1: 新增 state 和 action**

在 `stores/manga.ts` 的 `useMangaStore` 中，在 `imageCount` 定义后新增：

```typescript
const aspectRatio = ref('9:16')
const stylePresetName = ref('')
const styleReferenceImageUrl = ref('')

// 加载章节的 aspect ratio（从本地存储）
async function loadAspectRatio(chapterId: number) {
  const saved = uni.getStorageSync(`manga_aspect_${chapterId}`)
  if (saved) aspectRatio.value = saved
}

async function saveAspectRatio(chapterId: number, ratio: string) {
  aspectRatio.value = ratio
  uni.setStorageSync(`manga_aspect_${chapterId}`, ratio)
}

function setStylePreset(name: string) {
  stylePresetName.value = name
}

function setStyleReferenceImageUrl(url: string) {
  styleReferenceImageUrl.value = url
}
```

- [ ] **Step 2: 注册到 return 导出**

在 `return {` 块中添加：

```typescript
aspectRatio,
stylePresetName,
styleReferenceImageUrl,
loadAspectRatio,
saveAspectRatio,
setStylePreset,
setStyleReferenceImageUrl,
```

- [ ] **Step 3: 验证**

```bash
npm run type-check
```

---

### Task A2: 更新 manga API（regenerateImage 支持 options）

**Files:**
- Modify: `storycanvas-mobile/src/api/manga.ts`

- [ ] **Step 1: 修改 `regenerateImage` 签名**

当前：
```typescript
export function regenerateImage(chapterId: number, imageNumber: number, prompt: string, mode?: string): Promise<MangaImage> {
  return post<MangaImage>(`/api/chapters/${chapterId}/regenerate-image/${imageNumber}`, { prompt, mode: mode || 'regenerate' })
}
```

改为：
```typescript
export function regenerateImage(
  chapterId: number,
  imageNumber: number,
  prompt: string,
  mode?: string,
  options?: { size?: string; stylePresetName?: string; styleRefUrl?: string }
): Promise<MangaImage> {
  const body: Record<string, any> = { prompt, mode: mode || 'regenerate' }
  if (options?.size) body.size = options.size
  if (options?.stylePresetName) body.style_preset_name = options.stylePresetName
  if (options?.styleRefUrl) body.style_ref_url = options.styleRefUrl
  return post<MangaImage>(`/api/chapters/${chapterId}/regenerate-image/${imageNumber}`, body)
}
```

- [ ] **Step 2: 验证**

```bash
npm run type-check
```

---

### Task A3: 更新 `startMangaGeneration` 在 store 中传递参数

**Files:**
- Modify: `storycanvas-mobile/src/stores/manga.ts`

- [ ] **Step 1: 修改 `startMangaGeneration` 签名和 SSE body**

当前：
```typescript
const sse = useSSE()
sse.start({
  url: mangaApi.mangaStreamUrl(chapterId),
  headers,
  onEvent: (event) => { ... },
  ...
})
```

改为：
```typescript
const sse = useSSE()
const body: Record<string, any> = {}
if (aspectRatio.value && aspectRatio.value !== '9:16') {
  body.size = ASPECT_RATIO_MAP[aspectRatio.value] || undefined
}
if (stylePresetName.value) body.style_preset_name = stylePresetName.value
if (styleReferenceImageUrl.value) body.style_ref_url = styleReferenceImageUrl.value

sse.start({
  url: mangaApi.mangaStreamUrl(chapterId),
  method: 'POST',
  headers,
  body: Object.keys(body).length > 0 ? body : undefined,
  onEvent: (event) => { ... },
  ...
})
```

在 store 内或外部定义 `ASPECT_RATIO_MAP` 常量：
```typescript
const ASPECT_RATIO_MAP: Record<string, string> = {
  '9:16': '1024x1792',
  '3:4': '1024x1365',
  '2:3': '1024x1536',
  '1:1': '1024x1024',
  '3:2': '1536x1024',
  '4:3': '1365x1024',
  '16:9': '1792x1024',
}
```

- [ ] **Step 2: 验证**

```bash
npm run type-check
```

---

### Task A4: 创建 StyleSelector 组件

**Files:**
- Create: `storycanvas-mobile/src/components/style-selector/style-selector.vue`
- Modify: `storycanvas-mobile/src/api/manga.ts` (optional)

- [ ] **Step 1: 创建 `style-selector.vue` 组件**

```vue
<template>
  <view class="style-selector-overlay" @tap.self="handleClose">
    <view class="style-selector-modal">
      <view class="style-selector-modal__header">
        <text class="style-selector-modal__title">选择风格预设</text>
        <text class="style-selector-modal__close" @tap="handleClose">关闭</text>
      </view>

      <!-- 分类标签 -->
      <scroll-view class="style-selector-modal__categories" scroll-x>
        <view
          v-for="cat in categories"
          :key="cat.key"
          class="style-selector-modal__category-tab"
          :class="{ 'style-selector-modal__category-tab--active': activeCategory === cat.key }"
          @tap="activeCategory = cat.key"
        >
          <text>{{ cat.label }}</text>
        </view>
      </scroll-view>

      <!-- 预设网格 -->
      <scroll-view class="style-selector-modal__grid" scroll-y>
        <view
          v-for="preset in filteredPresets"
          :key="preset.id"
          class="style-selector-modal__preset-card"
          :class="{ 'style-selector-modal__preset-card--selected': selectedName === preset.name }"
          @tap="handleSelect(preset.name)"
        >
          <image
            v-if="preset.image_url"
            :src="preset.image_url"
            class="style-selector-modal__preset-image"
            mode="aspectFill"
          />
          <view v-else class="style-selector-modal__preset-placeholder">
            <lv-icon name="Palette" :size="24" />
          </view>
          <text class="style-selector-modal__preset-name">{{ preset.name }}</text>
          <text class="style-selector-modal__preset-category">{{ preset.category }}</text>
        </view>

        <!-- 自定义风格参考图 -->
        <view class="style-selector-modal__custom-section">
          <text class="style-selector-modal__section-label">自定义风格参考图</text>
          <view v-if="localRefUrl" class="style-selector-modal__ref-preview">
            <image :src="localRefUrl" mode="aspectFill" class="style-selector-modal__ref-image" />
            <view class="style-selector-modal__ref-actions">
              <lv-button size="sm" secondary @tap="handleUploadRef">替换</lv-button>
              <lv-button size="sm" danger @tap="handleClearRef">清除</lv-button>
            </view>
          </view>
          <lv-button v-else block outline @tap="handleUploadRef">上传风格参考图</lv-button>
        </view>
      </scroll-view>

      <view class="style-selector-modal__footer">
        <lv-button block @tap="handleConfirm">确认选择</lv-button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { VideoStylePreset } from '@/api/admin'
import { adminApi } from '@/api'
import { useImagePicker } from '@/composables/useImagePicker'
import { mangaApi } from '@/api'

const props = defineProps<{
  presets: VideoStylePreset[]
  selectedName: string
  styleRefUrl: string | null
  chapterId?: number | null
}>()

const emit = defineEmits<{
  (e: 'update:selectedName', name: string): void
  (e: 'update:styleRefUrl', url: string | null): void
  (e: 'close'): void
}>()

const imagePicker = useImagePicker()

const categories = [
  { key: 'all', label: '全部' },
  { key: 'realistic', label: '写实' },
  { key: 'anime', label: '动漫' },
  { key: 'artistic', label: '艺术' },
  { key: 'cinematic', label: '电影' },
]

const activeCategory = ref('all')
const localSelectedName = ref(props.selectedName)
const localRefUrl = ref(props.styleRefUrl)
const uploading = ref(false)

const filteredPresets = computed(() => {
  if (activeCategory.value === 'all') return props.presets
  return props.presets.filter(p => p.category === activeCategory.value)
})

function handleSelect(name: string) {
  localSelectedName.value = name
  localRefUrl.value = null // 选择内置预设时清除自定义参考图
}

async function handleUploadRef() {
  if (!props.chapterId) return
  try {
    const file = await imagePicker.pickImage()
    if (!file) return
    uploading.value = true
    const result = await mangaApi.uploadStyleReferenceImage(props.chapterId, file.path || file.tempFilePath)
    if (result.style_reference_image_url) {
      localRefUrl.value = result.style_reference_image_url
      localSelectedName.value = '' // 使用自定义参考图时清除预设
    }
  } catch (e: any) {
    uni.showToast({ title: e.message || '上传失败', icon: 'none' })
  } finally {
    uploading.value = false
  }
}

function handleClearRef() {
  localRefUrl.value = null
}

function handleConfirm() {
  emit('update:selectedName', localSelectedName.value)
  emit('update:styleRefUrl', localRefUrl.value)
  handleClose()
}

function handleClose() {
  emit('close')
}
</script>

<style lang="scss" scoped>
.style-selector-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 1000;
  display: flex;
  align-items: flex-end;
}

.style-selector-modal {
  width: 100%;
  max-height: 75vh;
  background: $lv-surface-solid;
  border-radius: $lv-radius-lg $lv-radius-lg 0 0;
  display: flex;
  flex-direction: column;

  &__header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 24rpx $lv-page-padding;
    border-bottom: 1rpx solid $lv-border-light;
  }

  &__title {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__close {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
    padding: 8rpx;
  }

  &__categories {
    display: flex;
    padding: 16rpx $lv-page-padding;
    white-space: nowrap;
  }

  &__category-tab {
    display: inline-flex;
    padding: 8rpx 24rpx;
    margin-right: 12rpx;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    background: $lv-bg-start;
    border-radius: $lv-radius-full;

    &--active {
      color: $lv-primary;
      background: $lv-primary-light;
      font-weight: 600;
    }
  }

  &__grid {
    flex: 1;
    padding: $lv-page-padding;
  }

  &__preset-card {
    display: inline-flex;
    flex-direction: column;
    align-items: center;
    width: calc(33.33% - 16rpx);
    margin: 8rpx;
    padding: 16rpx;
    border-radius: $lv-radius-md;
    border: 2rpx solid $lv-border;

    &--selected {
      border-color: $lv-primary;
      background: $lv-primary-lighter;
    }
  }

  &__preset-image {
    width: 160rpx;
    height: 120rpx;
    border-radius: $lv-radius-sm;
    margin-bottom: 8rpx;
  }

  &__preset-placeholder {
    width: 160rpx;
    height: 120rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    background: $lv-bg-start;
    border-radius: $lv-radius-sm;
    margin-bottom: 8rpx;
    color: $lv-text-muted;
  }

  &__preset-name {
    font-size: $lv-font-xs;
    font-weight: 600;
    color: $lv-text-primary;
    text-align: center;
  }

  &__preset-category {
    font-size: 20rpx;
    color: $lv-text-muted;
    margin-top: 4rpx;
  }

  &__custom-section {
    margin-top: 24rpx;
    padding-top: 24rpx;
    border-top: 1rpx solid $lv-border-light;
  }

  &__section-label {
    font-size: $lv-font-sm;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 12rpx;
    display: block;
  }

  &__ref-preview {
    display: flex;
    align-items: center;
    gap: 16rpx;
  }

  &__ref-image {
    width: 160rpx;
    height: 160rpx;
    border-radius: $lv-radius-sm;
  }

  &__ref-actions {
    display: flex;
    gap: 12rpx;
  }

  &__footer {
    padding: $lv-page-padding;
    border-top: 1rpx solid $lv-border-light;
  }
}
</style>
```

- [ ] **Step 2: 验证**

```bash
npm run type-check
```

---

### Task A5: 更新 manga.vue（比例 + 风格预设 UI）

**Files:**
- Modify: `storycanvas-mobile/src/pages/workspace/manga.vue`

- [ ] **Step 1: 在 settings 区域添加比例选择器和风格预设按钮**

在模板中，当前 settings 区域是色彩 + 张数。在其后添加：

```vue
<view class="manga-page__settings">
  <!-- 现有：色彩 + 张数 -->
  <text class="manga-page__label">比例:</text>
  <picker :value="aspectRatioIndex" :range="aspectRatioOptions.map(o => o.label)" @change="handleAspectRatioChange">
    <text class="manga-page__picker">{{ aspectRatioOptions[aspectRatioIndex].label }}</text>
  </picker>
</view>

<view class="manga-page__style-row">
  <lv-button
    secondary
    size="sm"
    :class="{ 'manga-page__style-btn--active': mangaStore.stylePresetName || mangaStore.styleReferenceImageUrl }"
    @tap="showStyleSelector = true"
  >
    <lv-icon name="Palette" :size="14" style="margin-right: 6rpx;" />
    {{ mangaStore.stylePresetName || (mangaStore.styleReferenceImageUrl ? '已上传风格参考图' : '选择风格') }}
  </lv-button>
</view>
```

- [ ] **Step 2: 添加 script 逻辑**

在 `<script setup>` 中添加：

```typescript
import StyleSelector from '@/components/style-selector/style-selector.vue'
import { adminApi } from '@/api'
import type { VideoStylePreset } from '@/api/admin'

const aspectRatioOptions = [
  { label: '9:16', value: '9:16' },
  { label: '3:4', value: '3:4' },
  { label: '2:3', value: '2:3' },
  { label: '1:1', value: '1:1' },
  { label: '3:2', value: '3:2' },
  { label: '4:3', value: '4:3' },
  { label: '16:9', value: '16:9' },
]

const aspectRatioIndex = ref(0)
const showStyleSelector = ref(false)
const stylePresets = ref<VideoStylePreset[]>([])

// 在 onLoad 中加载
async function loadStylePresets() {
  try {
    const result = await adminApi.listStylePresets()
    stylePresets.value = result.presets
  } catch {}
}

// onLoad 中调用 loadStylePresets()，同时加载 aspectRatio
function handleAspectRatioChange(e: any) {
  aspectRatioIndex.value = e.detail.value
  const ratio = aspectRatioOptions[aspectRatioIndex.value].value
  mangaStore.saveAspectRatio(chapterId, ratio)
}
```

- [ ] **Step 3: 在模板底部添加 StyleSelector 弹窗**

```vue
<StyleSelector
  v-if="showStyleSelector"
  :presets="stylePresets"
  :selected-name="mangaStore.stylePresetName"
  :style-ref-url="mangaStore.styleReferenceImageUrl"
  :chapter-id="chapterId"
  @update:selectedName="mangaStore.setStylePreset"
  @update:styleRefUrl="mangaStore.setStyleReferenceImageUrl"
  @close="showStyleSelector = false"
/>
```

- [ ] **Step 4: 添加 CSS**

```scss
&__style-row {
  display: flex;
  align-items: center;
  margin-bottom: 16rpx;
}

&__style-btn--active {
  border-color: $lv-primary;
  color: $lv-primary;
}
```

- [ ] **Step 5: 验证**

```bash
npm run type-check
```

---

### Task A6: 更新 chapter-view.vue 漫画 tab（比例 + 风格预设）

**Files:**
- Modify: `storycanvas-mobile/src/pages/workspace/chapter-view.vue`

- [ ] **Step 1: 在漫画 tab 的设置区添加比例和风格**

参照 Task A5 相同的模式，在 chapter-view.vue 的 `<template #tab-2>` 区域添加比例 picker 和风格预设按钮。

在 settings 行（当前有色彩 + 张数）后添加：

```vue
<text class="chapter-view__manga-label">比例:</text>
<picker :value="aspectRatioIndex" :range="aspectRatioOptions.map(o => o.label)" @change="handleAspectRatioChange">
  <text class="chapter-view__manga-picker">{{ aspectRatioOptions[aspectRatioIndex].label }}</text>
</picker>
```

在生成按钮下方或设置行下方添加风格按钮：

```vue
<view class="chapter-view__style-row">
  <lv-button secondary size="sm" @tap="showStyleSelector = true">
    <lv-icon name="Palette" :size="14" style="margin-right: 6rpx;" />
    {{ mangaStore.stylePresetName || (mangaStore.styleReferenceImageUrl ? '已上传风格参考图' : '选择风格') }}
  </lv-button>
</view>
```

- [ ] **Step 2: 添加 script 逻辑（在 chapter-view 的 script 区）**

```typescript
import StyleSelector from '@/components/style-selector/style-selector.vue'
import { adminApi } from '@/api'
import type { VideoStylePreset } from '@/api/admin'

const aspectRatioOptions = [
  { label: '9:16', value: '9:16' },
  { label: '3:4', value: '3:4' },
  { label: '2:3', value: '2:3' },
  { label: '1:1', value: '1:1' },
  { label: '3:2', value: '3:2' },
  { label: '4:3', value: '4:3' },
  { label: '16:9', value: '16:9' },
]

const aspectRatioIndex = ref(0)
const showStyleSelector = ref(false)
const stylePresets = ref<VideoStylePreset[]>([])
```

- [ ] **Step 3: 添加 StyleSelector 弹窗和 CSS**

```vue
<StyleSelector
  v-if="showStyleSelector"
  :presets="stylePresets"
  :selected-name="mangaStore.stylePresetName"
  :style-ref-url="mangaStore.styleReferenceImageUrl"
  :chapter-id="chapterId"
  @update:selectedName="mangaStore.setStylePreset"
  @update:styleRefUrl="mangaStore.setStyleReferenceImageUrl"
  @close="showStyleSelector = false"
/>
```

```scss
&__style-row {
  margin-bottom: 12rpx;
}
```

- [ ] **Step 4: 验证**

```bash
npm run type-check
```

---

## 子项目 C：角色参考图独立管理

### Task C1: 创建 character-ref-section 组件

**Files:**
- Create: `storycanvas-mobile/src/components/character-ref-section/character-ref-section.vue`

- [ ] **Step 1: 创建组件**

```vue
<template>
  <view class="char-ref-section">
    <text class="char-ref-section__title">角色参考图</text>

    <view v-if="loading" class="char-ref-section__loading">
      <text>加载中...</text>
    </view>

    <view v-else-if="characters.length === 0" class="char-ref-section__empty">
      <text>暂无角色数据，请先在角色设定中创建角色</text>
    </view>

    <view v-else class="char-ref-section__list">
      <view
        v-for="char in characters"
        :key="char.name"
        class="char-ref-section__char-item"
      >
        <view class="char-ref-section__char-header">
          <text class="char-ref-section__char-name">{{ char.name }}</text>
          <view class="char-ref-section__char-actions">
            <text class="char-ref-section__action-btn" @tap="handleUpload(char.name)">上传</text>
            <text
              class="char-ref-section__action-btn"
              :class="{ 'char-ref-section__action-btn--disabled': generatingChar === char.name }"
              @tap="handleGenerate(char.name)"
            >
              {{ generatingChar === char.name ? '生成中...' : 'AI 生成' }}
            </text>
          </view>
        </view>

        <!-- 参考图预览 -->
        <view v-if="charRefMap[char.name]" class="char-ref-section__ref-preview">
          <image
            :src="charRefMap[char.name].image_path"
            class="char-ref-section__ref-image"
            mode="aspectFill"
          />
          <view class="char-ref-section__ref-overlay">
            <text class="char-ref-section__ref-action" @tap="handleDelete(char.name)">删除</text>
          </view>
        </view>
        <view v-else class="char-ref-section__no-ref">
          <text>还没有该角色的参考图</text>
        </view>
      </view>
    </view>

    <!-- 批量生成按钮 -->
    <lv-button
      v-if="characters.length > 0"
      block
      outline
      size="sm"
      :loading="generatingAll"
      @tap="handleGenerateAll"
    >
      {{ generatingAll ? '批量生成中...' : '为所有角色生成参考图' }}
    </lv-button>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { mangaApi } from '@/api'
import { useImagePicker } from '@/composables/useImagePicker'
import { useSSE } from '@/composables/useSSE'

interface CharacterRef {
  filename: string
  image_path: string
  size_kb?: number
  label?: string
  kind?: string
  character_name?: string
}

const props = defineProps<{
  storyId: number
}>()

const imagePicker = useImagePicker()
const sse = useSSE()

const characters = ref<{ name: string }[]>([])
const charRefMap = ref<Record<string, CharacterRef | null>>({})
const loading = ref(true)
const generatingChar = ref('')
const generatingAll = ref(false)

// 解析角色列表和参考图
async function loadData() {
  loading.value = true
  try {
    // 获取角色名称列表
    const charResult = await mangaApi.getStoryCharacters(props.storyId)
    const names = parseCharacterNames(charResult.characters || '')
    characters.value = names.map(name => ({ name }))

    // 获取所有参考图
    const refResult = await mangaApi.getStoryRefImages(props.storyId)
    const refs: CharacterRef[] = (refResult.images || []).map((img: any) => ({
      ...img,
      character_name: img.label || ''
    }))

    // 按角色名建立映射
    const map: Record<string, CharacterRef | null> = {}
    for (const name of names) {
      const found = refs.find(r => r.label === name)
      map[name] = found || null
    }
    charRefMap.value = map
  } catch (e) {
    console.error('加载角色参考图数据失败:', e)
  } finally {
    loading.value = false
  }
}

function parseCharacterNames(text: string): string[] {
  const names: string[] = []
  const lines = text.split('\n')
  for (const line of lines) {
    const match = line.match(/^(.+?)[：:]/)
    if (match) names.push(match[1].trim())
  }
  return names
}

async function handleUpload(charName: string) {
  try {
    const file = await imagePicker.pickImage()
    if (!file) return
    const b64 = await fileToBase64(file)
    const result = await mangaApi.uploadChapterRefImage(props.storyId, b64) // 先复用章节级上传
    // 实际应使用 uploadCharacterRefImage API
    if (result.images) {
      const matched = result.images.find((img: any) => img.label === charName)
      if (matched) {
        charRefMap.value = { ...charRefMap.value, [charName]: { ...matched, character_name: charName } }
      }
    }
  } catch (e: any) {
    uni.showToast({ title: e.message || '上传失败', icon: 'none' })
  }
}

async function handleGenerate(charName: string) {
  generatingChar.value = charName
  // 使用 SSE 流式生成角色参考图
  const token = uni.getStorageSync('auth_token')
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`

  sse.start({
    url: mangaApi.characterRefImagesUrl(props.storyId),
    headers,
    body: { character_name: charName, overwrite: !!charRefMap.value[charName] },
    onEvent: (event) => {
      if (event.type === 'image' || event.type === 'done') {
        loadData() // 完成后重新加载
      }
    },
    onComplete: () => {
      generatingChar.value = ''
    }
  })
}

async function handleGenerateAll() {
  generatingAll.value = true
  const token = uni.getStorageSync('auth_token')
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`

  sse.start({
    url: mangaApi.characterRefImagesUrl(props.storyId),
    headers,
    body: { overwrite: false },
    onEvent: (event) => {
      if (event.type === 'done') loadData()
    },
    onComplete: () => {
      generatingAll.value = false
    }
  })
}

async function handleDelete(charName: string) {
  const ref = charRefMap.value[charName]
  if (!ref) return
  try {
    await mangaApi.deleteChapterRefImage(props.storyId, ref.filename)
    charRefMap.value = { ...charRefMap.value, [charName]: null }
    uni.showToast({ title: '已删除', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '删除失败', icon: 'none' })
  }
}

function fileToBase64(file: any): Promise<string> {
  return new Promise((resolve, reject) => {
    uni.getFileSystemManager().readFile({
      filePath: file.path || file.tempFilePath,
      encoding: 'base64',
      success: (res) => resolve(res.data as string),
      fail: reject
    })
  })
}

onMounted(() => {
  loadData()
})

// 当 storyId 变化时重新加载
watch(() => props.storyId, () => loadData())
</script>

<style lang="scss" scoped>
.char-ref-section {
  &__title {
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
    display: block;
    margin-bottom: 16rpx;
  }

  &__loading, &__empty {
    padding: 32rpx;
    text-align: center;
    color: $lv-text-muted;
  }

  &__char-item {
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
    padding: 16rpx;
    margin-bottom: 12rpx;
    border: 1rpx solid $lv-border;
  }

  &__char-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12rpx;
  }

  &__char-name {
    font-size: $lv-font-sm;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__char-actions {
    display: flex;
    gap: 12rpx;
  }

  &__action-btn {
    font-size: $lv-font-xs;
    color: $lv-primary;
    padding: 4rpx 12rpx;
    border-radius: $lv-radius-full;
    background: $lv-primary-light;

    &--disabled {
      opacity: 0.5;
    }
  }

  &__ref-preview {
    position: relative;
    border-radius: $lv-radius-sm;
    overflow: hidden;
  }

  &__ref-image {
    width: 100%;
    height: 200rpx;
    object-fit: cover;
  }

  &__ref-overlay {
    position: absolute;
    top: 8rpx;
    right: 8rpx;
    display: flex;
    gap: 8rpx;
  }

  &__ref-action {
    font-size: 20rpx;
    color: #fff;
    background: rgba(0, 0, 0, 0.5);
    padding: 4rpx 12rpx;
    border-radius: $lv-radius-full;
  }

  &__no-ref {
    padding: 24rpx;
    text-align: center;
    color: $lv-text-muted;
    font-size: $lv-font-xs;
    background: $lv-bg-start;
    border-radius: $lv-radius-sm;
    border: 1rpx dashed $lv-border;
  }
}
</style>
```

- [ ] **Step 2: 验证**

```bash
npm run type-check
```

---

### Task C2: 集成角色参考图到 manga.vue

**Files:**
- Modify: `storycanvas-mobile/src/pages/workspace/manga.vue`

- [ ] **Step 1: 在图片网格和底部工具按钮之间插入**

```vue
<CharacterRefSection
  v-if="chapterId && mangaStore.characterProfiles"
  :story-id="storyId"
  class="manga-page__char-ref"
/>
```

注：需要获取 `storyId` — 当前 manga.vue 只有 `chapterId`，需要在路由参数中传递或通过 API 获取。

- [ ] **Step 2: 导入组件**

```typescript
import CharacterRefSection from '@/components/character-ref-section/character-ref-section.vue'
```

- [ ] **Step 3: 验证**

```bash
npm run type-check
```

---

### Task C3: 集成角色参考图到 chapter-view.vue

**Files:**
- Modify: `storycanvas-mobile/src/pages/workspace/chapter-view.vue`

- [ ] **Step 1: 在 manga tab 底部添加**

```vue
<CharacterRefSection
  v-if="workspaceStore.activeChapter?.story_id"
  :story-id="workspaceStore.activeChapter.story_id"
  class="chapter-view__char-ref"
/>
```

- [ ] **Step 2: 导入**

```typescript
import CharacterRefSection from '@/components/character-ref-section/character-ref-section.vue'
```

- [ ] **Step 3: 验证**

```bash
npm run type-check
```

---

## 子项目 B：分镜脚本编辑

### Task B1: manga.vue 分镜行内编辑

**Files:**
- Modify: `storycanvas-mobile/src/pages/workspace/manga.vue`

- [ ] **Step 1: 替换分镜展示为可编辑模式**

当前分镜展示是只读的：
```vue
<view v-for="(scene, i) in mangaStore.scenes" :key="i" class="manga-page__scene-item">
  <text class="manga-page__scene-num">{{ i + 1 }}.</text>
  <text class="manga-page__scene-text">{{ scene }}</text>
</view>
```

改为：
```vue
<view v-for="(scene, i) in mangaStore.scenes" :key="i" class="manga-page__scene-item">
  <text class="manga-page__scene-num">{{ i + 1 }}.</text>
  <view v-if="editingIdx === i" class="manga-page__scene-edit-area">
    <textarea
      v-model="editText"
      class="manga-page__scene-textarea"
      :auto-height="true"
    />
    <view class="manga-page__scene-edit-actions">
      <lv-button size="xs" @tap="handleSaveScene(i)">保存</lv-button>
      <lv-button size="xs" secondary @tap="handleCancelEdit">取消</lv-button>
    </view>
  </view>
  <view v-else class="manga-page__scene-display">
    <text class="manga-page__scene-text">{{ scene }}</text>
    <text class="manga-page__scene-edit-btn" @tap="handleStartEdit(i, scene)">✏️</text>
  </view>
</view>
```

- [ ] **Step 2: 添加 script 逻辑**

```typescript
const editingIdx = ref(-1)
const editText = ref('')

function handleStartEdit(idx: number, text: string) {
  editingIdx.value = idx
  editText.value = text
}

function handleCancelEdit() {
  editingIdx.value = -1
  editText.value = ''
}

function handleSaveScene(idx: number) {
  const newScenes = [...mangaStore.scenes]
  newScenes[idx] = editText.value
  mangaStore.scenes = newScenes // 立即更新本地
  editingIdx.value = -1
  editText.value = ''
}

// 批量保存按钮
async function handleSaveAllScenes() {
  if (!chapterId) return
  await mangaStore.updateScenes(chapterId, mangaStore.scenes)
  uni.showToast({ title: '已保存', icon: 'success' })
}
```

- [ ] **Step 3: 在场景列表上方添加保存按钮**

```vue
<view class="manga-page__scene-toolbar">
  <text class="manga-page__section-title">分镜脚本 ({{ mangaStore.scenes.length }})</text>
  <lv-button v-if="mangaStore.scenes.length > 0" size="xs" @tap="handleSaveAllScenes">保存修改</lv-button>
</view>
```

- [ ] **Step 4: 添加降敏标记**

在场景文本旁显示降敏标签：
```vue
<span v-if="mangaStore.sanitizedIndices.includes(i)" class="manga-page__sanitized-badge">已自动降敏</span>
```

- [ ] **Step 5: 添加 CSS**

```scss
&__scene-display {
  flex: 1;
  display: flex;
  align-items: flex-start;
  gap: 8rpx;
}

&__scene-edit-btn {
  font-size: 28rpx;
  padding: 4rpx;
  opacity: 0.5;
}

&__scene-edit-area {
  flex: 1;
}

&__scene-textarea {
  width: 100%;
  min-height: 100rpx;
  padding: 12rpx;
  font-size: $lv-font-sm;
  border: 1rpx solid $lv-primary;
  border-radius: $lv-radius-sm;
  background: $lv-surface-solid;
}

&__scene-edit-actions {
  display: flex;
  gap: 12rpx;
  margin-top: 8rpx;
}

&__scene-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16rpx;
}

&__sanitized-badge {
  font-size: 20rpx;
  color: $lv-warning;
  background: #fff3cd;
  padding: 2rpx 8rpx;
  border-radius: $lv-radius-full;
  margin-left: 8rpx;
  white-space: nowrap;
}
```

- [ ] **Step 6: 验证**

```bash
npm run type-check
```

---

### Task B2: chapter-view.vue 分镜行内编辑

**Files:**
- Modify: `storycanvas-mobile/src/pages/workspace/chapter-view.vue`

- [ ] **Step 1: 应用与 Task B1 相同的分镜编辑改造**

复用 Task B1 的模式：替换 chapter-view.vue 中 `#tab-2` 下的场景列表为可编辑模式。添加 editingIdx、editText、save 函数。

- [ ] **Step 2: 验证**

```bash
npm run type-check
```

---

## 子项目 D：ImageRedrawModal 重绘弹窗

### Task D1: 创建 ImageRedrawModal 组件

**Files:**
- Create: `storycanvas-mobile/src/components/image-redraw-modal/image-redraw-modal.vue`

- [ ] **Step 1: 创建组件**

```vue
<template>
  <view class="redraw-overlay" @tap.self="handleClose">
    <view class="redraw-modal">
      <view class="redraw-modal__header">
        <text class="redraw-modal__title">{{ title }}</text>
        <text class="redraw-modal__close" @tap="handleClose">关闭</text>
      </view>

      <!-- 原图预览 -->
      <image
        v-if="imageSrc"
        :src="imageSrc"
        class="redraw-modal__image"
        mode="widthFix"
      />

      <!-- 提示词编辑 -->
      <view class="redraw-modal__prompt-section">
        <text class="redraw-modal__label">提示词</text>
        <textarea
          v-model="editPrompt"
          class="redraw-modal__textarea"
          :auto-height="true"
          placeholder="输入图片描述..."
        />
      </view>

      <!-- 模式选择 -->
      <view class="redraw-modal__mode-section">
        <text class="redraw-modal__label">模式</text>
        <view class="redraw-modal__mode-options">
          <text
            v-for="mode in modeOptions"
            :key="mode.value"
            class="redraw-modal__mode-btn"
            :class="{ 'redraw-modal__mode-btn--active': selectedMode === mode.value }"
            @tap="selectedMode = mode.value"
          >
            {{ mode.label }}
          </text>
        </view>
        <text v-if="selectedMode === 'inpaint'" class="redraw-modal__mode-hint">
          局部重绘在移动端暂不支持画笔涂抹，将使用整图重绘方式处理
        </text>
      </view>

      <view class="redraw-modal__footer">
        <lv-button :loading="busy" block @tap="handleSubmit">
          {{ busy ? '处理中...' : '确认重绘' }}
        </lv-button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  imageSrc: string
  title: string
  prompt: string
  busy: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'submit', payload: { prompt: string; mode: string }): void
}>()

const editPrompt = ref(props.prompt)
const selectedMode = ref('regenerate')

const modeOptions = [
  { label: '整图重绘', value: 'regenerate' },
  { label: '局部重绘', value: 'inpaint' },
]

function handleSubmit() {
  emit('submit', { prompt: editPrompt.value, mode: selectedMode.value })
}

function handleClose() {
  emit('close')
}
</script>

<style lang="scss" scoped>
.redraw-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  z-index: 1000;
  display: flex;
  align-items: flex-end;
}

.redraw-modal {
  width: 100%;
  max-height: 85vh;
  background: $lv-surface-solid;
  border-radius: $lv-radius-lg $lv-radius-lg 0 0;
  display: flex;
  flex-direction: column;
  padding: $lv-page-padding;

  &__header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16rpx;
  }

  &__title {
    font-size: $lv-font-lg;
    font-weight: 600;
  }

  &__close {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
    padding: 8rpx;
  }

  &__image {
    width: 100%;
    border-radius: $lv-radius-md;
    max-height: 400rpx;
    object-fit: contain;
    background: #000;
    margin-bottom: 16rpx;
  }

  &__label {
    font-size: $lv-font-sm;
    font-weight: 600;
    color: $lv-text-primary;
    display: block;
    margin-bottom: 8rpx;
  }

  &__textarea {
    width: 100%;
    min-height: 120rpx;
    padding: 12rpx;
    font-size: $lv-font-sm;
    border: 1rpx solid $lv-border;
    border-radius: $lv-radius-sm;
    margin-bottom: 16rpx;
  }

  &__mode-section {
    margin-bottom: 16rpx;
  }

  &__mode-options {
    display: flex;
    gap: 12rpx;
  }

  &__mode-btn {
    padding: 8rpx 24rpx;
    font-size: $lv-font-sm;
    border-radius: $lv-radius-full;
    border: 1rpx solid $lv-border;
    color: $lv-text-secondary;

    &--active {
      background: $lv-primary;
      color: #fff;
      border-color: $lv-primary;
    }
  }

  &__mode-hint {
    display: block;
    font-size: 20rpx;
    color: $lv-text-muted;
    margin-top: 8rpx;
  }

  &__footer {
    padding-top: 16rpx;
  }
}
</style>
```

- [ ] **Step 2: 验证**

```bash
npm run type-check
```

---

### Task D2: 集成到 manga-gallery.vue

**Files:**
- Modify: `storycanvas-mobile/src/pages/workspace/manga-gallery.vue`

- [ ] **Step 1: 在 gallery 页面添加重绘弹窗和功能**

在 gallery 页面添加状态和弹窗：

```vue
<lv-button @tap="handleOpenRedraw">重绘</lv-button>

<ImageRedrawModal
  v-if="showRedraw"
  :image-src="currentImageUrl"
  :title="`重绘第 ${currentImageNumber} 张`"
  :prompt="currentPrompt"
  :busy="redrawBusy"
  @close="showRedraw = false"
  @submit="handleRedrawSubmit"
/>
```

```typescript
import ImageRedrawModal from '@/components/image-redraw-modal/image-redraw-modal.vue'
import { mangaApi } from '@/api'
import { mangaImageUrl } from '@/utils/url'

const showRedraw = ref(false)
const redrawBusy = ref(false)

function handleOpenRedraw() {
  showRedraw.value = true
}

async function handleRedrawSubmit(payload: { prompt: string; mode: string }) {
  if (!chapterId || !currentImageNumber) return
  redrawBusy.value = true
  try {
    await mangaApi.regenerateImage(chapterId, currentImageNumber, payload.prompt, payload.mode)
    uni.showToast({ title: '重绘完成', icon: 'success' })
    showRedraw.value = false
    // 重新加载图片
    await loadImages()
  } catch (e: any) {
    uni.showToast({ title: e.message || '重绘失败', icon: 'none' })
  } finally {
    redrawBusy.value = false
  }
}
```

- [ ] **Step 2: 验证**

```bash
npm run type-check
```

---

### Task D3: 集成到 manga.vue（图片点击弹重绘）

**Files:**
- Modify: `storycanvas-mobile/src/pages/workspace/manga.vue`

- [ ] **Step 1: 在模板底部添加重绘弹窗**

```vue
<ImageRedrawModal
  v-if="showRedraw"
  :image-src="redrawImageSrc"
  :title="redrawTitle"
  :prompt="redrawPrompt"
  :busy="redrawBusy"
  @close="showRedraw = false"
  @submit="handleRedrawSubmit"
/>
```

- [ ] **Step 2: 添加 script**

```typescript
import ImageRedrawModal from '@/components/image-redraw-modal/image-redraw-modal.vue'

const showRedraw = ref(false)
const redrawImageSrc = ref('')
const redrawTitle = ref('')
const redrawPrompt = ref('')
const redrawImageNumber = ref(0)
const redrawBusy = ref(false)

function handleImageRedraw(img: MangaImage) {
  redrawImageSrc.value = mangaImageUrl(img.image_path)
  redrawImageNumber.value = img.image_number
  const scene = mangaStore.scenes[img.image_number - 1] || ''
  redrawTitle.value = `第 ${img.image_number} 张图片重绘`
  redrawPrompt.value = scene
  showRedraw.value = true
}

async function handleRedrawSubmit(payload: { prompt: string; mode: string }) {
  redrawBusy.value = true
  try {
    await mangaStore.regenerateImage(chapterId, redrawImageNumber.value, payload.prompt, payload.mode)
    uni.showToast({ title: '重绘完成', icon: 'success' })
    showRedraw.value = false
    await mangaStore.loadImages(chapterId)
  } catch (e: any) {
    uni.showToast({ title: e.message || '重绘失败', icon: 'none' })
  } finally {
    redrawBusy.value = false
  }
}
```

更新 `manga-image-card` 点击事件，不是直接导航到 gallery，而是先打开重绘弹窗：

```vue
<manga-image-card
  v-for="img in mangaStore.images"
  :key="img.id"
  :image-path="img.image_path"
  :image-number="img.image_number"
  @tap="handleImageRedraw(img)"
/>
```

- [ ] **Step 3: 验证**

```bash
npm run type-check
```

---

## 自检清单

- [ ] 1. **Spec 覆盖**: 所有 spec 中的功能被任务覆盖：
  - A1-A6 → 比例选择 + 风格预设
  - C1-C3 → 角色参考图独立管理
  - B1-B2 → 分镜脚本编辑
  - D1-D3 → ImageRedrawModal
- [ ] 2. **无占位符**: 所有任务包含完整代码
- [ ] 3. **类型一致性**: `regenerateImage` 签名在 Task A2 更新，与后续引用一致；store 导出在 Task A1 更新
