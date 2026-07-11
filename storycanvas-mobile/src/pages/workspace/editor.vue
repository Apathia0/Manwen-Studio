<template>
  <view class="editor-page">
    <view class="editor-page__navbar">
      <view class="editor-page__icon-btn" @tap="handleBack">
        <lv-icon name="ChevronLeft" :size="20" color="#0f172a" />
      </view>
      <view class="editor-page__navbar-copy">
        <text class="editor-page__navbar-title">{{ shortChapterTitle }}</text>
        <text :class="['editor-page__save-state', saveStatusClass]">{{ saveStatusText }}</text>
      </view>
      <view class="editor-page__icon-btn" @tap="showContextDrawer = true">
        <lv-icon name="Menu" :size="20" color="#0f172a" />
      </view>
    </view>

    <scroll-view scroll-y class="editor-page__scroll">
      <view class="editor-page__content">
        <view
          v-if="continuityPreview"
          class="editor-page__continuity"
          @tap="showContinuityDrawer = true"
        >
          <text class="editor-page__continuity-text">
            <text class="editor-page__continuity-label">章节衔接：</text>{{ continuityPreview }}。点击查看完整连续性摘要。
          </text>
        </view>

        <text class="editor-page__chapter-title">{{ fullChapterTitle }}</text>
        <textarea
          v-model="content"
          class="editor-page__textarea"
          placeholder="从这里开始创作正文..."
          :auto-height="true"
          :maxlength="-1"
          :cursor-spacing="120"
          @input="handleInput"
        />
      </view>
    </scroll-view>

    <view class="editor-page__bottom-action">
      <view class="editor-page__secondary-btn" @tap="showChapterDrawer = true">
        <lv-icon name="List" :size="18" color="#334155" />
        <text>章节</text>
      </view>
      <view class="editor-page__primary-btn" @tap="openAgent">
        <lv-icon name="Bot" :size="19" color="#ffffff" />
        <text>AI 创作助手</text>
      </view>
    </view>

    <view v-if="showChapterDrawer" class="editor-page__backdrop" @tap="showChapterDrawer = false">
      <view class="editor-page__drawer" @tap.stop>
        <view class="editor-page__drawer-handle" />
        <view class="editor-page__drawer-head">
          <text class="editor-page__drawer-title">章节</text>
          <text class="editor-page__drawer-meta">共 {{ chapters.length }} 章</text>
        </view>
        <scroll-view scroll-y class="editor-page__drawer-scroll">
          <view
            v-for="chapter in chapters"
            :key="chapter.id"
            class="editor-page__chapter-row"
            @tap="switchChapter(chapter)"
          >
            <text
              :class="[
                'editor-page__chapter-status',
                chapter.id === chapterId
                  ? 'editor-page__chapter-status--current'
                  : chapter.novel_content
                    ? 'editor-page__chapter-status--done'
                    : 'editor-page__chapter-status--pending'
              ]"
            >
              {{ chapter.id === chapterId ? '当前' : chapter.novel_content ? '完成' : '待写' }}
            </text>
            <view class="editor-page__chapter-copy">
              <text class="editor-page__chapter-name">{{ formatChapterTitle(chapter) }}</text>
              <text class="editor-page__chapter-meta">
                {{ chapter.novel_content ? `${chapter.word_count || chapter.novel_content.length} 字` : '仅有大纲' }}
              </text>
            </view>
            <lv-icon name="ChevronRight" :size="17" color="#94a3b8" />
          </view>
        </scroll-view>
        <view class="editor-page__drawer-button" @tap="createChapter">
          <lv-icon name="Plus" :size="17" color="#2563eb" />
          <text>新建章节</text>
        </view>
      </view>
    </view>

    <view v-if="showContinuityDrawer" class="editor-page__backdrop" @tap="showContinuityDrawer = false">
      <view class="editor-page__drawer" @tap.stop>
        <view class="editor-page__drawer-handle" />
        <view class="editor-page__drawer-head">
          <text class="editor-page__drawer-title">连续性摘要</text>
          <view class="editor-page__drawer-link" @tap="openContinuityEditor">编辑</view>
        </view>
        <scroll-view v-if="continuitySections.length" scroll-y class="editor-page__continuity-sections">
          <view
            v-for="section in continuitySections"
            :key="section.label"
            class="editor-page__continuity-section"
          >
            <text class="editor-page__continuity-section-label">{{ section.label }}</text>
            <text class="editor-page__continuity-section-value">{{ section.value }}</text>
          </view>
        </scroll-view>
        <view v-else class="editor-page__empty">当前章节暂无连续性摘要</view>
      </view>
    </view>

    <view v-if="showContextDrawer" class="editor-page__backdrop" @tap="showContextDrawer = false">
      <view class="editor-page__drawer" @tap.stop>
        <view class="editor-page__drawer-handle" />
        <text class="editor-page__drawer-title">创作上下文</text>
        <view class="editor-page__context-list">
          <view class="editor-page__context-row" @tap="openWorkspaceResource('bible')">
            <view class="editor-page__context-icon editor-page__context-icon--bible">
              <lv-icon name="BookOpen" :size="19" color="#7c3aed" />
            </view>
            <view class="editor-page__context-copy">
              <text class="editor-page__context-title">作品圣经</text>
              <text class="editor-page__context-desc">创意摘要、写作策略与世界设定</text>
            </view>
            <lv-icon name="ChevronRight" :size="17" color="#94a3b8" />
          </view>
          <view class="editor-page__context-row" @tap="openWorkspaceResource('deconstruction')">
            <view class="editor-page__context-icon editor-page__context-icon--reference">
              <lv-icon name="Library" :size="19" color="#b45309" />
            </view>
            <view class="editor-page__context-copy">
              <text class="editor-page__context-title">拆书引用</text>
              <text class="editor-page__context-desc">查看当前作品引用的拆书报告</text>
            </view>
            <lv-icon name="ChevronRight" :size="17" color="#94a3b8" />
          </view>
          <view class="editor-page__context-row" @tap="openAgent">
            <view class="editor-page__context-icon editor-page__context-icon--agent">
              <lv-icon name="Bot" :size="19" color="#2563eb" />
            </view>
            <view class="editor-page__context-copy">
              <text class="editor-page__context-title">AI 创作助手</text>
              <text class="editor-page__context-desc">携带当前章节上下文打开</text>
            </view>
            <lv-icon name="ChevronRight" :size="17" color="#94a3b8" />
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { chaptersApi } from '@/api'
import type { Chapter } from '@/api/types'
import LvIcon from '@/components/lv-icon/lv-icon.vue'

