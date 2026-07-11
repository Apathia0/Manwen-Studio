<template>
  <view class="page">
    <lv-navbar title="作品圣经" show-back />
    <scroll-view scroll-y class="page__scroll">
      <view class="intro">作品圣经会作为小说创作、连续性维护和 Agent 执行任务时的长期上下文。</view>
      <view v-if="loading" class="empty">正在加载...</view>
      <view v-for="section in sections" v-else :key="section.key" class="section">
        <view class="section__header" @tap="expanded[section.key] = !expanded[section.key]">
          <view><text class="section__title">{{ section.title }}</text><text class="section__hint">{{ section.hint }}</text></view>
          <text class="section__toggle">{{ expanded[section.key] ? '收起' : '展开' }}</text>
        </view>
        <view v-if="expanded[section.key]" class="section__body">
          <view v-for="field in section.fields" :key="field[0]" class="field">
            <text class="field__label">{{ field[1] }}</text>
            <textarea v-model="draft[section.key][field[0]]" class="field__input" :placeholder="`填写${field[1]}`" auto-height />
          </view>
        </view>
      </view>
      <lv-button v-if="!loading" block :loading="saving" @tap="save">保存作品圣经</lv-button>
    </scroll-view>
  </view>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { onboardingApi } from '@/api'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'

const storyId = ref(0)
const loading = ref(true)
const saving = ref(false)
const draft = reactive<Record<string, Record<string, string>>>({})
const expanded = reactive<Record<string, boolean>>({ creative_brief: true })
const originalBible = ref<Record<string, any>>({})
const listFields = new Set(['must_keep_rules', 'forbidden_patterns', 'preferred_plot_patterns', 'continuity_facts', 'open_loops'])
const sections: Array<{ key: string; title: string; hint: string; fields: string[][] }> = [
  { key: 'creative_brief', title: '创意摘要', hint: '定位、卖点、冲突与节奏', fields: [['one_line_premise','一句话梗概'],['project_positioning','项目定位'],['genre','题材方向'],['audience','目标受众'],['tone','整体基调'],['core_hook','核心卖点'],['protagonist_core','主角核心'],['main_conflict','主线矛盾'],['longline_mystery','长线悬念'],['serial_length_target','目标篇幅'],['pacing_strategy','节奏策略'],['must_keep_rules','必须保留'],['world_setting','世界观'],['open_story_notes','开放备注']] },
  { key: 'writing_guidance', title: '写作指导', hint: '开篇、章节密度与长篇推进策略', fields: [['opening_strategy','开书策略'],['chapter_density_strategy','章节密度策略'],['midgame_engine','中段驱动力'],['late_game_direction','后期方向'],['forbidden_patterns','避免的模式（每行一条）'],['preferred_plot_patterns','推荐情节模式（每行一条）']] },
  { key: 'story_state', title: '故事状态', hint: '连续性事实与待回收线索', fields: [['story_state','当前故事状态'],['continuity_facts','连续性事实（每行一条）'],['open_loops','未回收伏笔（每行一条）']] },
  { key: 'raw_input', title: '原始输入', hint: '保留最初创意、篇幅和硬性要求', fields: [['raw_idea','原始创意'],['raw_length_goal','原始篇幅目标'],['raw_must_keep','必须保留（每行一条）'],['raw_notes','原始备注'],['raw_hidden_setting','隐藏设定']] },
  { key: 'import_guidance', title: '导入指导', hint: '导入作品续写时遵循的边界', fields: [['import_material_type','导入素材类型'],['must_keep','必须保留（每行一条）'],['author_goal','作者目标'],['adjustment_scope','允许调整范围'],['longline_plan','长线预案'],['tone_guardrails','风格护栏']] }
]

