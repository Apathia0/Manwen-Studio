<script setup lang="ts">
import { onLaunch } from '@dcloudio/uni-app'
import { useAuthStore } from '@/stores/auth'

onLaunch(() => {
  const authStore = useAuthStore()
  authStore.checkSession()
})
</script>

<style>
@import '@/styles/base.scss';
</style>
