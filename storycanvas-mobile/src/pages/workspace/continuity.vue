<template>
  <view class="continuity-page">
    <lv-navbar title="连贯性记忆" show-back />
    <scroll-view scroll-y class="continuity-page__scroll">
      <lv-loading v-if="loading" />

      <template v-else>
        <view v-if="previousOpening" class="continuity-page__notice">
          <text class="continuity-page__notice-label">上一章必须承接</text>
          <text class="continuity-page__notice-text">{{ previousOpening }}</text>
        </view>

        <view class="continuity-page__section">
          <view class="continuity-page__section-header">
            <view>
              <text class="continuity-page__section-title">本章连续性</text>
              <text class="continuity-page__section-hint">这些信息会进入后续章节生成上下文</text>
            </view>
            <view class="continuity-page__edit-btn" @tap="editing ? saveMemory() : startEditing()">
              <lv-icon :name="editing ? 'Check' : 'Pencil'" :size="14" color="#2563eb" />
              <text class="continuity-page__edit-text">{{ editing ? '保存' : '编辑' }}</text>
            </view>
          </view>

          <template v-if="editing">
            <continuity-field v-model="draft.summary" label="当前章摘要" placeholder="概括本章已经发生的核心事件" multiline />
            <continuity-field v-model="draft.endingLocation" label="当前场景" placeholder="本章结束时所在位置" />
            <continuity-field v-model="draft.activeConflict" label="即时冲突" placeholder="下一章开场仍需处理的冲突" multiline />
            <continuity-field v-model="draft.activeCharacters" label="在场角色" placeholder="每行一个角色" multiline />
            <continuity-field v-model="draft.characterStates" label="角色当前状态" placeholder="每行一条状态" multiline />
            <continuity-field v-model="draft.immediateLoops" label="下一章应继续推进" placeholder="每行一条伏笔或待办事件" multiline />
          </template>

          <template v-else>
            <memory-row label="当前章摘要" :value="summaryText" />
            <memory-row label="当前场景" :value="textValue(handoff.ending_location)" />
            <memory-row label="即时冲突" :value="textValue(handoff.active_conflict)" />
            <memory-row label="在场角色" :value="listText(handoff.active_characters)" />
            <memory-row label="角色当前状态" :value="listText(handoff.character_states)" />
            <memory-row label="下一章应继续推进" :value="listText(handoff.immediate_open_loops)" />
          </template>
        </view>

        <view class="continuity-page__section">
          <view class="continuity-page__section-header">
            <view>
              <text class="continuity-page__section-title">作品长期记忆</text>
              <text class="continuity-page__section-hint">由系统持续维护，生成正文和 Agent 操作时自动引用</text>
            </view>
          </view>
          <memory-row label="当前故事状态" :value="textValue(storyMemory.story_state)" />
          <memory-row label="当前剧情弧" :value="textValue(storyMemory.current_arc_focus)" />
          <memory-row label="必须记住的事实" :value="listText(storyMemory.continuity_facts)" />
          <memory-row label="全局未回收伏笔" :value="listText(storyMemory.open_loops)" />
        </view>
      </template>
    </scroll-view>
  </view>
</template>

<script setup lang="ts">
import { defineComponent, h, reactive, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { chaptersApi, storiesApi } from '@/api'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'

const ContinuityField = defineComponent({
  props: {
    modelValue: { type: String, default: '' },
    label: { type: String, required: true },
    placeholder: { type: String, default: '' },
    multiline: { type: Boolean, default: false },
  },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () => h('view', { class: 'continuity-page__field' }, [
      h('text', { class: 'continuity-page__field-label' }, props.label),
      h(props.multiline ? 'textarea' : 'input', {
        class: ['continuity-page__input', props.multiline ? 'continuity-page__input--textarea' : ''],
        value: props.modelValue,
        placeholder: props.placeholder,
        onInput: (event: any) => emit('update:modelValue', event?.detail?.value || ''),
      }),
    ])
  },
})

const MemoryRow = defineComponent({
  props: {
    label: { type: String, required: true },
    value: { type: String, default: '' },
  },
  setup(props) {
    return () => h('view', { class: 'continuity-page__row' }, [
      h('text', { class: 'continuity-page__row-label' }, props.label),
      h('text', { class: ['continuity-page__row-value', !props.value ? 'continuity-page__row-value--empty' : ''] }, props.value || '未记录'),
    ])
  },
})

const chapterId = ref(0)
const loading = ref(true)
const saving = ref(false)
const editing = ref(false)
const summary = ref<Record<string, any>>({})
const handoff = ref<Record<string, any>>({})
const storyMemory = ref<Record<string, any>>({})
const previousOpening = ref('')
const draft = reactive({
  summary: '',
  endingLocation: '',
  activeConflict: '',
  activeCharacters: '',
  characterStates: '',
  immediateLoops: '',
})

const summaryText = ref('')

onLoad(options => {
  chapterId.value = Number(options?.chapterId || 0)
  if (!chapterId.value) {
    loading.value = false
    uni.showToast({ title: '缺少章节 ID', icon: 'none' })
    return
  }
  loadMemory()
})

