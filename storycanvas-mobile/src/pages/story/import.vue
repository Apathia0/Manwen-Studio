<template>
  <view class="import-page">
    <lv-navbar title="导入小说" show-back />
    <view class="import-page__content">
      <!-- 文件选择(微信小程序) -->
      <!-- #ifdef MP-WEIXIN -->
      <lv-button block @tap="chooseFileWx">
        <lv-icon name="FileUp" :size="14" color="#fff" style="margin-right: 8rpx;" />
        选择文件
      </lv-button>
      <!-- #endif -->

      <!-- 文件选择(H5 和其他平台) -->
      <!-- #ifndef MP-WEIXIN -->
      <view class="import-page__h5-file">
        <lv-button block @tap="triggerFileInput">
          <lv-icon name="FileUp" :size="14" color="#fff" style="margin-right: 8rpx;" />
          选择文件 (txt/md)
        </lv-button>
        <input
          ref="fileInputRef"
          type="file"
          accept=".txt,.md,text/plain,text/markdown"
          class="import-page__file-input"
          @change="handleFileChange"
        />
      </view>
      <!-- #endif -->

      <!-- 已选文件 -->
      <view v-if="selectedFile" class="import-page__file">
        <FileText :size="24" color="#475569" />
        <text class="import-page__file-name">{{ selectedFile }}</text>
      </view>

      <!-- 文本粘贴(H5 备用) -->
      <!-- #ifndef MP-WEIXIN -->
      <view class="import-page__paste">
        <text class="import-page__paste-label">或直接粘贴文本:</text>
        <textarea
          v-model="pastedText"
          class="import-page__textarea"
          placeholder="粘贴小说内容..."
        />
        <lv-button
          block
          secondary
          :disabled="!pastedText.trim() || parsing"
          :loading="parsing"
          @tap="handlePasteImport"
        >
          解析粘贴内容
        </lv-button>
      </view>
      <!-- #endif -->

      <!-- 提示 -->
      <view class="import-page__hint">
        <text class="import-page__hint-text">支持 txt, md 格式</text>
        <text class="import-page__hint-text">文件大小不超过 10MB</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { FileText } from '@lucide/vue'
import { importApi } from '@/api'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'

const selectedFile = ref('')
const pastedText = ref('')
const parsing = ref(false)
const fileInputRef = ref<any>(null)

// 微信小程序文件选择
function chooseFileWx() {
  // #ifdef MP-WEIXIN
  ;(uni as any).chooseMessageFile({
    count: 1,
    type: 'file',
    extension: ['txt', 'md', 'docx'],
    success: (res: any) => {
      selectedFile.value = res.tempFiles[0].name
      const filePath = res.tempFiles[0].path
      parseAndNavigateWx(filePath)
    },
    fail: () => {
      uni.showToast({ title: '取消选择', icon: 'none' })
    },
  })
  // #endif
}

// H5 触发文件输入
function triggerFileInput() {
  if (fileInputRef.value) {
    fileInputRef.value.click()
  }
}

// H5 文件选择处理
async function handleFileChange(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  selectedFile.value = file.name
  parsing.value = true
  try {
    const text = await readFileAsText(file)
    await parseTextAndCreate(text, file.name)
  } catch (err: any) {
    uni.showToast({ title: err.message || '解析失败', icon: 'none' })
  } finally {
    parsing.value = false
  }
}

// 读取文件为文本
function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = () => reject(new Error('文件读取失败'))
    reader.readAsText(file, 'UTF-8')
  })
}

// 粘贴文本导入
async function handlePasteImport() {
  if (!pastedText.value.trim()) return
  parsing.value = true
  try {
    await parseTextAndCreate(pastedText.value, 'pasted.txt')
  } catch (err: any) {
    uni.showToast({ title: err.message || '解析失败', icon: 'none' })
  } finally {
    parsing.value = false
  }
}

