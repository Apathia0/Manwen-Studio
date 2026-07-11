<template>
  <view class="framework-editor">
    <lv-navbar title="框架编辑器" show-back>
      <template #right>
        <view class="framework-editor__nav-save" @tap="handleSave">
          <lv-icon name="Save" :size="18" color="#2563eb" />
          <text class="framework-editor__nav-save-text">{{ saving ? '保存中...' : '保存' }}</text>
        </view>
      </template>
    </lv-navbar>

    <scroll-view scroll-y class="framework-editor__body">
      <!-- ══ Preview Section (collapsible) ══ -->
      <view class="framework-editor__preview-toggle" @tap="previewExpanded = !previewExpanded">
        <lv-icon name="Eye" :size="14" color="#2563eb" />
        <text class="framework-editor__preview-toggle-text">实时预览</text>
        <lv-icon :name="previewExpanded ? 'ChevronUp' : 'ChevronDown'" :size="12" color="#94a3b8" />
      </view>

      <template v-if="previewExpanded">
        <view class="framework-editor__preview">
          <view class="framework-editor__preview-card">
            <view class="framework-editor__preview-card-header framework-editor__preview-card-header--blue">
              <lv-icon name="FileText" :size="13" color="#3b82f6" />
              <text class="framework-editor__preview-card-label">故事描述</text>
            </view>
            <view class="framework-editor__preview-card-body">
              <text v-if="description.trim()" class="framework-editor__preview-text">{{ description }}</text>
              <text v-else class="framework-editor__preview-empty">暂无描述</text>
            </view>
          </view>

          <view class="framework-editor__preview-card">
            <view class="framework-editor__preview-card-header framework-editor__preview-card-header--emerald">
              <lv-icon name="Tag" :size="13" color="#10b981" />
              <text class="framework-editor__preview-card-label">标签设定</text>
            </view>
            <view class="framework-editor__preview-card-body">
              <template v-if="hasTags">
                <view class="framework-editor__preview-tags">
                  <template v-for="(value, key) in tags" :key="key">
                    <view v-if="value" class="framework-editor__preview-tag" :style="tagBadgeStyle(key)">
                      <text class="framework-editor__preview-tag-label">{{ tagLabel(key) }}</text>
                      <text class="framework-editor__preview-tag-value">{{ value }}</text>
                    </view>
                  </template>
                </view>
              </template>
              <text v-else class="framework-editor__preview-empty">暂无标签</text>
            </view>
          </view>

          <view class="framework-editor__preview-card">
            <view class="framework-editor__preview-card-header framework-editor__preview-card-header--violet">
              <lv-icon name="Users" :size="13" color="#8b5cf6" />
              <text class="framework-editor__preview-card-label">角色设定</text>
            </view>
            <view class="framework-editor__preview-card-body">
              <template v-if="characters.length > 0">
                <view v-for="(char, i) in characters" :key="i" class="framework-editor__preview-char">
                  <view class="framework-editor__preview-char-header" @tap="togglePreviewChar(i)">
                    <view class="framework-editor__preview-char-info">
                      <text class="framework-editor__preview-char-name">{{ char.name || '未命名角色' }}</text>
                      <text v-if="char.role" :class="['framework-editor__preview-char-role']" :style="roleStyle(char.role)">{{ char.role }}</text>
                    </view>
                    <lv-icon :name="previewCharExpanded[i] ? 'ChevronUp' : 'ChevronDown'" :size="12" color="#94a3b8" />
                  </view>
                  <view v-if="previewCharExpanded[i]" class="framework-editor__preview-char-detail">
                    <text v-if="char.description" class="framework-editor__preview-char-desc">{{ char.description }}</text>
                  </view>
                </view>
              </template>
              <text v-else class="framework-editor__preview-empty">暂无角色</text>
            </view>
          </view>

          <view class="framework-editor__preview-card">
            <view class="framework-editor__preview-card-header framework-editor__preview-card-header--amber">
              <lv-icon name="BookOpen" :size="13" color="#f59e0b" />
              <text class="framework-editor__preview-card-label">故事大纲</text>
            </view>
            <view class="framework-editor__preview-card-body">
              <template v-if="outlineActs.length > 0">
                <view v-for="(act, i) in outlineActs" :key="i" class="framework-editor__preview-act">
                  <view class="framework-editor__preview-act-header" @tap="togglePreviewAct(i)">
                    <text class="framework-editor__preview-act-badge" :style="actBadgeStyle(i)">第{{ i + 1 }}幕</text>
                    <text class="framework-editor__preview-act-title">{{ act.title }}</text>
                    <text class="framework-editor__preview-act-count">{{ (act.chapters || []).length }}章</text>
                    <lv-icon :name="previewActExpanded[i] ? 'ChevronUp' : 'ChevronDown'" :size="12" color="#94a3b8" />
                  </view>
                  <view v-if="previewActExpanded[i]">
                    <text v-if="act.summary" class="framework-editor__preview-act-summary">{{ act.summary }}</text>
                    <view v-for="ch in (act.chapters || []).slice(0, 5)" :key="ch.chapter_number" class="framework-editor__preview-chapter">
                      <text class="framework-editor__preview-chapter-num">#{{ String(ch.chapter_number).padStart(2, '0') }}</text>
                      <text class="framework-editor__preview-chapter-title">{{ ch.title }}</text>
                    </view>
                    <text v-if="(act.chapters || []).length > 5" class="framework-editor__preview-more">还有 {{ (act.chapters || []).length - 5 }} 章...</text>
                  </view>
                </view>
              </template>
              <text v-else class="framework-editor__preview-empty">暂无大纲</text>
            </view>
          </view>
        </view>
      </template>

      <!-- ══ Tab Navigation ══ -->
      <view class="framework-editor__tabs">
        <view
          v-for="tab in TAB_CONFIG"
          :key="tab.key"
          :class="['framework-editor__tab', { 'framework-editor__tab--active': activeTab === tab.key }]"
          @tap="activeTab = tab.key"
        >
          <lv-icon :name="tab.icon" :size="14" :color="activeTab === tab.key ? '#2563eb' : '#64748b'" />
          <text :class="['framework-editor__tab-label', { 'framework-editor__tab-label--active': activeTab === tab.key }]">{{ tab.label }}</text>
        </view>
      </view>

      <!-- ══ Tab Content ══ -->
      <view class="framework-editor__tab-content">
        <!-- Description Tab -->
        <template v-if="activeTab === 'description'">
          <view class="framework-editor__field-group">
            <text class="framework-editor__field-label">故事描述</text>
            <text class="framework-editor__field-hint">用一段话描述故事的核心设定、背景和主线。这段描述会影响所有 AI 生成的结果。</text>
            <textarea v-model="description" class="framework-editor__textarea" placeholder="输入故事描述..." rows="12" />
            <text class="framework-editor__word-count">已输入 {{ description.length }} 字</text>
          </view>
        </template>

        <!-- Tags Tab -->
        <template v-if="activeTab === 'tags'">
          <view class="framework-editor__field-group">
            <text class="framework-editor__field-label">标签设定</text>
            <text class="framework-editor__field-hint">定义故事的类型、主题、风格和受众定位。</text>
            <view v-for="key in TAG_KEYS" :key="key" class="framework-editor__tag-field">
              <view class="framework-editor__tag-badge" :style="tagBadgeStyle(key)">
                <text class="framework-editor__tag-badge-text">{{ tagLabel(key) }}</text>
              </view>
              <input v-model="tags[key]" :placeholder="'输入' + tagLabel(key) + '...'" class="framework-editor__tag-input" />
            </view>
          </view>
        </template>

        <!-- Characters Tab -->
        <template v-if="activeTab === 'characters'">
          <view class="framework-editor__field-group">
            <view class="framework-editor__char-header">
              <view>
                <text class="framework-editor__field-label">角色设定</text>
                <text class="framework-editor__field-hint">编辑故事中的角色，包括大五人格、角色弧光和关系网络。</text>
              </view>
              <lv-button size="sm" @tap="addCharacter">
                <lv-icon name="Plus" :size="12" color="#fff" style="margin-right: 4rpx;" />添加角色
              </lv-button>
            </view>

            <template v-if="characters.length === 0">
              <view class="framework-editor__empty-state">
                <text class="framework-editor__empty-state-text">暂无角色，点击上方「添加角色」开始创建</text>
              </view>
            </template>

            <view v-else class="framework-editor__char-list">
              <view v-for="(char, i) in characters" :key="i" class="framework-editor__char-editor-card">
                <view class="framework-editor__char-editor-header">
                  <view class="framework-editor__char-editor-toggle" @tap="toggleCharEditor(i)">
                    <lv-icon :name="charEditorExpanded[i] ? 'ChevronDown' : 'ChevronRight'" :size="14" color="#94a3b8" />
                  </view>
                  <text class="framework-editor__char-index">#{{ i + 1 }}</text>
                  <input v-model="char.name" placeholder="角色名称" class="framework-editor__char-name-input" />
                  <picker :value="roleOptions.indexOf(char.role || '')" :range="roleOptions" @change="(e: any) => { char.role = roleOptions[e.detail.value] || ''; triggerCharUpdate(i) }">
                    <text class="framework-editor__char-role-select" :style="roleStyle(char.role)">{{ char.role || '选择角色' }}</text>
                  </picker>
                  <view class="framework-editor__char-remove" @tap="removeCharacter(i)">
                    <Trash2 :size="14" color="#ef4444" />
                  </view>
                </view>

                <view v-if="charEditorExpanded[i]" class="framework-editor__char-editor-body">
                  <view class="framework-editor__char-field">
                    <text class="framework-editor__char-field-label">描述</text>
                    <textarea v-model="char.description" placeholder="角色描述..." class="framework-editor__char-input" rows="2" />
                  </view>

                  <view class="framework-editor__char-field">
                    <text class="framework-editor__char-field-label">大五人格</text>
                    <view class="framework-editor__bf-grid">
                      <view v-for="bf in BIG_FIVE_META" :key="bf.key" class="framework-editor__bf-item">
                        <text class="framework-editor__bf-key">{{ bf.key }}</text>
                        <view class="framework-editor__bf-bar-wrap">
                          <view class="framework-editor__bf-bar" :style="{ height: getBFValue(char, bf.key) + '%', backgroundColor: bf.hue }" />
                        </view>
                        <slider :value="getBFValue(char, bf.key)" min="0" max="100" activeColor="#2563eb" blockSize="12" @change="(e: any) => setBigFive(i, bf.key, e.detail.value)" />
                        <text class="framework-editor__bf-val">{{ getBFValue(char, bf.key) }}</text>
                      </view>
                    </view>
                  </view>

                  <view class="framework-editor__char-field">
                    <text class="framework-editor__char-field-label">角色弧光</text>
                    <input v-model="char.motivation" placeholder="动机..." class="framework-editor__char-input" />
                    <input v-model="char.fear" placeholder="恐惧..." class="framework-editor__char-input" style="margin-top: 8rpx;" />
                  </view>

                  <view class="framework-editor__char-field">
                    <view class="framework-editor__char-field-header">
                      <text class="framework-editor__char-field-label">关系网络</text>
                      <text class="framework-editor__char-add-link" @tap="addRelationship(i)">+ 添加关系</text>
                    </view>
                    <view v-for="(rel, ri) in getRelationships(char)" :key="ri" class="framework-editor__rel-row">
                      <input v-model="rel.character" placeholder="角色名" class="framework-editor__rel-input" />
                      <text class="framework-editor__rel-arrow">→</text>
                      <input v-model="rel.relationship" placeholder="关系描述" class="framework-editor__rel-input" />
                      <view class="framework-editor__rel-remove" @tap="removeRelationship(i, ri)">
                        <X :size="12" color="#ef4444" />
                      </view>
                    </view>
                  </view>
                </view>
              </view>
            </view>

            <text v-if="characters.length > 0" class="framework-editor__char-count">共 {{ characters.length }} 个角色</text>
          </view>
        </template>

        <!-- Outline Tab -->
        <template v-if="activeTab === 'outline'">
          <view class="framework-editor__field-group">
            <view class="framework-editor__outline-header">
              <view>
                <text class="framework-editor__field-label">故事大纲</text>
                <text class="framework-editor__field-hint">编辑分幕结构和每章的规划内容。</text>
              </view>
              <lv-button size="sm" @tap="addAct">
                <lv-icon name="Plus" :size="12" color="#fff" style="margin-right: 4rpx;" />添加幕
              </lv-button>
            </view>

            <text v-if="outlineActs.length > 0" class="framework-editor__outline-summary">共 {{ outlineActs.length }} 幕 · {{ totalChapters }} 章</text>

            <template v-if="outlineActs.length === 0">
              <view class="framework-editor__empty-state">
                <text class="framework-editor__empty-state-text">暂无大纲，点击上方「添加幕」开始构建故事结构</text>
              </view>
            </template>

            <view v-else class="framework-editor__act-list">
              <view v-for="(act, i) in outlineActs" :key="i" class="framework-editor__act-editor-card" :style="actBorderStyle(i)">
                <view class="framework-editor__act-editor-header">
                  <view class="framework-editor__act-editor-toggle" @tap="toggleActEditor(i)">
                    <lv-icon :name="actEditorExpanded[i] ? 'ChevronDown' : 'ChevronRight'" :size="14" color="#94a3b8" />
                  </view>
                  <text class="framework-editor__act-badge" :style="actBadgeStyle(i)">第{{ i + 1 }}幕</text>
                  <input v-model="act.title" placeholder="幕标题" class="framework-editor__act-title-input" />
                  <text class="framework-editor__act-chapter-count">{{ (act.chapters || []).length }}章</text>
                  <view class="framework-editor__act-remove" @tap="removeAct(i)">
                    <Trash2 :size="14" color="#ef4444" />
                  </view>
                </view>

                <view v-if="actEditorExpanded[i]" class="framework-editor__act-editor-body">
                  <view class="framework-editor__act-field">
                    <text class="framework-editor__act-field-label">概述</text>
                    <textarea v-model="act.summary" placeholder="此幕的概述..." class="framework-editor__act-textarea" rows="3" />
                  </view>

                  <view class="framework-editor__act-field">
                    <view class="framework-editor__act-field-header">
                      <text class="framework-editor__act-field-label">章节列表</text>
                      <text class="framework-editor__act-add-link" @tap="addChapter(i)">+ 添加章节</text>
                    </view>
                    <template v-if="(act.chapters || []).length === 0">
                      <text class="framework-editor__act-empty-hint">暂无章节</text>
                    </template>
                    <view v-for="(ch, ci) in getActChapters(act)" :key="ci" class="framework-editor__chapter-editor-card">
                      <view class="framework-editor__chapter-editor-header">
                        <view class="framework-editor__chapter-editor-toggle" @tap="toggleChapterEditor(i, ci)">
                          <lv-icon :name="chapterEditorExpanded[i]?.[ci] ? 'ChevronDown' : 'ChevronRight'" :size="12" color="#94a3b8" />
                        </view>
                        <text class="framework-editor__chapter-num">#{{ String(ch.chapter_number || (ci + 1)).padStart(2, '0') }}</text>
                        <input v-model="ch.title" placeholder="章节标题" class="framework-editor__chapter-title-input" />
                        <view class="framework-editor__chapter-remove" @tap="removeChapter(i, ci)">
                          <X :size="11" color="#94a3b8" />
                        </view>
                      </view>

                      <view v-if="chapterEditorExpanded[i]?.[ci]" class="framework-editor__chapter-editor-body">
                        <textarea v-model="ch.summary" placeholder="本章摘要..." class="framework-editor__chapter-summary-input" rows="2" />
                        <textarea
                          :value="keyEventsText(ch)"
                          placeholder="关键事件（每行一条）"
                          class="framework-editor__chapter-summary-input"
                          rows="3"
                          @input="updateKeyEvents(ch, $event)"
                        />
                        <view class="framework-editor__chapter-meta-grid">
                          <input v-model="ch.goal" placeholder="本章目标" class="framework-editor__chapter-field-input" />
                          <input v-model="ch.conflict" placeholder="本章冲突" class="framework-editor__chapter-field-input" />
                          <input v-model="ch.hook" placeholder="章末钩子" class="framework-editor__chapter-field-input" />
                          <input v-model="ch.payoff" placeholder="本章回报" class="framework-editor__chapter-field-input" />
                        </view>
                        <input v-model="ch.highlight" placeholder="爽点 / 情绪点 / 记忆点" class="framework-editor__chapter-field-input" />
                      </view>
                    </view>
                  </view>
                </view>
              </view>
            </view>
          </view>
        </template>
      </view>

      <!-- 底部留白 -->
      <view class="framework-editor__bottom-spacer" />
    </scroll-view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { X, Trash2 } from '@lucide/vue'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import { storiesApi } from '@/api'
