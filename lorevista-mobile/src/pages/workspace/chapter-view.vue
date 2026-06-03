<template>
  <view class="chapter-view">
    <view class="chapter-view__navbar">
      <view class="chapter-view__navbar-left">
        <view class="chapter-view__navbar-btn" @tap="goBack">
          <ArrowLeft :size="20" color="#0f172a" />
        </view>
      </view>
      <view class="chapter-view__navbar-center">
        <text class="chapter-view__navbar-title">{{ workspaceStore.activeChapterTitle }}</text>
      </view>
      <view class="chapter-view__navbar-right">
        <view class="chapter-view__navbar-btn" @tap="showMore">
          <MoreHorizontal :size="20" color="#0f172a" />
        </view>
      </view>
    </view>

    <lv-swiper-tabs
      :tabs="['框架', '编辑', '漫画', '助手']"
      v-model:current="activeTabIndex"
    >
      <!-- 框架标签 -->
      <template #tab-0>
        <scroll-view scroll-y class="chapter-view__tab-scroll">
          <view class="chapter-view__tab">
            <!-- 模板绑定 -->
            <template-binding
              v-if="storiesStore.activeStoryId"
              :story-id="storiesStore.activeStoryId"
              @bound="onTemplateBound"
            />

            <!-- 创意简报 -->
            <bible-summary
              v-if="storyBible && Object.keys(storyBible).length > 0"
              :bible="storyBible"
              :editable="true"
              @edit="handleEditBible"
            />

            <!-- 故事描述 -->
            <view class="fp__section fp__card">
              <view class="fp__section-header" @tap="toggleDescEdit">
                <view class="fp__section-title">
                  <lv-icon name="FileText" :size="16" color="#64748b" />
                  <text class="fp__section-label">故事描述</text>
                </view>
                <lv-icon :name="descEditing ? 'ChevronUp' : 'Pencil'" :size="14" color="#94a3b8" />
              </view>
              <view v-if="descEditing" class="fp__section-body">
                <textarea class="fp__textarea" v-model="descDraft" placeholder="描述你的故事..." />
                <view class="fp__actions">
                  <lv-button size="sm" secondary @tap="cancelDescEdit">取消</lv-button>
                  <lv-button size="sm" @tap="saveDesc" :loading="savingDesc">保存</lv-button>
                </view>
              </view>
              <view v-else class="fp__section-body">
                <text class="fp__desc-text">{{ storyDesc || '暂无描述' }}</text>
              </view>
            </view>

            <!-- 框架 AI 对话 -->
            <view class="fp__section fp__card">
              <view class="fp__section-header">
                <view class="fp__section-title">
                  <lv-icon name="MessageSquare" :size="16" color="#2563eb" />
                  <text class="fp__section-label">框架 AI 对话</text>
                </view>
                <view class="fp__header-actions">
                  <view v-if="hasFramework" class="fp__header-btn" @tap="handleContinueFramework">
                    <lv-icon name="Sparkles" :size="12" color="#2563eb" style="margin-right: 4rpx;" />一键续写
                  </view>
                  <text class="fp__header-btn" @tap="toggleSnapshots">{{ showSnapshots ? '收起' : '历史版本' }}</text>
                </view>
              </view>

              <!-- 快照列表 -->
              <view v-if="showSnapshots" class="fp__snapshots">
                <view v-if="loadingSnapshots" class="fp__loading-row">
                  <lv-loading />
                </view>
                <view v-else-if="snapshots.length === 0" class="fp__empty-row">
                  <text class="fp__empty-text">暂无历史版本</text>
                </view>
                <view v-else class="fp__snapshot-list">
                  <view v-for="(snap, i) in snapshots" :key="snap.id" class="fp__snapshot-item">
                    <text class="fp__snapshot-num">#{{ i + 1 }}</text>
                    <text class="fp__snapshot-time">{{ snap.created_at }}</text>
                    <text class="fp__snapshot-desc">{{ snap.reply_summary || snap.description || '' }}</text>
                    <lv-button size="sm" secondary @tap="handleRestoreSnapshot(snap.id)">回滚</lv-button>
                  </view>
                </view>
              </view>

              <!-- 对话记录 -->
              <view class="fp__chat-area" v-if="chatMessages.length > 0">
                <view v-for="(msg, i) in chatMessages" :key="i" :class="['fp__chat-msg', `fp__chat-msg--${msg.role}`]">
                  <view class="fp__chat-bubble">
                    <text class="fp__chat-text">{{ msg.content }}</text>
                    <view v-if="i === chatMessages.length - 1 && chatLoading" class="fp__chat-cursor" />
                  </view>
                </view>
              </view>
              <view v-else class="fp__chat-area">
                <text class="fp__chat-hint">
                  {{ hasFramework ? '告诉 AI 你想如何修改故事框架。' : '输入故事描述，AI 会先生成初始框架。' }}
                </text>
              </view>

              <!-- 输入 -->
              <view class="fp__chat-input-row">
                <input class="fp__chat-input" v-model="chatInput" :placeholder="chatPlaceholder" :disabled="chatLoading" />
                <lv-button size="sm" @tap="handleFrameworkChat" :loading="chatLoading" :disabled="!chatInput.trim()">
                  <lv-icon name="Wand2" :size="13" color="#fff" style="margin-right: 4rpx;" />{{ chatBtnLabel }}
                </lv-button>
              </view>
              <text v-if="chatError" class="fp__error">{{ chatError }}</text>
            </view>

            <!-- 手动编辑框架 -->
            <view class="fp__section fp__card">
              <view class="fp__section-header" @tap="toggleManualEdit">
                <view class="fp__section-title">
                  <lv-icon name="Pencil" :size="16" color="#64748b" />
                  <text class="fp__section-label">手动编辑框架</text>
                </view>
                <lv-icon :name="manualEditing ? 'ChevronUp' : 'ChevronDown'" :size="14" color="#94a3b8" />
              </view>
              <view v-if="manualEditing" class="fp__section-body">
                <textarea class="fp__textarea fp__textarea--mono" v-model="manualDraft" placeholder="{ ... }" />
                <view class="fp__actions">
                  <lv-button size="sm" secondary @tap="cancelManualEdit">取消</lv-button>
                  <lv-button size="sm" @tap="saveManualEdit" :loading="manualSaving">保存框架</lv-button>
                </view>
                <text v-if="manualError" class="fp__error">{{ manualError }}</text>
              </view>
            </view>

            <!-- 标签 -->
            <view class="fp__section fp__card">
              <view class="fp__section-header">
                <view class="fp__section-title">
                  <lv-icon name="Tag" :size="16" color="#64748b" />
                  <text class="fp__section-label">标签设定</text>
                </view>
                <text class="fp__badge" v-if="hasTags">已生成</text>
              </view>
              <view class="fp__section-body">
                <view class="fp__tags">
                  <lv-tag v-for="tag in tags" :key="tag" :text="tag" size="md" />
                </view>
              </view>
            </view>

            <!-- 角色 -->
            <view class="fp__section fp__card">
              <view class="fp__section-header" @tap="charactersExpanded = !charactersExpanded">
                <view class="fp__section-title">
                  <lv-icon name="Users" :size="16" color="#64748b" />
                  <text class="fp__section-label">角色设定</text>
                </view>
                <view class="fp__header-actions">
                  <text class="fp__badge" v-if="hasCharacters">{{ characters.length }} 个</text>
                  <lv-icon :name="charactersExpanded ? 'ChevronUp' : 'ChevronDown'" :size="14" color="#94a3b8" />
                </view>
              </view>
              <view v-if="charactersExpanded" class="fp__section-body">
                <character-card v-for="char in characters" :key="char.name" :character="char" />
              </view>
            </view>

            <!-- 故事大纲 -->
            <view class="fp__section fp__card">
              <view class="fp__section-header">
                <view class="fp__section-title">
                  <lv-icon name="ListTree" :size="16" color="#64748b" />
                  <text class="fp__section-label">故事大纲</text>
                </view>
                <view class="fp__header-actions">
                  <text class="fp__badge" v-if="outlineActs.length > 0">{{ outlineActs.length }} 幕</text>
                  <text class="fp__header-btn" @tap="outlineExpandedAll = !outlineExpandedAll">
                    {{ outlineExpandedAll ? '全部收起' : '全部展开' }}
                  </text>
                </view>
              </view>
              <view class="fp__section-body">
                <template v-if="outlineActs.length > 0">
                  <outline-tree
                    :outline="outlineActs"
                    :chapter-map="chapterMap"
                    :expanded-all="outlineExpandedAll"
                    @select="handleChapterSelect"
                    @generate="handleGenerateChapter"
                  />
                </template>
                <view v-else class="fp__empty-row">
                  <text class="fp__empty-text">暂无大纲，请通过 AI 对话先生成框架。</text>
                </view>
              </view>
            </view>

            <!-- 章节列表 -->
            <view class="fp__section fp__card">
              <view class="fp__section-header">
                <view class="fp__section-title">
                  <lv-icon name="BookOpen" :size="16" color="#64748b" />
                  <text class="fp__section-label">章节列表</text>
                </view>
                <view class="fp__header-actions">
                  <view class="fp__header-btn" @tap="handleRegenerateChapters" v-if="chapters.length > 0">
                    <lv-icon name="RefreshCw" :size="12" color="#64748b" style="margin-right: 4rpx;" />AI 生成章节
                  </view>
                </view>
              </view>
              <view class="fp__section-body">
                <template v-if="chapters.length > 0">
                  <view class="fp__jump-bar">
                    <input class="fp__jump-input" v-model="chapterJumpNum" type="number" placeholder="跳转章节号" @confirm="handleChapterJump" />
                    <lv-button size="sm" @tap="handleChapterJump">跳转</lv-button>
                  </view>
                  <view v-for="ch in paginatedChapters" :key="ch.chapter_number" class="fp__chapter-item">
                    <view class="fp__chapter-header">
                      <text class="fp__chapter-num">#{{ String(ch.chapter_number).padStart(2, '0') }}</text>
                      <text class="fp__chapter-title">{{ ch.title }}</text>
                      <text :class="['fp__chapter-status', `fp__chapter-status--${getChapterStatus(ch)}`]">
                        {{ getChapterStatusLabel(ch) }}
                      </text>
                    </view>
                    <view class="fp__chapter-actions">
                      <template v-if="chapterHasContent(ch)">
                        <text class="fp__chapter-btn fp__chapter-btn--primary" @tap="handleOpenChapter(ch)">打开正文</text>
                        <text class="fp__chapter-btn" @tap="handleAssessQuality(ch)">质量评估</text>
                      </template>
                      <text v-else class="fp__chapter-btn fp__chapter-btn--primary" @tap="handleGenerateChapter(ch)">生成正文</text>
                    </view>
                  </view>
                  <view v-if="totalPages > 1" class="fp__pagination">
                    <text class="fp__page-btn" :class="{ 'fp__page-btn--disabled': currentPage <= 1 }" @tap="prevPage">上一页</text>
                    <text class="fp__page-info">{{ chapterRangeText }}</text>
                    <text class="fp__page-btn" :class="{ 'fp__page-btn--disabled': currentPage >= totalPages }" @tap="nextPage">下一页</text>
                  </view>
                </template>
                <view v-else class="fp__empty-row">
                  <text class="fp__empty-text">暂无章节，请通过 AI 对话生成框架。</text>
                </view>
              </view>
            </view>

            <view class="fp__bottom-spacer" />
          </view>
        </scroll-view>
      </template>

      <!-- 编辑标签 -->
      <template #tab-1>
        <view class="chapter-view__edit-panel">
          <scroll-view scroll-y class="chapter-view__tab-scroll">
            <view class="chapter-view__tab">
              <continuity-card v-if="continuitySummary" :summary="continuitySummary" />

              <text class="chapter-view__chapter-title">{{ workspaceStore.activeChapterTitle }}</text>
              <view class="chapter-view__divider" />

              <view v-if="editorStore.loading" class="chapter-view__loading">
                <lv-loading />
              </view>
              <template v-else-if="localEditing">
                <textarea
                  class="chapter-view__editor-textarea"
                  :value="editorStore.draftContent"
                  @input="handleEditorInput"
                  placeholder="开始写作..."
                  auto-height
                />
                <view class="chapter-view__word-count">字数: {{ editorStore.wordCount }}</view>
              </template>
              <template v-else>
                <text class="chapter-view__content">{{ editorStore.content || '暂无内容，点击下方按钮开始创作' }}</text>
                <view class="chapter-view__word-count">字数: {{ editorStore.wordCount }}</view>
              </template>
            </view>
          </scroll-view>

          <view class="chapter-view__editor-toolbar">
            <template v-if="localEditing">
              <lv-button size="sm" @tap="saveLocalEdit" :loading="editorStore.saving">保存</lv-button>
              <lv-button size="sm" secondary @tap="cancelLocalEdit">取消</lv-button>
            </template>
            <template v-else>
              <lv-button size="sm" @tap="startLocalEdit">
                <lv-icon name="Pencil" :size="14" style="margin-right: 6rpx;" />编辑
              </lv-button>
              <lv-button size="sm" @tap="goChat">
                <lv-icon name="Bot" :size="14" style="margin-right: 6rpx;" />AI续写
              </lv-button>
              <lv-button size="sm" secondary @tap="handleQualityAssess">
                <lv-icon name="BarChart3" :size="14" style="margin-right: 6rpx;" />质量
              </lv-button>
              <view class="chapter-view__more" @tap="showEditorMore">
                <MoreHorizontal :size="20" color="#475569" />
              </view>
            </template>
          </view>
        </view>
      </template>

      <!-- 漫画标签 -->
      <template #tab-2>
        <scroll-view scroll-y class="chapter-view__tab-scroll">
          <view class="chapter-view__tab">
            <view class="chapter-view__manga-settings">
              <text class="chapter-view__manga-label">设置:</text>
              <picker :value="colorModeIndex" :range="['彩色', '黑白']" @change="handleColorModeChange">
                <text class="chapter-view__manga-picker">{{ ['彩色', '黑白'][colorModeIndex] }}</text>
              </picker>
              <picker :value="imageCountIndex" :range="imageCountOptions.map(o => o.label)" @change="handleImageCountChange">
                <text class="chapter-view__manga-picker">{{ imageCountOptions[imageCountIndex].label }}</text>
              </picker>
            </view>

            <lv-button block :loading="mangaStore.isGenerating" @tap="handleGenerateManga">
              <template v-if="mangaStore.isGenerating">生成中...</template>
              <template v-else>
                <lv-icon name="ImagePlus" :size="16" style="margin-right: 8rpx;" />生成漫画
              </template>
            </lv-button>

            <view v-if="mangaStore.isGenerating" class="chapter-view__manga-progress">
              <lv-progress :percentage="mangaStore.progressPercent" show-info />
              <text class="chapter-view__manga-status">{{ mangaStore.progress.statusMsg }}</text>
            </view>

            <view v-if="mangaStore.scenes.length > 0" class="chapter-view__scenes">
              <framework-section title="分镜脚本" icon="icon-film" :count="mangaStore.scenes.length">
                <view v-for="(scene, i) in mangaStore.scenes" :key="i" class="chapter-view__scene-item">
                  <text class="chapter-view__scene-num">{{ i + 1 }}.</text>
                  <text class="chapter-view__scene-text">{{ scene }}</text>
                </view>
              </framework-section>
            </view>

            <view class="chapter-view__manga-grid">
              <manga-image-card
                v-for="img in mangaStore.images"
                :key="img.id"
                :image-path="img.image_path"
                :image-number="img.image_number"
                @tap="goGallery(img.image_number)"
              />
            </view>

            <lv-empty v-if="!mangaStore.isGenerating && mangaStore.images.length === 0 && mangaStore.scenes.length === 0" title="暂无漫画" description="点击生成漫画开始创作" />

            <view class="chapter-view__manga-links">
              <lv-button secondary block size="sm" @tap="goCharacterProfiles">角色外观</lv-button>
              <lv-button secondary block size="sm" @tap="goRefImages">参考图</lv-button>
            </view>
          </view>
        </scroll-view>
      </template>

      <!-- 助手标签 -->
      <template #tab-3>
        <view class="chapter-view__agent-wrapper">
          <view class="chapter-view__agent-header">
            <lv-button size="sm" @tap="startNewAgentConversation">新对话</lv-button>
            <lv-button size="sm" secondary @tap="goAgentHistory">历史</lv-button>
          </view>

          <scroll-view scroll-y class="chapter-view__agent-messages" :scroll-into-view="agentScrollTarget">
            <chat-message
              v-for="msg in agentStore.messages"
              :key="msg.id"
              :role="msg.role"
              :content="msg.content"
              :tool-calls="msg.toolCalls"
            />
            <chat-message
              v-if="agentStore.streamingContent"
              role="assistant"
              :content="agentStore.streamingContent"
              :streaming="true"
            />
            <lv-loading v-if="agentStore.streaming && !agentStore.streamingContent" />
            <view id="agent-scroll-bottom" />
          </scroll-view>

          <view class="chapter-view__agent-quick">
            <view class="chapter-view__quick-grid">
              <view v-for="action in quickActions" :key="action" class="chapter-view__quick-btn" @tap="sendQuickAction(action)">
                <text class="chapter-view__quick-text">{{ action }}</text>
              </view>
            </view>
          </view>

          <chat-input
            v-model="agentInputText"
            :streaming="agentStore.streaming"
            @send="handleAgentSend"
            @stop="agentStore.stopStreaming()"
          />

          <changes-banner
            v-if="agentStore.pendingChanges.length > 0"
            :count="agentStore.pendingChanges.length"
            @view="handleViewChanges"
            @confirm="handleConfirmChanges"
            @rollback="handleRollbackChanges"
          />
        </view>
      </template>
    </lv-swiper-tabs>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { ArrowLeft, MoreHorizontal } from '@lucide/vue'