function asObject(value: any) { return typeof value === 'string' ? { content: value } : (value && typeof value === 'object' ? value : {}) }
async function load() {
  loading.value = true
  try {
    const bible = (await onboardingApi.getStoryBible(storyId.value)).story_bible || {}
    originalBible.value = bible && typeof bible === 'object' ? bible : {}
    for (const section of sections) {
      const source = asObject(section.key === 'creative_brief' ? (bible.creative_brief || bible) : bible[section.key])
      draft[section.key] = {}
      for (const [key] of section.fields) {
        const value = readCompatibleField(source, key)
        draft[section.key][key] = formatEditableValue(value)
      }
    }
  } finally { loading.value = false }
}
function formatEditableValue(value: any): string {
  if (Array.isArray(value)) return value.join('\n')
  if (value && typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value ?? '')
}
function readCompatibleField(source: Record<string, any>, key: string) {
  const aliases: Record<string, string[]> = {
    core_hook: ['selling_point', 'sellingPoint', 'hook'],
    longline_mystery: ['long_hook', 'longline'],
    serial_length_target: ['target_word_count'],
    must_keep_rules: ['must_keep'],
    world_setting: ['worldview'],
    open_story_notes: ['open_notes'],
    story_state: ['current_stage', 'focus', 'content'],
    open_loops: ['open_threads'],
    raw_idea: ['content'],
    import_material_type: ['material_type'],
  }
  return source[key] ?? aliases[key]?.map(alias => source[alias]).find(value => value != null)
}
async function save() {
  saving.value = true
  try {
    const payload: Record<string, any> = { ...originalBible.value }
    for (const section of sections) {
      const originalSection = section.key === 'creative_brief'
        ? asObject(originalBible.value.creative_brief)
        : asObject(originalBible.value[section.key])
      payload[section.key] = { ...originalSection }
      for (const [key] of section.fields) {
        const rawValue = draft[section.key][key] || ''
        if (listFields.has(key)) {
          payload[section.key][key] = String(rawValue).split(/\r?\n/).map((item: string) => item.trim()).filter(Boolean)
        } else if (key === 'world_setting') {
          const trimmed = String(rawValue).trim()
          if (!trimmed) {
            payload[section.key][key] = null
          } else {
            try {
              payload[section.key][key] = JSON.parse(trimmed)
            } catch {
              payload[section.key][key] = trimmed
            }
          }
        } else {
          payload[section.key][key] = String(rawValue).trim()
        }
      }
    }
    await onboardingApi.updateStoryBible(storyId.value, payload)
    uni.showToast({ title: '已保存', icon: 'success' })
  } finally { saving.value = false }
}
onLoad(options => { storyId.value = Number(options?.storyId || 0); load() })
</script>

<style lang="scss" scoped>
.page { height: 100vh; background: #f4f7fb; }
.page__scroll { height: 100%; box-sizing: border-box; padding: calc(var(--status-bar-height) + 108rpx) 24rpx 80rpx; }
.intro, .section { max-width: 960rpx; margin: 0 auto 16rpx; padding: 24rpx; background: #fff; border: 1rpx solid #e2e8f0; border-radius: 12rpx; }
.intro { color: #64748b; font-size: 24rpx; line-height: 1.6; }
.empty { padding: 100rpx; color: #94a3b8; text-align: center; }
.section__header { display: flex; align-items: center; justify-content: space-between; gap: 20rpx; }
.section__title { display: block; color: #0f172a; font-size: 28rpx; font-weight: 700; }
.section__hint { display: block; margin-top: 6rpx; color: #94a3b8; font-size: 22rpx; }
.section__toggle { color: #2563eb; font-size: 24rpx; }
.section__body { margin-top: 20rpx; padding-top: 2rpx; border-top: 1rpx solid #f1f5f9; }
.field { margin-top: 20rpx; }
.field__label { display: block; margin-bottom: 10rpx; color: #475569; font-size: 24rpx; font-weight: 600; }
.field__input { box-sizing: border-box; width: 100%; min-height: 88rpx; padding: 18rpx; background: #f8fafc; border: 1rpx solid #cbd5e1; border-radius: 8rpx; font-size: 25rpx; line-height: 1.6; }
</style>
