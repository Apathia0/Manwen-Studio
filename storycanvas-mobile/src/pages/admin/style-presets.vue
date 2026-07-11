<template>
  <view class="admin-style-presets">
    <!-- 头部 -->
    <view class="admin-style-presets__header">
      <text class="admin-style-presets__title">风格预设</text>
      <lv-button size="sm" @tap="openCreateModal">新建预设</lv-button>
    </view>

    <!-- 分类筛选 -->
    <scroll-view scroll-x class="admin-style-presets__filter" v-if="!loading && presets.length > 0">
      <view class="admin-style-presets__filter-inner">
        <view
          v-for="cat in categories"
          :key="cat.value"
          class="admin-style-presets__filter-chip"
          :class="{ 'admin-style-presets__filter-chip--active': selectedCategory === cat.value }"
          @tap="selectedCategory = cat.value"
        >
          <text>{{ cat.label }}</text>
        </view>
      </view>
    </scroll-view>

    <lv-loading v-if="loading" />

    <lv-empty v-else-if="filteredPresets.length === 0" title="暂无风格预设" />

    <view v-else class="admin-style-presets__grid">
      <view
        v-for="preset in filteredPresets"
        :key="preset.id"
        class="admin-style-presets__card"
        @tap="openEditModal(preset)"
      >
        <image
          v-if="preset.image_url"
          :src="mangaImageUrl(preset.image_url)"
          class="admin-style-presets__card-image"
          mode="aspectFill"
        />
        <view v-else class="admin-style-presets__card-image-placeholder">
          <lv-icon name="ImagePlus" :size="32" color="#94a3b8" />
        </view>
        <view class="admin-style-presets__card-info">
          <text class="admin-style-presets__card-name">{{ preset.name }}</text>
          <text class="admin-style-presets__card-category">{{ preset.category }} · 排序: {{ preset.sort_order }}</text>
        </view>
      </view>
    </view>

    <!-- 新建/编辑弹窗 -->
    <lv-modal
      :visible="showForm"
      :title="editingId ? '编辑预设' : '新建预设'"
      @update:visible="showForm = $event"
      :show-footer="false"
      :mask-closable="false"
    >
      <view class="admin-style-presets__form">
        <lv-input v-model="form.name" label="预设名称" placeholder="输入名称" />
        <lv-input v-model="form.category" label="分类" placeholder="如 realistic, anime" />
        <lv-input v-model="form.prompt_template" label="提示词模板" placeholder="可选的 prompt 模板" type="textarea" />

        <view class="admin-style-presets__form-section">
          <text class="admin-style-presets__form-label">预设图片</text>
          <view v-if="form.image_url" class="admin-style-presets__image-preview" @tap="chooseImage">
            <image :src="mangaImageUrl(form.image_url)" mode="aspectFill" class="admin-style-presets__image-preview-img" />
            <view class="admin-style-presets__image-overlay">
              <lv-icon name="ImagePlus" :size="18" color="#fff" />
              <text class="admin-style-presets__image-overlay-text">替换图片</text>
            </view>
          </view>
          <view v-else class="admin-style-presets__image-upload" @tap="chooseImage">
            <lv-icon name="ImagePlus" :size="24" color="#94a3b8" />
            <text class="admin-style-presets__image-upload-text">点击上传图片</text>
          </view>
        </view>

        <lv-input v-model="form.sort_order" label="排序" placeholder="0" type="number" />
        <lv-input v-model="form.image_style_params" label="图片风格参数 (JSON)" placeholder='{"style": "vibrant"}' type="textarea" />
        <lv-input v-model="form.video_style_params" label="视频风格参数 (JSON)" placeholder='{"motion": "smooth"}' type="textarea" />

        <view class="admin-style-presets__form-actions">
          <lv-button secondary @tap="cancelForm">取消</lv-button>
          <lv-button :loading="saving" @tap="handleSave">保存</lv-button>
        </view>

        <!-- 删除按钮（编辑时显示） -->
        <view v-if="editingId" class="admin-style-presets__delete-section">
          <lv-button type="danger" :loading="deleting" block @tap="handleDelete">删除此预设</lv-button>
        </view>
      </view>
    </lv-modal>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { adminApi } from '@/api'