import { useWorkspaceStore } from '@/stores/workspace'
import { useEditorStore } from '@/stores/editor'
import { useMangaStore } from '@/stores/manga'
import { useAgentStore } from '@/stores/agent'
import { useStoriesStore } from '@/stores/stories'
import { useUiStore } from '@/stores/ui'
import { storiesApi, frameworkApi, chaptersApi } from '@/api'
import type { Story, Character, OutlineAct, OutlineChapter, Chapter } from '@/api/types'
import type { FrameworkChatMessage, FrameworkSnapshotItem } from '@/api/types'
import { useSSE } from '@/composables/useSSE'
import { getToken } from '@/utils/storage'
import LvSwiperTabs from '@/components/lv-swiper-tabs/lv-swiper-tabs.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import LvTag from '@/components/lv-tag/lv-tag.vue'
import LvProgress from '@/components/lv-progress/lv-progress.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import FrameworkSection from '@/components/framework-section/framework-section.vue'
import CharacterCard from '@/components/character-card/character-card.vue'
import OutlineTree from '@/components/outline-tree/outline-tree.vue'
import ContinuityCard from '@/components/continuity-card/continuity-card.vue'
import MangaImageCard from '@/components/manga-image-card/manga-image-card.vue'
import ChatMessage from '@/components/chat-message/chat-message.vue'
import ChatInput from '@/components/chat-input/chat-input.vue'
import ChangesBanner from '@/components/changes-banner/changes-banner.vue'
import TemplateBinding from '@/components/template-binding/template-binding.vue'
import BibleSummary from '@/components/bible-summary/bible-summary.vue'