import { useUiStore } from '@/stores/ui'
import type { Story, Character, OutlineAct, OutlineChapter } from '@/api/types'

type EditableOutlineAct = OutlineAct & {
  summary?: string
}

// ─── 常量 ───
const TAB_CONFIG = [
  { key: 'description', label: '故事描述', icon: 'FileText' },
  { key: 'tags', label: '标签设定', icon: 'Tag' },
  { key: 'characters', label: '角色设定', icon: 'Users' },
  { key: 'outline', label: '故事大纲', icon: 'BookOpen' },
] as const

type TabKey = 'description' | 'tags' | 'characters' | 'outline'
const TAG_KEYS = ['type', 'theme', 'style', 'audience'] as const

const TAG_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  type: { bg: '#eff6ff', text: '#1d4ed8', border: '#bfdbfe' },
  theme: { bg: '#ecfdf5', text: '#047857', border: '#a7f3d0' },
  style: { bg: '#fffbeb', text: '#b45309', border: '#fde68a' },
  audience: { bg: '#f5f3ff', text: '#6d28d9', border: '#ddd6fe' },
}

const TAG_LABELS: Record<string, string> = {
  type: '类型', theme: '主题', style: '风格', audience: '受众',
}

const ROLE_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  '主角': { bg: '#fffbeb', text: '#b45309', border: '#fde68a' },
  '反派': { bg: '#fef2f2', text: '#b91c1c', border: '#fecaca' },
  '配角': { bg: '#eff6ff', text: '#1d4ed8', border: '#bfdbfe' },
}