const chapterId = ref(0)
const storyId = ref(0)
const chapterNumber = ref(0)
const chapterTitle = ref('')
const content = ref('')
const lastSavedContent = ref('')
const memorySummary = ref<Record<string, any>>({})
const chapters = ref<Chapter[]>([])
const saveStatus = ref<'saved' | 'saving' | 'unsaved'>('saved')
const showChapterDrawer = ref(false)
const showContinuityDrawer = ref(false)
const showContextDrawer = ref(false)
let saveTimer: ReturnType<typeof setTimeout> | null = null
let savePromise: Promise<void> | null = null
let lastSaveFailed = false
let chapterLoadSequence = 0

const shortChapterTitle = computed(() => {
  const title = chapterTitle.value?.trim()
  if (title && /^第\s*\d+\s*章/.test(title)) return title
  return title ? `第${chapterNumber.value}章 ${title}` : `第${chapterNumber.value}章`
})
const fullChapterTitle = computed(() => shortChapterTitle.value)
const saveStatusClass = computed(() => `editor-page__save-state--${saveStatus.value}`)
const saveStatusText = computed(() => {
  if (saveStatus.value === 'saving') return '自动保存中...'
  if (saveStatus.value === 'unsaved') return '等待自动保存'
  return '已自动保存'
})
const continuityData = computed(() => {
  const source = parseMemory(memorySummary.value)
  const summary = source.chapter_summary
  const handoff = source.chapter_handoff || {}
  return {
    summary: formatValue(typeof summary === 'string' ? summary : summary?.summary || source.summary),
    scene: formatValue(handoff.ending_location),
    conflict: formatValue(handoff.active_conflict),
    next: formatValue(handoff.immediate_open_loops || handoff.open_loops)
  }
})
const continuityPreview = computed(() => {
  return continuityData.value.conflict || continuityData.value.scene || continuityData.value.summary
})
const continuitySections = computed(() => {
  const data = continuityData.value
  return [
    { label: '当前章摘要', value: data.summary },
    { label: '当前场景', value: data.scene },
    { label: '即时冲突', value: data.conflict },
    { label: '下一章必须继续', value: data.next }
  ].filter(item => item.value)
})

