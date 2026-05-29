<template>
  <view class="import-guidance">
    <lv-navbar title="导入引导" show-back />
    <view class="import-guidance__chat">
      <scroll-view scroll-y class="import-guidance__messages">
        <view v-for="(msg,i) in messages" :key="i" :class="['import-guidance__msg', `import-guidance__msg--${msg.role}`]">
          <view class="import-guidance__bubble">{{ msg.content }}</view>
        </view>
      </scroll-view>
      <view class="import-guidance__input">
        <input v-model="inputText" placeholder="描述你的故事..." @confirm="sendMessage" />
        <view @tap="sendMessage" class="import-guidance__send-btn"><Send :size="24" color="#2563eb" /></view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Send } from '@lucide/vue'
import { post } from '@/utils/request'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'

interface Msg { role: 'user'|'assistant'; content: string }
const messages = ref<Msg[]>([{ role: 'assistant', content: '请告诉我你导入的故事是关于什么的？' }])
const inputText = ref('')
const storyId = ref(0)

async function sendMessage() {
  if (!inputText.value.trim()) return
  messages.value.push({ role: 'user', content: inputText.value })
  inputText.value = ''
  try {
    const res = await post(`/api/stories/${storyId.value}/import-context/message`, { content: inputText.value }) as any
    messages.value.push({ role: 'assistant', content: res.response || '已分析导入内容。' })
  } catch (e) { console.error(e) }
}
</script>

<style lang="scss" scoped>
.import-guidance { height: 100vh; display: flex; flex-direction: column; background: $lv-bg-start; &__chat { flex: 1; } &__messages { padding: $lv-page-padding; } &__msg { margin-bottom: 24rpx; } &__msg--user { text-align: right; } &__msg--user &__bubble { background: $lv-primary; color: #fff; border-radius: 24rpx 24rpx 8rpx 24rpx; display: inline-block; padding: 24rpx; max-width: 80%; } &__msg--assistant &__bubble { background: #f8fbff; border: 1rpx solid $lv-border-light; border-radius: 24rpx 24rpx 24rpx 8rpx; display: inline-block; padding: 24rpx; max-width: 85%; } &__input { display: flex; padding: 16rpx $lv-page-padding; background: #fff; border-top: 1rpx solid $lv-border-light; input { flex: 1; height: 72rpx; background: $lv-primary-lighter; border-radius: 36rpx; padding: 0 32rpx; } &__send-btn { margin-left: 16rpx; padding: 12rpx; @include flex-center; } }
}
</style>