const roleOptions = ['', '主角', '反派', '配角']

const BIG_FIVE_META = [
  { key: 'O', label: '开放性', hue: '#8b5cf6' },
  { key: 'C', label: '尽责性', hue: '#60a5fa' },
  { key: 'E', label: '外向性', hue: '#f59e0b' },
  { key: 'A', label: '宜人性', hue: '#34d399' },
  { key: 'N', label: '情绪性', hue: '#fb7185' },
]

const ACT_BADGE_COLORS = ['#eff6ff', '#ecfdf5', '#fffbef', '#f5f3ff', '#fef2f2']
const ACT_BORDER_COLORS = ['#60a5fa', '#38bdf8', '#34d399', '#f59e0b', '#8b5cf6']

// ─── 状态 ───
const uiStore = useUiStore()
const storyId = ref(0)

const activeTab = ref<TabKey>('description')
const previewExpanded = ref(true)
const saving = ref(false)
const loading = ref(true)

const description = ref('')
const tags = ref<Record<string, string>>({})
const characters = ref<Character[]>([])
const outlineActs = ref<EditableOutlineAct[]>([])
const originalOutline = ref<Record<string, any>>({})

const previewCharExpanded = ref<Record<number, boolean>>({})
const previewActExpanded = ref<Record<number, boolean>>({})
const charEditorExpanded = ref<Record<number, boolean>>({})
const actEditorExpanded = ref<Record<number, boolean>>({})
const chapterEditorExpanded = ref<Record<number, Record<number, boolean>>>({})

