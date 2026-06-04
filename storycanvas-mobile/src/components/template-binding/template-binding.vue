<template>
  <view class="template-binding">
    <view class="template-binding__header" @tap="showPicker = !showPicker">
      <view class="template-binding__header-left">
        <lv-icon name="Library" :size="14" color="#64748b" />
        <text class="template-binding__label">提示词模板：</text>
        <text v-if="loading" class="template-binding__loading">加载中...</text>
        <lv-tag
          v-else-if="currentTemplate"
          type="primary"
          :text="currentTemplate.name"
          size="sm"
        />
        <text v-else class="template-binding__default">系统默认</text>
      </view>
      <view class="template-binding__header-right">
        <text class="template-binding__toggle">{{ showPicker ? '收起' : '选择' }}</text>
      </view>
    </view>

    <!-- 解绑按钮 -->
    <view v-if="currentTemplate && !showPicker" class="template-binding__unbind" @tap="handleUnbind">
      <text class="template-binding__unbind-text">恢复默认模板</text>
    </view>

    <!-- 模板选择器 -->
    <view v-if="showPicker" class="template-binding__picker">
      <!-- 我的模板 -->
      <text class="template-binding__section-title">我的模板</text>
      <view v-if="myTemplates.length === 0" class="template-binding__empty">
        <text class="template-binding__empty-text">暂无自定义模板</text>
      </view>
      <view
        v-for="tpl in myTemplates"
        :key="tpl.id"
        class="template-binding__item"
        @tap="handleSelect(tpl)"
      >
        <text class="template-binding__item-name">{{ tpl.name }}</text>
        <lv-tag v-if="tpl.category" type="default" :text="tpl.category" size="sm" />
      </view>

      <!-- 公开模板 -->
      <text class="template-binding__section-title">公开模板</text>
      <view v-if="marketTemplates.length === 0" class="template-binding__empty">
        <text class="template-binding__empty-text">暂无公开模板</text>
      </view>
      <view
        v-for="tpl in marketTemplates"
        :key="tpl.id"
        class="template-binding__item"
        @tap="handleSelect(tpl)"
      >
        <text class="template-binding__item-name">{{ tpl.name }}</text>
        <text class="template-binding__item-author">@{{ tpl.author?.username || '未知' }}</text>
        <lv-tag v-if="tpl.visibility === 'official'" type="primary" text="官方" size="sm" />
      </view>

      <!-- 管理模板入口 -->
      <view class="template-binding__manage" @tap="goManageTemplates">
        <lv-icon name="Settings" :size="14" color="#2563eb" />
        <text class="template-binding__manage-text">管理我的模板</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { templatesApi } from '@/api'
import type { PromptTemplateItem } from '@/api/templates'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import LvTag from '@/components/lv-tag/lv-tag.vue'

const props = defineProps<{
  storyId: number
}>()

const emit = defineEmits<{
  bound: [template: PromptTemplateItem | null]
}>()

const loading = ref(false)
const showPicker = ref(false)
const currentTemplate = ref<PromptTemplateItem | null>(null)
const myTemplates = ref<PromptTemplateItem[]>([])
const marketTemplates = ref<PromptTemplateItem[]>([])

async function loadCurrent() {
  loading.value = true
  try {
    const res = await templatesApi.getStoryTemplate(props.storyId)
    currentTemplate.value = res.template
  } catch {
    // 忽略
  } finally {
    loading.value = false
  }
}

async function loadTemplates() {
  try {
    const [my, market] = await Promise.all([
      templatesApi.listMyTemplates({ page_size: 100 }),
      templatesApi.listPublicTemplates({ page_size: 100, sort: 'popular' }),
    ])
    myTemplates.value = my.templates
    marketTemplates.value = market.templates
  } catch {
    // 忽略
  }
}

watch(() => props.storyId, () => {
  loadCurrent()
})

onMounted(() => {
  loadCurrent()
})

watch(showPicker, (val) => {
  if (val) loadTemplates()
})

async function handleSelect(tpl: PromptTemplateItem) {
  try {
    await templatesApi.bindStoryTemplate(props.storyId, tpl.id)
    currentTemplate.value = tpl
    showPicker.value = false
    emit('bound', tpl)
    uni.showToast({ title: '已绑定模板', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '绑定失败', icon: 'none' })
  }
}

async function handleUnbind() {
  try {
    await templatesApi.unbindStoryTemplate(props.storyId)
    currentTemplate.value = null
    emit('bound', null)
    uni.showToast({ title: '已恢复默认', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '操作失败', icon: 'none' })
  }
}

function goManageTemplates() {
  uni.navigateTo({ url: '/pages/templates/index' })
}
</script>

<style lang="scss" scoped>
.template-binding {
  background: $lv-surface-solid;
  border-radius: $lv-radius-md;
  margin-bottom: 24rpx;
  overflow: hidden;

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 20rpx 24rpx;

    &:active {
      background: $lv-primary-lighter;
    }
  }

  &__header-left {
    display: flex;
    align-items: center;
    gap: 8rpx;
    flex: 1;
    min-width: 0;
  }

  &__header-right {
    flex-shrink: 0;
    margin-left: 16rpx;
  }

  &__label {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    flex-shrink: 0;
  }

  &__loading {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__default {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__toggle {
    font-size: $lv-font-xs;
    color: $lv-primary;
  }

  &__unbind {
    padding: 0 24rpx 16rpx;
  }

  &__unbind-text {
    font-size: $lv-font-xs;
    color: $lv-error;
  }

  &__picker {
    padding: 0 24rpx 24rpx;
    border-top: 1rpx solid $lv-border-light;
  }

  &__section-title {
    display: block;
    font-size: $lv-font-xs;
    font-weight: 600;
    color: $lv-text-secondary;
    margin-top: 16rpx;
    margin-bottom: 8rpx;
  }

  &__empty {
    padding: 16rpx 0;
  }

  &__empty-text {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__item {
    display: flex;
    align-items: center;
    gap: 12rpx;
    padding: 16rpx 12rpx;
    border-radius: $lv-radius-sm;

    &:active {
      background: $lv-primary-lighter;
    }
  }

  &__item-name {
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__item-author {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    flex-shrink: 0;
  }

  &__manage {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8rpx;
    padding: 20rpx;
    margin-top: 12rpx;
    border-top: 1rpx solid $lv-border-light;

    &:active {
      background: $lv-primary-lighter;
    }
  }

  &__manage-text {
    font-size: $lv-font-xs;
    color: $lv-primary;
  }
}
</style>
