<template>
  <view class="template-editor">
    <lv-navbar :title="isEdit ? '编辑模板' : '创建模板'" />

    <view class="template-editor__content">
      <!-- 基本信息 -->
      <view class="template-editor__section">
        <text class="template-editor__label">模板名称 <text class="template-editor__required">*</text></text>
        <lv-input v-model="name" placeholder="输入模板名称" />

        <text class="template-editor__label">模板描述</text>
        <lv-textarea v-model="description" placeholder="描述模板的用途和特点" :maxlength="200" />

        <view class="template-editor__row">
          <view class="template-editor__col">
            <text class="template-editor__label">分类</text>
            <lv-input v-model="category" placeholder="如：玄幻、都市" />
          </view>
          <view class="template-editor__col">
            <text class="template-editor__label">标签</text>
            <lv-input v-model="tagsStr" placeholder="逗号分隔" />
          </view>
        </view>
      </view>

      <!-- Tab 切换提示词类型 -->
      <lv-swiper-tabs
        :tabs="['框架生成', '正文扩写', '角色生成', '漫画风格']"
        v-model:current="activeTabIndex"
      />

      <!-- 编辑模式切换 -->
      <view class="template-editor__mode-switch">
        <text class="template-editor__mode-label">编辑模式：</text>
        <view
          :class="['template-editor__mode-btn', { 'template-editor__mode-btn--active': !expertMode }]"
          @tap="expertMode = false"
        >增量修改</view>
        <view
          :class="['template-editor__mode-btn', { 'template-editor__mode-btn--active': expertMode }]"
          @tap="expertMode = true"
        >专家模式</view>
      </view>

      <!-- 系统默认 prompt 参考 -->
      <view class="template-editor__sys-section">
        <view class="template-editor__sys-toggle" @tap="showSysPrompt = !showSysPrompt">
          <lv-icon :name="showSysPrompt ? 'ChevronDown' : 'ChevronRight'" :size="14" color="#94a3b8" />
          <text class="template-editor__sys-toggle-text">{{ showSysPrompt ? '收起' : '查看' }}系统内置提示词</text>
        </view>
        <view v-if="showSysPrompt" class="template-editor__sys-content">
          <text class="template-editor__sys-text">{{ currentSysDefault || '加载中...' }}</text>
        </view>
      </view>

      <!-- 编辑区 -->
      <view class="template-editor__edit-area">
        <template v-if="expertMode">
          <text class="template-editor__hint">直接修改完整的系统提示词，替换默认行为：</text>
          <lv-textarea
            v-model="currentPrompt"
            placeholder="在此编辑完整的提示词..."
            :maxlength="-1"
            :auto-height="false"
            class="template-editor__textarea-expert"
          />
        </template>
        <template v-else>
          <text class="template-editor__hint">在系统内置提示词基础上，添加你的自定义要求：</text>
          <text class="template-editor__hint-sub">提示：可以写「禁止...」「必须...」「强调...」「风格要求...」等</text>
          <lv-textarea
            v-model="currentRules"
            :placeholder="rulesPlaceholder"
            :maxlength="-1"
            :auto-height="false"
            class="template-editor__textarea-rules"
          />
        </template>
      </view>

      <!-- 错误提示 -->
      <view v-if="error" class="template-editor__error">
        <text>{{ error }}</text>
      </view>

      <!-- 操作按钮 -->
      <view class="template-editor__footer">
        <lv-button secondary @tap="handleCancel" style="flex: 1;">取消</lv-button>
        <lv-button :loading="saving" :disabled="!name.trim()" @tap="handleSave" style="flex: 2;">保存模板</lv-button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { templatesApi } from '@/api'
import type { PromptTemplateItem, SystemDefaultPrompts } from '@/api/templates'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvInput from '@/components/lv-input/lv-input.vue'
import LvTextarea from '@/components/lv-textarea/lv-textarea.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvSwiperTabs from '@/components/lv-swiper-tabs/lv-swiper-tabs.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'

const templateId = ref<number | null>(null)
const isEdit = computed(() => !!templateId.value)

// 页面参数通过 onLoad 获取
onLoad((options: any) => {
  if (options?.id) {
    templateId.value = Number(options.id)
  }
})

