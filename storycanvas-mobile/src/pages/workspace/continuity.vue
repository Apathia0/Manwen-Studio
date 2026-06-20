<template>
  <view class="continuity-page">
    <lv-navbar title="连贯性记忆" show-back />
    <view class="continuity-page__content">
      <!-- 章节摘要 -->
      <view class="continuity-page__section">
        <view class="continuity-page__section-header">
          <text class="continuity-page__section-title">章节摘要</text>
          <view class="continuity-page__edit-btn" @tap="toggleEditSummary">
            <lv-icon :name="editingSummary ? 'Check' : 'Pencil'" :size="14" color="#2563eb" />
            <text class="continuity-page__edit-text">{{ editingSummary ? '保存' : '编辑' }}</text>
          </view>
        </view>
        <view v-if="editingSummary" class="continuity-page__edit-area">
          <textarea
            v-model="summaryDraft"
            class="continuity-page__textarea"
            placeholder="章节摘要..."
            :disabled="saving"
          />
        </view>
        <view v-else class="continuity-page__display">
          <text class="continuity-page__text">{{ formatDict(summary) || '暂无章节摘要' }}</text>
        </view>
      </view>

      <!-- 章节交接 -->
      <view class="continuity-page__section">
        <view class="continuity-page__section-header">
          <text class="continuity-page__section-title">章节交接</text>
          <view class="continuity-page__edit-btn" @tap="toggleEditHandoff">
            <lv-icon :name="editingHandoff ? 'Check' : 'Pencil'" :size="14" color="#2563eb" />
            <text class="continuity-page__edit-text">{{ editingHandoff ? '保存' : '编辑' }}</text>
          </view>
        </view>
        <view v-if="editingHandoff" class="continuity-page__edit-area">
          <textarea
            v-model="handoffDraft"
            class="continuity-page__textarea"
            placeholder="章节交接信息..."
            :disabled="saving"
          />
        </view>
        <view v-else class="continuity-page__display">
          <text class="continuity-page__text">{{ formatDict(handoff) || '暂无章节交接' }}</text>
        </view>
      </view>

      <lv-empty
        v-if="!loading && Object.keys(summary).length === 0 && Object.keys(handoff).length === 0"
        title="暂无连贯性记忆"
        description="AI 生成章节后会自动产生连贯性记忆"
      />

      <lv-loading v-if="loading" />
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { chaptersApi } from '@/api'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'

const loading = ref(false)
const saving = ref(false)
const editingSummary = ref(false)
const editingHandoff = ref(false)
const summary = ref<Record<string, any>>({})
const handoff = ref<Record<string, any>>({})
const summaryDraft = ref('')
const handoffDraft = ref('')
const chapterId = ref(0)

onMounted(async () => {
  const pages = getCurrentPages()
  const page = pages[pages.length - 1] as any
  chapterId.value = Number(page.options?.chapterId || 0)
  if (!chapterId.value) {
    uni.showToast({ title: '缺少章节 ID', icon: 'none' })
    return
  }
  await loadMemory()
})

async function loadMemory() {
  loading.value = true
  try {
    // 从 chapter 详情获取 memory_summary 字段(后端无单独 GET 端点)
    const chapter = await chaptersApi.getChapter(chapterId.value)
    const mem = chapter.memory_summary
    if (mem && typeof mem === 'object') {
      summary.value = mem.chapter_summary || {}
      handoff.value = mem.chapter_handoff || {}
    }
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

function toggleEditSummary() {
  if (editingSummary.value) {
    saveSummary()
  } else {
    summaryDraft.value = dictToText(summary.value)
    editingSummary.value = true
  }
}

function toggleEditHandoff() {
  if (editingHandoff.value) {
    saveHandoff()
  } else {
    handoffDraft.value = dictToText(handoff.value)
    editingHandoff.value = true
  }
}

async function saveSummary() {
  saving.value = true
  try {
    const parsed = textToDict(summaryDraft.value)
    await chaptersApi.updateContinuity(chapterId.value, { chapter_summary: parsed })
    summary.value = parsed
    editingSummary.value = false
    uni.showToast({ title: '已保存', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '保存失败', icon: 'none' })
  } finally {
    saving.value = false
  }
}

async function saveHandoff() {
  saving.value = true
  try {
    const parsed = textToDict(handoffDraft.value)
    await chaptersApi.updateContinuity(chapterId.value, { chapter_handoff: parsed })
    handoff.value = parsed
    editingHandoff.value = false
    uni.showToast({ title: '已保存', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '保存失败', icon: 'none' })
  } finally {
    saving.value = false
  }
}

// 将 dict 格式化为可读文本
function formatDict(dict: Record<string, any>): string {
  if (!dict || Object.keys(dict).length === 0) return ''
  return Object.entries(dict)
    .map(([key, value]) => `${key}: ${typeof value === 'object' ? JSON.stringify(value) : value}`)
    .join('\n')
}

// 将 dict 转为文本(编辑模式)
function dictToText(dict: Record<string, any>): string {
  if (!dict || Object.keys(dict).length === 0) return ''
  return Object.entries(dict)
    .map(([key, value]) => `${key}: ${typeof value === 'object' ? JSON.stringify(value) : value}`)
    .join('\n')
}

// 将文本解析为 dict
function textToDict(text: string): Record<string, any> {
  const result: Record<string, any> = {}
  if (!text.trim()) return result
  for (const line of text.split('\n')) {
    const trimmed = line.trim()
    if (!trimmed) continue
    const match = trimmed.match(/^([^:：]{1,50})[:：]\s*(.*)$/)
    if (match) {
      const [, key, value] = match
      result[key.trim()] = value.trim()
    }
  }
  return result
}
</script>

<style lang="scss" scoped>
.continuity-page {
  min-height: 100vh;
  background: $lv-bg-start;

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding;
  }

  &__section {
    background: #fff;
    border-radius: $lv-radius-md;
    padding: 28rpx;
    margin-bottom: 16rpx;
    box-shadow: $lv-shadow-sm;
  }

  &__section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16rpx;
  }

  &__section-title {
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__edit-btn {
    display: flex;
    align-items: center;
    gap: 4rpx;
  }

  &__edit-text {
    font-size: $lv-font-sm;
    color: $lv-primary;
  }

  &__edit-area {
    background: $lv-primary-lighter;
    border-radius: $lv-radius-sm;
    padding: 16rpx;
  }

  &__textarea {
    width: 100%;
    min-height: 200rpx;
    font-size: $lv-font-sm;
    line-height: 1.6;
    color: $lv-text-primary;
  }

  &__display {
    min-height: 80rpx;
  }

  &__text {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    white-space: pre-wrap;
    line-height: 1.6;
  }
}
</style>
