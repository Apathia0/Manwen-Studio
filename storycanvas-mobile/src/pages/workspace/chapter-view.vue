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
      :tabs="['创作', '正文']"
      v-model:current="activeTabIndex"
    >
      <!-- 创作首页 -->
      <template #tab-0>
        <scroll-view scroll-y class="chapter-view__tab-scroll">
          <view class="chapter-view__tab">
            <view class="creation-home__chapter">
              <view>
                <text class="creation-home__eyebrow">正在创作</text>
                <text class="creation-home__title">{{ workspaceStore.activeChapterTitle || '选择一个章节开始创作' }}</text>
                <text class="creation-home__meta">共 {{ editorStore.wordCount }} 字 · {{ editorStore.content ? '正文已生成' : '等待生成正文' }}</text>
              </view>
              <lv-button size="sm" @tap="openCurrentEditor">继续编辑</lv-button>
            </view>

            <view class="creation-home__agent" @tap="openAgentTask('自由对话')">
              <view class="creation-home__agent-icon">
                <lv-icon name="Bot" :size="22" color="#ffffff" />
              </view>
              <view class="creation-home__agent-copy">
                <text class="creation-home__section-title">AI 创作助手</text>
                <text class="creation-home__section-desc">生成章节、调整大纲设定，或讨论创作问题</text>
              </view>
              <view class="creation-home__agent-open">
                <lv-icon name="ChevronRight" :size="18" color="#2563eb" />
              </view>
            </view>

            <view class="creation-home__section-head">
              <view>
                <text class="creation-home__section-title">按大纲创作正文</text>
                <text class="creation-home__section-desc">选择已有章节规划，直接生成对应正文</text>
              </view>
              <view class="creation-home__section-link" @tap="openFrameworkEditor">
                <text>管理大纲</text>
                <lv-icon name="ChevronRight" :size="14" color="#2563eb" />
              </view>
            </view>
            <view class="creation-home__chapter-plan">
              <template v-if="plannedChapters.length > 0">
                <view class="creation-home__chapter-plan-summary">
                  <text>{{ plannedChapterRangeText }}</text>
                  <text>{{ plannedChapters.filter(chapterHasContent).length }} 章已有正文</text>
                </view>
                <view
                  v-for="ch in paginatedPlannedChapters"
                  :key="`creation-${ch.chapter_number}`"
                  class="creation-home__chapter-plan-item"
                >
                  <view class="creation-home__chapter-plan-copy">
                    <view class="creation-home__chapter-plan-title-row">
                      <text class="creation-home__chapter-plan-num">第 {{ ch.chapter_number }} 章</text>
                      <text class="creation-home__chapter-plan-title">{{ ch.title }}</text>
                    </view>
                    <text v-if="ch.summary" class="creation-home__chapter-plan-desc">{{ ch.summary }}</text>
                    <text v-else-if="ch.key_events?.length" class="creation-home__chapter-plan-desc">{{ ch.key_events.join('、') }}</text>
                  </view>
                  <view
                    v-if="chapterHasContent(ch)"
                    class="creation-home__chapter-plan-action creation-home__chapter-plan-action--open"
                    @tap="handleOpenChapter(ch)"
                  >
                    <lv-icon name="BookOpen" :size="13" color="#2563eb" />
                    <text>打开</text>
                  </view>
                  <view
                    v-else
                    :class="[
                      'creation-home__chapter-plan-action',
                      {
                        'creation-home__chapter-plan-action--loading': generatingChapterNum === ch.chapter_number,
                        'creation-home__chapter-plan-action--disabled': generatingChapterNum !== 0 && generatingChapterNum !== ch.chapter_number,
                      },
                    ]"
                    @tap="handleGenerateChapterTap(ch)"
                  >
                    <view v-if="generatingChapterNum === ch.chapter_number" class="fp__chapter-btn-spinner" />
                    <lv-icon v-else name="Sparkles" :size="13" color="#ffffff" />
                    <text>{{ generatingChapterNum === ch.chapter_number ? '生成中' : '生成正文' }}</text>
                  </view>
                </view>
                <view v-if="plannedTotalPages > 1" class="creation-home__chapter-plan-pagination">
                  <view
                    :class="['creation-home__chapter-plan-page', { 'creation-home__chapter-plan-page--disabled': plannedCurrentPage <= 1 }]"
                    @tap="prevPlannedPage"
                  >
                    <lv-icon name="ChevronLeft" :size="14" />
                    <text>上一页</text>
                  </view>
                  <text class="creation-home__chapter-plan-page-info">{{ plannedCurrentPage }} / {{ plannedTotalPages }}</text>
                  <view
                    :class="['creation-home__chapter-plan-page', { 'creation-home__chapter-plan-page--disabled': plannedCurrentPage >= plannedTotalPages }]"
                    @tap="nextPlannedPage"
                  >
                    <text>下一页</text>
                    <lv-icon name="ChevronRight" :size="14" />
                  </view>
                </view>
              </template>
              <view v-else class="creation-home__chapter-plan-empty">
                <lv-icon name="ListTree" :size="24" color="#94a3b8" />
                <view class="creation-home__chapter-plan-empty-copy">
                  <text class="creation-home__shortcut-title">暂无章节规划</text>
                  <text class="creation-home__shortcut-desc">先在大纲与框架中规划章节，再按章生成正文</text>
                </view>
                <view class="creation-home__section-link" @tap="openFrameworkEditor">
                  <text>去规划</text>
                </view>
              </view>
            </view>

            <view class="creation-home__section-head">
              <text class="creation-home__section-title">创作资料</text>
            </view>
            <view class="creation-home__shortcut-grid">
              <view class="creation-home__shortcut" @tap="openFrameworkEditor">
                <view class="creation-home__shortcut-icon creation-home__shortcut-icon--outline">
                  <lv-icon name="ListTree" :size="20" color="#2563eb" />
                </view>
                <text class="creation-home__shortcut-title">大纲与框架</text>
                <text class="creation-home__shortcut-desc">章节安排、角色与标签</text>
              </view>
              <view class="creation-home__shortcut" @tap="handleEditBible">
                <view class="creation-home__shortcut-icon creation-home__shortcut-icon--bible">
                  <lv-icon name="BookOpen" :size="20" color="#7c3aed" />
                </view>
                <text class="creation-home__shortcut-title">作品圣经</text>
                <text class="creation-home__shortcut-desc">查看和编辑模块化摘要</text>
              </view>
              <view class="creation-home__shortcut" @tap="toggleMaterialPanel('cover')">
                <view class="creation-home__shortcut-icon creation-home__shortcut-icon--cover">
                  <lv-icon name="ImagePlus" :size="20" color="#be123c" />
                </view>
                <text class="creation-home__shortcut-title">封面与模板</text>
                <text class="creation-home__shortcut-desc">设置作品封面和创作模板</text>
              </view>
              <view class="creation-home__shortcut" @tap="toggleMaterialPanel('deconstruction')">
                <view class="creation-home__shortcut-icon creation-home__shortcut-icon--reference">
                  <lv-icon name="Library" :size="20" color="#b45309" />
                </view>
                <text class="creation-home__shortcut-title">拆书引用</text>
                <text class="creation-home__shortcut-desc">管理引用的拆书分析报告</text>
              </view>
              <view class="creation-home__shortcut" @tap="toggleMaterialPanel('history')">
                <view class="creation-home__shortcut-icon creation-home__shortcut-icon--history">
                  <lv-icon name="History" :size="20" color="#047857" />
                </view>
                <text class="creation-home__shortcut-title">版本记录</text>
                <text class="creation-home__shortcut-desc">查看并回滚框架历史版本</text>
              </view>
              <view class="creation-home__shortcut" @tap="activeTabIndex = 1">
                <view class="creation-home__shortcut-icon creation-home__shortcut-icon--chapter">
                  <lv-icon name="BookOpenText" :size="20" color="#475569" />
                </view>
                <text class="creation-home__shortcut-title">章节正文</text>
                <text class="creation-home__shortcut-desc">切换章节、阅读和编辑正文</text>
              </view>
            </view>

            <view v-if="activeMaterialPanel === 'cover'" class="creation-home__material-panel">
              <view class="creation-home__panel-head">
                <view>
                  <text class="creation-home__section-title">封面与创作模板</text>
                  <text class="creation-home__section-desc">这些设置会应用到当前作品</text>
                </view>
                <view class="creation-home__panel-close" @tap="activeMaterialPanel = ''">
                  <lv-icon name="X" :size="18" color="#64748b" />
                </view>
              </view>
              <view class="fp__cover-banner" @tap="handleCoverEdit">
                <image
                  v-if="storyStore.activeStory?.cover_image"
                  :src="coverImageUrl(storyStore.activeStory.cover_image) || ''"
                  class="fp__cover-img"
                  mode="aspectFill"
                />
                <view v-else class="fp__cover-placeholder">
                  <lv-icon name="ImagePlus" :size="28" color="#94a3b8" />
                  <text class="fp__cover-text">设置封面</text>
                </view>
                <view class="fp__cover-info">
                  <text class="fp__cover-title">{{ storyStore.activeStory?.title || '未命名' }}</text>
                  <text class="fp__cover-edit">点击编辑封面</text>
                </view>
              </view>
              <template-binding
                v-if="storyStore.activeStoryId"
                :story-id="storyStore.activeStoryId"
                @bound="onTemplateBound"
              />
            </view>

            <view v-if="activeMaterialPanel === 'deconstruction'" class="creation-home__material-panel">
              <view class="creation-home__panel-head">
                <view>
                  <text class="creation-home__section-title">拆书报告引用</text>
                  <text class="creation-home__section-desc">选择可供 Agent 和正文生成参考的报告</text>
                </view>
                <view class="creation-home__panel-close" @tap="activeMaterialPanel = ''">
                  <lv-icon name="X" :size="18" color="#64748b" />
                </view>
              </view>
              <deconstruction-refs v-if="storyId" :story-id="storyId" @changed="loadStoryData" />
            </view>

            <view v-if="activeMaterialPanel === 'history'" class="creation-home__material-panel">
              <view class="creation-home__panel-head">
                <view>
                  <text class="creation-home__section-title">框架历史版本</text>
                  <text class="creation-home__section-desc">回滚会恢复当时的故事框架内容</text>
                </view>
                <view class="creation-home__panel-close" @tap="activeMaterialPanel = ''">
                  <lv-icon name="X" :size="18" color="#64748b" />
                </view>
              </view>
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
                  <lv-button size="sm" secondary @tap="handleRestoreSnapshot(snap.id)" :loading="restoringSnapshot === snap.id" :disabled="restoringSnapshot > 0">回滚</lv-button>
                </view>
              </view>
            </view>

            <view class="creation-home__section-head">
              <text class="creation-home__section-title">拓展创作</text>
              <text class="creation-home__section-desc">按需使用，不影响小说创作</text>
            </view>
            <view class="creation-home__extension-list">
              <view class="creation-home__extension" @tap="openMangaWorkspace">
                <view class="creation-home__extension-icon creation-home__extension-icon--manga">
                  <lv-icon name="Images" :size="20" color="#be123c" />
                </view>
                <view class="creation-home__extension-copy">
                  <text class="creation-home__shortcut-title">漫画创作</text>
                  <text class="creation-home__shortcut-desc">分镜、风格、角色参考与出图</text>
                </view>
                <lv-icon name="ChevronRight" :size="18" color="#94a3b8" />
              </view>
              <view class="creation-home__extension" @tap="openVideoWorkspace">
                <view class="creation-home__extension-icon creation-home__extension-icon--video">
                  <lv-icon name="Clapperboard" :size="20" color="#047857" />
                </view>
                <view class="creation-home__extension-copy">
                  <text class="creation-home__shortcut-title">视频创作</text>
                  <text class="creation-home__shortcut-desc">剧本、镜头、素材与视频生成</text>
                </view>
                <lv-icon name="ChevronRight" :size="18" color="#94a3b8" />
              </view>
            </view>

            <view v-if="false">
            <!-- 封面 banner -->
            <view class="fp__cover-banner" @tap="handleCoverEdit">
              <image
                v-if="storyStore.activeStory?.cover_image"
                :src="coverImageUrl(storyStore.activeStory?.cover_image ?? null) || ''"
                class="fp__cover-img"
                mode="aspectFill"
              />
              <view v-else class="fp__cover-placeholder">
                <lv-icon name="ImagePlus" :size="32" color="#94a3b8" />
                <text class="fp__cover-text">设置封面</text>
              </view>
              <view class="fp__cover-info">
                <text class="fp__cover-title">{{ storyStore.activeStory?.title || '未命名' }}</text>
                <text class="fp__cover-edit">点击编辑封面</text>
              </view>
            </view>

            <!-- 模板绑定 -->
            <template-binding
              v-if="storyStore.activeStoryId"
              :story-id="storyStore.activeStoryId!"
              @bound="onTemplateBound"
            />

            <!-- 创意简报 -->
            <bible-summary
              v-if="storyBible && Object.keys(storyBible).length > 0"
              :bible="storyBible"
              :editable="true"
              @edit="handleEditBible"
            />
            <deconstruction-refs v-if="storyId" :story-id="storyId" @changed="loadStoryData" />

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

            <!-- 框架历史版本 -->
            <view class="fp__section fp__card">
              <view class="fp__section-header">
                <view class="fp__section-title">
                  <lv-icon name="History" :size="16" color="#2563eb" />
                  <text class="fp__section-label">框架历史版本</text>
                </view>
                <view class="fp__header-actions">
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
                    <lv-button size="sm" secondary @tap="handleRestoreSnapshot(snap.id)" :loading="restoringSnapshot === snap.id" :disabled="restoringSnapshot > 0">回滚</lv-button>
                  </view>
                </view>
              </view>
            </view>

            <!-- 框架编辑器入口 -->
            <view class="fp__section fp__card">
              <view class="fp__section-header" @tap="openFrameworkEditor">
                <view class="fp__section-title">
                  <lv-icon name="Pencil" :size="16" color="#2563eb" />
                  <text class="fp__section-label">打开框架编辑器</text>
                </view>
                <lv-icon name="ChevronRight" :size="14" color="#94a3b8" />
              </view>
              <view class="fp__section-body">
                <text class="fp__desc-text">打开包含预览区和编辑区的框架编辑器，可视化编辑故事描述、标签、角色和大纲。</text>
              </view>
            </view>

            <!-- 标签 -->
            <view class="fp__section fp__card">
              <view class="fp__section-header" @tap="tagsExpanded = !tagsExpanded">
                <view class="fp__section-title">
                  <lv-icon name="Tag" :size="16" color="#64748b" />
                  <text class="fp__section-label">标签设定</text>
                </view>
                <view class="fp__header-actions">
                  <text class="fp__header-btn" @tap.stop="handleRegenerateTags" :class="{ 'fp__header-btn--disabled': regeneratingTags }">
                    <lv-icon v-if="regeneratingTags" name="Loader" :size="12" color="#2563eb" style="margin-right: 4rpx; animation: spin 1s linear infinite;" />
                    <lv-icon v-else name="Sparkles" :size="12" color="#2563eb" style="margin-right: 4rpx;" />{{ regeneratingTags ? '生成中...' : 'AI 生成' }}
                  </text>
                  <text class="fp__badge" v-if="hasTags">已生成</text>
                  <lv-icon :name="tagsExpanded ? 'ChevronUp' : 'ChevronDown'" :size="14" color="#94a3b8" />
                </view>
              </view>
              <view v-if="tagsExpanded" class="fp__section-body">
                <view v-if="frameworkStory?.tags && typeof frameworkStory?.tags === 'object'" class="fp__tag-edit-list">
                  <view v-for="(val, key) in (frameworkStory?.tags as Record<string, any>)" :key="key" class="fp__tag-edit-row">
                    <text class="fp__tag-edit-label">{{ ({ type: '类型', theme: '主题', style: '风格', audience: '受众' } as Record<string, string>)[key] || key }}</text>
                    <template v-if="editingTagKey === key">
                      <input class="fp__tag-edit-input" v-model="editingTagDraft" :placeholder="'输入' + key" />
                      <lv-button size="sm" @tap="saveTagEdit">保存</lv-button>
                      <lv-button size="sm" secondary @tap="cancelTagEdit">取消</lv-button>
                    </template>
                    <text v-else class="fp__tag-edit-value" @tap="startTagEdit(key, typeof val === 'string' ? val : '')">{{ typeof val === 'string' && val ? val : '未设置' }}</text>
                  </view>
                </view>
                <view v-else class="fp__tags">
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
                  <text class="fp__header-btn" @tap.stop="handleRegenerateCharacters" :class="{ 'fp__header-btn--disabled': regeneratingChars }">
                    <lv-icon v-if="regeneratingChars" name="Loader" :size="12" color="#2563eb" style="margin-right: 4rpx; animation: spin 1s linear infinite;" />
                    <lv-icon v-else name="Sparkles" :size="12" color="#2563eb" style="margin-right: 4rpx;" />{{ regeneratingChars ? '生成中...' : 'AI 生成' }}
                  </text>
                  <text class="fp__badge" v-if="hasCharacters">{{ characters.length }} 个</text>
                  <lv-icon :name="charactersExpanded ? 'ChevronUp' : 'ChevronDown'" :size="14" color="#94a3b8" />
                </view>
              </view>
              <view v-if="charactersExpanded" class="fp__section-body">
                <template v-for="(char, ci) in characters" :key="char.name">
                  <character-card v-if="editingCharIndex !== ci" :character="char" />
                  <view v-else class="fp__char-edit-card">
                    <view class="fp__char-edit-field">
                      <text class="fp__char-edit-label">名称</text>
                      <input class="fp__char-edit-input" v-model="editingCharDraft!.name" placeholder="角色名" />
                    </view>
                    <view class="fp__char-edit-field">
                      <text class="fp__char-edit-label">角色</text>
                      <input class="fp__char-edit-input" v-model="editingCharDraft!.role" placeholder="主角/反派/配角" />
                    </view>
                    <view class="fp__char-edit-field">
                      <text class="fp__char-edit-label">描述</text>
                      <textarea class="fp__char-edit-textarea" v-model="editingCharDraft!.description" placeholder="角色描述..." />
                    </view>
                    <view class="fp__actions">
                      <lv-button size="sm" secondary @tap="cancelCharEdit">取消</lv-button>
                      <lv-button size="sm" @tap="saveCharEdit">保存</lv-button>
                    </view>
                  </view>
                  <view class="fp__char-edit-trigger" v-if="editingCharIndex !== ci" @tap="startCharEdit(ci)">
                    <lv-icon name="Pencil" :size="12" color="#2563eb" /><text class="fp__char-edit-trigger-text">编辑</text>
                  </view>
                </template>
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
                  <text class="fp__empty-text">暂无大纲，请打开框架编辑器补充，或使用 AI 创作助手生成内容。</text>
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
                  <view class="fp__header-btn" :class="{ 'fp__header-btn--disabled': regeneratingChapters }" @tap="!regeneratingChapters && handleRegenerateChapters()" v-if="chapters.length > 0">
                    <lv-icon v-if="regeneratingChapters" name="Loader" :size="12" color="#64748b" style="margin-right: 4rpx; animation: spin 1s linear infinite;" />
                    <lv-icon v-else name="RefreshCw" :size="12" color="#64748b" style="margin-right: 4rpx;" />{{ regeneratingChapters ? '生成中...' : 'AI 生成章节' }}
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
                      </template>
                        <view
                          v-else
                          :class="['fp__chapter-btn', 'fp__chapter-btn--primary', { 'fp__chapter-btn--loading': generatingChapterNum === ch.chapter_number }]"
                          @tap="handleGenerateChapterTap(ch)"
                        >
                          <view v-if="generatingChapterNum === ch.chapter_number" class="fp__chapter-btn-spinner" />
                          <text>{{ generatingChapterNum === ch.chapter_number ? '生成中...' : '生成正文' }}</text>
                        </view>
                    </view>
                  </view>
                  <view v-if="totalPages > 1" class="fp__pagination">
                    <text class="fp__page-btn" :class="{ 'fp__page-btn--disabled': currentPage <= 1 }" @tap="prevPage">上一页</text>
                    <text class="fp__page-info">{{ chapterRangeText }}</text>
                    <text class="fp__page-btn" :class="{ 'fp__page-btn--disabled': currentPage >= totalPages }" @tap="nextPage">下一页</text>
                  </view>
                </template>
                <view v-else class="fp__empty-row">
                  <text class="fp__empty-text">暂无章节，请打开框架编辑器补充大纲，或使用 AI 创作助手生成章节规划。</text>
                </view>
              </view>
            </view>

            <view class="fp__bottom-spacer" />
            </view>
          </view>
        </scroll-view>
      </template>

      <!-- 编辑标签 -->
      <template #tab-1>
        <view class="chapter-view__edit-panel">
          <scroll-view scroll-y class="chapter-view__tab-scroll">
            <view class="chapter-view__tab">
              <view class="chapter-view__chapter-switcher">
                <view class="chapter-view__chapter-nav-btn" @tap="switchToPreviousChapter">
                  <lv-icon name="ChevronLeft" :size="16" />
                </view>
                <scroll-view scroll-x class="chapter-view__chapter-tabs" show-scrollbar="false">
                  <view class="chapter-view__chapter-tabs-inner">
                    <view
                      v-for="chapter in workspaceStore.sortedChapters"
                      :key="chapter.id"
                      :class="['chapter-view__chapter-tab', { 'chapter-view__chapter-tab--active': chapter.id === workspaceStore.activeChapterId }]"
                      @tap="workspaceStore.setActiveChapter(chapter.id)"
                    >
                      <text>第{{ chapter.chapter_number }}章</text>
                    </view>
                  </view>
                </scroll-view>
                <view class="chapter-view__chapter-nav-btn" @tap="switchToNextChapter">
                  <lv-icon name="ChevronRight" :size="16" />
                </view>
                <view class="chapter-view__chapter-nav-btn" @tap="createNewChapter">
                  <lv-icon name="Plus" :size="16" />
                </view>
              </view>

              <continuity-card v-if="continuitySummary" :summary="continuitySummary" editable @edit="goContinuityEditor" />

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
                  @select="handleEditorSelect"
                  placeholder="开始写作..."
                  auto-height
                />
                <text v-if="selectedText" class="chapter-view__selection-hint">已选择 {{ selectedText.length }} 字，可进行 AI 改写或转为漫画分镜</text>
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
              <lv-button size="sm" secondary @tap="showSelectionActions" :disabled="!selectedText">选段工具</lv-button>
              <lv-button size="sm" secondary @tap="cancelLocalEdit">取消</lv-button>
            </template>
            <template v-else>
              <lv-button size="sm" @tap="startLocalEdit">
                <lv-icon name="Pencil" :size="14" style="margin-right: 6rpx;" />编辑
              </lv-button>
              <lv-button v-if="!editorStore.content" size="sm" secondary @tap="generateCurrentChapter" :loading="generatingCurrentChapter">
                <lv-icon name="Sparkles" :size="14" style="margin-right: 6rpx;" />生成正文
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
              <view class="chapter-view__manga-settings-row">
                <text class="chapter-view__manga-label">色彩:</text>
                <picker :value="colorModeIndex" :range="['彩色', '黑白']" @change="handleColorModeChange">
                  <text class="chapter-view__manga-picker">{{ ['彩色', '黑白'][colorModeIndex] }}</text>
                </picker>
                <text class="chapter-view__manga-label">张数:</text>
                <picker :value="imageCountIndex" :range="imageCountOptions.map(o => o.label)" @change="handleImageCountChange">
                  <text class="chapter-view__manga-picker">{{ imageCountOptions[imageCountIndex].label }}</text>
                </picker>
              </view>

              <!-- 比例选择 -->
              <scroll-view scroll-x class="chapter-view__manga-ratio-scroll" show-scrollbar="false">
                <view class="chapter-view__manga-ratio-tabs">
                  <view v-for="r in aspectRatioOptions" :key="r.value" :class="['chapter-view__manga-ratio-tab', { 'chapter-view__manga-ratio-tab--active': mangaStore.aspectRatio === r.value }]" @tap="handleAspectRatioChange(r.value)">
                    <text>{{ r.label }}</text>
                  </view>
                </view>
              </scroll-view>

              <!-- 风格预设 -->
              <view class="chapter-view__manga-preset-row" @tap="handleOpenStylePresetInManga">
                <text class="chapter-view__manga-preset-label">风格预设</text>
                <view class="chapter-view__manga-preset-value">
                  <text>{{ mangaStore.stylePresetName || '未选择' }}</text>
                </view>
              </view>
            </view>

            <lv-button v-if="mangaStore.scenes.length === 0" block :loading="regeneratingMangaScenes" @tap="handleMangaSceneRegenerate">
              <lv-icon name="Clapperboard" :size="16" style="margin-right: 8rpx;" />生成分镜
            </lv-button>
            <lv-button v-else block :loading="mangaStore.isGenerating || isPolling" @tap="handleGenerateManga">
              <template v-if="mangaStore.isGenerating || isPolling">生成中...</template>
              <template v-else>
                <lv-icon name="ImagePlus" :size="16" style="margin-right: 8rpx;" />{{ mangaStore.images.length > 0 ? '继续生成缺失图片' : `生成 ${mangaStore.imageCount} 张漫画` }}
              </template>
            </lv-button>
            <lv-button v-if="mangaStore.images.length > 0 && !mangaStore.isGenerating && !isPolling" block secondary @tap="resetAndGenerateManga">
              清空并重新生成全部
            </lv-button>
            <lv-button v-if="mangaStore.isGenerating || isPolling" block secondary @tap="handleCancelManga">
              取消生成
            </lv-button>
            <text v-if="mangaStore.scenes.length > 0 && mangaStore.scenes.length !== mangaStore.imageCount" class="chapter-view__manga-warning">
              当前分镜 {{ mangaStore.scenes.length }} 条，需与生成张数 {{ mangaStore.imageCount }} 张一致后才能出图。
            </text>

            <view v-if="mangaStore.isGenerating || isPolling" class="chapter-view__manga-progress">
              <lv-progress :percentage="mangaStore.progressPercent" show-info />
              <text class="chapter-view__manga-status">{{ mangaStore.progress.statusMsg }}</text>
            </view>

            <view v-if="mangaStore.scenes.length > 0" class="chapter-view__scenes">
              <framework-section title="分镜脚本" icon="icon-film" :count="mangaStore.scenes.length">
                <view class="chapter-view__scenes-actions">
                  <lv-button size="sm" secondary @tap="handleMangaSceneAdd">
                    <lv-icon name="Plus" :size="12" />新增
                  </lv-button>
                  <lv-button size="sm" secondary @tap="handleMangaSceneRegenerate" :loading="regeneratingMangaScenes">重生成</lv-button>
                </view>
                <view v-for="(scene, i) in mangaStore.scenes" :key="i" class="chapter-view__scene-item">
                  <template v-if="editingMangaSceneIndex === i">
                    <view class="chapter-view__scene-edit">
                      <textarea class="chapter-view__scene-textarea" v-model="editingMangaSceneDraft" />
                      <view class="chapter-view__scene-edit-actions">
                        <lv-button size="sm" secondary @tap="cancelMangaSceneEdit">取消</lv-button>
                        <lv-button size="sm" @tap="saveMangaSceneEdit(i)">保存</lv-button>
                      </view>
                    </view>
                  </template>
                  <template v-else>
                    <text class="chapter-view__scene-num">{{ i + 1 }}.</text>
                    <text class="chapter-view__scene-text" @tap="startMangaSceneEdit(i, scene)">{{ scene }}</text>
                    <view class="chapter-view__scene-row-actions">
                      <view class="chapter-view__scene-btn" @tap="startMangaSceneEdit(i, scene)"><lv-icon name="Pencil" :size="12" color="#2563eb" /></view>
                      <view class="chapter-view__scene-btn" @tap="handleMangaSceneDelete(i)"><lv-icon name="Trash2" :size="12" color="#ef4444" /></view>
                    </view>
                  </template>
                </view>
              </framework-section>
            </view>

            <view v-if="mangaStore.scenes.length > 0" class="chapter-view__manga-grid">
              <view
                v-for="(scene, index) in mangaStore.scenes"
                :key="index"
                class="chapter-view__manga-grid-item"
              >
                <template v-if="getMangaImage(index + 1)">
                  <manga-image-card
                    :image-path="getMangaImage(index + 1)!.image_path"
                    :image-number="index + 1"
                    :cache-bust="redrawCacheBust"
                    :aspect-ratio="mangaStore.aspectRatio"
                    @tap="goGallery(index + 1)"
                  />
                  <view class="chapter-view__manga-redraw-btn" @tap.stop="openRedraw(getMangaImage(index + 1)!)">
                    <text class="chapter-view__manga-redraw-btn-text">重绘</text>
                  </view>
                </template>
                <view v-else class="chapter-view__manga-placeholder">
                  <text class="chapter-view__manga-placeholder-num">第 {{ index + 1 }} 格</text>
                  <text class="chapter-view__manga-placeholder-text">{{ scene }}</text>
                  <lv-button size="sm" :loading="generatingSingleImage === index + 1" @tap="generateSingleMangaImage(index + 1, scene)">生成此格</lv-button>
                </view>
              </view>
            </view>

            <!-- 图片重绘弹窗 -->
            <image-redraw-modal
              :visible="showRedrawModal"
              :image-url="redrawImageUrl"
              :image-number="redrawImageNumber"
              :chapter-id="workspaceStore.activeChapterId"
              ref-type="manga"
              @close="showRedrawModal = false"
              @success="onRedrawSuccess"
            />

            <lv-empty v-if="!mangaStore.isGenerating && !isPolling && mangaStore.images.length === 0 && mangaStore.scenes.length === 0" title="暂无漫画" description="点击生成漫画开始创作" />

            <view class="chapter-view__manga-links">
              <view class="chapter-view__manga-links-row">
                <lv-button secondary block size="sm" @tap="goCharacterRefs">角色参考</lv-button>
                <lv-button secondary block size="sm" @tap="goCharacterProfiles">角色外观</lv-button>
                <lv-button secondary block size="sm" @tap="goRefImages">参考图</lv-button>
              </view>
            </view>
          </view>
        </scroll-view>
      </template>

      <!-- 视频标签 - 内嵌工作流 -->
      <template #tab-3>
        <scroll-view scroll-y class="chapter-view__tab-scroll">
          <view class="chapter-view__tab">
            <chapter-video-workflow-content
              v-if="workspaceStore.activeChapterId"
              :chapter-id="workspaceStore.activeChapterId"
              :story-id="storyId"
            />
            <lv-empty v-else title="请先选择章节" description="在框架标签中选择一个章节" />
          </view>
        </scroll-view>
      </template>

      <!-- 助手标签 -->
      <template #tab-4>
        <view class="chapter-view__agent-wrapper">
          <view class="chapter-view__agent-header">
            <lv-button size="sm" @tap="startNewAgentConversation" :loading="creatingAgentConv" :disabled="creatingAgentConv">新对话</lv-button>
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
              :tool-calls="agentStore.streamingToolCalls"
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
            :confirming="confirmingChanges"
            :rollbacking="rollbackingChanges"
            @view="handleViewChanges"
            @confirm="handleConfirmChanges"
            @rollback="handleRollbackChanges"
          />
        </view>
      </template>
    </lv-swiper-tabs>
    <change-diff-sheet
      :visible="showAgentChangeDiff"
      :changes="agentStore.pendingChanges"
      :confirming="confirmingChanges"
      :rollbacking="rollbackingChanges"
      @close="showAgentChangeDiff = false"
      @confirm="handleConfirmChanges"
      @rollback="handleRollbackChanges"
    />
    <view v-if="rewritePreview.visible" class="chapter-view__rewrite-mask" @tap.self="closeRewritePreview">
      <view class="chapter-view__rewrite-sheet">
        <view class="chapter-view__rewrite-header">
          <view>
            <text class="chapter-view__rewrite-title">确认改写</text>
            <text class="chapter-view__rewrite-subtitle">应用前请核对原文与 AI 改写结果</text>
          </view>
          <view class="chapter-view__rewrite-close" @tap="closeRewritePreview">
            <lv-icon name="X" :size="18" color="#64748b" />
          </view>
        </view>
        <scroll-view scroll-y class="chapter-view__rewrite-content">
          <view class="chapter-view__rewrite-block chapter-view__rewrite-block--original">
            <text class="chapter-view__rewrite-label">原文选段</text>
            <text class="chapter-view__rewrite-text">{{ rewritePreview.original }}</text>
          </view>
          <view class="chapter-view__rewrite-block chapter-view__rewrite-block--result">
            <text class="chapter-view__rewrite-label chapter-view__rewrite-label--result">AI 改写</text>
            <text class="chapter-view__rewrite-text">{{ rewritePreview.rewritten }}</text>
          </view>
        </scroll-view>
        <view class="chapter-view__rewrite-actions">
          <lv-button secondary block @tap="closeRewritePreview">保留原文</lv-button>
          <lv-button block @tap="applyRewritePreview">替换到正文</lv-button>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onUnmounted } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import { ArrowLeft, MoreHorizontal } from '@lucide/vue'