// 解析文本并创建故事
async function parseTextAndCreate(text: string, filename: string) {
  // 简单分章: 按"第X章"或"第X话"分割
  const chapters = splitChapters(text)
  if (chapters.length === 0) {
    uni.showToast({ title: '未检测到章节内容', icon: 'none' })
    return
  }

  const title = filename.replace(/\.(txt|md|docx)$/i, '')

  try {
    const result = await importApi.createFromImport({
      title,
      chapters,
      analyze_framework: true,
    }) as any

    uni.showToast({ title: '导入成功', icon: 'success' })
    // 跳转到导入引导页（与 Web 端行为对齐）
    setTimeout(() => {
      const sid = result.story_id || result.id
      if (sid) {
        uni.redirectTo({ url: `/pages/story/import-guidance?storyId=${sid}` })
      } else {
        uni.navigateBack()
      }
    }, 1500)
  } catch (err: any) {
    uni.showToast({ title: err.message || '创建失败', icon: 'none' })
  }
}

// 微信小程序: 上传文件解析并创建故事
async function parseAndNavigateWx(filePath: string) {
  parsing.value = true
  try {
    const token = uni.getStorageSync('lv_auth_token')
    const res = await new Promise<any>((resolve, reject) => {
      uni.uploadFile({
        url: '/api/import/parse',
        filePath,
        name: 'file',
        header: {
          'Authorization': token ? `Bearer ${token}` : '',
        },
        success: (res) => {
          if (res.statusCode === 200) {
            resolve(JSON.parse(res.data))
          } else {
            reject(new Error('文件解析失败'))
          }
        },
        fail: (err) => {
          reject(new Error(err.errMsg || '文件上传失败'))
        },
      })
    })

    // 从解析结果创建故事
    const chapters = (res.chapters || []).map((ch: any, i: number) => ({
      chapter_number: i + 1,
      title: ch.title || `第 ${i + 1} 章`,
      content: ch.content || '',
      detection_method: ch.detection_method || 'api',
    }))

    const result = await importApi.createFromImport({
      title: res.detected_title || selectedFile.value.replace(/\.(txt|md|docx)$/i, ''),
      chapters,
      analyze_framework: true,
    })

    uni.showToast({ title: '导入成功', icon: 'success' })
    setTimeout(() => {
      const sid = result.story_id || result.id
      if (sid) {
        uni.redirectTo({ url: `/pages/story/import-guidance?storyId=${sid}` })
      } else {
        uni.navigateBack()
      }
    }, 1500)
  } catch (err: any) {
    uni.showToast({ title: err.message || '解析失败', icon: 'none' })
  } finally {
    parsing.value = false
  }
}

// 简单章节分割
function splitChapters(text: string): { chapter_number: number; title: string; content: string; detection_method: string }[] {
  const chapters: { chapter_number: number; title: string; content: string; detection_method: string }[] = []
  // 按"第X章"或"第X话"分割
  const parts = text.split(/\n(?=第[一二三四五六七八九十百千\d]+[章节话回])/)
  if (parts.length <= 1) {
    // 无法分章,作为单章
    if (text.trim()) {
      chapters.push({
        chapter_number: 1,
        title: '第 1 章',
        content: text.trim(),
        detection_method: 'single',
      })
    }
  } else {
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i].trim()
      if (!part) continue
      const titleMatch = part.match(/^(第[一二三四五六七八九十百千\d]+[章节话回][^\n]*)/)
      chapters.push({
        chapter_number: i + 1,
        title: titleMatch ? titleMatch[1] : `第 ${i + 1} 章`,
        content: part,
        detection_method: 'regex',
      })
    }
  }
  return chapters
}
</script>

<style lang="scss" scoped>
.import-page {
  min-height: 100vh;
  background: $lv-bg-start;

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding;
  }

  &__h5-file {
    position: relative;
  }

  &__file-input {
    position: absolute;
    width: 0;
    height: 0;
    opacity: 0;
    overflow: hidden;
  }

  &__file {
    display: flex;
    align-items: center;
    background: #fff;
    border-radius: $lv-radius-md;
    padding: 28rpx;
    margin-top: 24rpx;
    gap: 16rpx;
  }

  &__file-name {
    font-size: $lv-font-sm;
    color: $lv-text-primary;
  }

  &__paste {
    margin-top: 32rpx;
  }

  &__paste-label {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    margin-bottom: 12rpx;
  }

  &__textarea {
    width: 100%;
    min-height: 200rpx;
    padding: 20rpx;
    border: 1rpx solid $lv-border;
    border-radius: $lv-radius-sm;
    font-size: $lv-font-sm;
    background: #fff;
    margin-bottom: 16rpx;
  }

  &__hint {
    margin-top: 32rpx;
    text-align: center;
  }

  &__hint-text {
    display: block;
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }
}
</style>