const workspaceStore = useWorkspaceStore()
const editorStore = useEditorStore()
const mangaStore = useMangaStore()
const agentStore = useAgentStore()
const storyStore = useStoriesStore()
const uiStore = useUiStore()

const activeTabIndex = ref(0)
const continuitySummary = ref('')
const agentInputText = ref('')
const localEditing = ref(false)
const colorModeIndex = ref(0)
const imageCountIndex = ref(1)

const agentScrollTarget = ref('')
const agentInitialized = ref(false)
const quickActions = ['阅读当前章节', '修改当前章节', '优化故事框架', '质量评估', '优化分镜脚本', '角色设定建议']

const imageCountOptions = [
  { label: '4张', value: 4 },
  { label: '6张', value: 6 },
  { label: '8张', value: 8 },
  { label: '10张', value: 10 },
  { label: '12张', value: 12 },
  { label: '15张', value: 15 },
  { label: '20张', value: 20 }
]

const storyId = ref(0)

// =================== 框架标签数据 ===================

// --- Data ---
const frameworkStory = ref<Story | null>(null)
const tags = ref<string[]>([])
const characters = ref<Character[]>([])
const charactersExpanded = ref(true)
const outlineActs = ref<OutlineAct[]>([])
const chapters = ref<OutlineChapter[]>([])
const chapterMap = ref<Map<number, Chapter>>(new Map())