// ─── Computed ───
const hasTags = computed(() => Object.values(tags.value).some(v => typeof v === 'string' && v.trim()))
const totalChapters = computed(() => outlineActs.value.reduce((sum, act) => sum + (act.chapters || []).length, 0))

// ─── Helper Functions ───
function tagLabel(key: string): string { return TAG_LABELS[key] || key }

function tagBadgeStyle(key: string): Record<string, string> {
  const c = TAG_COLORS[key]
  return c ? { backgroundColor: c.bg, color: c.text } : {}
}

function roleStyle(role: string | undefined): Record<string, string> {
  if (!role) return { backgroundColor: '#f1f5f9', color: '#64748b' }
  const c = ROLE_COLORS[role]
  return c ? { backgroundColor: c.bg, color: c.text, borderColor: c.border } : { backgroundColor: '#f1f5f9', color: '#64748b' }
}

function actBadgeStyle(index: number): Record<string, string> {
  return { backgroundColor: ACT_BADGE_COLORS[index % ACT_BADGE_COLORS.length] }
}

function actBorderStyle(index: number): Record<string, string> {
  return { borderLeftColor: ACT_BORDER_COLORS[index % ACT_BORDER_COLORS.length] }
}

function getBFValue(char: Character, key: string): number {
  const bf = char.big_five || {} as any
  const val = bf[key] || bf[key.toLowerCase()]
  return typeof val === 'number' ? Math.max(0, Math.min(100, val > 10 ? val : val * 10)) : 50
}

