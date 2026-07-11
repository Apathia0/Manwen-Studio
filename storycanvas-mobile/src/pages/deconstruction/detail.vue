<template>
  <view class="page">
    <lv-navbar title="拆书报告" show-back />
    <scroll-view scroll-y class="page__scroll">
      <view class="summary">
        <text class="summary__title">{{ result?.title || '拆书任务' }}</text>
        <text class="summary__meta">{{ result?.author || '未知作者' }} · {{ statusText }}</text>
      </view>
      <view v-if="loading" class="empty">正在加载...</view>
      <template v-else>
        <view v-if="status !== 'completed'" class="progress">
          <text class="progress__text">{{ result?.progress_markdown || statusText }}</text>
          <lv-button v-if="status === 'not_started' || status === 'failed'" block :loading="actionLoading" @tap="start">开始拆解</lv-button>
          <lv-button v-if="status === 'running' || status === 'pending'" block secondary @tap="cancel">取消任务</lv-button>
        </view>
        <view v-else class="report">
          <view class="report__header">
            <text class="report__title">完整报告</text>
            <text class="report__edit" @tap="editing = !editing">{{ editing ? '取消' : '编辑' }}</text>
          </view>
          <textarea v-if="editing" v-model="draft" class="report__textarea" />
          <text v-else class="report__content">{{ draft || '暂无报告内容' }}</text>
          <lv-button v-if="editing" block :loading="actionLoading" @tap="save">保存报告</lv-button>
        </view>
        <view v-if="status === 'completed'" class="report">
          <view class="report__header">
            <view>
              <text class="report__title">作者风格画像</text>
              <text class="report__status">{{ authorStatusText }}</text>
            </view>
            <text v-if="authorStatus === 'completed'" class="report__edit" @tap="authorEditing = !authorEditing">{{ authorEditing ? '取消' : '编辑' }}</text>
          </view>
          <text v-if="authorStatus === 'running' || authorStatus === 'pending'" class="progress__text">{{ authorProgress || '正在分析作者风格...' }}</text>
          <textarea v-if="authorEditing" v-model="authorDraft" class="report__textarea" />
          <text v-else-if="authorStatus === 'completed'" class="report__content">{{ authorDraft || '暂无作者画像内容' }}</text>
          <lv-button v-if="authorEditing" block :loading="authorActionLoading" @tap="saveAuthorReport">保存作者画像</lv-button>
          <lv-button v-else-if="authorStatus === 'not_started' || authorStatus === 'failed'" block secondary :loading="authorActionLoading" @tap="startAuthorAnalysis">
            {{ authorStatus === 'failed' ? '重新生成作者画像' : '生成作者画像' }}
          </lv-button>
        </view>
        <view v-if="status === 'completed'" class="resume">
          <text class="resume__title">继续拆解</text>
          <text class="resume__desc">原文新增或任务中断时，可按需要继续运行拆书流程。</text>
          <view class="resume__actions">
            <lv-button size="sm" secondary :loading="actionLoading" @tap="resume('partial')">补充分析</lv-button>
            <lv-button size="sm" secondary :loading="actionLoading" @tap="resume('quick_report')">重建报告</lv-button>
            <lv-button size="sm" secondary :loading="actionLoading" @tap="resume('full')">完整续跑</lv-button>
          </view>
        </view>
      </template>
    </scroll-view>
  </view>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { deconstructionApi } from '@/api'
import type { DeconstructionWorkResult } from '@/api/deconstruction'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'

const workId = ref(0)
const result = ref<DeconstructionWorkResult | null>(null)
const status = ref('not_started')
const loading = ref(true)
const actionLoading = ref(false)
const editing = ref(false)
const draft = ref('')
const authorStatus = ref('not_started')
const authorProgress = ref('')
const authorDraft = ref('')
const authorEditing = ref(false)
const authorActionLoading = ref(false)
let timer: ReturnType<typeof setInterval> | null = null

const statusText = computed(() => ({ completed: '已完成', running: '分析中', pending: '等待中', failed: '执行失败', not_started: '尚未开始' } as Record<string, string>)[status.value] || status.value)
const authorStatusText = computed(() => ({ completed: '已生成', running: '分析中', pending: '等待中', failed: '生成失败', not_started: '尚未生成' } as Record<string, string>)[authorStatus.value] || authorStatus.value)