const name = ref('')
const description = ref('')
const category = ref('')
const tagsStr = ref('')
const activeTabIndex = ref(0)
const expertMode = ref(false)
const showSysPrompt = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)

const sysDefaults = ref<SystemDefaultPrompts | null>(null)
const template = ref<PromptTemplateItem | null>(null)

// 提示词类型映射
const promptTypes = ['framework', 'chapter', 'character', 'manga_style'] as const
type PromptType = typeof promptTypes[number]

const activeTab = computed<PromptType>(() => promptTypes[activeTabIndex.value])

// 增量规则
const rules = ref<Record<PromptType, string>>({
  framework: '',
  chapter: '',
  character: '',
  manga_style: '',
})

// 专家模式完整 prompt
const prompts = ref<Record<PromptType, string>>({
  framework: '',
  chapter: '',
  character: '',
  manga_style: '',
})

const currentRules = computed({
  get: () => rules.value[activeTab.value],
  set: (v: string) => { rules.value[activeTab.value] = v },
})

const currentPrompt = computed({
  get: () => prompts.value[activeTab.value],
  set: (v: string) => { prompts.value[activeTab.value] = v },
})

const currentSysDefault = computed(() => {
  if (!sysDefaults.value) return ''
  return sysDefaults.value[activeTab.value] || ''
})

const rulesPlaceholder = computed(() => {
  const placeholders: Record<PromptType, string> = {
    framework: '例如：\n- 禁止在前5章内揭露世界观核心秘密\n- 每个主要角色必须有独立的成长副线\n- 章节末尾必须留下悬念或钩子',
    chapter: '例如：\n- 每章不低于2000字\n- 对话占正文比例不超过40%\n- 场景切换必须有过渡段落',
    character: '例如：\n- 所有角色必须有具体的身高和体型描述\n- 禁止出现玛丽苏/龙傲天类型角色\n- 反派必须有合理的动机',
    manga_style: '例如：\n- 禁止使用Q版/简笔画风格\n- 场景必须使用电影级构图\n- 角色服装必须符合故事时代背景',
  }
  return placeholders[activeTab.value]
})

// 切换到专家模式时初始化
watch(expertMode, (val) => {
  if (val) {
    const sysDefault = currentSysDefault.value
    const currentRulesVal = currentRules.value
    if (!currentPrompt.value.trim()) {
      currentPrompt.value = currentRulesVal.trim()
        ? sysDefault + '\n\n## 用户自定义要求\n' + currentRulesVal.trim()
        : sysDefault
    }
  }
})

onMounted(async () => {
  // 加载系统默认提示词
  try {
    sysDefaults.value = await templatesApi.getSystemDefaultPrompts()
  } catch {
    // 忽略
  }

  // 编辑模式：加载模板数据
  if (isEdit.value && templateId.value) {
    try {
      const tpl = await templatesApi.getPromptTemplate(templateId.value)
      template.value = tpl
      name.value = tpl.name
      description.value = tpl.description || ''
      category.value = tpl.category || ''
      tagsStr.value = (tpl.tags || []).join(', ')

      // 判断是增量模式还是专家模式
      // 如果 prompt 包含 "## 用户自定义要求"，则提取增量部分
      const types: PromptType[] = ['framework', 'chapter', 'character', 'manga_style']
      for (const type of types) {
        const promptVal = (tpl as any)[`${type}_prompt`] || ''
        const marker = '## 用户自定义要求'
        const idx = promptVal.indexOf(marker)
        if (idx >= 0) {
          // 增量模式
          rules.value[type] = promptVal.slice(idx + marker.length).trim()
          prompts.value[type] = ''
        } else {
          // 专家模式内容
          prompts.value[type] = promptVal
          if (promptVal.trim()) {
            // 如果有内容但不是增量格式，切到专家模式
            expertMode.value = true
          }
        }
      }
    } catch (e: any) {
      uni.showToast({ title: e.message || '加载模板失败', icon: 'none' })
    }
  }
})