function setBigFive(charIndex: number, key: string, value: number) {
  const bf = { ...(characters.value[charIndex].big_five || {}) } as any
  bf[key] = value
  characters.value[charIndex] = { ...characters.value[charIndex], big_five: bf }
}

function getRelationships(char: Character): Record<string, string>[] {
  return Array.isArray((char as any).relationships) ? (char as any).relationships : []
}

function getActChapters(act: EditableOutlineAct): any[] {
  return Array.isArray(act.chapters) ? act.chapters : []
}

function triggerCharUpdate(i: number) {
  characters.value = [...characters.value]
}

// ─── Toggles ───
function togglePreviewChar(i: number) { previewCharExpanded.value[i] = !previewCharExpanded.value[i] }
function togglePreviewAct(i: number) { previewActExpanded.value[i] = !previewActExpanded.value[i] }
function toggleCharEditor(i: number) { charEditorExpanded.value[i] = !charEditorExpanded.value[i] }
function toggleActEditor(i: number) { actEditorExpanded.value[i] = !actEditorExpanded.value[i] }
function toggleChapterEditor(actIdx: number, chIdx: number) {
  if (!chapterEditorExpanded.value[actIdx]) chapterEditorExpanded.value[actIdx] = {}
  chapterEditorExpanded.value[actIdx][chIdx] = !chapterEditorExpanded.value[actIdx]?.[chIdx]
}

// ─── Character Operations ───
function addCharacter() {
  characters.value.push({
    name: '', role: '', description: '', personality: '', motivation: '', fear: '',
    big_five: {}, arc: {},
  } as any)
}

function removeCharacter(index: number) {
  characters.value = characters.value.filter((_, i) => i !== index)
}

function addRelationship(charIndex: number) {
  const char = characters.value[charIndex]
  const rels = Array.isArray((char as any).relationships) ? [...(char as any).relationships] : []
  rels.push({ character: '', relationship: '' })
  characters.value[charIndex] = { ...char, relationships: rels }
}

function removeRelationship(charIndex: number, relIndex: number) {
  const char = characters.value[charIndex]
  const rels = Array.isArray((char as any).relationships) ? [...(char as any).relationships] : []
  rels.splice(relIndex, 1)
  characters.value[charIndex] = { ...char, relationships: rels }
}

// ─── Outline Operations ───
function addAct() {
  const actNum = outlineActs.value.length + 1
  outlineActs.value.push({ act: String(actNum), title: `第 ${actNum} 幕`, chapters: [] })
}

function removeAct(index: number) {
  outlineActs.value = outlineActs.value.filter((_, i) => i !== index)
}

function addChapter(actIndex: number) {
  const act = outlineActs.value[actIndex]
  const chapters = act.chapters || []
  const allChapters = outlineActs.value.flatMap(a => a.chapters || [])
  const globalMax = allChapters.length > 0 ? Math.max(...allChapters.map(ch => Number(ch.chapter_number) || 0)) : 0
  const nextNum = globalMax + 1
  chapters.push({
    chapter_number: nextNum,
    title: `第 ${nextNum} 章`,
    summary: '',
    is_current: false,
    key_events: [],
    goal: '',
    conflict: '',
    hook: '',
    payoff: '',
    highlight: '',
  })
  outlineActs.value[actIndex] = { ...act, chapters: [...chapters] }
}

function keyEventsText(chapter: OutlineChapter): string {
  return Array.isArray(chapter.key_events) ? chapter.key_events.join('\n') : String(chapter.key_events || '')
}

function updateKeyEvents(chapter: OutlineChapter, event: any) {
  chapter.key_events = String(event?.detail?.value || '')
    .split(/\r?\n|[;,，]/)
    .map(item => item.trim())
    .filter(Boolean)
}

function removeChapter(actIndex: number, chIndex: number) {
  const act = outlineActs.value[actIndex]
  const chapters = (act.chapters || []).filter((_, i) => i !== chIndex)
  outlineActs.value[actIndex] = { ...act, chapters }
}

// ─── Load Data ───
async function loadData() {
  if (!storyId.value) return
  loading.value = true
  try {
    const s: Story = await storiesApi.getStory(storyId.value)
    description.value = s.description || ''
    tags.value = {}
    if (s.tags && typeof s.tags === 'object') {
      for (const [k, v] of Object.entries(s.tags)) {
        if (typeof v === 'string') tags.value[k] = v
      }
    }
    characters.value = (s.characters || []) as Character[]
    const raw = s.outline as any
    originalOutline.value = raw && typeof raw === 'object' ? raw : {}
    outlineActs.value = (raw?.three_acts || []).map((act: EditableOutlineAct) => ({
      ...act,
      chapters: (act.chapters || []).map(chapter => ({
        ...chapter,
        key_events: Array.isArray(chapter.key_events)
          ? chapter.key_events.map(item => String(item)).filter(Boolean)
          : [],
      })),
    }))
  } catch (e: any) {
    uiStore.error(e.message || '加载框架数据失败')
  } finally {
    loading.value = false
  }
}

