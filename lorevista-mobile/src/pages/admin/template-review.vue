<template>
  <view class="admin-template-review">
    <view class="admin-template-review__content">
      <view class="admin-template-review__header">
        <text class="admin-template-review__count">共 {{ templates.length }} 个待审核</text>
        <lv-button size="sm" secondary @tap="loadTemplates">刷新</lv-button>
      </view>

      <lv-loading v-if="loading" />

      <view v-else-if="templates.length === 0" class="admin-template-review__empty">
        <lv-empty title="暂无待审核的模板" />
      </view>

      <view v-else class="admin-template-review__list">
        <view v-for="tpl in templates" :key="tpl.id" class="admin-template-review__item">
          <view class="admin-template-review__item-header">
            <text class="admin-template-review__item-name">{{ tpl.name }}</text>
            <lv-tag type="warning" text="待审核" size="sm" />
          </view>
          <view class="admin-template-review__item-meta">
            <text v-if="tpl.author" class="admin-template-review__item-author">{{ tpl.author.username }}</text>
            <text v-if="tpl.category" class="admin-template-review__item-category">{{ tpl.category }}</text>
            <text class="admin-template-review__item-time">{{ tpl.submitted_at || tpl.created_at }}</text>
          </view>
          <text class="admin-template-review__item-desc">{{ tpl.description || '无描述' }}</text>

          <!-- 提示词内容 -->
          <view class="admin-template-review__prompts">
            <view
              class="admin-template-review__prompts-toggle"
              @tap="togglePromptExpand(tpl.id)"
            >
              <lv-icon :name="expandedPrompts.has(tpl.id) ? 'ChevronUp' : 'ChevronDown'" :size="14" color="#94a3b8" />
              <text class="admin-template-review__prompts-toggle-text">查看提示词内容</text>
            </view>
            <view v-if="expandedPrompts.has(tpl.id)" class="admin-template-review__prompts-content">
              <view v-if="tpl.framework_prompt" class="admin-template-review__prompt-section">
                <text class="admin-template-review__prompt-label">框架生成</text>
                <text class="admin-template-review__prompt-text">{{ tpl.framework_prompt }}</text>
              </view>
              <view v-if="tpl.chapter_prompt" class="admin-template-review__prompt-section">
                <text class="admin-template-review__prompt-label">正文扩写</text>
                <text class="admin-template-review__prompt-text">{{ tpl.chapter_prompt }}</text>
              </view>
              <view v-if="tpl.character_prompt" class="admin-template-review__prompt-section">
                <text class="admin-template-review__prompt-label">角色生成</text>
                <text class="admin-template-review__prompt-text">{{ tpl.character_prompt }}</text>
              </view>
              <view v-if="tpl.manga_style_prompt" class="admin-template-review__prompt-section">
                <text class="admin-template-review__prompt-label">漫画风格</text>
                <text class="admin-template-review__prompt-text">{{ tpl.manga_style_prompt }}</text>
              </view>
            </view>
          </view>

          <!-- 审核备注 -->
          <lv-input
            v-model="reviewNotes[tpl.id]"
            placeholder="审核备注（拒绝时必填）"
            size="sm"
          />

          <!-- 操作按钮 -->
          <view class="admin-template-review__item-actions">
            <lv-button size="sm" @tap="handleApprove(tpl, 'public')">通过</lv-button>
            <lv-button size="sm" @tap="handleApprove(tpl, 'official')">通过并推荐</lv-button>
            <lv-button size="sm" type="danger" @tap="handleReject(tpl)">拒绝</lv-button>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { adminApi } from '@/api'
import type { PromptTemplateItem } from '@/api/admin'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvTag from '@/components/lv-tag/lv-tag.vue'
import LvInput from '@/components/lv-input/lv-input.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'

const loading = ref(false)
const templates = ref<PromptTemplateItem[]>([])
const reviewNotes = ref<Record<number, string>>({})
const expandedPrompts = ref(new Set<number>())

onMounted(() => loadTemplates())

async function loadTemplates() {
  loading.value = true
  try {
    const res = await adminApi.listPendingTemplates()
    templates.value = res.templates
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

function togglePromptExpand(id: number) {
  if (expandedPrompts.value.has(id)) {
    expandedPrompts.value.delete(id)
  } else {
    expandedPrompts.value.add(id)
  }
}

async function handleApprove(tpl: PromptTemplateItem, visibility: string) {
  try {
    await adminApi.approveTemplate(tpl.id, visibility, reviewNotes.value[tpl.id])
    uni.showToast({ title: '已通过', icon: 'success' })
    await loadTemplates()
  } catch (e: any) {
    uni.showToast({ title: e.message || '操作失败', icon: 'none' })
  }
}

async function handleReject(tpl: PromptTemplateItem) {
  const note = reviewNotes.value[tpl.id]
  if (!note?.trim()) {
    uni.showToast({ title: '请填写拒绝原因', icon: 'none' })
    return
  }
  try {
    await adminApi.rejectTemplate(tpl.id, note)
    uni.showToast({ title: '已拒绝', icon: 'success' })
    await loadTemplates()
  } catch (e: any) {
    uni.showToast({ title: e.message || '操作失败', icon: 'none' })
  }
}
</script>

<style lang="scss" scoped>
.admin-template-review {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx) $lv-page-padding $lv-page-padding;
  }

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 20rpx;
  }

  &__count {
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__list {
    display: flex;
    flex-direction: column;
    gap: 20rpx;
  }

  &__item {
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: 24rpx;
    box-shadow: $lv-shadow-sm;
  }

  &__item-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12rpx;
  }

  &__item-name {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__item-meta {
    display: flex;
    gap: 16rpx;
    margin-bottom: 8rpx;
    flex-wrap: wrap;
  }

  &__item-author {
    font-size: $lv-font-xs;
    color: $lv-text-secondary;
  }

  &__item-category {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__item-time {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__item-desc {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    margin-bottom: 16rpx;
  }

  &__prompts {
    margin-bottom: 16rpx;
  }

  &__prompts-toggle {
    display: flex;
    align-items: center;
    gap: 8rpx;
    padding: 8rpx 0;
  }

  &__prompts-toggle-text {
    font-size: $lv-font-xs;
    color: $lv-primary;
  }

  &__prompts-content {
    background: $lv-primary-lighter;
    border-radius: $lv-radius-md;
    padding: 16rpx;
    max-height: 400rpx;
    overflow: auto;
  }

  &__prompt-section {
    margin-bottom: 16rpx;

    &:last-child {
      margin-bottom: 0;
    }
  }

  &__prompt-label {
    display: block;
    font-size: $lv-font-xs;
    font-weight: 600;
    color: $lv-text-secondary;
    margin-bottom: 8rpx;
  }

  &__prompt-text {
    display: block;
    font-size: $lv-font-xs;
    color: $lv-text-secondary;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-all;
  }

  &__item-actions {
    display: flex;
    gap: 12rpx;
    margin-top: 16rpx;
    border-top: 1rpx solid $lv-border-light;
    padding-top: 16rpx;
  }

  &__empty {
    padding: 60rpx 0;
  }
}
</style>
