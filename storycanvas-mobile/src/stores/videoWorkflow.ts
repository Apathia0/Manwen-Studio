import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { videoApi } from '@/api'
import type {
  ScriptScene, VideoShot, ChapterVideoWorkflow, StoryVideoCharacter,
  ChapterVideoShot, VideoAsset, VideoStylePreset, ChapterVideoWorkflowStatus,
} from '@/api/types'

export type VideoWorkflowPhase = 'idle' | 'screenplay' | 'shots' | 'storyboard' | 'video' | 'concat'

export const useVideoWorkflowStore = defineStore('videoWorkflow', () => {
  const screenplay = ref('')
  const scenes = ref<ScriptScene[]>([])
  const shots = ref<VideoShot[]>([])
  const workflows = ref<ChapterVideoWorkflow[]>([])
  const activeWorkflow = ref<ChapterVideoWorkflow | null>(null)
  const characterList = ref<StoryVideoCharacter[]>([])
  const characterProfiles = ref('')
  const currentWorkflow = ref<ChapterVideoWorkflow | null>(null)
  const currentShots = ref<ChapterVideoShot[]>([])
  const chapterAssets = ref<VideoAsset[]>([])
  const stylePresets = ref<VideoStylePreset[]>([])
  const selectedReferenceIds = ref<number[]>([])
  const selectedStyle = ref('写实电影感')
  const styleReferenceImageUrl = ref<string | null>(null)
  const videoAspectRatio = ref<'16:9' | '9:16'>('16:9')
  const selectedShotIds = ref<number[]>([])
  const skippedShotIds = ref<number[]>([])
  const workflowRunning = ref(false)
  const concatVideoUrl = ref<string | null>(null)
  const loading = ref(false)
  const generating = ref(false)
  const phase = ref<VideoWorkflowPhase>('idle')

  const isBusy = computed(() => generating.value)

  const sceneOptions = computed(() =>
    scenes.value.map(s => ({
      label: `场景${s.scene_number}: ${s.title}`,
      value: s.id,
    }))
  )

  async function fetchScreenplay(chapterId: number) {
    loading.value = true
    try {
      const result = await videoApi.listScreenplayScenes(chapterId)
      screenplay.value = result.screenplay || ''
      scenes.value = result.scenes || []
    } catch {
      screenplay.value = ''
      scenes.value = []
    } finally {
      loading.value = false
    }
  }

  async function generateScreenplay(chapterId: number, payload?: {
    mode?: string
    style?: string
    target_duration_seconds?: number
    scene_count_hint?: number
    regenerate?: boolean
  }) {
    generating.value = true
    phase.value = 'screenplay'
    try {
      const result = await videoApi.generateScreenplay(chapterId, payload || {})
      screenplay.value = result.screenplay || ''
      scenes.value = result.scenes || []
      return result
    } finally {
      generating.value = false
      phase.value = 'idle'
    }
  }

  async function fetchShots(sceneId: number) {
    loading.value = true
    try {
      const result = await videoApi.listSceneShots(sceneId)
      shots.value = result.shots || []
    } catch {
      shots.value = []
    } finally {
      loading.value = false
    }
  }

  async function generateShots(sceneId: number, payload?: {
    style?: string
    shot_count_hint?: number
    regenerate?: boolean
    duration_budget_seconds?: number
  }) {
    generating.value = true
    phase.value = 'shots'
    try {
      const result = await videoApi.generateSceneShots(sceneId, payload)
      shots.value = result.shots || []
      return result
    } finally {
      generating.value = false
      phase.value = 'idle'
    }
  }

  async function fetchWorkflows(chapterId: number) {
    loading.value = true
    try {
      const result = await videoApi.listChapterVideoWorkflows(chapterId)
      workflows.value = result.workflows || []
    } catch {
      workflows.value = []
    } finally {
      loading.value = false
    }
  }

  async function createWorkflow(payload: {
    chapter_id: number
    character_reference_ids?: number[]
    video_style?: string
    style_reference_image_url?: string | null
  }) {
    generating.value = true
    try {
      const result = await videoApi.createChapterVideoWorkflow(payload)
      workflows.value.push(result)
      activeWorkflow.value = result
      return result
    } finally {
      generating.value = false
    }
  }

  async function fetchCharacters(storyId: number) {
    loading.value = true
    try {
      const result = await videoApi.listStoryVideoCharacters(storyId)
      characterList.value = result.characters || []
      characterProfiles.value = result.video_character_profiles || ''
    } catch {
      characterList.value = []
      characterProfiles.value = ''
    } finally {
      loading.value = false
    }
  }

  async function generateCharacters(storyId: number) {
    generating.value = true
    try {
      const result = await videoApi.generateStoryVideoCharacters(storyId)
      characterList.value = result.characters || []
      characterProfiles.value = result.video_character_profiles || ''
      return result
    } finally {
      generating.value = false
    }
  }

  async function loadWorkflowDetail(workflowId: number) {
    loading.value = true
    try {
      const detail = await videoApi.getChapterVideoWorkflow(workflowId)
      currentWorkflow.value = detail
      currentShots.value = detail.shots || []
      return detail
    } catch {
      currentWorkflow.value = null
      currentShots.value = []
      return null
    } finally {
      loading.value = false
    }
  }

  async function loadChapterAssets(chapterId: number) {
    try {
      const res = await videoApi.listVideoAssets(chapterId)
      chapterAssets.value = res.assets || []
    } catch {
      chapterAssets.value = []
    }
  }

  async function loadStylePresets() {
    try {
      const res = await videoApi.listStylePresets()
      stylePresets.value = res.presets || []
    } catch {
      stylePresets.value = []
    }
  }

  async function parseShots(workflowId: number) {
    generating.value = true
    phase.value = 'shots'
    try {
      await videoApi.parseChapterWorkflowShots(workflowId)
      await loadWorkflowDetail(workflowId)
    } finally {
      generating.value = false
      phase.value = 'idle'
    }
  }

  async function generateShotDetails(workflowId: number, shotIds: number[]) {
    generating.value = true
    phase.value = 'shots'
    try {
      await videoApi.generateChapterWorkflowShotDetails(workflowId, { shot_ids: shotIds })
      await loadWorkflowDetail(workflowId)
    } finally {
      generating.value = false
      phase.value = 'idle'
    }
  }

  async function generateStoryboards(workflowId: number, shotIds: number[]) {
    generating.value = true
    phase.value = 'storyboard'
    try {
      await videoApi.generateChapterWorkflowStoryboards(workflowId, { shot_ids: shotIds })
      await loadWorkflowDetail(workflowId)
    } finally {
      generating.value = false
      phase.value = 'idle'
    }
  }

  async function generateVideos(workflowId: number, shotIds: number[]) {
    generating.value = true
    phase.value = 'video'
    try {
      await videoApi.generateChapterWorkflowVideos(workflowId, { shot_ids: shotIds })
      await loadWorkflowDetail(workflowId)
    } finally {
      generating.value = false
      phase.value = 'idle'
    }
  }

  async function runAllStages(workflowId: number) {
    generating.value = true
    try {
      await videoApi.runAllChapterWorkflowStages(workflowId)
      await loadWorkflowDetail(workflowId)
    } finally {
      generating.value = false
      phase.value = 'idle'
    }
  }

  async function concatVideo(workflowId: number) {
    generating.value = true
    phase.value = 'concat'
    try {
      const result = await videoApi.concatChapterVideoWorkflow(workflowId)
      concatVideoUrl.value = result.video_url
      return result
    } finally {
      generating.value = false
      phase.value = 'idle'
    }
  }

  async function resetWorkflow(workflowId: number) {
    generating.value = true
    try {
      await videoApi.resetChapterWorkflow(workflowId)
      await loadWorkflowDetail(workflowId)
      concatVideoUrl.value = null
      selectedShotIds.value = []
      skippedShotIds.value = []
    } finally {
      generating.value = false
    }
  }

  async function clearShotStoryboard(shotId: number) {
    try {
      await videoApi.clearShotStoryboard(shotId)
      if (currentWorkflow.value) await loadWorkflowDetail(currentWorkflow.value.id)
    } catch (e: any) {
      uni.showToast({ title: e.message || '清除失败', icon: 'none' })
      throw e
    }
  }

  async function clearShotVideo(shotId: number) {
    try {
      await videoApi.clearShotVideo(shotId)
      if (currentWorkflow.value) await loadWorkflowDetail(currentWorkflow.value.id)
    } catch (e: any) {
      uni.showToast({ title: e.message || '清除失败', icon: 'none' })
      throw e
    }
  }

  async function saveShotPrompts(shotId: number, prompts: {
    storyboard_prompt?: string | null
    video_prompt?: string | null
    scene_prompt?: string | null
    prop_prompts?: Array<{ name: string; prompt: string }> | null
  }) {
    try {
      await videoApi.saveChapterShotPrompts(shotId, prompts)
      if (currentWorkflow.value) await loadWorkflowDetail(currentWorkflow.value.id)
    } catch (e: any) {
      uni.showToast({ title: e.message || '保存失败', icon: 'none' })
      throw e
    }
  }

  async function uploadStyleReferenceImage(workflowId: number, filePath: string) {
    generating.value = true
    try {
      const result = await videoApi.uploadStyleReferenceImage(workflowId, filePath)
      styleReferenceImageUrl.value = result.style_reference_image_url
      return result
    } finally {
      generating.value = false
    }
  }

  function toggleShotSelection(shotId: number) {
    const idx = selectedShotIds.value.indexOf(shotId)
    if (idx >= 0) selectedShotIds.value.splice(idx, 1)
    else selectedShotIds.value.push(shotId)
  }

  function toggleShotSkip(shotId: number) {
    const idx = skippedShotIds.value.indexOf(shotId)
    if (idx >= 0) skippedShotIds.value.splice(idx, 1)
    else {
      skippedShotIds.value.push(shotId)
      const selIdx = selectedShotIds.value.indexOf(shotId)
      if (selIdx >= 0) selectedShotIds.value.splice(selIdx, 1)
    }
  }

  function selectAllShots() {
    if (currentShots.value.length === 0) return
    selectedShotIds.value = currentShots.value
      .filter(s => !skippedShotIds.value.includes(s.id))
      .map(s => s.id)
  }

  function clearSelection() {
    selectedShotIds.value = []
  }

  return {
    screenplay,
    scenes,
    shots,
    workflows,
    activeWorkflow,
    characterList,
    characterProfiles,
    currentWorkflow, currentShots, chapterAssets, stylePresets,
    selectedReferenceIds, selectedStyle, styleReferenceImageUrl,
    videoAspectRatio, selectedShotIds, skippedShotIds, workflowRunning, concatVideoUrl,
    loading,
    generating,
    phase,
    isBusy,
    sceneOptions,
    fetchScreenplay,
    generateScreenplay,
    fetchShots,
    generateShots,
    fetchWorkflows,
    createWorkflow,
    fetchCharacters,
    generateCharacters,
    loadWorkflowDetail, loadChapterAssets, loadStylePresets,
    parseShots, generateShotDetails, generateStoryboards, generateVideos,
    runAllStages, concatVideo, resetWorkflow,
    clearShotStoryboard, clearShotVideo, saveShotPrompts, uploadStyleReferenceImage,
    toggleShotSelection, toggleShotSkip, selectAllShots, clearSelection,
  }
})