onLoad((options) => {
  chapterId.value = Number(options?.chapterId || 0)
  storyId.value = Number(options?.storyId || 0)
  if (chapterId.value) loadContent()
})

onBeforeUnmount(() => {
  if (saveTimer) clearTimeout(saveTimer)
  void autoSave()
})

async function loadContent() {
  try {
    const chapter = await chaptersApi.getChapter(chapterId.value)
    applyChapter(chapter)
    await loadChapters()
  } catch {
    uni.showToast({ title: '加载正文失败', icon: 'none' })
  }
}

function applyChapter(chapter: Chapter) {
  chapterId.value = chapter.id
  storyId.value = storyId.value || chapter.story_id
  chapterNumber.value = chapter.chapter_number
  chapterTitle.value = chapter.title || ''
  content.value = chapter.novel_content || ''
  lastSavedContent.value = content.value
  memorySummary.value = chapter.memory_summary || {}
  saveStatus.value = 'saved'
}

async function loadChapters() {
  if (!storyId.value) return
  chapters.value = await chaptersApi.getChapters(storyId.value)
}

function handleInput() {
  saveStatus.value = 'unsaved'
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    saveTimer = null
    void autoSave()
  }, 1800)
}

async function autoSave() {
  if (saveTimer) {
    clearTimeout(saveTimer)
    saveTimer = null
  }
  if (savePromise) {
    await savePromise
    if (lastSaveFailed) return
    if (content.value !== lastSavedContent.value) return autoSave()
    return
  }
  if (!chapterId.value || content.value === lastSavedContent.value) return
  const targetChapterId = chapterId.value
  const targetContent = content.value
  lastSaveFailed = false
  saveStatus.value = 'saving'
  savePromise = (async () => {
    try {
      const chapter = await chaptersApi.saveContent(targetChapterId, targetContent)
      const index = chapters.value.findIndex(item => item.id === chapter.id)
      if (index >= 0) chapters.value[index] = chapter
      if (chapterId.value === targetChapterId) {
        lastSavedContent.value = targetContent
        saveStatus.value = content.value === targetContent ? 'saved' : 'unsaved'
      }
    } catch {
      lastSaveFailed = true
      if (chapterId.value === targetChapterId) saveStatus.value = 'unsaved'
    }
  })()
  await savePromise
  savePromise = null
}

async function handleBack() {
  if (saveTimer) clearTimeout(saveTimer)
  await autoSave()
  if (saveStatus.value !== 'saved') {
    uni.showModal({
      title: '正文尚未保存',
      content: '保存失败，仍要退出正文编辑吗？',
      success: (res) => {
        if (res.confirm) uni.navigateBack()
      }
    })
    return
  }
  uni.navigateBack()
}

async function switchChapter(chapter: Chapter) {
  await autoSave()
  if (saveStatus.value !== 'saved') {
    uni.showToast({ title: '请先等待当前正文保存', icon: 'none' })
    return
  }
  showChapterDrawer.value = false
  const sequence = ++chapterLoadSequence
  try {
    const detail = await chaptersApi.getChapter(chapter.id)
    if (sequence === chapterLoadSequence) applyChapter(detail)
  } catch (error: any) {
    if (sequence === chapterLoadSequence) {
      uni.showToast({ title: error?.message || '切换章节失败', icon: 'none' })
    }
  }
}

async function createChapter() {
  if (!storyId.value) return
  await autoSave()
  if (saveStatus.value !== 'saved') return
  try {
    const chapter = await chaptersApi.createChapter(storyId.value)
    await loadChapters()
    showChapterDrawer.value = false
    applyChapter(chapter)
  } catch (error: any) {
    uni.showToast({ title: error?.message || '创建章节失败', icon: 'none' })
  }
}