import type { VideoStylePreset } from '@/api/admin'
import { uploadAsset } from '@/utils/upload'
import { mangaImageUrl } from '@/utils/url'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvInput from '@/components/lv-input/lv-input.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import LvModal from '@/components/lv-modal/lv-modal.vue'

const loading = ref(false)
const presets = ref<VideoStylePreset[]>([])
const showForm = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const deleting = ref(false)
const uploading = ref(false)

// 分类筛选
const categories = [
  { label: '全部', value: 'all' },
  { label: '写实', value: 'realistic' },
  { label: '动漫', value: 'anime' },
  { label: '艺术', value: 'artistic' },
  { label: '游戏', value: 'game' },
  { label: '电影', value: 'cinematic' },
]
const selectedCategory = ref('all')

const filteredPresets = computed(() => {
  if (selectedCategory.value === 'all') return presets.value
  return presets.value.filter(p => p.category === selectedCategory.value)
})

const form = ref({
  name: '',
  category: 'realistic',
  image_url: '',
  prompt_template: '',
  image_style_params: '',
  video_style_params: '',
  sort_order: '0',
})

onMounted(async () => {
  await loadPresets()
})

async function loadPresets() {
  loading.value = true
  try {
    const res = await adminApi.listStylePresets()
    presets.value = res.presets
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

function openCreateModal() {
  editingId.value = null
  resetForm()
  showForm.value = true
}

function openEditModal(preset: VideoStylePreset) {
  editingId.value = preset.id
  form.value = {
    name: preset.name,
    category: preset.category,
    image_url: preset.image_url || '',
    prompt_template: preset.prompt_template || '',
    image_style_params: preset.image_style_params ? JSON.stringify(preset.image_style_params, null, 2) : '',
    video_style_params: preset.video_style_params ? JSON.stringify(preset.video_style_params, null, 2) : '',
    sort_order: String(preset.sort_order),
  }
  showForm.value = true
}

function resetForm() {
  form.value = {
    name: '',
    category: 'realistic',
    image_url: '',
    prompt_template: '',
    image_style_params: '',
    video_style_params: '',
    sort_order: '0',
  }
}

function cancelForm() {
  showForm.value = false
}

function chooseImage() {
  uni.chooseImage({
    count: 1,
    sizeType: ['compressed'],
    sourceType: ['album', 'camera'],
    success: async (res) => {
      const tempFilePath = res.tempFilePaths[0]
      uploading.value = true
      try {
        const result = await uploadImage(tempFilePath)
        if (result.url) {
          form.value.image_url = result.url
        }
      } catch (e: any) {
        uni.showToast({ title: e.message || '上传失败', icon: 'none' })
      } finally {
        uploading.value = false
      }
    },
  })
}

function uploadImage(filePath: string): Promise<{ success: boolean; url: string }> {
  return uploadAsset({
    url: '/api/video-style-presets/upload-image',
    filePath,
  }).then(res => res.data as { success: boolean; url: string })
}

function parseJSON(str: string): Record<string, unknown> | null {
  if (!str.trim()) return null
  try {
    return JSON.parse(str)
  } catch {
    return null
  }
}

async function handleSave() {
  if (!form.value.name.trim()) {
    uni.showToast({ title: '请输入预设名称', icon: 'none' })
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.value.name.trim(),
      category: form.value.category.trim() || 'realistic',
      image_url: form.value.image_url || null,
      prompt_template: form.value.prompt_template.trim() || undefined,
      image_style_params: parseJSON(form.value.image_style_params) || undefined,
      video_style_params: parseJSON(form.value.video_style_params) || undefined,
      sort_order: parseInt(form.value.sort_order) || 0,
    }
    if (editingId.value) {
      await adminApi.updateStylePreset(editingId.value, payload)
      uni.showToast({ title: '更新成功', icon: 'success' })
    } else {
      await adminApi.createStylePreset(payload)
      uni.showToast({ title: '创建成功', icon: 'success' })
    }
    showForm.value = false
    await loadPresets()
  } catch (e: any) {
    uni.showToast({ title: e.message || '保存失败', icon: 'none' })
  } finally {
    saving.value = false
  }
}

function handleDelete() {
  if (!editingId.value) return
  uni.showModal({
    title: '确认删除',
    content: `确定删除风格预设「${form.value.name}」？`,
    confirmColor: '#be123c',
    success: async (res) => {
      if (res.confirm && editingId.value) {
        deleting.value = true
        try {
          await adminApi.deleteStylePreset(editingId.value)
          showForm.value = false
          uni.showToast({ title: '已删除', icon: 'success' })
          await loadPresets()
        } catch (e: any) {
          uni.showToast({ title: e.message || '删除失败', icon: 'none' })
        } finally {
          deleting.value = false
        }
      }
    },
  })
}
</script>

<style lang="scss" scoped>
.admin-style-presets {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: $lv-page-padding;
    padding-bottom: 0;
  }

  &__title {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__filter {
    white-space: nowrap;
    padding: 20rpx $lv-page-padding;
  }

  &__filter-inner {
    display: inline-flex;
    gap: 12rpx;
  }

  &__filter-chip {
    display: inline-flex;
    align-items: center;
    padding: 10rpx 24rpx;
    border-radius: $lv-radius-xl;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    background: $lv-surface-solid;
    border: 1rpx solid $lv-border;
    transition: all 0.2s;

    &--active {
      color: $lv-text-on-primary;
      background: $lv-primary;
      border-color: $lv-primary;
    }
  }

  &__grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20rpx;
    padding: $lv-page-padding;
  }

  &__card {
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    overflow: hidden;
    box-shadow: $lv-shadow-sm;
    border: 2rpx solid transparent;

    &:active {
      border-color: $lv-primary;
    }
  }

  &__card-image {
    width: 100%;
    height: 200rpx;
    display: block;
  }

  &__card-image-placeholder {
    width: 100%;
    height: 200rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    background: $lv-primary-lighter;
  }

  &__card-info {
    padding: 16rpx;
  }

  &__card-name {
    display: block;
    font-size: $lv-font-sm;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 4rpx;
  }

  &__card-category {
    display: block;
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__form-section {
    margin-bottom: $lv-item-gap;
  }

  &__form-label {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    font-weight: 500;
    margin-bottom: 12rpx;
  }

  &__image-preview {
    position: relative;
    width: 100%;
    height: 200rpx;
    border-radius: $lv-radius-sm;
    overflow: hidden;
  }

  &__image-preview-img {
    width: 100%;
    height: 100%;
  }

  &__image-overlay {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8rpx;
    background: rgba(0, 0, 0, 0.4);
    opacity: 0;
    transition: opacity 0.2s;
  }

  &__image-preview:active &__image-overlay {
    opacity: 1;
  }

  &__image-overlay-text {
    font-size: $lv-font-xs;
    color: #fff;
  }

  &__image-upload {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12rpx;
    height: 200rpx;
    background: $lv-primary-lighter;
    border: 2rpx dashed $lv-border;
    border-radius: $lv-radius-sm;

    &:active {
      background: darken($lv-primary-lighter, 5%);
    }
  }

  &__image-upload-text {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__form-actions {
    display: flex;
    gap: 16rpx;
    margin-top: 20rpx;
  }

  &__delete-section {
    margin-top: 32rpx;
    padding-top: 24rpx;
    border-top: 1rpx solid $lv-border-light;
  }
}
</style>