// --- Description ---
const descEditing = ref(false)
const descDraft = ref('')
const savingDesc = ref(false)
const storyDesc = computed(() => frameworkStory.value?.description || '')

// --- Story Bible ---
const storyBible = computed(() => frameworkStory.value?.story_bible || {})

function onTemplateBound() {
  // 模板绑定后可刷新框架相关数据
}

function handleEditBible() {
  // 跳转到引导页面编辑创意简报
  if (storiesStore.activeStoryId) {
    uni.navigateTo({ url: `/pages/story/onboarding?storyId=${storiesStore.activeStoryId}` })
  }
}

function toggleDescEdit() {
  if (descEditing.value) return
  descDraft.value = frameworkStory.value?.description || ''
  descEditing.value = true
}
function cancelDescEdit() { descEditing.value = false }
async function saveDesc() {
  if (!frameworkStory.value) return
  savingDesc.value = true
  try {
    await storiesApi.updateStory(frameworkStory.value.id, { description: descDraft.value } as any)
    frameworkStory.value.description = descDraft.value
    descEditing.value = false
    uiStore.success('已保存')
  } catch (e: any) {
    uiStore.error(e.message || '保存失败')
  } finally { savingDesc.value = false }
}

// --- Tags ---
const hasTags = computed(() => tags.value.length > 0)

// --- Characters ---
const hasCharacters = computed(() => characters.value.length > 0)

// --- Framework AI Chat ---
const hasFramework = computed(() => outlineActs.value.length >= 2)
const chatInput = ref('')
const chatMessages = ref<FrameworkChatMessage[]>([])
const chatLoading = ref(false)
const chatError = ref('')
const showSnapshots = ref(false)
const snapshots = ref<FrameworkSnapshotItem[]>([])
const loadingSnapshots = ref(false)
const outlineExpandedAll = ref(true)

// --- 章节列表分页 ---
const pageSize = 20
const currentPage = ref(1)
const chapterJumpNum = ref('')

const totalPages = computed(() => Math.max(1, Math.ceil(chapters.value.length / pageSize)))

const paginatedChapters = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return chapters.value.slice(start, start + pageSize)
})

const chapterRangeText = computed(() => {
  if (chapters.value.length === 0) return '0 章'
  const start = (currentPage.value - 1) * pageSize + 1
  const end = Math.min(currentPage.value * pageSize, chapters.value.length)
  return `第 ${start}-${end} 章 / 共 ${chapters.value.length} 章`
})

const chatPlaceholder = computed(() =>
  hasFramework.value ? '告诉 AI 你希望如何修改故事框架...' : '输入故事描述，生成初始框架...'
)
const chatBtnLabel = computed(() =>
  chatLoading.value ? '处理中' : hasFramework.value ? '发送建议' : '生成框架'
)

let sseHandle: ReturnType<typeof useSSE> | null = null

function toggleSnapshots() {
  showSnapshots.value = !showSnapshots.value
  if (showSnapshots.value) loadSnapshots()
}

async function loadSnapshots() {
  if (!storyId.value) return
  loadingSnapshots.value = true
  try {
    const res = await frameworkApi.getSnapshots(storyId.value)
    snapshots.value = res.snapshots || []
  } catch { snapshots.value = []
  } finally { loadingSnapshots.value = false }
}

async function handleRestoreSnapshot(snapshotId: number) {
  if (!storyId.value) return
  uni.showModal({
    title: '确认回滚',
    content: '回滚将先保存当前状态再恢复所选版本，确认继续？',
    success: async (res) => {
      if (!res.confirm) return
      try {
        await frameworkApi.restoreSnapshot(storyId.value, snapshotId)
        uiStore.success('已回滚')
        await loadStoryData()
      } catch (e: any) {
        uiStore.error(e.message || '回滚失败')
      }
    }
  })
}