import { useWorkspaceStore } from '@/stores/workspace'
import { useEditorStore } from '@/stores/editor'
import { useMangaStore } from '@/stores/manga'
import { useAgentStore } from '@/stores/agent'
import { useMangaGenerationStatus } from '@/composables/useMangaGenerationStatus'
import { useStoriesStore } from '@/stores/stories'
import { useUiStore } from '@/stores/ui'
import { storiesApi, frameworkApi, chaptersApi, mangaApi } from '@/api'
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
import ChangeDiffSheet from '@/components/change-diff-sheet/change-diff-sheet.vue'
import TemplateBinding from '@/components/template-binding/template-binding.vue'
import BibleSummary from '@/components/bible-summary/bible-summary.vue'
import { coverImageUrl, mangaImageUrl } from '@/utils/url'
import { useVideoWorkflowStore } from '@/stores/videoWorkflow'
import ChapterVideoWorkflowContent from '@/components/chapter-video-workflow-content/chapter-video-workflow-content.vue'
import ImageRedrawModal from '@/components/image-redraw-modal/image-redraw-modal.vue'
import DeconstructionRefs from '@/components/deconstruction-refs/deconstruction-refs.vue'

const workspaceStore = useWorkspaceStore()
const editorStore = useEditorStore()
const mangaStore = useMangaStore()
const agentStore = useAgentStore()
const storyStore = useStoriesStore()
const uiStore = useUiStore()

