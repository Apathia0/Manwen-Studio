<template>
  <view class="page">
    <lv-navbar title="拆书库" show-back />
    <view class="page__content">
      <view class="page__actions">
        <lv-button block @tap="openCreate">新建拆书任务</lv-button>
      </view>
      <view v-if="loading" class="page__empty">正在加载拆书库...</view>
      <view v-else-if="works.length === 0" class="page__empty">暂无拆书任务</view>
      <view v-for="work in works" :key="work.id" class="work" @tap="openDetail(work.id)">
        <view class="work__top">
          <text class="work__title">{{ work.title }}</text>
          <text :class="['work__status', `work__status--${work.decon_status}`]">{{ statusText(work) }}</text>
        </view>
        <text class="work__meta">{{ work.author || '未知作者' }} · {{ work.platform || '文本导入' }}</text>
        <text class="work__progress">{{ work.progress_markdown || `已抓取 ${work.crawled_chapters || 0} 章` }}</text>
        <view class="work__bottom">
          <text class="work__link">查看报告</text>
          <text class="work__delete" @tap.stop="remove(work)">删除</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { onShow } from '@dcloudio/uni-app'
import { ref } from 'vue'
import { deconstructionApi } from '@/api'
import type { DeconstructionWorkItem } from '@/api/deconstruction'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'

const works = ref<DeconstructionWorkItem[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try { works.value = await deconstructionApi.listWorks() } finally { loading.value = false }
}
function statusText(work: DeconstructionWorkItem) {
  return ({ completed: '已完成', running: '分析中', pending: '等待中', failed: '失败', not_started: '未开始' } as Record<string, string>)[work.decon_status] || work.decon_status
}
function openCreate() { uni.navigateTo({ url: '/pages/deconstruction/work' }) }
function openDetail(id: number) { uni.navigateTo({ url: `/pages/deconstruction/detail?workId=${id}` }) }
function remove(work: DeconstructionWorkItem) {
  uni.showModal({
    title: '删除拆书任务',
    content: `确定删除《${work.title}》及其报告吗？`,
    success: async result => {
      if (!result.confirm) return
      await deconstructionApi.deleteWork(work.id)
      await load()
    }
  })
}
onShow(load)
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: #f4f7fb; }
.page__content { padding: calc(var(--status-bar-height) + 108rpx) 24rpx 40rpx; max-width: 960rpx; margin: 0 auto; }
.page__actions { margin-bottom: 20rpx; }
.page__empty { padding: 100rpx 20rpx; color: #94a3b8; text-align: center; }
.work { padding: 24rpx; margin-bottom: 16rpx; background: #fff; border: 1rpx solid #e2e8f0; border-radius: 12rpx; }
.work__top, .work__bottom { display: flex; justify-content: space-between; align-items: center; gap: 16rpx; }
.work__title { flex: 1; color: #0f172a; font-size: 30rpx; font-weight: 700; }
.work__status { padding: 6rpx 12rpx; color: #64748b; background: #f1f5f9; border-radius: 6rpx; font-size: 22rpx; }
.work__status--completed { color: #15803d; background: #f0fdf4; }
.work__status--running { color: #1d4ed8; background: #eff6ff; }
.work__status--failed { color: #dc2626; background: #fef2f2; }
.work__meta, .work__progress { display: block; margin-top: 12rpx; color: #64748b; font-size: 24rpx; }
.work__progress { color: #94a3b8; }
.work__bottom { margin-top: 22rpx; padding-top: 18rpx; border-top: 1rpx solid #f1f5f9; }
.work__link { color: #2563eb; font-size: 24rpx; }
.work__delete { color: #ef4444; font-size: 24rpx; }
</style>
