<template>
  <view :class="avatarClasses">
    <image v-if="src" :src="src" class="lv-avatar__image" mode="aspectFill" />
    <text v-else class="lv-avatar__text">{{ initials }}</text>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface AvatarProps {
  src?: string
  name?: string
  size?: number
}

const props = withDefaults(defineProps<AvatarProps>(), {
  src: '',
  name: '',
  size: 80
})

const avatarClasses = computed(() => [
  'lv-avatar',
  {
    'lv-avatar--has-image': props.src
  }
])

const initials = computed(() => {
  if (!props.name) return ''
  return props.name.charAt(0).toUpperCase()
})
</script>

<style lang="scss" scoped>
.lv-avatar {
  width: 80rpx;
  height: 80rpx;
  border-radius: 50%;
  background: $lv-primary-light;
  @include flex-center;
  overflow: hidden;

  &--has-image {
    background: transparent;
  }

  &__image {
    width: 100%;
    height: 100%;
  }

  &__text {
    font-size: $lv-font-xl;
    font-weight: 600;
    color: $lv-primary;
  }
}
</style>
