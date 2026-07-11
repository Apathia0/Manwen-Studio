<template>
  <view class="story-library">
    <lv-navbar :title="siteName">
      <template #right>
        <view class="story-library__announcement-button" @tap="openAnnouncement">
          <lv-badge :value="platformStore.announcement ? '!' : ''">
            <Bell :size="20" color="#0f172a" />
          </lv-badge>
        </view>
      </template>
    </lv-navbar>

    <view class="story-library__content">
      <lv-pull-refresh v-model="refreshing" @refresh="handleRefresh">
        <view v-if="storyStore.loading && storyStore.list.length === 0" class="story-library__loading">
          <lv-skeleton avatar :rows="3" v-for="i in 3" :key="i" />
        </view>

        <view v-else-if="storyStore.list.length === 0" class="story-library__empty">
          <lv-empty title="暂无故事" description="创建你的第一个故事开始创作之旅">
            <template #action>
              <lv-button @tap="goCreate">创建故事</lv-button>
            </template>
          </lv-empty>
        </view>

        <view v-else class="story-library__list">
          <story-card
            v-for="story in storyStore.sortedStories"
            :key="story.id"
            :story="story"
            @select="handleStoryTap"
            @longpress="handleStoryLongPress"
            @cover-click="handleCoverClick"
            @delete="handleStoryDelete"
          />
        </view>
      </lv-pull-refresh>
    </view>

    <lv-fab @tap="handleFabTap" />

    <lv-action-sheet
      v-model:visible="showActionSheet"
      :actions="fabActions"
      @select="handleActionSelect"
    />

    <lv-action-sheet
      v-model:visible="showStoryMenu"
      :actions="storyActions"
      @select="handleStoryActionSelect"
    />

    <lv-modal
      :visible="showAnnouncement"
      :title="platformStore.announcement?.title || '平台公告'"
      :show-cancel="false"
      show-close
      confirm-text="我知道了"
      @update:visible="handleAnnouncementVisibility"
    >
      <scroll-view scroll-y class="story-library__announcement-content">
        <rich-text
          v-if="platformStore.announcement"
          :nodes="platformStore.announcement.content"
        />
        <text v-else class="story-library__announcement-empty">暂无公告</text>
      </scroll-view>
    </lv-modal>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useStoriesStore } from '@/stores/stories'
import { usePlatformStore } from '@/stores/platform'
import type { Story } from '@/api/types'
import { exportStory } from '@/utils/exportStory'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvBadge from '@/components/lv-badge/lv-badge.vue'
import LvPullRefresh from '@/components/lv-pull-refresh/lv-pull-refresh.vue'
import LvSkeleton from '@/components/lv-skeleton/lv-skeleton.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvFab from '@/components/lv-fab/lv-fab.vue'
import LvActionSheet from '@/components/lv-action-sheet/lv-action-sheet.vue'
import LvModal from '@/components/lv-modal/lv-modal.vue'
import StoryCard from '@/components/story-card/story-card.vue'
import { Bell } from '@lucide/vue'

const storyStore = useStoriesStore()
const platformStore = usePlatformStore()
const siteName = computed(() => platformStore.settings?.site_name?.trim() || 'StoryCanvas')

const refreshing = ref(false)
const showActionSheet = ref(false)
const showStoryMenu = ref(false)
const showAnnouncement = ref(false)
const selectedStory = ref<Story | null>(null)

const fabActions = [
  { text: '新建故事' },
  { text: '导入小说' }
]

const storyActions = [
  { text: '编辑信息' },
  { text: '编辑封面' },
  { text: '导出' },
  { text: '删除', danger: true }
]

onMounted(async () => {
  void storyStore.fetchStories().catch(() => {})
  void platformStore.fetchAnnouncement()
})

async function handleRefresh() {
  try {
    await Promise.allSettled([
      storyStore.fetchStories(),
      platformStore.fetchAnnouncement()
    ])
  } finally {
    refreshing.value = false
  }
}

