<template>
  <view class="page">
    <lv-navbar title="新建拆书" show-back />
    <scroll-view scroll-y class="page__scroll">
      <view class="tabs">
        <view :class="['tabs__item', { 'tabs__item--active': mode === 'text' }]" @tap="mode = 'text'">粘贴原文</view>
        <view :class="['tabs__item', { 'tabs__item--active': mode === 'file' }]" @tap="mode = 'file'">上传 TXT</view>
        <view :class="['tabs__item', { 'tabs__item--active': mode === 'search' }]" @tap="mode = 'search'">在线搜书</view>
      </view>
      <view v-if="mode === 'text'" class="form">
        <input v-model="title" class="field" placeholder="作品名称" />
        <input v-model="author" class="field" placeholder="作者（可选）" />
        <textarea v-model="text" class="textarea" placeholder="粘贴小说正文，导入后可开始拆解..." />
        <lv-button block :loading="submitting" @tap="submitText">导入并创建</lv-button>
      </view>
      <view v-else-if="mode === 'file'" class="form">
        <input v-model="title" class="field" placeholder="作品名称（可留空读取文件名）" />
        <input v-model="author" class="field" placeholder="作者（可选）" />
        <view class="file-picker" @tap="chooseFile">
          <text class="file-picker__title">{{ selectedFileName || '选择 TXT 文件' }}</text>
          <text class="file-picker__hint">支持从本机文件中选择小说原文</text>
        </view>
        <lv-button block :loading="submitting" :disabled="!selectedFilePath" @tap="submitFile">上传并创建</lv-button>
      </view>
      <view v-else class="form">
        <view class="search">
          <input v-model="keyword" class="field search__input" placeholder="输入书名或关键词" />
          <lv-button :loading="searching" @tap="search">搜索</lv-button>
        </view>
        <view v-for="item in results" :key="item.book_id || item.id" class="result">
          <view class="result__meta">
            <text class="result__title">{{ item.title }}</text>
            <text class="result__sub">{{ item.author || '未知作者' }}</text>
          </view>
          <lv-button size="sm" :loading="submitting" @tap="create(item)">添加</lv-button>
        </view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { deconstructionApi } from '@/api'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'

const mode = ref<'text' | 'file' | 'search'>('text')
const title = ref('')
const author = ref('')
const text = ref('')
const keyword = ref('')
const results = ref<any[]>([])
const submitting = ref(false)
const searching = ref(false)
const selectedFilePath = ref('')
const selectedFileName = ref('')

async function submitText() {
  if (!title.value.trim() || !text.value.trim()) return uni.showToast({ title: '请填写作品名称和正文', icon: 'none' })
  submitting.value = true
  try {
    const result = await deconstructionApi.importText({ title: title.value.trim(), author: author.value.trim(), text: text.value })
    uni.redirectTo({ url: `/pages/deconstruction/detail?workId=${result.work_id}` })
  } finally { submitting.value = false }
}
function chooseFile() {
  const done = (files: any[]) => {
    const file = files?.[0]
    if (!file) return
    selectedFilePath.value = file.path || file.tempFilePath || ''
    selectedFileName.value = file.name || selectedFilePath.value.split(/[\\/]/).pop() || '已选择文件'
    if (!title.value.trim()) title.value = selectedFileName.value.replace(/\.txt$/i, '')
  }
  // #ifdef MP-WEIXIN
  uni.chooseMessageFile({ count: 1, type: 'file', extension: ['txt'], success: res => done(res.tempFiles as any[]) })
  // #endif
  // #ifndef MP-WEIXIN
  uni.chooseFile({ count: 1, extension: ['.txt'], success: (res: any) => done(res.tempFiles || []) } as any)
  // #endif
}
async function submitFile() {
  if (!selectedFilePath.value) return
  submitting.value = true
  try {
    const result = await deconstructionApi.importFile(selectedFilePath.value, title.value.trim() || undefined, author.value.trim() || undefined)
    uni.redirectTo({ url: `/pages/deconstruction/detail?workId=${result.work_id}` })
  } finally { submitting.value = false }
}
async function search() {
  if (!keyword.value.trim()) return
  searching.value = true
  try {
    const result = await deconstructionApi.searchNovels(keyword.value.trim())
    results.value = result.items || result.results || result || []
  } finally { searching.value = false }
}
async function create(item: any) {
  submitting.value = true
  try {
    const result = await deconstructionApi.createWork({
      title: item.title,
      author: item.author,
      book_id: String(item.book_id || item.id),
      platform: item.platform || 'qidian'
    })
    uni.redirectTo({ url: `/pages/deconstruction/detail?workId=${result.work_id}` })
  } finally { submitting.value = false }
}
</script>

<style lang="scss" scoped>
.page { height: 100vh; background: #f4f7fb; }
.page__scroll { height: 100%; box-sizing: border-box; padding: calc(var(--status-bar-height) + 108rpx) 24rpx 40rpx; }
.tabs { display: grid; grid-template-columns: repeat(3, 1fr); padding: 6rpx; margin-bottom: 20rpx; background: #e2e8f0; border-radius: 10rpx; }
.tabs__item { padding: 18rpx; color: #64748b; text-align: center; font-size: 26rpx; }
.tabs__item--active { color: #0f172a; background: #fff; border-radius: 8rpx; font-weight: 600; }
.form { max-width: 960rpx; margin: 0 auto; }
.field, .textarea { box-sizing: border-box; width: 100%; margin-bottom: 16rpx; padding: 22rpx; background: #fff; border: 1rpx solid #cbd5e1; border-radius: 10rpx; font-size: 26rpx; }
.textarea { height: 560rpx; }
.file-picker { margin-bottom: 20rpx; padding: 48rpx 24rpx; text-align: center; background: #fff; border: 2rpx dashed #94a3b8; border-radius: 10rpx; }
.file-picker__title { display: block; color: #2563eb; font-size: 28rpx; font-weight: 600; }
.file-picker__hint { display: block; margin-top: 10rpx; color: #94a3b8; font-size: 22rpx; }
.search { display: flex; gap: 12rpx; }
.search__input { flex: 1; }
.result { display: flex; align-items: center; gap: 20rpx; padding: 22rpx; margin-bottom: 12rpx; background: #fff; border-radius: 10rpx; }
.result__meta { flex: 1; min-width: 0; }
.result__title { display: block; color: #0f172a; font-weight: 600; }
.result__sub { display: block; margin-top: 6rpx; color: #94a3b8; font-size: 22rpx; }
</style>