const activeTabIndex = ref(0)
const activeMaterialPanel = ref<'' | 'cover' | 'deconstruction' | 'history'>('')
const continuitySummary = ref<Record<string, any> | null>(null)
const agentInputText = ref('')
const localEditing = ref(false)
const colorModeIndex = ref(0)
const imageCountIndex = ref(1)
const chapterId = computed(() => workspaceStore.activeChapterId)

// ComputedRef 可安全赋值给 Ref（只读读取）
const {
  isPolling,
  stopPolling: stopMangaPolling,
  checkAndResume: checkMangaStatus
} = useMangaGenerationStatus(chapterId)
let chapterLoadSequence = 0

const agentScrollTarget = ref('')
const agentInitialized = ref(false)
const quickActions = ['阅读当前章节', '修改当前章节', '优化故事框架', '质量评估', '去AI味', '角色设定建议']

// 按钮级 loading 状态(独立于全局 loading,提供按钮即时视觉反馈)
const generatingChapterNum = ref(0)      // 正在生成正文的章节号(0 = 无)
const assessingChapterNum = ref(0)       // 正在质量评估的章节号(框架标签)
const regeneratingChapters = ref(false)  // AI 生成章节
const continuingFramework = ref(false)   // 一键续写
const restoringSnapshot = ref(0)         // 回滚快照 ID
const assessingQuality = ref(false)      // 编辑标签质量评估
const generatingCurrentChapter = ref(false)
const generatingSingleImage = ref(0)
const selectedText = ref('')
const selectionStart = ref(0)
const selectionEnd = ref(0)
const creatingAgentConv = ref(false)     // 新建 Agent 对话
const confirmingChanges = ref(false)     // 确认变更
const rollbackingChanges = ref(false)    // 撤回变更
const showAgentChangeDiff = ref(false)   // 修改对比全屏页
const rewritePreview = ref({
  visible: false,
  original: '',
  rewritten: '',
  start: 0,
  end: 0,
})

