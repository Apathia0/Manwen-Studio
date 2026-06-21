<template>
  <view class="char-profiles">
    <lv-navbar title="角色外观" show-back />
    <view class="char-profiles__content">
      <!-- 操作按钮 -->
      <view class="char-profiles__actions">
        <lv-button size="sm" @tap="handleGenerate" :loading="generating">
          <lv-icon name="Sparkles" :size="12" color="#fff" style="margin-right: 4rpx;" />
          AI 生成
        </lv-button>
        <lv-button size="sm" secondary @tap="toggleEdit">
          <lv-icon :name="editing ? 'Check' : 'Pencil'" :size="12" :color="editing ? '#2563eb' : '#64748b'" style="margin-right: 4rpx;" />
          {{ editing ? '保存' : '编辑' }}
        </lv-button>
      </view>

      <!-- 编辑模式 -->
      <view v-if="editing" class="char-profiles__edit">
        <textarea
          v-model="draftText"
          class="char-profiles__textarea"
          placeholder="角色名: 张三&#10;性别: 男&#10;年龄: 18&#10;外貌: 黑发黑眼...&#10;&#10;角色名: 李四&#10;..."
          :disabled="saving"
        />
        <view class="char-profiles__edit-actions">
          <lv-button size="sm" secondary @tap="cancelEdit">取消</lv-button>
          <lv-button size="sm" @tap="saveEdit" :loading="saving">保存</lv-button>
        </view>
      </view>

      <!-- 展示模式 -->
      <view v-else class="char-profiles__cards">
        <view v-for="card in parsedCards" :key="card.name" class="char-profiles__card">
          <view class="char-profiles__card-header">
            <text class="char-profiles__name">{{ card.name }}</text>
          </view>
          <view v-for="field in card.fields" :key="field.label" class="char-profiles__field">
            <text class="char-profiles__field-label">{{ field.label }}</text>
            <text class="char-profiles__field-value">{{ field.value }}</text>
          </view>
        </view>
        <lv-empty v-if="parsedCards.length === 0" title="暂无角色" description="点击 AI 生成或编辑添加角色" />
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { mangaApi } from '@/api'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'

interface CharCard {
  name: string
  fields: { label: string; value: string }[]
}

const rawText = ref('')
const editing = ref(false)
const saving = ref(false)
const generating = ref(false)
const draftText = ref('')
const storyId = ref(0)

const parsedCards = computed<CharCard[]>(() => parseCharacterCards(rawText.value))

onMounted(async () => {
  const pages = getCurrentPages()
  const page = pages[pages.length - 1] as any
  storyId.value = Number(page.options?.storyId || 0)
  if (!storyId.value) {
    uni.showToast({ title: '缺少故事 ID', icon: 'none' })
    return
  }
  await loadCharacters()
})

async function loadCharacters() {
  try {
    const res = await mangaApi.getStoryCharacters(storyId.value)
    rawText.value = res.characters || ''
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  }
}

async function handleGenerate() {
  if (generating.value) return
  generating.value = true
  try {
    const res = await mangaApi.generateStoryCharacters(storyId.value)
    rawText.value = res.characters || ''
    uni.showToast({ title: '角色已生成', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '生成失败', icon: 'none' })
  } finally {
    generating.value = false
  }
}

function toggleEdit() {
  if (editing.value) {
    saveEdit()
  } else {
    draftText.value = rawText.value
    editing.value = true
  }
}

function cancelEdit() {
  editing.value = false
  draftText.value = ''
}

async function saveEdit() {
  saving.value = true
  try {
    await mangaApi.updateStoryCharacters(storyId.value, draftText.value)
    rawText.value = draftText.value
    editing.value = false
    uni.showToast({ title: '已保存', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '保存失败', icon: 'none' })
  } finally {
    saving.value = false
  }
}

// 解析角色文本为卡片列表(格式: 以"角色名:"开头的文本块)
function parseCharacterCards(text: string): CharCard[] {
  const normalized = (text || '').replace(/\r\n/g, '\n').trim()
  if (!normalized) return []

  const blocks = normalized.split(/\n(?=角色名[:：])/).filter(b => b.trim())
  const cards: CharCard[] = []

  for (let i = 0; i < blocks.length; i++) {
    const block = blocks[i].trim()
    if (!block) continue
    let name = `角色 ${i + 1}`
    const fields: { label: string; value: string }[] = []

    for (const rawLine of block.split('\n')) {
      const line = rawLine.trim()
      if (!line) continue
      const match = line.match(/^([^:：]{1,20})[:：]\s*(.+)$/)
      if (match) {
        const [, label, value] = match
        const labelStr = label.trim()
        const valueStr = value.trim()
        if (labelStr === '角色名') {
          name = valueStr
        }
        fields.push({ label: labelStr, value: valueStr })
      } else if (fields.length > 0) {
        // 多行值追加到上一个字段
        fields[fields.length - 1].value += `\n${line}`
      }
    }
    cards.push({ name, fields })
  }
  return cards
}
</script>

<style lang="scss" scoped>
.char-profiles {
  min-height: 100vh;
  background: $lv-bg-start;

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding;
  }

  &__actions {
    display: flex;
    gap: 16rpx;
    margin-bottom: 24rpx;
  }

  &__edit {
    background: #fff;
    border-radius: $lv-radius-md;
    padding: 24rpx;
  }

  &__textarea {
    width: 100%;
    min-height: 400rpx;
    font-size: $lv-font-sm;
    line-height: 1.6;
    color: $lv-text-primary;
    font-family: monospace;
  }

  &__edit-actions {
    display: flex;
    gap: 16rpx;
    justify-content: flex-end;
    margin-top: 16rpx;
  }

  &__cards {
    display: flex;
    flex-direction: column;
    gap: 16rpx;
  }

  &__card {
    background: #fff;
    border-radius: $lv-radius-md;
    padding: 28rpx;
    box-shadow: $lv-shadow-sm;
  }

  &__card-header {
    margin-bottom: 16rpx;
    padding-bottom: 12rpx;
    border-bottom: 1rpx solid $lv-border-light;
  }

  &__name {
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__field {
    margin-bottom: 12rpx;
  }

  &__field-label {
    display: block;
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    margin-bottom: 4rpx;
  }

  &__field-value {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    white-space: pre-wrap;
  }
}
</style>