onLoad((options) => {
  storyId.value = parseInt(options?.storyId || '0')
  loadData()
})

// ─── Save ───
async function handleSave() {
  saving.value = true
  try {
    const cleanTags: Record<string, string> = {}
    for (const [key, val] of Object.entries(tags.value)) {
      if (val && val.trim()) cleanTags[key] = val.trim()
    }

    const outlinePayload: Record<string, any> = {
      ...originalOutline.value,
      three_acts: outlineActs.value.map(act => ({
        ...act,
        act: act.act,
        title: act.title,
        summary: (act as any).summary || '',
        chapters: (act.chapters || []).map(ch => ({
          ...ch,
          chapter_number: ch.chapter_number,
          title: ch.title,
          summary: ch.summary || '',
          is_current: ch.is_current || false,
          key_events: Array.isArray(ch.key_events) ? ch.key_events.map(item => String(item).trim()).filter(Boolean) : [],
          goal: ch.goal?.trim() || undefined,
          conflict: ch.conflict?.trim() || undefined,
          hook: ch.hook?.trim() || undefined,
          payoff: ch.payoff?.trim() || undefined,
          highlight: ch.highlight?.trim() || undefined,
        })),
      })),
    }

    await storiesApi.updateStory(storyId.value, {
      description: description.value || '',
      tags: cleanTags,
      characters: characters.value,
      outline: outlinePayload,
    } as any)

    uiStore.success('框架已保存')
    uni.navigateBack()
  } catch (e: any) {
    uiStore.error(e.message || '保存框架失败')
  } finally {
    saving.value = false
  }
}
</script>

