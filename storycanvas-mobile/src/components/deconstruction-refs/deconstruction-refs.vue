<template>
  <view class="refs">
    <view class="refs__header" @tap="expanded = !expanded">
      <view>
        <text class="refs__title">拆书报告引用</text>
        <text class="refs__hint">Agent 会参考已引用作品的写法与套路</text>
      </view>
      <text class="refs__count">{{ refs.length }} 份</text>
    </view>
    <view v-if="expanded" class="refs__body">
      <view v-if="loading" class="refs__empty">正在加载...</view>
      <template v-else>
        <view v-for="item in refs" :key="item.id" class="refs__row">
          <view class="refs__meta">
            <text class="refs__name">{{ item.title }}</text>
            <text class="refs__sub">{{ item.author || '未知作者' }}</text>
          </view>
          <text class="refs__action refs__action--danger" @tap="remove(item)">取消引用</text>
        </view>
        <view v-for="work in availableWorks" :key="work.id" class="refs__row">
          <view class="refs__meta">
            <text class="refs__name">{{ work.title }}</text>
            <text class="refs__sub">{{ work.author || '未知作者' }} · 可引用</text>
          </view>
          <text class="refs__action" @tap="add(work.id)">引用</text>
        </view>
        <view v-if="refs.length === 0 && availableWorks.length === 0" class="refs__empty">
          暂无已完成报告，先去拆书库创建。
        </view>
        <view class="refs__library" @tap="openLibrary">打开拆书库</view>
      </template>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { deconstructionApi } from '@/api'
import type { DeconstructionRefItem, DeconstructionWorkItem } from '@/api/deconstruction'

const props = defineProps<{ storyId: number }>()
const emit = defineEmits<{ changed: [] }>()
const expanded = ref(false)
const loading = ref(false)
const refs = ref<DeconstructionRefItem[]>([])
const works = ref<DeconstructionWorkItem[]>([])

const availableWorks = computed(() => {
  const used = new Set(refs.value.map(item => item.work_id))
  return works.value.filter(item => item.decon_status === 'completed' && !used.has(item.id))
})

async function load() {
  loading.value = true
  try {
    ;[refs.value, works.value] = await Promise.all([
      deconstructionApi.listRefs(props.storyId),
      deconstructionApi.listWorks()
    ])
  } finally {
    loading.value = false
  }
}

async function add(workId: number) {
  await deconstructionApi.addRef(props.storyId, workId)
  await load()
  emit('changed')
}

async function remove(item: DeconstructionRefItem) {
  await deconstructionApi.removeRef(props.storyId, item.id)
  await load()
  emit('changed')
}

function openLibrary() {
  uni.navigateTo({ url: '/pages/deconstruction/index' })
}

onMounted(load)
</script>

<style lang="scss" scoped>
.refs {
  background: #fff;
  border: 1rpx solid #e2e8f0;
  border-radius: 12rpx;
  overflow: hidden;
}
.refs__header, .refs__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20rpx;
}
.refs__header { padding: 24rpx; }
.refs__title, .refs__name { display: block; color: #0f172a; font-weight: 600; font-size: 28rpx; }
.refs__hint, .refs__sub { display: block; margin-top: 6rpx; color: #94a3b8; font-size: 22rpx; }
.refs__count { color: #2563eb; font-size: 24rpx; }
.refs__body { padding: 0 24rpx 24rpx; border-top: 1rpx solid #f1f5f9; }
.refs__row { padding: 20rpx 0; border-bottom: 1rpx solid #f1f5f9; }
.refs__meta { min-width: 0; flex: 1; }
.refs__action { color: #2563eb; font-size: 24rpx; }
.refs__action--danger { color: #ef4444; }
.refs__empty { padding: 28rpx 0; color: #94a3b8; text-align: center; font-size: 24rpx; }
.refs__library { margin-top: 20rpx; padding: 18rpx; color: #2563eb; background: #eff6ff; text-align: center; border-radius: 8rpx; font-size: 24rpx; }
</style>
