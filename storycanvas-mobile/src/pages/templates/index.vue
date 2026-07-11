<template>
  <view class="template-page">
    <lv-navbar title="模板广场" />

    <view class="template-page__content">
      <!-- Tab 切换 -->
      <lv-swiper-tabs
        :tabs="['我的模板', '模板广场']"
        v-model:current="activeTab"
      />

      <!-- 我的模板 -->
      <template v-if="activeTab === 0">
        <view class="template-page__actions">
          <lv-button size="sm" @tap="goCreateTemplate">
            <template #default>
              <view style="display: flex; align-items: center; gap: 8rpx;">
                <Plus :size="14" />
                <text>创建模板</text>
              </view>
            </template>
          </lv-button>
        </view>

        <lv-loading v-if="loading" />

        <view v-else-if="myTemplates.length === 0" class="template-page__empty">
          <lv-empty title="还没有模板" description="点击上方按钮创建第一个提示词模板" />
        </view>

        <view v-else class="template-page__list">
          <view
            v-for="tpl in myTemplates"
            :key="tpl.id"
            class="template-card"
          >
            <view class="template-card__header">
              <text class="template-card__name">{{ tpl.name }}</text>
              <lv-tag
                :type="statusTagType(tpl.status)"
                :text="statusLabel(tpl.status)"
                size="sm"
              />
              <lv-tag
                v-if="tpl.visibility === 'official'"
                type="primary"
                text="官方推荐"
                size="sm"
              />
            </view>
            <text class="template-card__desc">{{ tpl.description || '无描述' }}</text>
            <view class="template-card__meta">
              <text v-if="tpl.category" class="template-card__category">{{ tpl.category }}</text>
              <text class="template-card__usage">使用 {{ tpl.usage_count }} 次 · {{ tpl.updated_at.slice(0, 10) }}</text>
            </view>
            <view class="template-card__actions">
              <view class="template-card__btn" @tap="goEditTemplate(tpl)">
                <Pencil :size="14" color="#64748b" />
                <text>编辑</text>
              </view>
              <view
                v-if="tpl.status === 'draft'"
                class="template-card__btn template-card__btn--primary"
                @tap="handleSubmitReview(tpl)"
              >
                <Upload :size="14" color="#2563eb" />
                <text>申请公开</text>
              </view>
              <view class="template-card__btn template-card__btn--danger" @tap="handleDelete(tpl)">
                <Trash2 :size="14" color="#ef4444" />
                <text>删除</text>
              </view>
            </view>
          </view>
        </view>
      </template>

      <!-- 模板广场 -->
      <template v-if="activeTab === 1">
        <lv-loading v-if="marketLoading" />

        <view v-else-if="marketTemplates.length === 0" class="template-page__empty">
          <lv-empty title="暂无公开模板" description="社区还没有公开的模板" />
        </view>

        <view v-else class="template-page__market">
          <view
            v-for="tpl in marketTemplates"
            :key="tpl.id"
            class="market-card"
          >
            <view class="market-card__header">
              <lv-tag
                v-if="tpl.visibility === 'official'"
                type="primary"
                text="官方"
                size="sm"
              />
              <text class="market-card__name">{{ tpl.name }}</text>
            </view>
            <text class="market-card__desc">{{ tpl.description || '无描述' }}</text>
            <view class="market-card__meta">
              <lv-tag v-if="tpl.category" type="default" :text="tpl.category" size="sm" />
              <text class="market-card__author">{{ tpl.author?.username || '未知' }} · 使用 {{ tpl.usage_count }} 次</text>
            </view>
            <view class="market-card__actions">
              <view
                :class="['market-card__like', { 'market-card__like--active': tpl.is_liked }]"
                @tap="handleLike(tpl)"
              >
                <Heart :size="14" :fill="tpl.is_liked ? '#ef4444' : 'none'" :color="tpl.is_liked ? '#ef4444' : '#94a3b8'" />
                <text>{{ tpl.like_count }}</text>
              </view>
              <view class="market-card__btn" @tap="handleFork(tpl)">
                <Copy :size="14" color="#64748b" />
                <text>复制使用</text>
              </view>
            </view>
          </view>
        </view>
      </template>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { onMounted } from 'vue'
import { templatesApi } from '@/api'
import type { PromptTemplateItem } from '@/api/templates'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvTag from '@/components/lv-tag/lv-tag.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import LvSwiperTabs from '@/components/lv-swiper-tabs/lv-swiper-tabs.vue'
import { Plus, Pencil, Upload, Trash2, Heart, Copy } from '@lucide/vue'

const activeTab = ref(0)
const loading = ref(false)
const marketLoading = ref(false)
const myTemplates = ref<PromptTemplateItem[]>([])
const marketTemplates = ref<PromptTemplateItem[]>([])

const statusLabels: Record<string, string> = {
  draft: '草稿',
  pending: '审核中',
  approved: '已通过',
  rejected: '已拒绝',
}

function statusLabel(status: string): string {
  return statusLabels[status] || status
}

function statusTagType(status: string): 'success' | 'warning' | 'error' | 'default' {
  if (status === 'approved') return 'success'
  if (status === 'pending') return 'warning'
  if (status === 'rejected') return 'error'
  return 'default'
}