async function handleFrameworkChat() {
  const instruction = chatInput.value.trim()
  if (!instruction || chatLoading.value) return

  chatMessages.value.push({ role: 'user', content: instruction })
  chatInput.value = ''
  chatLoading.value = true
  chatError.value = ''

  if (!hasFramework.value && chatMessages.value.length === 1) {
    try {
      await frameworkApi.generateFramework(storyId.value, instruction)
      chatMessages.value.push({
        role: 'assistant',
        content: '已根据这段故事描述生成初始框架。你可以继续告诉 AI 想修改的方向。'
      })
      await loadStoryData()
    } catch (e: any) {
      chatError.value = e.message || '生成框架失败'
      chatMessages.value.pop()
    } finally { chatLoading.value = false }
    return
  }

  // SSE adjust
  const token = getToken()
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`

  let assistantContent = ''
  const sse = useSSE()
  sseHandle = sse
  sse.start({
    url: frameworkApi.adjustUrl(storyId.value),
    headers,
    body: { messages: chatMessages.value.map(m => ({ role: m.role, content: m.content })) },
    onEvent: (event) => {
      if (event.type === 'token') {
        assistantContent += (event.data as any).content || ''
        const last = chatMessages.value[chatMessages.value.length - 1]
        if (last?.role === 'assistant' && last !== chatMessages.value[0]) {
          last.content = assistantContent
        } else {
          chatMessages.value.push({ role: 'assistant', content: assistantContent })
        }
      } else if (event.type === 'done') {
        if (event.data?.content && assistantContent !== event.data.content) {
          const last = chatMessages.value[chatMessages.value.length - 1]
          if (last) last.content = event.data.content
        }
        chatLoading.value = false
        loadStoryData()
      } else if (event.type === 'error') {
        chatLoading.value = false
        chatError.value = (event.data as any)?.error || '请求失败'
      }
    },
    onError: () => { chatLoading.value = false; chatError.value = '网络错误' },
    onComplete: () => { chatLoading.value = false }
  })
}

async function handleContinueFramework() {
  if (!hasFramework.value || chatLoading.value) return
  chatLoading.value = true
  chatError.value = ''
  try {
    const res = await frameworkApi.continueFramework(storyId.value)
    chatMessages.value.push({ role: 'assistant', content: res.reply || '已续写完成' })
    await loadStoryData()
    await loadChapters()
  } catch (e: any) {
    chatError.value = e.message || '续写失败'
  } finally {
    chatLoading.value = false
  }
}

// --- Manual Edit ---
const manualEditing = ref(false)
const manualDraft = ref('')
const manualSaving = ref(false)
const manualError = ref('')

function toggleManualEdit() {
  manualEditing.value = !manualEditing.value
  if (manualEditing.value && frameworkStory.value) {
    manualDraft.value = JSON.stringify({
      description: frameworkStory.value.description || '',
      tags: frameworkStory.value.tags || {},
      characters: frameworkStory.value.characters || [],
      outline: frameworkStory.value.outline || {}
    }, null, 2)
  }
}
function cancelManualEdit() {
  manualEditing.value = false
  manualError.value = ''
}
async function saveManualEdit() {
  if (!frameworkStory.value) return
  manualSaving.value = true
  manualError.value = ''
  try {
    const parsed = JSON.parse(manualDraft.value)
    const payload: any = {}
    if ('description' in parsed) payload.description = parsed.description ?? ''
    if ('tags' in parsed) payload.tags = parsed.tags ?? {}
    if ('characters' in parsed) payload.characters = parsed.characters ?? []
    if ('outline' in parsed) payload.outline = parsed.outline ?? {}
    await storiesApi.updateStory(frameworkStory.value.id, payload)
    await loadStoryData()
    manualEditing.value = false
    uiStore.success('框架已保存')
  } catch (e: any) {
    manualError.value = e.message?.includes('JSON') ? e.message : '保存框架失败'
  } finally { manualSaving.value = false }
}

// --- Chapters ---
function chapterHasContent(ch: OutlineChapter): boolean {
  const actual = chapterMap.value.get(ch.chapter_number)
  return !!(actual?.novel_content?.trim()) || !!(actual?.messages?.length)
}

function getChapterStatus(ch: OutlineChapter): string {
  const actual = chapterMap.value.get(ch.chapter_number)
  if (!actual) return 'pending'
  if (actual.status === 'completed' || actual.novel_content) return 'completed'
  if (actual.novel_content) return 'draft'
  return 'pending'
}

function getChapterStatusLabel(ch: OutlineChapter): string {
  const labels: Record<string, string> = { pending: '待生成', draft: '草稿', completed: '已发布' }
  return labels[getChapterStatus(ch)] || '待生成'
}

function handleOpenChapter(ch: OutlineChapter) {
  handleChapterSelect(ch)
}

function handleChapterSelect(ch: OutlineChapter) {
  const actual = chapterMap.value.get(ch.chapter_number)
  if (actual) {
    workspaceStore.setActiveChapter(actual.id)
    activeTabIndex.value = 1
  }
}

async function handleGenerateChapter(ch: OutlineChapter) {
  const act = outlineActs.value.find(a => a.chapters.some(c => c.chapter_number === ch.chapter_number))
  if (!act) {
    uiStore.error('找不到所属幕')
    return
  }
  uiStore.setLoading(true)
  try {
    await frameworkApi.expandChapter(storyId.value, {
      act: String(act.act),
      chapter_number: ch.chapter_number,
      chapter_title: ch.title,
      summary: ch.summary || undefined,
    })
    uiStore.setLoading(false)
    uiStore.success('正文已生成')
    await loadStoryData()
    await loadChapters()
    handleChapterSelect(ch)
  } catch (e: any) {
    uiStore.setLoading(false)
    uiStore.error(e.message || '生成正文失败')
  }
}

async function handleAssessQuality(ch: OutlineChapter) {
  const actual = chapterMap.value.get(ch.chapter_number)
  if (!actual?.id) {
    uiStore.error('该章节尚未生成，无法评估')
    return
  }
  uiStore.setLoading(true)
  try {
    const result = await chaptersApi.qualityAssess(actual.id)
    uiStore.setLoading(false)
    const scores = result.scores || {}
    const lines = Object.entries(scores).map(([k, v]) => `${k}: ${v}/10`).join('\n')
    uni.showModal({ title: '质量评估', content: lines, showCancel: false })
  } catch (e: any) {
    uiStore.setLoading(false)
    uiStore.error(e.message || '评估失败')
  }
}

async function handleRegenerateChapters() {
  if (!storyId.value) return
  uiStore.setLoading(true)
  try {
    await frameworkApi.regenerateOutline(storyId.value)
    uiStore.setLoading(false)
    uiStore.success('章节已更新')
    await loadStoryData()
  } catch (e: any) {
    uiStore.setLoading(false)
    uiStore.error(e.message || '生成失败')
  }
}

// --- 章节列表分页与跳转 ---
function prevPage() {
  if (currentPage.value > 1) currentPage.value--
}

function nextPage() {
  if (currentPage.value < totalPages.value) currentPage.value++
}

function handleChapterJump() {
  const num = parseInt(chapterJumpNum.value)
  if (isNaN(num) || num < 1) {
    uiStore.error('请输入有效的章节号')
    return
  }
  const page = Math.ceil(num / pageSize)
  if (page < 1 || page > totalPages.value) {
    uiStore.error('章节号超出范围')
    return
  }
  currentPage.value = page
  chapterJumpNum.value = ''
}

// --- Load data ---
async function loadStoryData() {
  if (!storyId.value) return
  try {
    const s = await storiesApi.getStory(storyId.value)
    frameworkStory.value = s
    tags.value = extractTags(s.tags)
    characters.value = (s.characters || []) as Character[]
    const raw = s.outline as any
    outlineActs.value = (raw?.three_acts || []) as OutlineAct[]
  } catch (e: any) {
    uiStore.error(e.message || '加载框架失败')
  }
}

async function loadChapters() {
  if (!storyId.value) return
  try {
    const list = await chaptersApi.getChapters(storyId.value)
    chapterMap.value = new Map(list.map((c: Chapter) => [c.chapter_number, c]))
    chapters.value = buildChapterList(outlineActs.value, list)
    currentPage.value = 1
  } catch { /* ignore */ }
}

function extractTags(raw: Record<string, any> | null): string[] {
  if (!raw) return []
  const result: string[] = []
  Object.values(raw).forEach((val) => {
    if (Array.isArray(val)) result.push(...val.filter((v): v is string => typeof v === 'string'))
    else if (typeof val === 'string') result.push(val)
  })
  return [...new Set(result)]
}

function buildChapterList(acts: OutlineAct[], actualList: Chapter[]): OutlineChapter[] {
  const planned: OutlineChapter[] = []
  const seen = new Set<number>()

  for (const act of acts) {
    for (const ch of act.chapters) {
      if (ch.chapter_number) seen.add(ch.chapter_number)
      planned.push(ch)
    }
  }

  for (const ch of actualList) {
    if (!seen.has(ch.chapter_number)) {
      planned.push({
        chapter_number: ch.chapter_number,
        title: ch.title || `第 ${ch.chapter_number} 话`,
        summary: '',
        is_current: false
      })
    }
  }

  return planned.sort((a, b) => a.chapter_number - b.chapter_number)
}

// =================== 监听 ===================

// 监听章节切换，重新加载编辑器内容
watch(() => workspaceStore.activeChapterId, async (newId) => {
  if (newId) {
    await editorStore.loadContent(newId)
  }
})

// 首次切换到助手tab时，自动加载最近会话
watch(() => activeTabIndex.value, async (tabIndex) => {
  if (tabIndex !== 3 || agentInitialized.value) return
  agentInitialized.value = true
  if (!storyId.value) return
  try {
    await agentStore.loadConversations(storyId.value)
    if (agentStore.conversations.length > 0) {
      const latest = agentStore.conversations[0]
      await agentStore.loadConversation(storyId.value, latest.id)
    }
  } catch (e) {
    console.error('加载助手会话失败', e)
  }
})

// 助手自动滚动到最新消息
watch(() => agentStore.streamingContent, () => {
  nextTick(() => {
    agentScrollTarget.value = 'agent-scroll-bottom'
  })
})

watch(() => agentStore.messages.length, () => {
  nextTick(() => {
    agentScrollTarget.value = 'agent-scroll-bottom'
  })
})

// =================== 生命周期 ===================

onLoad(async (options) => {
  const id = parseInt(options?.storyId || '0')
  if (!id) {
    uiStore.error('未指定故事')
    return
  }
  storyId.value = id
  storyStore.setActiveStory(id)

  // 支持从框架页跳转到指定章节
  const targetChapterNumber = options?.chapterNumber ? parseInt(options.chapterNumber) : null

  // 如果有目标章节号，先设置避免 loadWorkspace 覆盖
  if (targetChapterNumber) {
    const chapterList = await chaptersApi.getChapters(id)
    const target = chapterList.find(c => c.chapter_number === targetChapterNumber)
    if (target) {
      workspaceStore.setActiveChapter(target.id)
    }
  }

  try {
    await Promise.all([
      workspaceStore.loadWorkspace(id),
      loadStoryData(),
    ])
    await loadChapters()

    if (workspaceStore.activeChapterId) {
      await editorStore.loadContent(workspaceStore.activeChapterId)
      await Promise.all([
        mangaStore.loadColorMode(workspaceStore.activeChapterId),
        mangaStore.loadImageCount(workspaceStore.activeChapterId),
        mangaStore.loadChapterManga(workspaceStore.activeChapterId)
      ])
    }

    colorModeIndex.value = mangaStore.colorMode === 'bw' ? 1 : 0
    const countIdx = imageCountOptions.findIndex(o => o.value === mangaStore.imageCount)
    if (countIdx !== -1) imageCountIndex.value = countIdx
  } catch (e) {
    console.error('加载工作台失败:', e)
    uiStore.error('加载工作台失败')
  }
})

// =================== 导航 ===================

function goBack() {
  uni.navigateBack()
}

function goChat() {
  const chapter = workspaceStore.activeChapter
  if (chapter) {
    uni.navigateTo({ url: `/pages/workspace/chat?chapterId=${chapter.id}` })
  }
}

function goCharacterProfiles() {
  uni.navigateTo({ url: `/pages/workspace/character-profiles?storyId=${storyId.value}` })
}

function goRefImages() {
  const chapter = workspaceStore.activeChapter
  if (chapter) {
    uni.navigateTo({ url: `/pages/workspace/ref-images?chapterId=${chapter.id}` })
  }
}

function goAgentHistory() {
  uni.navigateTo({ url: `/pages/workspace/agent-history?storyId=${storyId.value}` })
}

function goGallery(imageNumber: number) {
  const chapter = workspaceStore.activeChapter
  if (chapter) {
    uni.navigateTo({
      url: `/pages/workspace/manga-gallery?chapterId=${chapter.id}&imageNumber=${imageNumber}`
    })
  }
}

// =================== 编辑标签 ===================

function startLocalEdit() {
  const chapter = workspaceStore.activeChapter
  if (chapter) {
    editorStore.startEditing()
    localEditing.value = true
  }
}

function handleEditorInput(e: any) {
  editorStore.updateDraft(e.detail.value)
}

function cancelLocalEdit() {
  editorStore.cancelEditing()
  localEditing.value = false
}

async function saveLocalEdit() {
  const chapter = workspaceStore.activeChapter
  if (!chapter) return
  await editorStore.saveContent(chapter.id)
  localEditing.value = false
  uni.showToast({ title: '已保存', icon: 'success' })
}

async function handleQualityAssess() {
  const chapter = workspaceStore.activeChapter
  if (!chapter) return
  try {
    const result = await chaptersApi.qualityAssess(chapter.id)
    const scores = result.scores || {}
    const lines = Object.entries(scores).map(([k, v]) => `${k}: ${v}/10`).join('\n')
    uni.showModal({
      title: '质量评估',
      content: lines || `综合评分: ${scores.overall || 'N/A'}`,
      showCancel: false
    })
  } catch (e: any) {
    uiStore.error(e.message || '评估失败')
  }
}

// =================== 漫画标签 ===================

function handleColorModeChange(e: any) {
  colorModeIndex.value = e.detail.value
  const mode = colorModeIndex.value === 0 ? 'color' : 'bw'
  const chapter = workspaceStore.activeChapter
  if (chapter) {
    mangaStore.saveColorMode(chapter.id, mode as 'color' | 'bw')
  }
}

function handleImageCountChange(e: any) {
  imageCountIndex.value = e.detail.value
  const count = imageCountOptions[imageCountIndex.value].value
  const chapter = workspaceStore.activeChapter
  if (chapter) {
    mangaStore.saveImageCount(chapter.id, count)
  }
}

async function handleGenerateManga() {
  const chapter = workspaceStore.activeChapter
  if (!chapter) {
    uiStore.error('请先选择章节')
    return
  }
  await mangaStore.startMangaGeneration(chapter.id)
}

// =================== 助手标签 ===================

async function startNewAgentConversation() {
  if (!storyId.value) return
  try {
    await agentStore.createConversation(storyId.value)
    agentStore.messages = [{ id: 'welcome', role: 'assistant', content: '我是你的AI写作助手，有什么可以帮到你的？' }]
  } catch (e: any) {
    uiStore.error(e.message || '创建失败')
  }
}

async function handleAgentSend(text: string) {
  if (!text.trim() || !storyId.value) return
  agentInputText.value = ''
  try {
    const chapter = workspaceStore.activeChapter
    await agentStore.sendMessage(storyId.value, text, chapter?.id)
  } catch (e: any) {
    uiStore.error(e.message || '发送消息失败')
  }
}

function handleViewChanges() {
  const changes = agentStore.pendingChanges
  if (changes.length === 0) return
  const text = changes.map((c, i) =>
    `${i + 1}. ${c.description}\n${c.diff}`
  ).join('\n\n')
  uni.showModal({ title: '待确认的修改', content: text })
}

async function handleConfirmChanges() {
  try {
    await agentStore.confirmChanges(storyId.value)
    uiStore.success('变更已确认')
  } catch (e: any) {
    uiStore.error(e.message || '确认失败')
  }
}

async function handleRollbackChanges() {
  try {
    await agentStore.rollbackChanges(storyId.value)
    uiStore.success('变更已撤回')
  } catch (e: any) {
    uiStore.error(e.message || '撤回失败')
  }
}

function sendQuickAction(action: string) {
  handleAgentSend(action)
}

// =================== 更多菜单 ===================

function showMore() {
  uni.showActionSheet({
    itemList: ['角色外观', '连贯性记忆', '质量评估', '参考图'],
    success: (res) => {
      switch (res.tapIndex) {
        case 0: goCharacterProfiles(); break
        case 1: {
          const chapter = workspaceStore.activeChapter
          if (chapter) {
            uni.navigateTo({ url: `/pages/workspace/continuity?chapterId=${chapter.id}` })
          }
          break
        }
        case 2: handleQualityAssess(); break
        case 3: goRefImages(); break
      }
    }
  })
}

function showEditorMore() {
  uni.showActionSheet({
    itemList: ['重写选段', '调整内容', '扩写章节'],
    success: (res) => {
      if (res.tapIndex === 0 || res.tapIndex === 1 || res.tapIndex === 2) {
        goChat()
      }
    }
  })
}
</script>

<style lang="scss" scoped>
.chapter-view {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__navbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 88rpx;
    padding: 0 $lv-page-padding;
    padding-top: var(--status-bar-height);
    @include lv-glass-navbar;
    z-index: 10;
  }

  &__navbar-left,
  &__navbar-right {
    display: flex;
    gap: 16rpx;
  }

  &__navbar-btn {
    width: 48rpx;
    height: 48rpx;
    @include flex-center;
  }

  &__navbar-center {
    flex: 1;
    text-align: center;
  }

  &__navbar-title {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__edit-panel {
    display: flex;
    flex-direction: column;
    height: 100%;
  }

  &__tab-scroll {
    flex: 1;
    overflow: hidden;
  }

  &__tab {
    padding: $lv-page-padding;
  }

  &__chapter-title {
    display: block;
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 16rpx;
  }

  &__divider {
    height: 1rpx;
    background: $lv-border-light;
    margin-bottom: 16rpx;
  }

  &__content {
    font-size: $lv-font-base;
    color: $lv-text-primary;
    line-height: 1.8;
    white-space: pre-wrap;
  }

  &__editor-textarea {
    width: 100%;
    min-height: 300rpx;
    padding: 24rpx;
    font-size: 32rpx;
    line-height: 1.8;
    color: $lv-text-primary;
    background: $lv-surface-solid;
    border: 2rpx solid $lv-primary;
    border-radius: $lv-radius-md;
    box-sizing: border-box;
  }

  &__editor-actions {
    display: flex;
    gap: 16rpx;
    justify-content: flex-end;
    margin-top: 16rpx;
  }

  &__word-count {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
    margin-top: 24rpx;
  }

  &__loading {
    display: flex;
    justify-content: center;
    padding: 48rpx 0;
  }

  &__editor-toolbar {
    display: flex;
    align-items: center;
    gap: 12rpx;
    padding: 16rpx;
    background: $lv-surface-solid;
    border-top: 1rpx solid $lv-border-light;
    @include safe-area-bottom(16rpx);
  }

  &__more {
    width: 64rpx;
    height: 64rpx;
    @include flex-center;
    color: $lv-text-secondary;
  }

  &__manga-settings {
    display: flex;
    align-items: center;
    gap: 16rpx;
    margin-bottom: 16rpx;
  }

  &__manga-label {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__manga-picker {
    font-size: $lv-font-sm;
    color: $lv-primary;
    background: $lv-primary-light;
    padding: 8rpx 16rpx;
    border-radius: $lv-radius-full;
  }

  &__manga-progress {
    margin: 16rpx 0;
    padding: 24rpx;
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
  }

  &__manga-status {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    margin-top: 12rpx;
  }

  &__scenes {
    margin: 16rpx 0;
  }

  &__scene-item {
    display: flex;
    gap: 12rpx;
    padding: 12rpx 0;
    border-bottom: 1rpx solid $lv-border-light;
  }

  &__scene-num {
    font-size: $lv-font-sm;
    color: $lv-primary;
    font-weight: 600;
    flex-shrink: 0;
  }

  &__scene-text {
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    line-height: 1.6;
  }

  &__manga-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16rpx;
    margin: 16rpx 0;
  }

  &__manga-links {
    display: flex;
    gap: 16rpx;
    margin-top: 16rpx;
  }

  &__agent-wrapper {
    display: flex;
    flex-direction: column;
    height: 100%;
  }

  &__agent-header {
    display: flex;
    gap: 16rpx;
    padding: 16rpx $lv-page-padding;
    padding-top: 8rpx;
    flex-shrink: 0;
  }

  &__agent-quick {
    padding: 0 $lv-page-padding 16rpx;
    flex-shrink: 0;
  }

  &__quick-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12rpx;
  }

  &__quick-btn {
    padding: 20rpx;
    background: $lv-surface-solid;
    border: 1rpx solid $lv-border;
    border-radius: $lv-radius-sm;
    text-align: center;
    &:active { background: $lv-primary-lighter; }
  }

  &__quick-text {
    font-size: $lv-font-sm;
    color: $lv-text-primary;
  }

  &__agent-messages {
    flex: 1;
    min-height: 0;
    padding: 0 $lv-page-padding;
    overflow: hidden;
  }
}

// =================== Framework 卡片样式 ===================

.fp {
  &__section {
    margin-bottom: 20rpx;
  }

  &__card {
    background: $lv-surface-solid;
    border-radius: 20rpx;
    overflow: hidden;
  }

  &__section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 24rpx;
    border-bottom: 1rpx solid $lv-border-light;
    cursor: pointer;
    &:active { opacity: 0.7; }
  }

  &__section-title {
    display: flex;
    align-items: center;
    gap: 10rpx;
  }

  &__section-label {
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__section-body {
    padding: 24rpx;
  }

  &__header-actions {
    display: flex;
    align-items: center;
    gap: 16rpx;
  }

  &__header-btn {
    font-size: 22rpx;
    color: $lv-primary;
    display: inline-flex;
    align-items: center;
    &:active { opacity: 0.6; }
  }

  &__badge {
    font-size: 20rpx;
    color: #15803d;
    background: #dcfce7;
    padding: 4rpx 16rpx;
    border-radius: 20rpx;
  }

  &__desc-text {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    line-height: 1.6;
  }

  &__textarea {
    width: 100%;
    padding: 20rpx;
    font-size: $lv-font-sm;
    line-height: 1.6;
    color: $lv-text-primary;
    background: $lv-bg-start;
    border: 2rpx solid $lv-border;
    border-radius: $lv-radius-sm;
    min-height: 160rpx;
    box-sizing: border-box;
    &--mono {
      font-family: monospace;
      font-size: 20rpx;
      min-height: 300rpx;
    }
  }

  &__actions {
    display: flex;
    gap: 16rpx;
    justify-content: flex-end;
    margin-top: 16rpx;
  }

  &__tags {
    display: flex;
    flex-wrap: wrap;
    gap: 12rpx;
  }

  // --- Chat ---
  &__chat-area {
    padding: 16rpx 24rpx;
    max-height: 300rpx;
    overflow-y: auto;
  }

  &__chat-hint {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
    line-height: 1.6;
  }

  &__chat-msg {
    margin-bottom: 16rpx;
    display: flex;
    &--user { justify-content: flex-end; }
    &--assistant { justify-content: flex-start; }
  }

  &__chat-bubble {
    max-width: 85%;
    padding: 16rpx 20rpx;
    border-radius: 16rpx;
    font-size: $lv-font-sm;
    line-height: 1.6;
    .fp__chat-msg--user & {
      background: $lv-primary;
      color: $lv-text-on-primary;
      border-radius: 16rpx 16rpx 4rpx 16rpx;
    }
    .fp__chat-msg--assistant & {
      background: #f0f4ff;
      color: $lv-text-primary;
      border: 1rpx solid $lv-border-light;
      border-radius: 16rpx 16rpx 16rpx 4rpx;
    }
  }

  &__chat-text { white-space: pre-wrap; }

  &__chat-cursor {
    display: inline-block;
    width: 4rpx;
    height: 24rpx;
    background: $lv-primary;
    animation: fpPulse 1s infinite;
    vertical-align: middle;
    margin-left: 4rpx;
  }

  &__chat-input-row {
    display: flex;
    align-items: center;
    gap: 12rpx;
    padding: 16rpx 24rpx;
    border-top: 1rpx solid $lv-border-light;
  }

  &__chat-input {
    flex: 1;
    height: 60rpx;
    padding: 0 16rpx;
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    background: $lv-primary-lighter;
    border-radius: $lv-radius-lg;
    box-sizing: border-box;
  }

  // --- Snapshots ---
  &__snapshots {
    border-bottom: 1rpx solid $lv-border-light;
    max-height: 400rpx;
    overflow-y: auto;
  }

  &__snapshot-list {
    padding: 16rpx 24rpx;
  }

  &__snapshot-item {
    display: flex;
    align-items: center;
    gap: 12rpx;
    padding: 12rpx 0;
    border-bottom: 1rpx solid $lv-border-light;
    font-size: $lv-font-sm;
    &:last-child { border-bottom: none; }
  }

  &__snapshot-num {
    color: $lv-text-muted;
    font-family: monospace;
  }

  &__snapshot-time {
    color: $lv-text-secondary;
  }

  &__snapshot-desc {
    flex: 1;
    color: $lv-text-muted;
    @include text-ellipsis;
  }

  // --- Chapter list ---
  &__chapter-item {
    padding: 16rpx 0;
    border-bottom: 1rpx solid $lv-border-light;
    &:last-child { border-bottom: none; }
  }

  &__chapter-header {
    display: flex;
    align-items: center;
    gap: 12rpx;
  }

  &__chapter-num {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
    font-family: monospace;
    min-width: 64rpx;
  }

  &__chapter-title {
    flex: 1;
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    @include text-ellipsis;
  }

  &__chapter-status {
    font-size: 20rpx;
    padding: 2rpx 12rpx;
    border-radius: 12rpx;
    &--pending { background: #f1f5f9; color: #64748b; }
    &--draft { background: #fef3c7; color: #92400e; }
    &--completed { background: #dcfce7; color: #15803d; }
  }

  &__chapter-actions {
    display: flex;
    gap: 12rpx;
    margin-top: 12rpx;
    padding-left: 64rpx;
  }

  &__chapter-btn {
    font-size: 20rpx;
    color: $lv-primary;
    padding: 4rpx 16rpx;
    background: #eff6ff;
    border-radius: 12rpx;
    &:active { opacity: 0.6; }
    &--primary {
      background: $lv-primary;
      color: #fff;
    }
  }

  // --- Common ---
  &__empty-row { padding: 24rpx 0; text-align: center; }
  &__empty-text { font-size: $lv-font-sm; color: $lv-text-muted; }
  &__loading-row { padding: 24rpx 0; @include flex-center; }
  &__error { display: block; padding: 0 24rpx 16rpx; font-size: $lv-font-sm; color: #dc2626; }
  &__bottom-spacer { height: 80rpx; }

  // --- Jump bar ---
  &__jump-bar {
    display: flex;
    align-items: center;
    gap: 12rpx;
    margin-bottom: 16rpx;
  }
  &__jump-input {
    flex: 1;
    height: 60rpx;
    padding: 0 16rpx;
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    background: $lv-primary-lighter;
    border-radius: $lv-radius-lg;
    box-sizing: border-box;
  }

  // --- Pagination ---
  &__pagination {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16rpx;
    margin-top: 20rpx;
    padding-top: 16rpx;
    border-top: 1rpx solid $lv-border-light;
  }
  &__page-btn {
    font-size: 22rpx;
    color: $lv-primary;
    padding: 8rpx 24rpx;
    background: #eff6ff;
    border-radius: 12rpx;
    &:active { opacity: 0.6; }
    &--disabled {
      color: $lv-text-muted;
      background: #f1f5f9;
      pointer-events: none;
    }
  }
  &__page-info {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }
}

@keyframes fpPulse {
  0% { opacity: 1; }
  50% { opacity: 0.3; }
  100% { opacity: 1; }
}
</style>
