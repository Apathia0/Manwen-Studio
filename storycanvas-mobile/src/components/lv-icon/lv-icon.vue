<script setup lang="ts">
import {
  PenLine, Sparkles, BookOpen, Palette, Megaphone,
  Star, Gem, Gift, CheckCircle, XCircle,
  Loader, Pencil, Bot, BarChart3, ImagePlus, Volume2,
  ChevronDown, ChevronRight, ChevronUp, Plus, X, Save,
  FileText, Tag, Users, Trash2, Eye, Wand2
} from '@lucide/vue'

const iconMap: Record<string, any> = {
  PenLine, Sparkles, BookOpen, Palette, Megaphone,
  Star, Gem, Gift, CheckCircle, XCircle,
  Loader, Pencil, Bot, BarChart3, ImagePlus, Volume2,
  ChevronDown, ChevronRight, ChevronUp, Plus, X, Save,
  FileText, Tag, Users, Trash2, Eye, Wand2
}

const props = withDefaults(defineProps<{
  name: string
  size?: number
  color?: string
}>(), {
  size: 24
})

const icon = iconMap[props.name]
</script>

<template>
  <component
    :is="icon"
    v-if="icon"
    :size="size"
    :color="color"
    :stroke-width="1.8"
  />
</template>