async function openAgent() {
  showContextDrawer.value = false
  if (!storyId.value || !chapterId.value) return
  await autoSave()
  if (saveStatus.value !== 'saved') {
    uni.showToast({ title: '正文保存失败，请稍后重试', icon: 'none' })
    return
  }
  uni.navigateTo({
    url: `/pages/workspace/agent?storyId=${storyId.value}&chapterId=${chapterId.value}&task=${encodeURIComponent('自由对话')}`
  })
}

function openContinuityEditor() {
  showContinuityDrawer.value = false
  uni.navigateTo({ url: `/pages/workspace/continuity?chapterId=${chapterId.value}` })
}

async function openWorkspaceResource(panel: 'bible' | 'deconstruction') {
  showContextDrawer.value = false
  await autoSave()
  if (saveStatus.value !== 'saved') {
    uni.showToast({ title: '正文保存失败，请稍后重试', icon: 'none' })
    return
  }
  if (panel === 'bible') {
    uni.navigateTo({ url: `/pages/story/story-bible?storyId=${storyId.value}` })
    return
  }
  uni.redirectTo({
    url: `/pages/workspace/chapter-view?storyId=${storyId.value}&material=${panel}`
  })
}

function formatChapterTitle(chapter: Chapter) {
  const title = chapter.title?.trim() || ''
  if (/^第\s*\d+\s*章/.test(title)) return title
  return `第${chapter.chapter_number}章${title ? ` ${title}` : ''}`
}

function parseMemory(value: unknown): Record<string, any> {
  if (value && typeof value === 'object') return value as Record<string, any>
  if (typeof value !== 'string' || !value.trim()) return {}
  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return { summary: value }
  }
}

function formatValue(value: any): string {
  if (!value) return ''
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(formatValue).filter(Boolean).join('；')
  if (typeof value === 'object') {
    return Object.entries(value)
      .map(([key, item]) => `${key}：${formatValue(item)}`)
      .join('；')
  }
  return String(value)
}
</script>