async function load() {
  try {
    const current = await deconstructionApi.getStatus(workId.value)
    status.value = current.status || current.decon_status || 'not_started'
    if (status.value === 'completed') {
      result.value = await deconstructionApi.getResult(workId.value)
      draft.value = result.value.report_markdown || ''
      await loadAuthorStyle()
      stopPolling()
    } else {
      result.value = { id: workId.value, title: current.title || '拆书任务', author: current.author, status: status.value, progress_markdown: current.progress || current.progress_markdown }
    }
  } finally { loading.value = false }
}
async function start() {
  actionLoading.value = true
  try { await deconstructionApi.startWork(workId.value); await load(); startPolling() } finally { actionLoading.value = false }
}
async function cancel() { await deconstructionApi.cancelWork(workId.value); await load() }
async function save() {
  actionLoading.value = true
  try { await deconstructionApi.updateReport(workId.value, draft.value); editing.value = false } finally { actionLoading.value = false }
}
async function resume(mode: 'full' | 'partial' | 'quick_report') {
  actionLoading.value = true
  try {
    await deconstructionApi.resumeWork(workId.value, mode)
    status.value = 'pending'
    startPolling()
  } finally { actionLoading.value = false }
}
async function loadAuthorStyle() {
  const current = await deconstructionApi.getAuthorStyleStatus(workId.value)
  authorStatus.value = current.status
  authorProgress.value = current.progress || ''
  if (current.status === 'completed') {
    const authorResult = await deconstructionApi.getAuthorStyle(workId.value)
    authorDraft.value = authorResult.report_markdown || ''
  }
}
async function startAuthorAnalysis() {
  authorActionLoading.value = true
  try {
    await deconstructionApi.startAuthorStyle(workId.value)
    authorStatus.value = 'pending'
    startPolling()
  } finally { authorActionLoading.value = false }
}
async function saveAuthorReport() {
  authorActionLoading.value = true
  try {
    await deconstructionApi.updateAuthorStyleReport(workId.value, authorDraft.value)
    authorEditing.value = false
  } finally { authorActionLoading.value = false }
}
function startPolling() { if (!timer) timer = setInterval(load, 3000) }
function stopPolling() { if (timer) clearInterval(timer); timer = null }
onLoad(options => { workId.value = Number(options?.workId || 0); load().then(() => { if (status.value === 'running' || status.value === 'pending') startPolling() }) })
onUnmounted(stopPolling)
</script>

<style lang="scss" scoped>
.page { height: 100vh; background: #f4f7fb; }
.page__scroll { height: 100%; box-sizing: border-box; padding: calc(var(--status-bar-height) + 108rpx) 24rpx 50rpx; }
.summary, .progress, .report, .resume { max-width: 960rpx; margin: 0 auto 18rpx; padding: 24rpx; background: #fff; border: 1rpx solid #e2e8f0; border-radius: 12rpx; }
.summary__title { display: block; color: #0f172a; font-size: 32rpx; font-weight: 700; }
.summary__meta { display: block; margin-top: 8rpx; color: #64748b; font-size: 24rpx; }
.empty { padding: 100rpx; color: #94a3b8; text-align: center; }
.progress__text { display: block; margin-bottom: 22rpx; color: #64748b; white-space: pre-wrap; }
.report__header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20rpx; }
.report__title { color: #0f172a; font-weight: 700; }
.report__status { display: block; margin-top: 6rpx; color: #94a3b8; font-size: 22rpx; }
.report__edit { color: #2563eb; font-size: 24rpx; }
.report__content { display: block; color: #334155; font-size: 26rpx; line-height: 1.8; white-space: pre-wrap; }
.report__textarea { box-sizing: border-box; width: 100%; min-height: 900rpx; padding: 20rpx; margin-bottom: 18rpx; background: #f8fafc; border: 1rpx solid #cbd5e1; border-radius: 8rpx; font-size: 25rpx; line-height: 1.7; }
.resume__title { display: block; color: #0f172a; font-weight: 700; }
.resume__desc { display: block; margin: 10rpx 0 18rpx; color: #64748b; font-size: 24rpx; line-height: 1.6; }
.resume__actions { display: flex; flex-wrap: wrap; gap: 12rpx; }
</style>