const editingMangaSceneIndex = ref(-1)
const editingMangaSceneDraft = ref('')
const regeneratingMangaScenes = ref(false)

// ── 图片重绘 ──
const showRedrawModal = ref(false)
const redrawImageUrl = ref('')
const redrawImageNumber = ref(0)
const redrawCacheBust = ref(0)

function openRedraw(img: any) {
  redrawImageUrl.value = mangaImageUrl(img.image_path)
  redrawImageNumber.value = img.image_number
  showRedrawModal.value = true
}

function onRedrawSuccess() {
  // 刷新后缓存升级
  redrawCacheBust.value = Date.now()
  // 重新加载漫画图片列表
  if (workspaceStore.activeChapterId) {
    mangaStore.loadChapterManga(workspaceStore.activeChapterId)
  }
}

function startMangaSceneEdit(index: number, text: string) {
  editingMangaSceneIndex.value = index
  editingMangaSceneDraft.value = text
}
function cancelMangaSceneEdit() {
  editingMangaSceneIndex.value = -1
  editingMangaSceneDraft.value = ''
}
async function saveMangaSceneEdit(index: number) {
  if (!workspaceStore.activeChapterId) return
  const newScenes = [...mangaStore.scenes]
  newScenes[index] = editingMangaSceneDraft.value
  try {
    await mangaApi.updateScenes(workspaceStore.activeChapterId, newScenes)
    mangaStore.scenes = newScenes
    editingMangaSceneIndex.value = -1
    editingMangaSceneDraft.value = ''
    uiStore.success('已保存')
  } catch (e: any) {
    uiStore.error(e.message || '保存失败')
  }
}
function handleMangaSceneAdd() {
  const newScenes = [...mangaStore.scenes, '']
  mangaStore.scenes = newScenes
  editingMangaSceneIndex.value = newScenes.length - 1
  editingMangaSceneDraft.value = ''
}
function handleMangaSceneDelete(index: number) {
  uni.showModal({
    title: '确认删除',
    content: '确定删除此分镜？',
    success: async (res) => {
      if (!res.confirm) return
      if (!workspaceStore.activeChapterId) return
      const newScenes = mangaStore.scenes.filter((_: any, i: number) => i !== index)
      try {
        await mangaApi.updateScenes(workspaceStore.activeChapterId, newScenes)
        mangaStore.scenes = newScenes
        uiStore.success('已删除')
      } catch (e: any) {
        uiStore.error(e.message || '删除失败')
      }
    }
  })
}
async function handleMangaSceneRegenerate() {
  if (regeneratingMangaScenes.value || !workspaceStore.activeChapterId) return
  regeneratingMangaScenes.value = true
  try {
    await mangaStore.generateScenes(workspaceStore.activeChapterId)
    uiStore.success('分镜已重新生成')
  } catch (e: any) {
    uiStore.error(e.message || '重生成失败')
  } finally {
    regeneratingMangaScenes.value = false
  }
}

const imageCountOptions = [
  { label: '4张', value: 4 },
  { label: '6张', value: 6 },
  { label: '8张', value: 8 },
  { label: '10张', value: 10 },
  { label: '12张', value: 12 },
  { label: '15张', value: 15 },
  { label: '20张', value: 20 }
]

const aspectRatioOptions = [
  { label: '9:16', value: '9:16' },
  { label: '3:4', value: '3:4' },
  { label: '2:3', value: '2:3' },
  { label: '1:1', value: '1:1' },
  { label: '3:2', value: '3:2' },
  { label: '4:3', value: '4:3' },
  { label: '16:9', value: '16:9' },
]

const storyId = ref(0)

// =================== 框架标签数据 ===================

// --- Data ---
const frameworkStory = ref<Story | null>(null)
const tags = ref<string[]>([])
const characters = ref<Character[]>([])
const tagsExpanded = ref(true)
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

// --- 封面编辑 ---
function handleCoverEdit() {
  if (storyStore.activeStoryId) {
    uni.navigateTo({
      url: `/pages/story/cover-edit?storyId=${storyStore.activeStoryId}`
    })
  }
}

function refreshCoverImage() {
  const story = storyStore.list.find(s => s.id === storyStore.activeStoryId)
  if (story && frameworkStory.value) {
    story.cover_image = frameworkStory.value.cover_image
  }
}

onShow(() => {
  if (storyStore.activeStoryId) {
    storiesApi.getStory(storyStore.activeStoryId).then(story => {
      const target = storyStore.list.find(s => s.id === storyStore.activeStoryId)
      if (target && story.cover_image !== target.cover_image) {
        target.cover_image = story.cover_image
      }
      if (frameworkStory.value) {
        frameworkStory.value.cover_image = story.cover_image
      }
    }).catch(() => {})
  }
})

function onTemplateBound() {
  // 模板绑定后可刷新框架相关数据
}

function handleEditBible() {
  if (storyStore.activeStoryId) {
    uni.navigateTo({ url: `/pages/story/story-bible?storyId=${storyStore.activeStoryId}` })
  }
}

function goContinuityEditor() {
  const chapterId = workspaceStore.activeChapterId
  if (chapterId) uni.navigateTo({ url: `/pages/workspace/continuity?chapterId=${chapterId}` })
}

function openAgentTask(task: string) {
  if (!storyId.value) {
    uiStore.error('请先选择作品')
    return
  }
  uni.navigateTo({
    url: `/pages/workspace/agent?storyId=${storyId.value}&chapterId=${workspaceStore.activeChapterId || ''}&task=${encodeURIComponent(task)}`
  })
}

function openCurrentEditor() {
  const chapter = workspaceStore.activeChapter
  if (!chapter) {
    uiStore.error('请先选择章节')
    return
  }
  uni.navigateTo({
    url: `/pages/workspace/editor?storyId=${storyId.value}&chapterId=${chapter.id}`
  })
}

function openMangaWorkspace() {
  const chapter = workspaceStore.activeChapter
  if (!chapter) {
    uiStore.error('请先选择章节')
    return
  }
  uni.navigateTo({
    url: `/pages/workspace/manga?storyId=${storyId.value}&chapterId=${chapter.id}`
  })
}

function openVideoWorkspace() {
  const chapter = workspaceStore.activeChapter
  if (!chapter) {
    uiStore.error('请先选择章节')
    return
  }
  uni.navigateTo({
    url: `/pages/workspace/video-workflow?storyId=${storyId.value}&chapterId=${chapter.id}`
  })
}