<style lang="scss" scoped>
.framework-editor {
  min-height: 100vh;
  background: #f8fafc;

  &__nav-save {
    display: flex;
    align-items: center;
    gap: 6rpx;
    padding: 12rpx 20rpx;
  }

  &__nav-save-text {
    font-size: 24rpx;
    color: #2563eb;
    font-weight: 500;
  }

  &__body {
    height: calc(100vh - 88rpx - var(--status-bar-height));
    padding-top: calc(88rpx + var(--status-bar-height));
  }

  // ── Preview ──
  &__preview-toggle {
    display: flex;
    align-items: center;
    gap: 8rpx;
    padding: 16rpx 32rpx;
    background: #f8fafc;
    border-bottom: 1rpx solid #e5edf8;
  }

  &__preview-toggle-text {
    flex: 1;
    font-size: 22rpx;
    font-weight: 500;
    color: #2563eb;
  }

  &__preview {
    padding: 16rpx 32rpx;
    background: #f8fafc;
    border-bottom: 1rpx solid #e5edf8;
  }

  &__preview-card {
    background: #fff;
    border-radius: 16rpx;
    border: 1rpx solid #e2e8f0;
    margin-bottom: 12rpx;
    overflow: hidden;
  }

  &__preview-card-header {
    display: flex;
    align-items: center;
    gap: 8rpx;
    padding: 12rpx 16rpx;
    border-bottom: 1rpx solid #e5edf8;
    border-left: 6rpx solid;
    &--blue { border-left-color: #60a5fa; }
    &--emerald { border-left-color: #34d399; }
    &--violet { border-left-color: #a78bfa; }
    &--amber { border-left-color: #fbbf24; }
  }

  &__preview-card-label {
    font-size: 22rpx;
    font-weight: 600;
    color: #334155;
  }

  &__preview-card-body {
    padding: 12rpx 16rpx;
  }

  &__preview-text {
    font-size: 22rpx;
    color: #475569;
    line-height: 1.6;
    white-space: pre-wrap;
  }

  &__preview-empty {
    font-size: 20rpx;
    color: #94a3b8;
    font-style: italic;
  }

  &__preview-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 8rpx;
  }

  &__preview-tag {
    display: inline-flex;
    align-items: center;
    gap: 6rpx;
    padding: 4rpx 16rpx;
    border-radius: 20rpx;
    font-size: 18rpx;
    border: 1rpx solid;
  }

  &__preview-tag-label { opacity: 0.7; }
  &__preview-tag-value { font-weight: 500; }

  &__preview-char {
    border-bottom: 1rpx solid #f1f5f9;
    &:last-child { border-bottom: none; }
  }

  &__preview-char-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10rpx 0;
  }

  &__preview-char-info {
    display: flex;
    align-items: center;
    gap: 8rpx;
  }

  &__preview-char-name {
    font-size: 22rpx;
    font-weight: 500;
    color: #334155;
  }

  &__preview-char-role {
    font-size: 16rpx;
    padding: 2rpx 12rpx;
    border-radius: 12rpx;
  }

  &__preview-char-detail { padding: 0 0 10rpx; }

  &__preview-char-desc {
    font-size: 20rpx;
    color: #64748b;
  }

  &__preview-act {
    border-bottom: 1rpx solid #f1f5f9;
    &:last-child { border-bottom: none; }
  }

  &__preview-act-header {
    display: flex;
    align-items: center;
    gap: 8rpx;
    padding: 10rpx 0;
  }

  &__preview-act-badge {
    font-size: 16rpx;
    padding: 2rpx 12rpx;
    border-radius: 12rpx;
    font-weight: 500;
  }

  &__preview-act-title {
    flex: 1;
    font-size: 22rpx;
    font-weight: 500;
    color: #334155;
  }

  &__preview-act-count {
    font-size: 18rpx;
    color: #94a3b8;
  }

  &__preview-act-summary {
    font-size: 20rpx;
    color: #64748b;
    padding: 4rpx 0 8rpx;
    line-height: 1.5;
  }

  &__preview-chapter {
    display: flex;
    align-items: center;
    gap: 8rpx;
    padding: 4rpx 0;
  }

  &__preview-chapter-num {
    font-size: 18rpx;
    color: #94a3b8;
    font-family: monospace;
    min-width: 56rpx;
  }

  &__preview-chapter-title {
    font-size: 20rpx;
    color: #475569;
  }

  &__preview-more {
    font-size: 18rpx;
    color: #94a3b8;
    padding: 4rpx 0;
  }

  // ── Tabs ──
  &__tabs {
    display: flex;
    border-bottom: 1rpx solid #e5edf8;
    background: #f8fbff;
    padding: 0 16rpx;
    position: sticky;
    top: 0;
    z-index: 10;
  }

  &__tab {
    display: flex;
    align-items: center;
    gap: 6rpx;
    padding: 16rpx 20rpx;
    border-bottom: 3rpx solid transparent;
    &--active { border-bottom-color: #2563eb; }
  }

  &__tab-label {
    font-size: 22rpx;
    color: #64748b;
    font-weight: 500;
    &--active { color: #2563eb; }
  }

  // ── Tab Content ──
  &__tab-content {
    padding: 24rpx 32rpx;
    padding-bottom: 80rpx;
  }

  &__field-group { margin-bottom: 24rpx; }

  &__field-label {
    display: block;
    font-size: 26rpx;
    font-weight: 600;
    color: #1e293b;
    margin-bottom: 8rpx;
  }

  &__field-hint {
    display: block;
    font-size: 20rpx;
    color: #94a3b8;
    line-height: 1.5;
    margin-bottom: 16rpx;
  }

  &__textarea {
    width: 100%;
    padding: 20rpx;
    font-size: 24rpx;
    line-height: 1.6;
    color: #334155;
    background: #fcfcfa;
    border: 2rpx solid #e2e8f0;
    border-radius: 16rpx;
    min-height: 240rpx;
    box-sizing: border-box;
    outline: none;
  }

  &__word-count {
    display: block;
    text-align: right;
    font-size: 18rpx;
    color: #94a3b8;
    margin-top: 8rpx;
  }

  // ── Tags ──
  &__tag-field { margin-bottom: 16rpx; }

  &__tag-badge {
    display: inline-flex;
    padding: 4rpx 16rpx;
    border-radius: 20rpx;
    font-size: 18rpx;
    font-weight: 500;
    margin-bottom: 8rpx;
  }

  &__tag-input {
    width: 100%;
    padding: 16rpx 20rpx;
    font-size: 24rpx;
    color: #334155;
    background: #fcfcfa;
    border: 2rpx solid #e2e8f0;
    border-radius: 12rpx;
    box-sizing: border-box;
    outline: none;
  }

  // ── Characters ──
  &__char-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    margin-bottom: 16rpx;
  }

  &__empty-state {
    padding: 48rpx;
    text-align: center;
    border: 2rpx dashed #e2e8f0;
    border-radius: 16rpx;
  }

  &__empty-state-text {
    font-size: 22rpx;
    color: #94a3b8;
  }

  &__char-list {
    display: flex;
    flex-direction: column;
    gap: 12rpx;
  }

  &__char-editor-card {
    border: 1rpx solid #e2e8f0;
    border-radius: 16rpx;
    overflow: hidden;
    background: #fff;
  }

  &__char-editor-header {
    display: flex;
    align-items: center;
    gap: 8rpx;
    padding: 16rpx;
    border-bottom: 1rpx solid #f1f5f9;
  }

  &__char-editor-toggle { padding: 4rpx; }

  &__char-index {
    font-size: 20rpx;
    color: #94a3b8;
    min-width: 40rpx;
  }

  &__char-name-input {
    flex: 1;
    font-size: 24rpx;
    font-weight: 500;
    color: #334155;
    background: transparent;
    border: none;
    outline: none;
  }

  &__char-role-select {
    font-size: 18rpx;
    padding: 4rpx 16rpx;
    border-radius: 20rpx;
  }

  &__char-remove { padding: 8rpx; }

  &__char-editor-body { padding: 16rpx; }
  &__char-field { margin-bottom: 16rpx; }

  &__char-field-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8rpx;
  }

  &__char-field-label {
    display: block;
    font-size: 20rpx;
    font-weight: 500;
    color: #64748b;
    margin-bottom: 8rpx;
  }

  &__char-add-link {
    font-size: 20rpx;
    color: #2563eb;
    font-weight: 500;
  }

  &__char-input {
    width: 100%;
    padding: 12rpx 16rpx;
    font-size: 22rpx;
    color: #334155;
    background: #fcfcfa;
    border: 1rpx solid #e2e8f0;
    border-radius: 10rpx;
    box-sizing: border-box;
    outline: none;
  }

  &__char-count {
    display: block;
    text-align: right;
    font-size: 20rpx;
    color: #94a3b8;
    margin-top: 12rpx;
  }

  // ── Big Five ──
  &__bf-grid {
    display: flex;
    gap: 12rpx;
    justify-content: space-between;
  }

  &__bf-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4rpx;
    flex: 1;
  }

  &__bf-key {
    font-size: 18rpx;
    font-weight: 700;
    color: #64748b;
  }

  &__bf-bar-wrap {
    width: 100%;
    height: 80rpx;
    background: #f1f5f9;
    border-radius: 8rpx;
    display: flex;
    align-items: flex-end;
    overflow: hidden;
  }

  &__bf-bar {
    width: 100%;
    border-radius: 8rpx;
    transition: height 0.2s;
  }

  &__bf-val { font-size: 16rpx; color: #94a3b8; }

  // ── Relationships ──
  &__rel-row {
    display: flex;
    align-items: center;
    gap: 8rpx;
    margin-bottom: 8rpx;
  }

  &__rel-input {
    flex: 1;
    padding: 10rpx 12rpx;
    font-size: 20rpx;
    color: #334155;
    background: #fcfcfa;
    border: 1rpx solid #e2e8f0;
    border-radius: 8rpx;
    outline: none;
  }

  &__rel-arrow { font-size: 20rpx; color: #94a3b8; }
  &__rel-remove { padding: 4rpx; }

  // ── Outline ──
  &__outline-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    margin-bottom: 8rpx;
  }

  &__outline-summary {
    display: block;
    font-size: 20rpx;
    color: #94a3b8;
    margin-bottom: 16rpx;
  }

  &__act-list {
    display: flex;
    flex-direction: column;
    gap: 12rpx;
  }

  &__act-editor-card {
    border: 1rpx solid #e2e8f0;
    border-radius: 16rpx;
    overflow: hidden;
    background: #fff;
    border-left: 6rpx solid #60a5fa;
  }

  &__act-editor-header {
    display: flex;
    align-items: center;
    gap: 8rpx;
    padding: 16rpx;
    border-bottom: 1rpx solid #f1f5f9;
  }

  &__act-editor-toggle { padding: 4rpx; }

  &__act-badge {
    font-size: 18rpx;
    padding: 4rpx 16rpx;
    border-radius: 20rpx;
    font-weight: 500;
  }

  &__act-title-input {
    flex: 1;
    font-size: 24rpx;
    font-weight: 500;
    color: #334155;
    background: transparent;
    border: none;
    outline: none;
  }

  &__act-chapter-count { font-size: 18rpx; color: #94a3b8; }
  &__act-remove { padding: 8rpx; }
  &__act-editor-body { padding: 16rpx; }
  &__act-field { margin-bottom: 16rpx; }

  &__act-field-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8rpx;
  }

  &__act-field-label {
    display: block;
    font-size: 20rpx;
    font-weight: 500;
    color: #64748b;
    margin-bottom: 8rpx;
  }

  &__act-add-link {
    font-size: 20rpx;
    color: #2563eb;
    font-weight: 500;
  }

  &__act-textarea {
    width: 100%;
    padding: 12rpx 16rpx;
    font-size: 22rpx;
    color: #334155;
    background: #fcfcfa;
    border: 1rpx solid #e2e8f0;
    border-radius: 10rpx;
    box-sizing: border-box;
    outline: none;
  }

  &__act-empty-hint { font-size: 20rpx; color: #94a3b8; font-style: italic; }

  // ── Chapters ──
  &__chapter-editor-card {
    border: 1rpx solid #e2e8f0;
    border-radius: 10rpx;
    margin-bottom: 8rpx;
    background: #fcfcfa;
  }

  &__chapter-editor-header {
    display: flex;
    align-items: center;
    gap: 6rpx;
    padding: 10rpx 12rpx;
  }

  &__chapter-editor-toggle { padding: 2rpx; }

  &__chapter-num {
    font-size: 18rpx;
    color: #94a3b8;
    font-family: monospace;
    min-width: 48rpx;
  }

  &__chapter-title-input {
    flex: 1;
    font-size: 22rpx;
    color: #334155;
    background: transparent;
    border: none;
    outline: none;
  }

  &__chapter-remove { padding: 4rpx; }

  &__chapter-editor-body {
    padding: 8rpx 12rpx 12rpx;
    border-top: 1rpx solid #f1f5f9;
  }

  &__chapter-summary-input {
    width: 100%;
    padding: 10rpx 12rpx;
    font-size: 20rpx;
    color: #334155;
    background: #fff;
    border: 1rpx solid #e2e8f0;
    border-radius: 8rpx;
    outline: none;
    margin-bottom: 8rpx;
    box-sizing: border-box;
  }

  &__chapter-field-input {
    width: 100%;
    padding: 10rpx 12rpx;
    font-size: 20rpx;
    color: #334155;
    background: #fff;
    border: 1rpx solid #e2e8f0;
    border-radius: 8rpx;
    outline: none;
    box-sizing: border-box;
    margin-bottom: 8rpx;
  }

  &__chapter-meta-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8rpx;
  }

  &__bottom-spacer { height: 80rpx; }
}
</style>
