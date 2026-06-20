<template>
  <view class="char-refs">
    <lv-navbar title="角色参考图" show-back />
    <view class="char-refs__content">
      <CharacterRefSection
        v-if="storyId"
        :story-id="storyId"
        :chapter-id="chapterId"
        source-type="story"
        @change="handleRefChange"
      />
      <lv-empty v-else title="缺少故事" description="无法加载角色参考图" />
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import CharacterRefSection from '@/components/character-ref-section/character-ref-section.vue'

const storyId = ref(0)
const chapterId = ref(0)

onLoad((options) => {
  storyId.value = parseInt(options?.storyId || '0')
  chapterId.value = parseInt(options?.chapterId || '0')
})

function handleRefChange() {
  // 参考图变更后不做特殊处理，用户返回时会重新加载
}
</script>

<style lang="scss" scoped>
.char-refs {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx) $lv-page-padding $lv-page-padding;
  }
}
</style>