function toggleMaterialPanel(panel: 'cover' | 'deconstruction' | 'history') {
  activeMaterialPanel.value = activeMaterialPanel.value === panel ? '' : panel
  if (panel === 'history' && activeMaterialPanel.value === 'history' && snapshots.value.length === 0) {
    loadSnapshots()
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

function countOutlineChapters(outline: Record<string, any> | null | undefined): number {
  const acts = Array.isArray(outline?.three_acts) ? outline!.three_acts : []
  const numbers = new Set<number>()
  acts.forEach((act: any) => {
    const actChapters = Array.isArray(act?.chapters) ? act.chapters : []
    actChapters.forEach((chapter: any) => {
      const chapterNumber = Number(chapter?.chapter_number)
      if (Number.isInteger(chapterNumber) && chapterNumber > 0) {
        numbers.add(chapterNumber)
      }
    })
  })
  return numbers.size
}

function formatAppliedOperations(ops: string[] | undefined): string {
  if (!ops?.length) return ''
  const opLabels: Record<string, string> = {
    update_character: '更新角色',
    add_character: '新增角色',
    remove_character: '删除角色',
    update_chapter: '更新章节',
    add_chapter: '新增章节',
    insert_chapter_after: '新增章节',
    delete_chapter: '删除章节',
    update_story_description: '更新故事描述',
    update_tags: '更新标签',
    update_act_summary: '更新阶段概述',
  }
  const fieldLabels: Record<string, string> = {
    'patch:description': '故事描述',
    'patch:tags.type': '类型标签',
    'patch:tags.theme': '主题标签',
    'patch:tags.style': '风格标签',
    'patch:tags.audience': '受众标签',
    'patch:outline.themes': '主题列表',
    'patch:outline.foreshadowing': '伏笔列表',
    'patch:outline.serial_strategy': '连载策略',
  }
  const seen = new Set<string>()
  const labels: string[] = []
  for (const op of ops) {
    const [prefix] = op.split(':')
    const label = fieldLabels[op] || opLabels[prefix]
    if (label && !seen.has(label)) {
      seen.add(label)
      labels.push(label)
    }
    if (labels.length >= 4) break
  }
  return labels.length ? `\n\n已修改：${labels.join('、')}。` : ''
}

const chatInput = ref('')
const chatMessages = ref<FrameworkChatMessage[]>([])
const chatLoading = ref(false)
const chatError = ref('')
const showSnapshots = ref(false)
const snapshots = ref<FrameworkSnapshotItem[]>([])
const loadingSnapshots = ref(false)
const outlineExpandedAll = ref(true)

// --- 框架编辑器页面 ---
function openFrameworkEditor() {
  uni.navigateTo({ url: `/pages/workspace/framework-editor?storyId=${storyId.value}` })
}

// --- 标签内联编辑 ---
const editingTagKey = ref('')
const editingTagDraft = ref('')
const regeneratingTags = ref(false)
function startTagEdit(key: string, value: string) {
  editingTagKey.value = key
  editingTagDraft.value = value
}
function cancelTagEdit() { editingTagKey.value = ''; editingTagDraft.value = '' }
async function saveTagEdit() {
  if (!frameworkStory.value || !editingTagKey.value) return
  try {
    const currentTags = { ...(frameworkStory.value.tags || {}) }
    currentTags[editingTagKey.value] = editingTagDraft.value
    await storiesApi.updateStory(frameworkStory.value.id, { tags: currentTags } as any)
    frameworkStory.value.tags = currentTags
    tags.value = extractTags(currentTags)
    editingTagKey.value = ''
    uiStore.success('标签已更新')
  } catch (e: any) { uiStore.error(e.message || '更新标签失败') }
}
async function handleRegenerateTags() {
  if (!storyId.value || regeneratingTags.value) return
  regeneratingTags.value = true
  try {
    await frameworkApi.regenerateTags(storyId.value)
    await loadStoryData()
    uiStore.success('标签已重新生成')
  } catch (e: any) { uiStore.error(e.message || '重生成标签失败') }
  finally { regeneratingTags.value = false }
}

// --- 角色内联编辑 ---
const editingCharIndex = ref(-1)
const editingCharDraft = ref<Character | null>(null)
const regeneratingChars = ref(false)
function startCharEdit(index: number) {
  editingCharIndex.value = index
  editingCharDraft.value = JSON.parse(JSON.stringify(characters.value[index]))
}
function cancelCharEdit() { editingCharIndex.value = -1; editingCharDraft.value = null }
async function saveCharEdit() {
  if (!frameworkStory.value || editingCharIndex.value < 0 || !editingCharDraft.value) return
  try {
    const chars = [...characters.value]
    chars[editingCharIndex.value] = editingCharDraft.value
    await storiesApi.updateStory(frameworkStory.value.id, { characters: chars } as any)
    frameworkStory.value.characters = chars
    characters.value = chars
    editingCharIndex.value = -1
    editingCharDraft.value = null
    uiStore.success('角色已更新')
  } catch (e: any) { uiStore.error(e.message || '更新角色失败') }
}
async function handleRegenerateCharacters() {
  if (!storyId.value || regeneratingChars.value) return
  regeneratingChars.value = true
  try {
    await frameworkApi.regenerateCharacters(storyId.value)
    await loadStoryData()
    uiStore.success('角色已重新生成')
  } catch (e: any) { uiStore.error(e.message || '重生成角色失败') }
  finally { regeneratingChars.value = false }
}

// --- 大纲内联编辑 ---
const editingOutlineActIndex = ref(-1)
const editingOutlineChapterIndex = ref(-1)
const editingOutlineField = ref('')
const editingOutlineDraft = ref('')
function startOutlineEdit(actIndex: number, field: string, value: string, chIndex = -1) {
  editingOutlineActIndex.value = actIndex
  editingOutlineChapterIndex.value = chIndex
  editingOutlineField.value = field
  editingOutlineDraft.value = value
}
function cancelOutlineEdit() {
  editingOutlineActIndex.value = -1
  editingOutlineChapterIndex.value = -1
  editingOutlineField.value = ''
  editingOutlineDraft.value = ''
}
async function saveOutlineEdit() {
  if (!frameworkStory.value || editingOutlineActIndex.value < 0 || !editingOutlineField.value) return
  try {
    const outline = JSON.parse(JSON.stringify(frameworkStory.value.outline || { three_acts: [] }))
    const acts = outline.three_acts || []
    if (editingOutlineChapterIndex.value >= 0) {
      const ch = acts[editingOutlineActIndex.value]?.chapters?.[editingOutlineChapterIndex.value]
      if (ch) ch[editingOutlineField.value] = editingOutlineDraft.value
    } else {
      if (acts[editingOutlineActIndex.value]) acts[editingOutlineActIndex.value][editingOutlineField.value] = editingOutlineDraft.value
    }
    await storiesApi.updateStory(frameworkStory.value.id, { outline } as any)
    frameworkStory.value.outline = outline
    outlineActs.value = (outline.three_acts || []) as OutlineAct[]
    cancelOutlineEdit()
    uiStore.success('大纲已更新')
  } catch (e: any) { uiStore.error(e.message || '更新大纲失败') }
}

// --- 章节列表分页 ---
const pageSize = 20
const currentPage = ref(1)
const chapterJumpNum = ref('')
const plannedPageSize = 8
const plannedCurrentPage = ref(1)

const plannedChapters = computed(() =>
  outlineActs.value.flatMap(act => act.chapters || [])
)

const plannedTotalPages = computed(() =>
  Math.max(1, Math.ceil(plannedChapters.value.length / plannedPageSize))
)

const paginatedPlannedChapters = computed(() => {
  const start = (plannedCurrentPage.value - 1) * plannedPageSize
  return plannedChapters.value.slice(start, start + plannedPageSize)
})

const plannedChapterRangeText = computed(() => {
  if (plannedChapters.value.length === 0) return '0 章'
  const start = (plannedCurrentPage.value - 1) * plannedPageSize + 1
  const end = Math.min(plannedCurrentPage.value * plannedPageSize, plannedChapters.value.length)
  return `第 ${start}-${end} 章 / 共 ${plannedChapters.value.length} 章`
})

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
  if (!storyId.value || restoringSnapshot.value) return
  uni.showModal({
    title: '确认回滚',
    content: '回滚将先保存当前状态再恢复所选版本，确认继续？',
    success: async (res) => {
      if (!res.confirm) return
      restoringSnapshot.value = snapshotId
      try {
        await frameworkApi.restoreSnapshot(storyId.value, snapshotId)
        uiStore.success('已回滚')
        await loadStoryData()
      } catch (e: any) {
        uiStore.error(e.message || '回滚失败')
      } finally {
        restoringSnapshot.value = 0
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
  if (!hasFramework.value || chatLoading.value || continuingFramework.value) return
  continuingFramework.value = true
  chatLoading.value = true
  chatError.value = ''
  try {
    const beforeCount = countOutlineChapters(frameworkStory.value?.outline)
    const res = await frameworkApi.continueFramework(storyId.value)
    const afterCount = countOutlineChapters(res.story?.outline)
    const delta = Math.max(0, afterCount - beforeCount)
    const visibilityHint = afterCount > beforeCount
      ? `\n\n已从 ${beforeCount} 章扩展到 ${afterCount} 章，新增 ${delta} 章。请在下方"故事大纲/章节列表"里查看新增规划。`
      : '\n\n已完成续写请求，但章节数量没有增加；建议查看"故事大纲"是否更新了阶段内容，或输入更明确的扩展章数再试。'
    const operationHint = formatAppliedOperations(res.applied_operations)
    const appliedHint = res.applied_operations?.length
      ? `\n\n实际已应用改动：\n- ${res.applied_operations.join('\n- ')}`
      : ''
    const warningHint = res.warnings?.length
      ? `\n\n未执行或需注意：\n- ${res.warnings.join('\n- ')}`
      : ''
    const validationHint = res.validation_errors?.length
      ? `\n\n校验提示：\n- ${res.validation_errors.join('\n- ')}`
      : ''
    chatMessages.value.push({
      role: 'assistant',
      content: `${res.reply || '已续写后续大纲、章节与可能出现的新角色。'}${visibilityHint}${operationHint}${appliedHint}${warningHint}${validationHint}`
    })
    await loadStoryData()
    await loadChapters()
  } catch (e: any) {
    chatError.value = e.message || '续写框架失败，请稍后重试。'
  } finally {
    chatLoading.value = false
    continuingFramework.value = false
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

function handleGenerateChapterTap(ch: OutlineChapter) {
  if (generatingChapterNum.value === ch.chapter_number) return
  handleGenerateChapter(ch)
}

function handleAssessQualityTap(ch: OutlineChapter) {
  if (assessingChapterNum.value === ch.chapter_number) return
  handleAssessQuality(ch)
}
function chapterHasContent(ch: OutlineChapter): boolean {
  const actual = chapterMap.value.get(ch.chapter_number)
  return !!(actual?.novel_content?.trim()) || !!(actual?.messages?.length)
}

function getChapterStatus(ch: OutlineChapter): string {
  const actual = chapterMap.value.get(ch.chapter_number)
  if (!actual) return 'pending'
  if (actual.status === 'completed') return 'completed'
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
  if (generatingChapterNum.value) return
  const act = outlineActs.value.find(a => a.chapters.some(c => c.chapter_number === ch.chapter_number))
  if (!act) {
    uiStore.error('找不到所属幕')
    return
  }
  generatingChapterNum.value = ch.chapter_number
  try {
    await frameworkApi.expandChapter(storyId.value, {
      act: String(act.act),
      chapter_number: ch.chapter_number,
      chapter_title: ch.title,
      key_events: ch.key_events,
      summary: ch.summary || undefined,
      goal: ch.goal || undefined,
      conflict: ch.conflict || undefined,
      hook: ch.hook || undefined,
      payoff: ch.payoff || undefined,
      highlight: ch.highlight || undefined,
    })
    uiStore.success('正文已生成')
    await loadStoryData()
    await loadChapters()
    handleChapterSelect(ch)
  } catch (e: any) {
    uiStore.error(e.message || '生成正文失败')
  } finally {
    generatingChapterNum.value = 0
  }
}

async function handleAssessQuality(ch: OutlineChapter) {
  if (assessingChapterNum.value) return
  const actual = chapterMap.value.get(ch.chapter_number)
  if (!actual?.id) {
    uiStore.error('该章节尚未生成，无法评估')
    return
  }
  assessingChapterNum.value = ch.chapter_number
  try {
    const result = await chaptersApi.qualityAssess(actual.id)
    showQualityResult(result)
  } catch (e: any) {
    uiStore.error(e.message || '评估失败')
  } finally {
    assessingChapterNum.value = 0
  }
}

async function handleRegenerateChapters() {
  if (!storyId.value || regeneratingChapters.value) return
  regeneratingChapters.value = true
  try {
    await frameworkApi.regenerateOutline(storyId.value)
    uiStore.success('章节已更新')
    await loadStoryData()
  } catch (e: any) {
    uiStore.error(e.message || '生成失败')
  } finally {
    regeneratingChapters.value = false
  }
}

// --- 章节列表分页与跳转 ---
function prevPage() {
  if (currentPage.value > 1) currentPage.value--
}

function nextPage() {
  if (currentPage.value < totalPages.value) currentPage.value++
}

function prevPlannedPage() {
  if (plannedCurrentPage.value > 1) plannedCurrentPage.value--
}

function nextPlannedPage() {
  if (plannedCurrentPage.value < plannedTotalPages.value) plannedCurrentPage.value++
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
    const loadSequence = ++chapterLoadSequence
    stopMangaPolling()
    mangaStore.detachActiveStream()
    mangaStore.setActiveChapterContext(newId)
    editorStore.setActiveChapterContext(newId)
    localEditing.value = false
    clearSelection()
    continuitySummary.value = workspaceStore.activeChapter?.memory_summary || null
    editingMangaSceneIndex.value = -1
    mangaStore.phase = 'idle'
    await Promise.all([
      editorStore.loadContent(newId),
      mangaStore.loadColorMode(newId),
      mangaStore.loadImageCount(newId),
      mangaStore.loadChapterManga(newId),
      mangaStore.loadAspectRatio(newId),
      mangaStore.loadStylePreset(newId)
    ])
    if (loadSequence !== chapterLoadSequence || workspaceStore.activeChapterId !== newId) {
      return
    }
    colorModeIndex.value = mangaStore.colorMode === 'bw' ? 1 : 0
    const countIndex = imageCountOptions.findIndex(option => option.value === mangaStore.imageCount)
    if (countIndex >= 0) imageCountIndex.value = countIndex
    checkMangaStatus()
  }
})

async function refreshAgentUpdatedContent(payload?: { storyId?: number; chapterId?: number }) {
  if (payload?.storyId && payload.storyId !== storyId.value) return
  await Promise.all([loadStoryData(), loadChapters()])
  if (workspaceStore.activeChapterId) {
    await editorStore.loadContent(workspaceStore.activeChapterId)
  }
}

uni.$on('agent-content-updated', refreshAgentUpdatedContent)
onUnmounted(() => {
  uni.$off('agent-content-updated', refreshAgentUpdatedContent)
})

// 首次切换到助手tab时，自动加载最近会话
watch(() => activeTabIndex.value, async (tabIndex) => {
  if (tabIndex !== 4 || agentInitialized.value) return
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
  const material = options?.material
  if (material === 'cover' || material === 'deconstruction' || material === 'history') {
    activeMaterialPanel.value = material
  }

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
      loadStoryData()
    ])
    await loadChapters()

    if (workspaceStore.activeChapterId) {
      continuitySummary.value = workspaceStore.activeChapter?.memory_summary || null
      await editorStore.loadContent(workspaceStore.activeChapterId)
    }
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

function handleMangaRefChange() {
  // 参考图变化时刷新
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

function handleEditorSelect(e: any) {
  const target = e?.target || e?.detail || {}
  const start = Number(target.selectionStart ?? target.start ?? 0)
  const end = Number(target.selectionEnd ?? target.end ?? start)
  selectionStart.value = Math.min(start, end)
  selectionEnd.value = Math.max(start, end)
  selectedText.value = editorStore.draftContent.slice(selectionStart.value, selectionEnd.value)
}

function cancelLocalEdit() {
  editorStore.cancelEditing()
  localEditing.value = false
  clearSelection()
}

async function saveLocalEdit() {
  const chapter = workspaceStore.activeChapter
  if (!chapter) return
  await editorStore.saveContent(chapter.id)
  localEditing.value = false
  clearSelection()
  uni.showToast({ title: '已保存', icon: 'success' })
}

function clearSelection() {
  selectedText.value = ''
  selectionStart.value = 0
  selectionEnd.value = 0
}

function showSelectionActions() {
  if (!selectedText.value) {
    uiStore.info('请先在正文中选择一段文字')
    return
  }
  uni.showActionSheet({
    itemList: ['AI 改写选段', '选段生成漫画分镜'],
    success: (res) => {
      if (res.tapIndex === 0) rewriteSelectedContent()
      if (res.tapIndex === 1) createScenesFromSelectedContent()
    }
  })
}

async function rewriteSelectedContent() {
  const chapter = workspaceStore.activeChapter
  const original = selectedText.value
  if (!chapter || !original) return
  try {
    uni.showLoading({ title: 'AI 改写中' })
    const result = await chaptersApi.rewriteSelection(chapter.id, original, buildRewriteContext(chapter))
    uni.hideLoading()
    rewritePreview.value = {
      visible: true,
      original,
      rewritten: result.rewritten_text,
      start: selectionStart.value,
      end: selectionEnd.value,
    }
  } catch (e: any) {
    uni.hideLoading()
    uiStore.error(e.message || '改写失败')
  }
}

function buildRewriteContext(chapter: Chapter): string {
  const parts: string[] = []
  if (chapter.act) parts.push(`幕：${chapter.act}`)
  if (chapter.key_events?.length) {
    const events = chapter.key_events
      .slice(0, 5)
      .map((event: any) => typeof event === 'string' ? event : event?.title || event?.event || '')
      .filter(Boolean)
      .join('、')
    if (events) parts.push(`关键事件：${events}`)
  }
  const names = (frameworkStory.value?.characters || [])
    .map(character => character.name)
    .filter(Boolean)
    .slice(0, 6)
    .join('、')
  if (names) parts.push(`角色：${names}`)
  return parts.join(' | ')
}

function closeRewritePreview() {
  rewritePreview.value.visible = false
}

function applyRewritePreview() {
  const preview = rewritePreview.value
  if (!preview.rewritten.trim()) return
  const draft = editorStore.draftContent
  editorStore.updateDraft(draft.slice(0, preview.start) + preview.rewritten + draft.slice(preview.end))
  rewritePreview.value.visible = false
  clearSelection()
  uiStore.success('已替换选段，请保存正文')
}

async function createScenesFromSelectedContent() {
  const chapter = workspaceStore.activeChapter
  if (!chapter || !selectedText.value) return
  try {
    uni.showLoading({ title: '生成分镜中' })
    const result = await mangaApi.scenesFromSelection(
      chapter.id,
      selectedText.value,
      mangaStore.characterProfiles || undefined,
      mangaStore.imageCount
    )
    if (workspaceStore.activeChapterId !== chapter.id) return
    mangaStore.scenes = result.scenes || []
    uni.hideLoading()
    uiStore.success(`已生成 ${mangaStore.scenes.length} 条分镜`)
    openMangaWorkspace()
  } catch (e: any) {
    uni.hideLoading()
    uiStore.error(e.message || '生成分镜失败')
  }
}

async function generateCurrentChapter() {
  const chapter = workspaceStore.activeChapter
  if (!chapter || generatingCurrentChapter.value) return
  generatingCurrentChapter.value = true
  try {
    const planned = findOutlineChapter(chapter.chapter_number)
    const hasExistingChat = Array.isArray(chapter.messages) && chapter.messages.length > 0
    let result: Chapter
    if (!hasExistingChat && planned && (planned.chapter.act || planned.chapter.key_events?.length)) {
      result = await frameworkApi.expandChapter(storyId.value, {
        act: String(planned.chapter.act || planned.act.act),
        chapter_number: planned.chapter.chapter_number,
        chapter_title: planned.chapter.title || chapter.title || `第 ${chapter.chapter_number} 章`,
        key_events: planned.chapter.key_events,
        summary: planned.chapter.summary || undefined,
        goal: planned.chapter.goal || undefined,
        conflict: planned.chapter.conflict || undefined,
        hook: planned.chapter.hook || undefined,
        payoff: planned.chapter.payoff || undefined,
        highlight: planned.chapter.highlight || undefined,
      }) as Chapter
    } else {
      result = await chaptersApi.generateNovel(chapter.id)
    }
    if (workspaceStore.activeChapterId !== chapter.id) return
    workspaceStore.updateChapterInList(result)
    await editorStore.loadContent(chapter.id)
    uiStore.success('正文已生成')
  } catch (e: any) {
    uiStore.error(e.message || '生成正文失败')
  } finally {
    generatingCurrentChapter.value = false
  }
}

function findOutlineChapter(chapterNumber: number): { act: OutlineAct; chapter: OutlineChapter } | null {
  for (const act of outlineActs.value) {
    const chapter = (act.chapters || []).find(item => item.chapter_number === chapterNumber)
    if (chapter) return { act, chapter }
  }
  return null
}

function showQualityResult(scores: import('@/api/chapters').QualityScore) {
  const labels: Record<string, string> = {
    overall: '综合评分',
    content: '内容完整度',
    writing: '文笔表现',
    plot: '情节推进',
    character: '角色塑造'
  }
  const lines = ['overall', 'content', 'writing', 'plot', 'character']
    .filter(key => typeof scores[key as keyof typeof scores] === 'number')
    .map(key => `${labels[key]}：${scores[key as keyof typeof scores]}/10`)
    .join('\n')
  uni.showModal({ title: '质量评估', content: lines || '暂无评分结果', showCancel: false })
}

async function handleQualityAssess() {
  const chapter = workspaceStore.activeChapter
  if (!chapter || assessingQuality.value) return
  assessingQuality.value = true
  try {
    const result = await chaptersApi.qualityAssess(chapter.id)
    showQualityResult(result)
  } catch (e: any) {
    uiStore.error(e.message || '评估失败')
  } finally {
    assessingQuality.value = false
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

function handleAspectRatioChange(ratio: string) {
  const chapter = workspaceStore.activeChapter
  if (chapter) {
    mangaStore.saveAspectRatio(chapter.id, ratio)
  }
}

async function handleGenerateManga() {
  const chapter = workspaceStore.activeChapter
  if (!chapter) {
    uiStore.error('请先选择章节')
    return
  }
  try {
    await mangaStore.startMangaGeneration(chapter.id)
  } catch (e: any) {
    uiStore.error(e.message || '启动漫画生成失败')
  }
}

function getMangaImage(imageNumber: number) {
  return mangaStore.images.find(image => image.image_number === imageNumber)
}

async function generateSingleMangaImage(imageNumber: number, scene: string) {
  const chapter = workspaceStore.activeChapter
  if (!chapter || generatingSingleImage.value) return
  generatingSingleImage.value = imageNumber
  try {
    const image = await mangaApi.regenerateImage(chapter.id, imageNumber, scene, 'regenerate', {
      stylePresetName: mangaStore.stylePresetName || undefined,
      styleRefUrl: mangaStore.styleReferenceImageUrl || undefined
    })
    if (workspaceStore.activeChapterId !== chapter.id) return
    const existingIndex = mangaStore.images.findIndex(item => item.image_number === imageNumber)
    if (existingIndex >= 0) mangaStore.images[existingIndex] = image
    else mangaStore.images.push(image)
    mangaStore.images.sort((a, b) => a.image_number - b.image_number)
    uiStore.success(`第 ${imageNumber} 格已生成`)
  } catch (e: any) {
    uiStore.error(e.message || '单格生成失败')
  } finally {
    generatingSingleImage.value = 0
  }
}

function resetAndGenerateManga() {
  const chapter = workspaceStore.activeChapter
  if (!chapter) return
  uni.showModal({
    title: '重新生成全部',
    content: '将清空本章现有漫画图片，并从第 1 格重新生成。分镜脚本会保留。',
    confirmText: '清空并生成',
    success: async (res) => {
      if (!res.confirm) return
      try {
        await mangaApi.clearMangaImages(chapter.id)
        mangaStore.images = []
        await mangaStore.startMangaGeneration(chapter.id)
      } catch (e: any) {
        uiStore.error(e.message || '重新生成失败')
      }
    }
  })
}

async function handleCancelManga() {
  const chapter = workspaceStore.activeChapter
  if (!chapter) return
  stopMangaPolling()
  try {
    await mangaStore.stopGeneration(chapter.id)
    uiStore.info('已取消生成')
  } catch (e: any) {
    uiStore.error(e.message || '取消生成失败，请稍后重试')
    checkMangaStatus()
  }
}

function handleOpenStylePresetInManga() {
  const chapterId = workspaceStore.activeChapterId
  if (chapterId) uni.navigateTo({ url: `/pages/workspace/manga-style?chapterId=${chapterId}` })
}

function goCharacterRefs() {
  const chapterId = workspaceStore.activeChapterId
  if (storyId.value && chapterId) {
    uni.navigateTo({ url: `/pages/workspace/character-refs?storyId=${storyId.value}&chapterId=${chapterId}` })
  }
}

// =================== 助手标签 ===================

async function startNewAgentConversation() {
  if (!storyId.value || creatingAgentConv.value) return
  creatingAgentConv.value = true
  try {
    await agentStore.createConversation(storyId.value, undefined, workspaceStore.activeChapterId || undefined)
    agentStore.messages = [{ id: 'welcome', role: 'assistant', content: '我是你的AI写作助手，有什么可以帮到你的？' }]
  } catch (e: any) {
    uiStore.error(e.message || '创建失败')
  } finally {
    creatingAgentConv.value = false
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

async function handleViewChanges() {
  if (!storyId.value) return
  try {
    await agentStore.loadPendingChanges(storyId.value)
    showAgentChangeDiff.value = true
  } catch (e: any) {
    uiStore.error(e.message || '加载修改对比失败')
  }
}

async function handleConfirmChanges() {
  if (confirmingChanges.value || rollbackingChanges.value) return
  confirmingChanges.value = true
  try {
    await agentStore.confirmChanges(storyId.value)
    showAgentChangeDiff.value = false
    await Promise.all([loadStoryData(), loadChapters()])
    if (workspaceStore.activeChapterId) {
      await editorStore.loadContent(workspaceStore.activeChapterId)
    }
    uiStore.success('变更已确认')
  } catch (e: any) {
    uiStore.error(e.message || '确认失败')
  } finally {
    confirmingChanges.value = false
  }
}

async function handleRollbackChanges() {
  if (confirmingChanges.value || rollbackingChanges.value) return
  rollbackingChanges.value = true
  try {
    await agentStore.rollbackChanges(storyId.value)
    showAgentChangeDiff.value = false
    await Promise.all([loadStoryData(), loadChapters()])
    if (workspaceStore.activeChapterId) {
      await editorStore.loadContent(workspaceStore.activeChapterId)
    }
    uiStore.success('变更已撤回')
  } catch (e: any) {
    uiStore.error(e.message || '撤回失败')
  } finally {
    rollbackingChanges.value = false
  }
}

function sendQuickAction(action: string) {
  const prompts: Record<string, string> = {
    阅读当前章节: '请阅读当前章节，概括核心情节、人物状态、冲突和伏笔，并指出需要延续的上下文。',
    修改当前章节: '请检查当前章节并提出可执行的修改方案，重点改善节奏、逻辑、人物动机和语言表现。',
    优化故事框架: '请结合当前章节审视故事框架，指出结构问题并给出具体优化建议。',
    质量评估: '请从内容完整度、文笔、情节推进、角色塑造和去 AI 味五个方面评估当前章节。',
    去AI味: '请对当前章节进行去AI味处理，检测并清除禁用词、句式套路、解释腔、结尾升华和模板化表达，让文字更自然。',
    角色设定建议: '请结合当前故事与章节，检查角色设定的一致性并给出补充建议。'
  }
  handleAgentSend(prompts[action] || action)
}

// =================== 更多菜单 ===================

function showMore() {
  uni.showActionSheet({
    itemList: ['角色外观', '连贯性记忆', '参考图', '资产管理'],
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
        case 2: goRefImages(); break
        case 3: {
          const chapter = workspaceStore.activeChapter
          if (chapter) {
            uni.navigateTo({ url: `/pages/workspace/video-assets?chapterId=${chapter.id}` })
          }
          break
        }
      }
    }
  })
}

function showEditorMore() {
  uni.showActionSheet({
    itemList: ['选段工具', '调整全文', '重新生成正文', '删除本章'],
    success: (res) => {
      if (res.tapIndex === 0) startLocalEdit()
      if (res.tapIndex === 1) promptAdjustContent()
      if (res.tapIndex === 2) confirmRegenerateChapter()
      if (res.tapIndex === 3) deleteCurrentChapter()
    }
  })
}

function confirmRegenerateChapter() {
  const hasContent = Boolean(editorStore.content)
  if (!hasContent) {
    generateCurrentChapter()
    return
  }
  uni.showModal({
    title: '重新生成正文',
    content: '此操作会用 AI 新生成的正文覆盖当前整章内容，建议先确认现有内容已保存或备份。',
    confirmText: '确认重生成',
    confirmColor: '#dc2626',
    success: (res) => {
      if (res.confirm) generateCurrentChapter()
    }
  })
}

function promptAdjustContent() {
  const chapter = workspaceStore.activeChapter
  if (!chapter) return
  uni.showModal({
    title: '调整全文',
    editable: true,
    placeholderText: '例如：加快节奏、增强冲突、减少解释性文字',
    success: async (res) => {
      const instruction = String(res.content || '').trim()
      if (!res.confirm || !instruction) return
      try {
        uni.showLoading({ title: '调整中' })
        const result = await chaptersApi.adjustContent(chapter.id, instruction)
        if (workspaceStore.activeChapterId !== chapter.id) {
          uni.hideLoading()
          return
        }
        workspaceStore.updateChapterInList(result)
        await editorStore.loadContent(chapter.id)
        uni.hideLoading()
        uiStore.success('正文已调整')
      } catch (e: any) {
        uni.hideLoading()
        uiStore.error(e.message || '调整失败')
      }
    }
  })
}

function switchToPreviousChapter() {
  workspaceStore.prevChapter()
}

function switchToNextChapter() {
  workspaceStore.nextChapter()
}

async function createNewChapter() {
  if (!storyId.value) return
  try {
    const chapter = await workspaceStore.createChapter(storyId.value)
    await loadChapters()
    workspaceStore.setActiveChapter(chapter.id)
    uiStore.success('新章节已创建')
  } catch (e: any) {
    uiStore.error(e.message || '创建章节失败')
  }
}

function deleteCurrentChapter() {
  const chapter = workspaceStore.activeChapter
  if (!chapter) return
  uni.showModal({
    title: '删除章节',
    content: `确定删除“${workspaceStore.activeChapterTitle}”？正文、分镜和生成结果将一并移除。`,
    confirmColor: '#dc2626',
    success: async (res) => {
      if (!res.confirm) return
      try {
        await workspaceStore.deleteChapter(chapter.id)
        await loadChapters()
        uiStore.success('章节已删除')
      } catch (e: any) {
        uiStore.error(e.message || '删除章节失败')
      }
    }
  })
}
</script>

<style lang="scss" scoped>
.fp__cover-banner {
  display: flex;
  align-items: center;
  gap: 24rpx;
  background: #fff;
  border-radius: $lv-radius-md;
  padding: 20rpx;
  margin-bottom: $lv-section-gap;
  box-shadow: $lv-shadow-sm;
}

.fp__cover-img {
  width: 120rpx;
  height: 160rpx;
  border-radius: $lv-radius-sm;
  flex-shrink: 0;
}

.fp__cover-placeholder {
  width: 120rpx;
  height: 160rpx;
  background: $lv-primary-lighter;
  border-radius: $lv-radius-sm;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  flex-shrink: 0;
}

.fp__cover-text {
  font-size: $lv-font-xs;
  color: $lv-text-muted;
}

.fp__cover-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8rpx;
}

.fp__cover-title {
  font-size: $lv-font-base;
  font-weight: 600;
  color: $lv-text-primary;
}

.fp__cover-edit {
  font-size: $lv-font-sm;
  color: $lv-primary;
}

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

  &__chapter-switcher {
    display: flex;
    align-items: center;
    gap: 10rpx;
    margin-bottom: 20rpx;
  }

  &__chapter-tabs {
    flex: 1;
    min-width: 0;
    white-space: nowrap;
  }

  &__chapter-tabs-inner {
    display: inline-flex;
    gap: 10rpx;
  }

  &__chapter-tab {
    flex-shrink: 0;
    padding: 10rpx 18rpx;
    border-radius: $lv-radius-sm;
    background: #fff;
    color: $lv-text-secondary;
    font-size: $lv-font-sm;
    border: 1rpx solid $lv-border;
  }

  &__chapter-tab--active {
    color: #fff;
    background: $lv-primary;
    border-color: $lv-primary;
  }

  &__chapter-nav-btn {
    width: 56rpx;
    height: 56rpx;
    flex-shrink: 0;
    border-radius: $lv-radius-sm;
    background: #fff;
    border: 1rpx solid $lv-border;
    @include flex-center;
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

  &__selection-hint {
    display: block;
    margin-top: 12rpx;
    padding: 12rpx 16rpx;
    border-radius: $lv-radius-sm;
    background: $lv-primary-lighter;
    color: $lv-primary;
    font-size: $lv-font-xs;
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
    flex-direction: column;
    align-items: stretch;
    gap: 16rpx;
    margin-bottom: 16rpx;
    padding: 20rpx;
    background: $lv-surface-solid;
    border: 1rpx solid $lv-border-light;
    border-radius: $lv-radius-md;
  }

  &__manga-settings-row {
    display: grid;
    grid-template-columns: auto 1fr auto 1fr;
    align-items: center;
    gap: 12rpx;
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

  &__manga-warning {
    display: block;
    margin: 12rpx 0 16rpx;
    font-size: $lv-font-sm;
    line-height: 1.5;
    color: #b45309;
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
    flex: 1;
  }

  &__scenes-actions {
    display: flex;
    gap: 8rpx;
    margin-bottom: 12rpx;
  }
  &__scene-edit {
    width: 100%;
  }
  &__scene-textarea {
    width: 100%;
    min-height: 120rpx;
    padding: 16rpx;
    background: $lv-bg-start;
    border-radius: $lv-radius-sm;
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    line-height: 1.6;
  }
  &__scene-edit-actions {
    display: flex;
    gap: 8rpx;
    justify-content: flex-end;
    margin-top: 8rpx;
  }
  &__scene-row-actions {
    display: flex;
    gap: 8rpx;
    flex-shrink: 0;
    margin-left: auto;
    align-items: center;
  }
  &__scene-btn {
    padding: 4rpx 8rpx;
  }

  &__manga-grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 16rpx;
    margin: 16rpx 0;
  }

  &__manga-grid-item {
    position: relative;
    width: 100%;
    max-width: 760rpx;
    margin: 0 auto;
  }

  &__manga-placeholder {
    min-height: 360rpx;
    padding: 24rpx;
    border: 1rpx dashed $lv-border;
    border-radius: $lv-radius-md;
    background: #fff;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 16rpx;
  }

  &__manga-placeholder-num {
    color: $lv-primary;
    font-size: $lv-font-sm;
    font-weight: 600;
  }

  &__manga-placeholder-text {
    color: $lv-text-secondary;
    font-size: $lv-font-xs;
    line-height: 1.6;
    display: -webkit-box;
    -webkit-line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  &__manga-redraw-btn {
    position: absolute;
    top: 8rpx;
    right: 8rpx;
    padding: 6rpx 14rpx;
    background: rgba(0, 0, 0, 0.6);
    border-radius: $lv-radius-sm;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 2;

    &:active {
      opacity: 0.7;
    }
  }

  &__manga-redraw-btn-text {
    font-size: 20rpx;
    color: #ffffff;
    font-weight: 500;
  }

  &__manga-links {
    margin-top: 16rpx;
  }

  &__manga-links-row {
    display: flex;
    gap: 16rpx;
  }

  &__manga-settings-row {
    display: flex;
    align-items: center;
    gap: 12rpx;
    margin-bottom: 12rpx;
  }

  &__manga-ratio-scroll {
    white-space: nowrap;
    margin-bottom: 12rpx;
  }

  &__manga-ratio-tabs {
    display: inline-flex;
    gap: 8rpx;
  }

  &__manga-ratio-tab {
    display: inline-flex;
    align-items: center;
    padding: 8rpx 16rpx;
    background: $lv-surface-solid;
    border-radius: $lv-radius-full;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    border: 1rpx solid $lv-border-light;
    transition: all 0.2s;

    &--active {
      background: $lv-primary;
      color: #fff;
      border-color: $lv-primary;
    }
  }

  &__manga-preset-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16rpx;
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
    margin-bottom: 16rpx;
  }

  &__manga-preset-label {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__manga-preset-value {
    display: flex;
    align-items: center;
    gap: 8rpx;
    font-size: $lv-font-sm;
    color: $lv-text-primary;
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

  &__video-entry-card {
    display: flex;
    align-items: center;
    gap: 16rpx;
    padding: 24rpx;
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    margin-bottom: 20rpx;
    &:active { opacity: 0.8; }
  }
  &__video-entry-icon {
    width: 80rpx; height: 80rpx;
    border-radius: $lv-radius-md;
    background: $lv-primary-light;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
  }
  &__video-entry-body { flex: 1; }
  &__video-entry-title { font-size: $lv-font-base; font-weight: 600; color: $lv-text-primary; display: block; margin-bottom: 4rpx; }
  &__video-entry-desc { font-size: $lv-font-sm; color: $lv-text-muted; }
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
    display: inline-flex;
    align-items: center;
    gap: 8rpx;
    &:active { opacity: 0.6; }
    &--primary {
      background: $lv-primary;
      color: #fff;
    }
    &--loading {
      opacity: 0.6;
      pointer-events: none;
    }
  }

  &__chapter-btn-spinner {
    width: 20rpx;
    height: 20rpx;
    border: 3rpx solid rgba(128,128,128,0.2);
    border-top-color: currentColor;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    flex-shrink: 0;
  }

  // --- Common ---
  &__empty-row { padding: 24rpx 0; text-align: center; }
  &__empty-text { font-size: $lv-font-sm; color: $lv-text-muted; }
  &__loading-row { padding: 24rpx 0; @include flex-center; }
  &__error { display: block; padding: 0 24rpx 16rpx; font-size: $lv-font-sm; color: #dc2626; }
  &__bottom-spacer { height: 80rpx; }

  // --- Tag Inline Edit ---
  &__tag-edit-list {
    display: flex;
    flex-direction: column;
    gap: 12rpx;
  }
  &__tag-edit-row {
    display: flex;
    align-items: center;
    gap: 12rpx;
  }
  &__tag-edit-label {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    min-width: 80rpx;
    font-weight: 500;
  }
  &__tag-edit-value {
    flex: 1;
    font-size: $lv-font-sm;
    color: $lv-primary;
    padding: 8rpx 12rpx;
    background: $lv-primary-lighter;
    border-radius: $lv-radius-sm;
  }
  &__tag-edit-input {
    flex: 1;
    height: 56rpx;
    padding: 0 12rpx;
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    background: #fff;
    border: 2rpx solid $lv-primary;
    border-radius: $lv-radius-sm;
    box-sizing: border-box;
  }

  // --- Character Inline Edit ---
  &__char-edit-card {
    background: $lv-surface-solid;
    border: 1rpx solid $lv-border;
    border-radius: $lv-radius-md;
    padding: $lv-card-padding;
    margin-bottom: 12rpx;
  }
  &__char-edit-field {
    margin-bottom: 12rpx;
  }
  &__char-edit-label {
    display: block;
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    margin-bottom: 4rpx;
  }
  &__char-edit-input {
    width: 100%;
    height: 56rpx;
    padding: 0 12rpx;
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    background: #fff;
    border: 2rpx solid $lv-border;
    border-radius: $lv-radius-sm;
    box-sizing: border-box;
  }
  &__char-edit-textarea {
    width: 100%;
    padding: 12rpx;
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    background: #fff;
    border: 2rpx solid $lv-border;
    border-radius: $lv-radius-sm;
    min-height: 120rpx;
    box-sizing: border-box;
  }
  &__char-edit-trigger {
    display: inline-flex;
    align-items: center;
    gap: 4rpx;
    padding: 8rpx 0 16rpx 24rpx;
  }
  &__char-edit-trigger-text {
    font-size: $lv-font-sm;
    color: $lv-primary;
  }

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

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.fp__header-btn--disabled {
  opacity: 0.5;
  pointer-events: none;
}

.creation-home {
  &__chapter {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 20rpx;
    padding: 24rpx;
    margin-bottom: 20rpx;
    background: #ffffff;
    border: 1rpx solid #e2e8f0;
    border-radius: 8rpx;
  }

  &__eyebrow {
    display: block;
    margin-bottom: 6rpx;
    font-size: 21rpx;
    color: #64748b;
  }

  &__title {
    display: block;
    font-size: 30rpx;
    line-height: 1.35;
    font-weight: 700;
    color: #0f172a;
  }

  &__meta {
    display: block;
    margin-top: 8rpx;
    font-size: 22rpx;
    color: #64748b;
  }

  &__agent {
    min-height: 104rpx;
    display: flex;
    align-items: center;
    padding: 18rpx 20rpx;
    margin-bottom: 28rpx;
    background: #eff6ff;
    border: 1rpx solid #bfdbfe;
    border-radius: 8rpx;
    &:active { background: #dbeafe; }
  }

  &__agent-icon {
    width: 64rpx;
    height: 64rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    border-radius: 14rpx;
    background: #2563eb;
  }

  &__agent-copy,
  &__extension-copy {
    flex: 1;
    min-width: 0;
    margin-left: 16rpx;
  }

  &__agent-open {
    width: 56rpx;
    height: 56rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  &__section-title {
    display: block;
    font-size: 28rpx;
    font-weight: 700;
    color: #0f172a;
  }

  &__section-desc {
    display: block;
    margin-top: 4rpx;
    font-size: 21rpx;
    color: #64748b;
  }

  &__shortcut-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12rpx;
  }

  &__shortcut {
    min-width: 0;
    padding: 20rpx;
    border: 1rpx solid #e2e8f0;
    border-radius: 8rpx;
    background: #ffffff;
    &:active { background: #f8fafc; }
  }

  &__shortcut-title {
    display: block;
    margin-top: 10rpx;
    font-size: 25rpx;
    font-weight: 600;
    color: #0f172a;
  }

  &__shortcut-desc {
    display: block;
    margin-top: 6rpx;
    font-size: 21rpx;
    line-height: 1.45;
    color: #64748b;
  }

  &__shortcut-icon {
    width: 58rpx;
    height: 58rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 10rpx;
    &--outline { background: #eff6ff; }
    &--bible { background: #f5f3ff; }
    &--cover { background: #fff1f2; }
    &--reference { background: #fffbeb; }
    &--history { background: #ecfdf5; }
    &--chapter { background: #f1f5f9; }
  }

  &__section-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin: 0 0 14rpx;
    &--framework { margin-top: 32rpx; }
  }

  &__section-link {
    display: flex;
    align-items: center;
    gap: 2rpx;
    flex-shrink: 0;
    font-size: 22rpx;
    font-weight: 600;
    color: #2563eb;
    &:active { opacity: 0.65; }
  }

  &__chapter-plan {
    overflow: hidden;
    margin-bottom: 28rpx;
    border: 1rpx solid #e2e8f0;
    border-radius: 8rpx;
    background: #ffffff;
  }

  &__chapter-plan-summary {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14rpx 18rpx;
    border-bottom: 1rpx solid #e2e8f0;
    background: #f8fafc;
    font-size: 20rpx;
    color: #64748b;
  }

  &__chapter-plan-item {
    display: flex;
    align-items: center;
    gap: 16rpx;
    min-height: 112rpx;
    padding: 16rpx 18rpx;
    border-bottom: 1rpx solid #e2e8f0;
  }

  &__chapter-plan-copy {
    flex: 1;
    min-width: 0;
  }

  &__chapter-plan-title-row {
    display: flex;
    align-items: center;
    gap: 10rpx;
    min-width: 0;
  }

  &__chapter-plan-num {
    flex-shrink: 0;
    font-size: 20rpx;
    color: #64748b;
  }

  &__chapter-plan-title {
    overflow: hidden;
    flex: 1;
    font-size: 24rpx;
    font-weight: 600;
    color: #0f172a;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__chapter-plan-desc {
    display: -webkit-box;
    overflow: hidden;
    margin-top: 8rpx;
    font-size: 20rpx;
    line-height: 1.45;
    color: #64748b;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
  }

  &__chapter-plan-action {
    min-width: 132rpx;
    height: 58rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6rpx;
    flex-shrink: 0;
    padding: 0 14rpx;
    border-radius: 8rpx;
    background: #2563eb;
    font-size: 21rpx;
    font-weight: 600;
    color: #ffffff;
    &:active { background: #1d4ed8; }
    &--open {
      border: 1rpx solid #bfdbfe;
      background: #eff6ff;
      color: #2563eb;
      &:active { background: #dbeafe; }
    }
    &--loading {
      pointer-events: none;
      opacity: 0.7;
    }
    &--disabled {
      pointer-events: none;
      opacity: 0.4;
    }
  }

  &__chapter-plan-pagination {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14rpx 18rpx;
    background: #f8fafc;
  }

  &__chapter-plan-page {
    min-width: 112rpx;
    height: 48rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 2rpx;
    font-size: 21rpx;
    color: #334155;
    &--disabled {
      pointer-events: none;
      opacity: 0.35;
    }
  }

  &__chapter-plan-page-info {
    font-size: 20rpx;
    color: #64748b;
  }

  &__chapter-plan-empty {
    display: flex;
    align-items: center;
    gap: 16rpx;
    padding: 22rpx 18rpx;
  }

  &__chapter-plan-empty-copy {
    flex: 1;
    min-width: 0;
  }

  &__chapter-plan-empty-copy &__shortcut-title {
    margin-top: 0;
  }

  &__shortcut-grid {
    margin-bottom: 28rpx;
  }

  &__material-panel {
    margin: -8rpx 0 28rpx;
    padding: 22rpx;
    border: 1rpx solid #dbe3ee;
    border-radius: 8rpx;
    background: #ffffff;
  }

  &__panel-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16rpx;
    margin-bottom: 20rpx;
  }

  &__panel-close {
    width: 52rpx;
    height: 52rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    border-radius: 8rpx;
    background: #f1f5f9;
  }

  &__extension-list {
    overflow: hidden;
    margin-bottom: 8rpx;
    border: 1rpx solid #e2e8f0;
    border-radius: 8rpx;
    background: #ffffff;
  }

  &__extension {
    min-height: 104rpx;
    display: flex;
    align-items: center;
    padding: 18rpx 20rpx;
    border-bottom: 1rpx solid #e2e8f0;
    &:last-child { border-bottom: 0; }
    &:active { background: #f8fafc; }
  }

  &__extension-icon {
    width: 60rpx;
    height: 60rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    border-radius: 12rpx;
    &--manga { background: #fff1f2; }
    &--video { background: #ecfdf5; }
  }

  &__extension-copy &__shortcut-title {
    margin-top: 0;
  }

  &__rewrite-mask {
    position: fixed;
    inset: 0;
    z-index: 120;
    display: flex;
    align-items: flex-end;
    background: rgba(15, 23, 42, 0.48);
  }

  &__rewrite-sheet {
    width: 100%;
    max-height: 88vh;
    display: flex;
    flex-direction: column;
    padding-bottom: env(safe-area-inset-bottom);
    border-radius: 20rpx 20rpx 0 0;
    background: #ffffff;
  }

  &__rewrite-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 20rpx;
    padding: 28rpx 28rpx 22rpx;
    border-bottom: 1rpx solid #e2e8f0;
  }

  &__rewrite-title,
  &__rewrite-subtitle,
  &__rewrite-label,
  &__rewrite-text {
    display: block;
  }

  &__rewrite-title {
    color: #0f172a;
    font-size: 30rpx;
    font-weight: 700;
  }

  &__rewrite-subtitle {
    margin-top: 6rpx;
    color: #64748b;
    font-size: 22rpx;
  }

  &__rewrite-close {
    width: 56rpx;
    height: 56rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    border-radius: 8rpx;
    background: #f1f5f9;
  }

  &__rewrite-content {
    flex: 1;
    min-height: 0;
    padding: 24rpx 28rpx;
    box-sizing: border-box;
  }

  &__rewrite-block {
    margin-bottom: 20rpx;
    padding: 22rpx;
    border: 1rpx solid #dbe3ee;
    border-radius: 8rpx;
    background: #f8fafc;

    &--result {
      border-color: #bfdbfe;
      background: #eff6ff;
    }
  }

  &__rewrite-label {
    margin-bottom: 12rpx;
    color: #64748b;
    font-size: 22rpx;
    font-weight: 600;

    &--result { color: #1d4ed8; }
  }

  &__rewrite-text {
    color: #1e293b;
    font-size: 26rpx;
    line-height: 1.75;
    white-space: pre-wrap;
  }

  &__rewrite-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16rpx;
    padding: 20rpx 28rpx 24rpx;
    border-top: 1rpx solid #e2e8f0;
  }
}
</style>
