<script setup lang="ts">
import { computed } from 'vue'
import {
  ArrowLeft, BookOpenText, ChevronLeft, Clapperboard, Ellipsis,
  FileUp, History, Image, Images, Info, Library, List, ListTree,
  Menu, MessageSquare, Play, RefreshCw, Settings, Upload, Video,
  PenLine, Sparkles, BookOpen, Palette, Megaphone,
  Star, Gem, Gift, CheckCircle, XCircle,
  Loader, Pencil, Bot, BarChart3, ImagePlus, Volume2,
  ChevronDown, ChevronRight, ChevronUp, Plus, X, Save,
  FileText, Tag, User, Users, ClipboardList, Trash2, Eye, Wand2, CircleHelp
} from '@lucide/vue'

const iconMap: Record<string, any> = {
  ArrowLeft, BookOpenText, ChevronLeft, Clapperboard, Ellipsis,
  FileUp, History, Image, Images, Info, Library, List, ListTree,
  Menu, MessageSquare, Play, RefreshCw, Settings, Upload, Video,
  PenLine, Sparkles, BookOpen, Palette, Megaphone,
  Star, Gem, Gift, CheckCircle, XCircle,
  Loader, Pencil, Bot, BarChart3, ImagePlus, Volume2,
  ChevronDown, ChevronRight, ChevronUp, Plus, X, Save,
  FileText, Tag, User, Users, ClipboardList, Trash2, Eye, Wand2
}

const props = withDefaults(defineProps<{
  name: string
  size?: number
  color?: string
}>(), {
  size: 24
})

const icon = computed(() => iconMap[props.name] || CircleHelp)
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