<style lang="scss" scoped>
.editor-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #ffffff;

  &__navbar {
    min-height: 88rpx;
    display: grid;
    grid-template-columns: 64rpx minmax(0, 1fr) 64rpx;
    align-items: center;
    padding: calc(var(--status-bar-height) + 8rpx) 20rpx 8rpx;
    border-bottom: 1rpx solid #e2e8f0;
    background: rgba(255, 255, 255, 0.98);
  }

  &__icon-btn {
    width: 64rpx;
    height: 64rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 8rpx;
    &:active { background: #f1f5f9; }
  }

  &__navbar-copy {
    min-width: 0;
    text-align: center;
  }

  &__navbar-title,
  &__save-state {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__navbar-title {
    font-size: 28rpx;
    font-weight: 700;
    color: #0f172a;
  }

  &__save-state {
    margin-top: 2rpx;
    font-size: 20rpx;
    &--saved { color: #047857; }
    &--saving { color: #b45309; }
    &--unsaved { color: #64748b; }
  }

  &__scroll {
    flex: 1;
    min-height: 0;
  }

  &__content {
    padding: 28rpx 32rpx 48rpx;
  }

  &__continuity {
    margin-bottom: 30rpx;
    padding: 22rpx 24rpx;
    border-left: 6rpx solid #2563eb;
    border-radius: 8rpx;
    background: #eff6ff;
    &:active { background: #dbeafe; }
  }

  &__continuity-text {
    font-size: 24rpx;
    line-height: 1.6;
    color: #34445f;
  }

  &__continuity-label {
    font-weight: 700;
  }

  &__chapter-title {
    display: block;
    margin-bottom: 28rpx;
    font-size: 38rpx;
    line-height: 1.4;
    font-weight: 700;
    color: #0f172a;
  }

  &__textarea {
    width: 100%;
    min-height: 920rpx;
    padding: 0;
    box-sizing: border-box;
    border: 0;
    background: transparent;
    color: #252e3e;
    font-family: "Noto Serif SC", "Songti SC", serif;
    font-size: 31rpx;
    line-height: 2;
  }

  &__bottom-action {
    flex-shrink: 0;
    display: flex;
    gap: 16rpx;
    padding: 16rpx 24rpx calc(16rpx + env(safe-area-inset-bottom));
    border-top: 1rpx solid #e2e8f0;
    background: rgba(255, 255, 255, 0.98);
    box-shadow: 0 -8rpx 24rpx rgba(28, 40, 65, 0.06);
  }

  &__secondary-btn,
  &__primary-btn {
    height: 76rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10rpx;
    border-radius: 8rpx;
    font-size: 26rpx;
    font-weight: 600;
  }

  &__secondary-btn {
    width: 164rpx;
    flex-shrink: 0;
    color: #334155;
    border: 1rpx solid #cbd5e1;
    background: #ffffff;
  }

  &__primary-btn {
    flex: 1;
    color: #ffffff;
    background: #2563eb;
    &:active { background: #1d4ed8; }
  }

  &__backdrop {
    position: fixed;
    z-index: 50;
    inset: 0;
    display: flex;
    align-items: flex-end;
    background: rgba(17, 25, 39, 0.4);
  }

  &__drawer {
    width: 100%;
    max-height: 78vh;
    padding: 16rpx 28rpx calc(28rpx + env(safe-area-inset-bottom));
    box-sizing: border-box;
    overflow: hidden;
    border-radius: 28rpx 28rpx 0 0;
    background: #ffffff;
    box-shadow: 0 -16rpx 40rpx rgba(25, 35, 52, 0.16);
  }

  &__drawer-handle {
    width: 64rpx;
    height: 7rpx;
    margin: 0 auto 24rpx;
    border-radius: 999rpx;
    background: #d6dbe3;
  }

  &__drawer-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 18rpx;
  }

  &__drawer-title {
    display: block;
    font-size: 30rpx;
    font-weight: 700;
    color: #0f172a;
  }

  &__drawer-meta,
  &__drawer-link {
    font-size: 23rpx;
    color: #64748b;
  }

  &__drawer-link { color: #2563eb; }

  &__drawer-scroll {
    height: 52vh;
  }

  &__chapter-row,
  &__context-row {
    min-height: 104rpx;
    display: flex;
    align-items: center;
    gap: 16rpx;
    border-bottom: 1rpx solid #e2e8f0;
  }

  &__chapter-status {
    flex-shrink: 0;
    padding: 7rpx 12rpx;
    border-radius: 6rpx;
    font-size: 20rpx;
    &--current { color: #1d4ed8; background: #dbeafe; }
    &--done { color: #047857; background: #d1fae5; }
    &--pending { color: #b45309; background: #fef3c7; }
  }

  &__chapter-copy,
  &__context-copy {
    flex: 1;
    min-width: 0;
  }

  &__chapter-name,
  &__context-title {
    display: block;
    font-size: 26rpx;
    font-weight: 600;
    color: #0f172a;
  }

  &__chapter-meta,
  &__context-desc {
    display: block;
    margin-top: 6rpx;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 22rpx;
    color: #64748b;
  }

  &__drawer-button {
    height: 72rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8rpx;
    margin-top: 20rpx;
    border: 1rpx solid #bfdbfe;
    border-radius: 8rpx;
    background: #eff6ff;
    color: #2563eb;
    font-size: 25rpx;
    font-weight: 600;
  }

  &__continuity-sections {
    height: 58vh;
  }

  &__continuity-section {
    padding: 22rpx 0;
    border-bottom: 1rpx solid #e2e8f0;
    &:last-child { border-bottom: 0; }
  }

  &__continuity-section-label {
    display: block;
    margin-bottom: 10rpx;
    font-size: 22rpx;
    color: #64748b;
  }

  &__continuity-section-value {
    display: block;
    font-size: 26rpx;
    line-height: 1.65;
    color: #0f172a;
  }

  &__empty {
    padding: 64rpx 0;
    text-align: center;
    color: #94a3b8;
    font-size: 24rpx;
  }

  &__context-list {
    margin-top: 18rpx;
  }

  &__context-icon {
    width: 60rpx;
    height: 60rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    border-radius: 10rpx;
    &--bible { background: #f5f3ff; }
    &--reference { background: #fffbeb; }
    &--agent { background: #eff6ff; }
  }
}
</style>
