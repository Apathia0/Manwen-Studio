import { ref } from 'vue'

export function useTheme() {
  const isDark = ref(false)

  function toggleTheme() {
    isDark.value = !isDark.value
  }

  return {
    isDark,
    toggleTheme
  }
}
