<template>
  <view class="ref-images">
    <lv-navbar title="参考图" show-back />
    <view class="ref-images__content">
      <lv-button block @tap="handleAdd">添加参考图</lv-button>
      <view class="ref-images__grid">
        <ref-image-card v-for="(img,i) in images" :key="i" :image-path="img.path" @delete="handleDelete(i)" />
      </view>
      <lv-empty v-if="images.length === 0" title="暂无参考图" description="上传角色参考图帮助AI保持一致形象" />
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { get, del } from '@/utils/request'
import { useImagePicker } from '@/composables/useImagePicker'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import RefImageCard from '@/components/ref-image-card/ref-image-card.vue'

const images = ref<{path:string}[]>([])
const { chooseAndConvert } = useImagePicker()

onMounted(async () => {
  const pages = getCurrentPages(); const page = pages[pages.length - 1] as any
  const chapterId = page.options?.chapterId || 0
  try {
    const res = await get(`/api/chapters/${chapterId}/ref-images`) as any
    images.value = res.images || []
  } catch (e) { console.error(e) }
})

async function handleAdd() {
  const base64List = await chooseAndConvert()
  if (base64List.length > 0) uni.showToast({ title: '上传成功', icon: 'success' })
}

async function handleDelete(index: number) {
  images.value.splice(index, 1)
  uni.showToast({ title: '已删除', icon: 'success' })
}
</script>

<style lang="scss" scoped>
.ref-images {
  min-height: 100vh; background: $lv-bg-start;
  &__content { padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding; }
  &__grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16rpx; margin-top: 16rpx; }
}
</style>