async function handleSave() {
  if (!name.value.trim()) {
    error.value = '请输入模板名称'
    return
  }
  saving.value = true
  error.value = null

  try {
    const payload: Record<string, any> = {
      name: name.value.trim(),
      description: description.value.trim(),
      category: category.value.trim(),
      tags: tagsStr.value.split(',').map(t => t.trim()).filter(Boolean),
    }

    if (expertMode.value) {
      payload.framework_prompt = prompts.value.framework.trim() || null
      payload.chapter_prompt = prompts.value.chapter.trim() || null
      payload.character_prompt = prompts.value.character.trim() || null
      payload.manga_style_prompt = prompts.value.manga_style.trim() || null
    } else {
      const sys = sysDefaults.value
      if (rules.value.framework.trim()) {
        payload.framework_prompt = (sys?.framework || '') + '\n\n## 用户自定义要求\n' + rules.value.framework.trim()
      }
      if (rules.value.chapter.trim()) {
        payload.chapter_prompt = (sys?.chapter || '') + '\n\n## 用户自定义要求\n' + rules.value.chapter.trim()
      }
      if (rules.value.character.trim()) {
        payload.character_prompt = (sys?.character || '') + '\n\n## 用户自定义要求\n' + rules.value.character.trim()
      }
      if (rules.value.manga_style.trim()) {
        payload.manga_style_prompt = (sys?.manga_style || '') + '\n\n## 用户自定义要求\n' + rules.value.manga_style.trim()
      }
    }

    if (isEdit.value && templateId.value) {
      await templatesApi.updatePromptTemplate(templateId.value, payload)
    } else {
      await templatesApi.createPromptTemplate(payload)
    }

    uni.showToast({ title: '保存成功', icon: 'success' })
    setTimeout(() => uni.navigateBack(), 800)
  } catch (e: any) {
    error.value = e.message || '保存失败'
  } finally {
    saving.value = false
  }
}

function handleCancel() {
  uni.navigateBack()
}
</script>

<style lang="scss" scoped>
.template-editor {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx) $lv-page-padding $lv-page-padding;
  }

  &__section {
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: 32rpx;
    margin-bottom: $lv-section-gap;
    box-shadow: $lv-shadow-sm;
  }

  &__label {
    display: block;
    font-size: $lv-font-sm;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 12rpx;
    margin-top: 20rpx;

    &:first-child {
      margin-top: 0;
    }
  }

  &__required {
    color: $lv-error;
  }

  &__row {
    display: flex;
    gap: 20rpx;
  }

  &__col {
    flex: 1;
  }

  &__mode-switch {
    display: flex;
    align-items: center;
    gap: 16rpx;
    margin: 24rpx 0;
    padding: 0 8rpx;
  }

  &__mode-label {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__mode-btn {
    padding: 10rpx 24rpx;
    border-radius: $lv-radius-full;
    font-size: $lv-font-xs;
    color: $lv-text-secondary;
    border: 1rpx solid $lv-border-light;

    &--active {
      background: $lv-primary;
      color: #fff;
      border-color: $lv-primary;
    }
  }

  &__sys-section {
    margin-bottom: 24rpx;
  }

  &__sys-toggle {
    display: flex;
    align-items: center;
    gap: 8rpx;
    padding: 12rpx 0;
  }

  &__sys-toggle-text {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__sys-content {
    background: $lv-primary-lighter;
    border-radius: $lv-radius-md;
    padding: 24rpx;
    max-height: 400rpx;
    overflow-y: auto;
  }

  &__sys-text {
    font-size: $lv-font-xs;
    color: $lv-text-secondary;
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-all;
  }

  &__edit-area {
    margin-bottom: 24rpx;
  }

  &__hint {
    display: block;
    font-size: $lv-font-xs;
    color: $lv-text-secondary;
    margin-bottom: 12rpx;
  }

  &__hint-sub {
    display: block;
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    margin-bottom: 16rpx;
  }

  &__textarea-expert,
  &__textarea-rules {
    min-height: 400rpx;
  }

  &__error {
    background: rgba($lv-error, 0.1);
    border-radius: $lv-radius-md;
    padding: 20rpx;
    margin-bottom: 24rpx;
  }

  &__footer {
    display: flex;
    gap: 20rpx;
    padding-top: 24rpx;
    border-top: 1rpx solid $lv-border-light;
  }
}
</style>