async function loadMyTemplates() {
  loading.value = true
  try {
    const res = await templatesApi.listMyTemplates({ page_size: 50 })
    myTemplates.value = res.templates
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

async function loadMarketTemplates() {
  marketLoading.value = true
  try {
    const res = await templatesApi.listPublicTemplates({ page_size: 50, sort: 'popular' })
    marketTemplates.value = res.templates
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    marketLoading.value = false
  }
}

watch(activeTab, (tab) => {
  if (tab === 0) loadMyTemplates()
  else loadMarketTemplates()
})

onMounted(() => {
  loadMyTemplates()
})

function goCreateTemplate() {
  uni.navigateTo({ url: '/pages/workspace/template-editor' })
}

function goEditTemplate(tpl: PromptTemplateItem) {
  uni.navigateTo({ url: `/pages/workspace/template-editor?id=${tpl.id}` })
}

async function handleDelete(tpl: PromptTemplateItem) {
  uni.showModal({
    title: '确认删除',
    content: `确定删除模板「${tpl.name}」？`,
    success: async (res) => {
      if (res.confirm) {
        try {
          await templatesApi.deletePromptTemplate(tpl.id)
          myTemplates.value = myTemplates.value.filter(t => t.id !== tpl.id)
          uni.showToast({ title: '已删除', icon: 'success' })
        } catch (e: any) {
          uni.showToast({ title: e.message || '删除失败', icon: 'none' })
        }
      }
    }
  })
}

async function handleSubmitReview(tpl: PromptTemplateItem) {
  try {
    await templatesApi.submitTemplateForReview(tpl.id)
    uni.showToast({ title: '已提交审核', icon: 'success' })
    loadMyTemplates()
  } catch (e: any) {
    uni.showToast({ title: e.message || '提交失败', icon: 'none' })
  }
}

async function handleLike(tpl: PromptTemplateItem) {
  try {
    if (tpl.is_liked) {
      const res = await templatesApi.unlikeTemplate(tpl.id)
      tpl.is_liked = res.is_liked
      tpl.like_count = res.like_count
    } else {
      const res = await templatesApi.likeTemplate(tpl.id)
      tpl.is_liked = res.is_liked
      tpl.like_count = res.like_count
    }
  } catch (e: any) {
    uni.showToast({ title: e.message || '操作失败', icon: 'none' })
  }
}

async function handleFork(tpl: PromptTemplateItem) {
  try {
    await templatesApi.forkPromptTemplate(tpl.id)
    uni.showToast({ title: '已复制到我的模板', icon: 'success' })
    loadMyTemplates()
    activeTab.value = 0
  } catch (e: any) {
    uni.showToast({ title: e.message || '复制失败', icon: 'none' })
  }
}
</script>

<style lang="scss" scoped>
.template-page {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx) $lv-page-padding $lv-page-padding;
  }

  &__actions {
    display: flex;
    justify-content: flex-end;
    margin-bottom: $lv-section-gap;
  }

  &__empty {
    padding-top: 120rpx;
  }

  &__list,
  &__market {
    display: flex;
    flex-direction: column;
    gap: 24rpx;
  }
}

.template-card {
  background: $lv-surface-solid;
  border-radius: $lv-radius-lg;
  padding: 32rpx;
  box-shadow: $lv-shadow-sm;

  &__header {
    display: flex;
    align-items: center;
    gap: 12rpx;
    margin-bottom: 12rpx;
    flex-wrap: wrap;
  }

  &__name {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__desc {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    margin-bottom: 12rpx;
    @include text-ellipsis(2);
  }

  &__meta {
    display: flex;
    align-items: center;
    gap: 12rpx;
    margin-bottom: 20rpx;
    flex-wrap: wrap;
  }

  &__category {
    display: inline-block;
    padding: 4rpx 12rpx;
    background: $lv-primary-lighter;
    border-radius: $lv-radius-xs;
    font-size: $lv-font-xs;
    color: $lv-text-secondary;
  }

  &__usage {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__actions {
    display: flex;
    gap: 16rpx;
    border-top: 1rpx solid $lv-border-light;
    padding-top: 20rpx;
  }

  &__btn {
    display: flex;
    align-items: center;
    gap: 6rpx;
    padding: 8rpx 16rpx;
    border-radius: $lv-radius-sm;
    font-size: $lv-font-xs;
    color: $lv-text-secondary;

    &:active {
      background: $lv-primary-lighter;
    }

    &--primary {
      color: $lv-primary;
    }

    &--danger {
      color: $lv-error;
    }
  }
}

.market-card {
  background: $lv-surface-solid;
  border-radius: $lv-radius-lg;
  padding: 32rpx;
  box-shadow: $lv-shadow-sm;

  &__header {
    display: flex;
    align-items: center;
    gap: 12rpx;
    margin-bottom: 12rpx;
  }

  &__name {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__desc {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    margin-bottom: 12rpx;
    @include text-ellipsis(2);
  }

  &__meta {
    display: flex;
    align-items: center;
    gap: 12rpx;
    margin-bottom: 20rpx;
    flex-wrap: wrap;
  }

  &__author {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__actions {
    display: flex;
    align-items: center;
    gap: 24rpx;
    border-top: 1rpx solid $lv-border-light;
    padding-top: 20rpx;
  }

  &__like {
    display: flex;
    align-items: center;
    gap: 6rpx;
    font-size: $lv-font-xs;
    color: $lv-text-muted;

    &--active {
      color: $lv-error;
    }
  }

  &__btn {
    display: flex;
    align-items: center;
    gap: 6rpx;
    font-size: $lv-font-xs;
    color: $lv-text-secondary;

    &:active {
      opacity: 0.7;
    }
  }
}
</style>