async function loadMemory() {
  loading.value = true
  try {
    const chapter = await chaptersApi.getChapter(chapterId.value)
    const memory = chapter.memory_summary && typeof chapter.memory_summary === 'object' ? chapter.memory_summary : {}
    summary.value = recordValue(memory.chapter_summary)
    handoff.value = recordValue(memory.chapter_handoff)
    summaryText.value = textValue(summary.value.summary) || textValue(summary.value.content)

    const [story, chapters] = await Promise.all([
      storiesApi.getStory(chapter.story_id),
      chaptersApi.getChapters(chapter.story_id),
    ])
    storyMemory.value = recordValue(story.story_memory)
    const previous = chapters
      .filter(item => item.chapter_number < chapter.chapter_number)
      .sort((a, b) => b.chapter_number - a.chapter_number)[0]
    const previousHandoff = recordValue(previous?.memory_summary?.chapter_handoff)
    previousOpening.value = textValue(previousHandoff.opening_must_continue)
  } catch (error: any) {
    uni.showToast({ title: error.message || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

function startEditing() {
  draft.summary = summaryText.value
  draft.endingLocation = textValue(handoff.value.ending_location)
  draft.activeConflict = textValue(handoff.value.active_conflict)
  draft.activeCharacters = listText(handoff.value.active_characters, '\n')
  draft.characterStates = listText(handoff.value.character_states, '\n')
  draft.immediateLoops = listText(handoff.value.immediate_open_loops, '\n')
  editing.value = true
}

async function saveMemory() {
  if (saving.value) return
  saving.value = true
  try {
    const chapterSummary = {
      ...summary.value,
      summary: draft.summary.trim(),
    }
    const chapterHandoff = {
      ...handoff.value,
      ending_location: draft.endingLocation.trim(),
      active_conflict: draft.activeConflict.trim(),
      active_characters: toLines(draft.activeCharacters),
      character_states: toLines(draft.characterStates),
      immediate_open_loops: toLines(draft.immediateLoops),
    }
    await chaptersApi.updateContinuity(chapterId.value, {
      chapter_summary: chapterSummary,
      chapter_handoff: chapterHandoff,
    })
    summary.value = chapterSummary
    handoff.value = chapterHandoff
    summaryText.value = chapterSummary.summary
    editing.value = false
    uni.showToast({ title: '已保存', icon: 'success' })
  } catch (error: any) {
    uni.showToast({ title: error.message || '保存失败', icon: 'none' })
  } finally {
    saving.value = false
  }
}

function recordValue(value: any): Record<string, any> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function textValue(value: any): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return ''
}

function listText(value: any, separator = '；'): string {
  if (Array.isArray(value)) return value.map(item => textValue(item)).filter(Boolean).join(separator)
  return textValue(value)
}

function toLines(value: string): string[] {
  return value.split(/\r?\n/).map(item => item.trim()).filter(Boolean)
}
</script>

<style lang="scss" scoped>
.continuity-page {
  height: 100vh;
  background: #f4f7fb;

  &__scroll {
    height: 100%;
    box-sizing: border-box;
    padding: calc(var(--status-bar-height) + 108rpx) 24rpx 80rpx;
  }

  &__notice,
  &__section {
    max-width: 960rpx;
    margin: 0 auto 16rpx;
    padding: 24rpx;
    border: 1rpx solid #e2e8f0;
    border-radius: 8rpx;
    background: #ffffff;
  }

  &__notice {
    border-color: #bfdbfe;
    background: #eff6ff;
  }

  &__notice-label,
  &__notice-text,
  &__section-title,
  &__section-hint,
  &__field-label,
  &__row-label,
  &__row-value {
    display: block;
  }

  &__notice-label {
    margin-bottom: 8rpx;
    color: #1d4ed8;
    font-size: 22rpx;
    font-weight: 700;
  }

  &__notice-text {
    color: #334155;
    font-size: 25rpx;
    line-height: 1.6;
  }

  &__section-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 20rpx;
    margin-bottom: 20rpx;
  }

  &__section-title {
    color: #0f172a;
    font-size: 28rpx;
    font-weight: 700;
  }

  &__section-hint {
    margin-top: 6rpx;
    color: #94a3b8;
    font-size: 21rpx;
    line-height: 1.5;
  }

  &__edit-btn {
    display: flex;
    align-items: center;
    gap: 6rpx;
    flex-shrink: 0;
    padding: 10rpx 14rpx;
    border-radius: 8rpx;
    background: #eff6ff;
  }

  &__edit-text {
    color: #2563eb;
    font-size: 22rpx;
    font-weight: 600;
  }

  &__field,
  &__row {
    margin-top: 18rpx;
  }

  &__field-label,
  &__row-label {
    margin-bottom: 8rpx;
    color: #475569;
    font-size: 23rpx;
    font-weight: 600;
  }

  &__input {
    box-sizing: border-box;
    width: 100%;
    height: 72rpx;
    padding: 14rpx 16rpx;
    border: 1rpx solid #cbd5e1;
    border-radius: 8rpx;
    background: #f8fafc;
    color: #1e293b;
    font-size: 24rpx;

    &--textarea {
      min-height: 128rpx;
      line-height: 1.6;
    }
  }

  &__row {
    padding-top: 18rpx;
    border-top: 1rpx solid #f1f5f9;
  }

  &__row-value {
    color: #334155;
    font-size: 25rpx;
    line-height: 1.65;
    white-space: pre-wrap;

    &--empty { color: #94a3b8; }
  }
}
</style>