async function openAnnouncement() {
  if (platformStore.announcement) {
    showAnnouncement.value = true
    return
  }

  uni.showLoading({ title: '加载公告...' })
  try {
    await platformStore.fetchAnnouncement()
    if (platformStore.announcement) {
      showAnnouncement.value = true
    } else {
      uni.showToast({ title: '暂无公告', icon: 'none' })
    }
  } finally {
    uni.hideLoading()
  }
}

function handleAnnouncementVisibility(visible: boolean) {
  showAnnouncement.value = visible
  if (!visible) {
    platformStore.dismissAnnouncement()
  }
}

function handleStoryTap(story: Story) {
  storyStore.setActiveStory(story.id)
  // 引导流程判定（与 Web 端 openWorkspace 逻辑对齐）
  // 优先级: import guidance > onboarding > 工作台
  if (story.source_type === 'import' && !story.import_context_completed) {
    uni.navigateTo({ url: `/pages/story/import-guidance?storyId=${story.id}` })
    return
  }
  if (!story.onboarding_completed) {
    uni.navigateTo({ url: `/pages/story/onboarding?storyId=${story.id}` })
    return
  }
  // 已完成所有引导，直接进入工作台
  uni.navigateTo({ url: `/pages/workspace/chapter-view?storyId=${story.id}` })
}

function handleCoverClick(story: Story) {
  uni.navigateTo({ url: `/pages/story/cover-edit?storyId=${story.id}` })
}

function handleStoryLongPress(story: Story) {
  selectedStory.value = story
  showStoryMenu.value = true
}

function handleFabTap() {
  showActionSheet.value = true
}

function handleActionSelect(index: number) {
  if (index === 0) {
    goCreate()
  } else {
    goImport()
  }
}

function handleStoryActionSelect(index: number) {
  if (!selectedStory.value) return

  switch (index) {
    case 0:
      uni.navigateTo({ url: `/pages/story/detail?id=${selectedStory.value.id}` })
      break
    case 1:
      uni.navigateTo({ url: `/pages/story/cover-edit?id=${selectedStory.value.id}` })
      break
    case 2:
      handleExport()
      break
    case 3:
      confirmDelete()
      break
  }
}

async function handleExport() {
  if (!selectedStory.value) return
  uni.showLoading({ title: '导出中...' })
  try {
    await exportStory(selectedStory.value.id)
  } catch (e: any) {
    uni.showToast({ title: e.message || '导出失败', icon: 'none' })
  } finally {
    uni.hideLoading()
  }
}

async function confirmDelete() {
  if (!selectedStory.value) return
  const storyId = selectedStory.value.id
  const storyTitle = selectedStory.value.title
  uni.showModal({
    title: '确认删除',
    content: `确定要删除故事「${storyTitle}」吗？此操作不可撤销。`,
    confirmColor: '#be123c',
    success: async (res) => {
      if (!res.confirm) return
      try {
        await storyStore.deleteStory(storyId)
        uni.showToast({ title: '已删除', icon: 'success' })
      } catch (e: any) {
        uni.showToast({ title: e.message || '删除失败', icon: 'none' })
      }
    }
  })
}

function handleStoryDelete(story: Story) {
  selectedStory.value = story
  confirmDelete()
}

function goCreate() {
  uni.navigateTo({ url: '/pages/story/create' })
}

function goImport() {
  uni.navigateTo({ url: '/pages/story/import' })
}
</script>

<style lang="scss" scoped>
.story-library {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding-top: calc(var(--status-bar-height) + 88rpx);
    padding-bottom: 120rpx;
  }

  &__loading,
  &__empty {
    padding: $lv-page-padding;
  }

  &__list {
    padding: $lv-page-padding;
    display: flex;
    flex-direction: column;
    gap: $lv-item-gap;
  }

  &__announcement-button {
    width: 64rpx;
    height: 64rpx;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  &__announcement-content {
    height: 50vh;
    max-height: 720rpx;
    font-size: $lv-font-sm;
    line-height: 1.7;
    color: $lv-text-primary;
  }

  &__announcement-empty {
    display: block;
    padding: 32rpx 0;
    text-align: center;
    color: $lv-text-muted;
  }
}
</style>
