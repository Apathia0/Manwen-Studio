import { memo, useCallback, useEffect, useRef, useState } from 'react';
import { BookOpen, ChevronUp, ChevronDown, Download, ImageIcon, Loader2, Sparkles, Pencil, RefreshCw, Check, X, ImagePlus, Trash2, Square, Upload, MousePointer, Palette, Settings2, UserRound, MapPinned, Package } from 'lucide-react';
import { useMemo as useMemoValue } from 'react';
import { createPortal } from 'react-dom';
import { ImageRedrawModal } from './shared/ImageRedrawModal';
import ImageZoomView from './shared/ImageZoomView';
import StyleSelectorModal from './StyleSelectorModal';
import MangaAssetManagementModal from './MangaAssetManagementModal';
import MangaStoryboardImportModal from './MangaStoryboardImportModal';
import {
  generateMangaStream,
  generateScenes, scenesFromSelection,
  getChapter,
  getScenes,
  updateScenes,
  regenerateImage,
  resetMangaImages,
  getCharacters,
  generateStoryCharactersFromFramework,
  generateStoryCharRefStream,
  saveCharacters,
  resetChapterCharacters,
  getChapterRefImages,
  addChapterRefImage,
  deleteChapterRefImage,
  refImageUrl,
  redrawChapterRefImage,
  redrawStoryRefImage,
  getColorMode,
  setColorMode,
  getImageCount,
  setImageCount,
  ALLOWED_IMAGE_COUNTS,
  mangaImageUrl,
  getMangaGenerationStatus,
  cancelMangaGeneration,
  uploadCharacterRefImage,
  deleteCharacterRefImage,
  saveMangaAssetBindings,
  listStylePresets,
  uploadMangaStyleReference,
  type ImageRedrawMode,
  type Chapter,
  type MangaProgress,
  type ColorMode,
  type RefSource,
  type RefImage,
  type VideoStylePreset,
  type MangaAsset,
  type MangaAssetBinding,
} from '../api';
import { genStore } from '../genStore';
import { toast } from '../lib/toast';
import { normalizeErrorMessage } from '../lib/errors';

interface Props {
  chapter: Chapter | null;
  entitlements?: Record<string, any> | null;
  onChapterRefresh?: (chapterId: number) => void;
  selectedText?: string;
  chapterContext?: { characters?: any[] };
  isWorkspacePreviewMode?: boolean;
  onWorkspacePreviewModeChange?: (expanded: boolean) => void;
  onClearSelection?: () => void;
  onOpenSourceViewer?: () => void;
}

interface ImageItem {
  image_number: number;
  image_path: string;
  prompt: string;
}

interface CharacterCardField {
  label: string;
  value: string;
}

interface CharacterAppearanceCard {
  name: string;
  fields: CharacterCardField[];
  raw: string;
}

type ImageEditTarget =
  | {
    kind: 'manga';
    title: string;
    imageSrc: string;
    prompt: string;
    imageNumber: number;
    isNewImage?: boolean;
  }
  | {
    kind: 'ref';
    title: string;
    imageSrc: string;
    prompt: string;
    filename: string;
    owner: 'story' | 'chapter';
  };

type RefPreviewTarget = {
  image: RefImage;
  title: string;
  prompt: string;
  redrawTitle?: string;
};

type ImageLoadStatus = 'loading' | 'ready' | 'error';

function mergeImages(...groups: ImageItem[][]): ImageItem[] {
  const merged = new Map<number, ImageItem>();
  groups.flat().forEach((img) => {
    merged.set(img.image_number, img);
  });
  return Array.from(merged.values()).sort((a, b) => a.image_number - b.image_number);
}

function parseCharacterAppearanceCards(raw: string): CharacterAppearanceCard[] {
  const text = raw.trim();
  if (!text) return [];

  const blocks = text
    .replace(/\r\n/g, '\n')
    .split(/(?=^角色名[:：])/m)
    .map((block) => block.trim())
    .filter(Boolean);

  return blocks.map((block, index) => {
    const fields: CharacterCardField[] = [];
    let fallbackName = `角色 ${index + 1}`;

    for (const line of block.split('\n').map((item) => item.trim()).filter(Boolean)) {
      const match = line.match(/^([^:：]{1,20})[:：]\s*(.+)$/);
      if (match) {
        const [, label, value] = match;
        const cleanLabel = label.trim();
        const cleanValue = value.trim();
        if (!cleanValue) continue;
        if (cleanLabel === '角色名') fallbackName = cleanValue;
        fields.push({ label: cleanLabel, value: cleanValue });
      } else if (fields.length > 0) {
        const last = fields[fields.length - 1];
        last.value = `${last.value}\n${line}`;
      } else {
        fields.push({ label: '描述', value: line });
      }
    }

    return { name: fallbackName, fields, raw: block };
  });
}

function renameCharacterCard(rawText: string, oldName: string, newName: string): string {
  const lines = rawText.replace(/\r\n/g, '\n').split('\n');
  const result: string[] = [];
  let inTargetBlock = false;
  let foundRoleName = false;

  for (const line of lines) {
    const roleNameMatch = line.match(/^角色名[:：]\s*(.+)$/);
    if (roleNameMatch) {
      if (inTargetBlock && roleNameMatch[1].trim() === oldName) {
        result.push(`角色名：${newName}`);
        foundRoleName = true;
        continue;
      }
      inTargetBlock = true;
    } else if (roleNameMatch === null && line.trim() === '' && inTargetBlock) {
      inTargetBlock = false;
    }
    result.push(line);
  }

  if (!foundRoleName) {
    const blocks = rawText.replace(/\r\n/g, '\n').split(/(?=^角色名[:：])/m);
    const updatedBlocks = blocks.map((block, idx) => {
      if (idx === 0 && block.trim()) {
        return `角色名：${newName}\n${block}`;
      }
      return block;
    });
    return updatedBlocks.join('\n').trim();
  }

  return result.join('\n').trim();
}

function closeWorkspacePreview(
  setLightboxIdx: (value: number) => void,
  onWorkspacePreviewModeChange?: (expanded: boolean) => void,
) {
  setLightboxIdx(-1);
  onWorkspacePreviewModeChange?.(false);
}

function closeRefWorkspacePreview(
  setRefPreviewImage: (value: RefPreviewTarget | null) => void,
  onWorkspacePreviewModeChange?: (expanded: boolean) => void,
) {
  setRefPreviewImage(null);
  onWorkspacePreviewModeChange?.(false);
}

type Phase = 'idle' | 'generating-scenes' | 'editing-scenes' | 'generating-images';
type MangaAssetExtractionType = 'character' | 'scene' | 'prop';

const MANGA_ASSET_EXTRACTION_OPTIONS: Array<{ key: MangaAssetExtractionType; label: string }> = [
  { key: 'character', label: '角色' },
  { key: 'scene', label: '场景' },
  { key: 'prop', label: '道具' },
];
const DEFAULT_IMAGE_COUNT = 10;

const ASPECT_RATIO_OPTIONS = [
  { label: '9:16', size: '1024x1792' },
  { label: '3:4', size: '1024x1365' },
  { label: '2:3', size: '1024x1536' },
  { label: '1:1', size: '1024x1024' },
  { label: '3:2', size: '1536x1024' },
  { label: '4:3', size: '1365x1024' },
  { label: '16:9', size: '1792x1024' },
] as const;

export default memo(function MangaPanel({
  chapter,
  onChapterRefresh,
  selectedText,
  chapterContext,
  isWorkspacePreviewMode = false,
  onWorkspacePreviewModeChange,
  onClearSelection,
  onOpenSourceViewer,
}: Props) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [progress, setProgress] = useState({ current: 0, total: DEFAULT_IMAGE_COUNT });
  const [statusMsg, setStatusMsg] = useState('');
  const [images, setImages] = useState<ImageItem[]>([]);
  const [lightboxIdx, setLightboxIdx] = useState<number>(-1);
  const [errorMsg, setErrorMsg] = useState('');
  const [scenes, setScenes] = useState<string[]>([]);
  const [sanitizedSceneIdxs, setSanitizedSceneIdxs] = useState<number[]>([]);
  const [editingIdx, setEditingIdx] = useState<number>(-1);
  const [failedSceneIdx, setFailedSceneIdx] = useState<number>(-1);
  const [editText, setEditText] = useState('');
  const [savingScenes, setSavingScenes] = useState(false);
  const [regenIdx, setRegenIdx] = useState<number>(-1);
  const [panelGenLoading, setPanelGenLoading] = useState<number[]>([]);
  const [charText, setCharText] = useState('');
  const [charSource, setCharSource] = useState<'chapter' | 'story' | 'none'>('none');
  const [charEditing, setCharEditing] = useState(false);
  const [charDraft, setCharDraft] = useState('');
  const [charSaving, setCharSaving] = useState(false);
  const [charGenerating, setCharGenerating] = useState(false);
  const [charRefGeneratingKey, setCharRefGeneratingKey] = useState<string>('');
  const [charExpanded, setCharExpanded] = useState(false);
  const [expandedAppearanceCards, setExpandedAppearanceCards] = useState<Record<string, boolean>>({});
  const [refImages, setRefImages] = useState<RefImage[]>([]);
  const [refSource, setRefSource] = useState<RefSource>('none');
  const [refMax, setRefMax] = useState(4);
  const [refUploading, setRefUploading] = useState(false);
  const [assetModalOpen, setAssetModalOpen] = useState(false);
  const [storyboardImportOpen, setStoryboardImportOpen] = useState(false);
  // 仅保留历史引用图的兼容状态，旧垫图界面不再对用户开放。
  const [refModalOpen, setRefModalOpen] = useState(false);
  const [legacyReferenceUiEnabled] = useState(false);
  const mangaAssets: MangaAsset[] = [];
  const [assetBindings, setAssetBindings] = useState<MangaAssetBinding[]>([]);
  const assetsLoading = false;
  const [colorMode, setColorModeState] = useState<ColorMode>('bw');
  const [imageCount, setImageCountState] = useState(DEFAULT_IMAGE_COUNT);
const [aspectRatio, setAspectRatio] = useState<string>('9:16');
  const [stylePresets, setStylePresets] = useState<VideoStylePreset[]>([]);
  const [selectedStylePresetName, setSelectedStylePresetName] = useState<string>('');
  const [styleReferenceImageUrl, setStyleReferenceImageUrl] = useState<string | null>(null);
  const [styleSelectorOpen, setStyleSelectorOpen] = useState(false);
  const styleSelectionTouchedRef = useRef(false);
  const [showColorMenu, setShowColorMenu] = useState(false);
  const [assetConfigOpen, setAssetConfigOpen] = useState(false);
  const [autoAssetExtractionEnabled, setAutoAssetExtractionEnabled] = useState(true);
  const [autoAssetExtractionTypes, setAutoAssetExtractionTypes] = useState<MangaAssetExtractionType[]>(['character', 'scene', 'prop']);

  const colorMenuRef = useRef<HTMLDivElement>(null);
  const assetConfigRef = useRef<HTMLDivElement>(null);
  const refFileRef = useRef<HTMLInputElement>(null);
  const lightboxRef = useRef<HTMLDivElement>(null);
  const sceneDetailRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const chapterLoadRequestRef = useRef(0);
  const sceneAbortRef = useRef<AbortController | null>(null);
  const charRefStreamRef = useRef<AbortController | null>(null);
  const [selectionLoading, setSelectionLoading] = useState(false);
  const [scenesFromSelectionFlag, setScenesFromSelectionFlag] = useState(false);
  const [ignorePersistedImages, setIgnorePersistedImages] = useState(false);
  const [imageLoadStates, setImageLoadStates] = useState<Record<string, ImageLoadStatus>>({});
  const [imageLoadSrcs, setImageLoadSrcs] = useState<Record<string, string>>({});
  const [refLoadStates, setRefLoadStates] = useState<Record<string, ImageLoadStatus>>({});
  const [refLoadSrcs, setRefLoadSrcs] = useState<Record<string, string>>({});
  const [refPreviewImage, setRefPreviewImage] = useState<RefPreviewTarget | null>(null);
  const [imageEditTarget, setImageEditTarget] = useState<ImageEditTarget | null>(null);
  const [refImageVersion, setRefImageVersion] = useState(0);
  const mangaAbortRef = useRef<Map<number, AbortController>>(new Map());
  const imagePreloadAttemptsRef = useRef<Record<string, number>>({});
  const refPreloadAttemptsRef = useRef<Record<string, number>>({});
  const backendTaskPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const checkBackendMangaStatusRef = useRef<((chapterId: number) => Promise<void>) | null>(null);
  const [charRefModalOpen, setCharRefModalOpen] = useState(false);
  const [charRefModalCharName, setCharRefModalCharName] = useState('');
  const [charRefModalImage, setCharRefModalImage] = useState<RefImage | null>(null);
  const [charRefModalUploading, setCharRefModalUploading] = useState(false);
  const charRefFileRef = useRef<HTMLInputElement>(null);
  const parsedCharacterCards = useMemoValue(() => parseCharacterAppearanceCards(charText), [charText]);
  const maxImagesPerChapter = 20;
  const selectableImageCounts = ALLOWED_IMAGE_COUNTS;
  const refImageByLabel = useMemoValue(() => {
    const map = new Map<string, RefImage>();
    refImages.forEach((img) => {
      if (img.label) map.set(img.label, img);
    });
    return map;
  }, [refImages]);
  const refImageSrc = useCallback(
    (imagePath: string) => {
      const base = refImageUrl(imagePath);
      return refImageVersion > 0 ? `${base}?t=${refImageVersion}` : base;
    },
    [refImageVersion],
  );
  const isAppearanceCardExpanded = useCallback(
    (key: string) => expandedAppearanceCards[key] ?? true,
    [expandedAppearanceCards],
  );
  const [editingCardIdx, setEditingCardIdx] = useState<number | null>(null);
  const [editingCardName, setEditingCardName] = useState('');

  // Subscribe to module-level generation store so we re-render when any chapter's gen state changes
  const [, setStoreTick] = useState(0);
  useEffect(() => genStore.subscribe(() => setStoreTick((t) => t + 1)), []);
  const liveGen = chapter ? genStore.get(chapter.id) : undefined;
  const isLiveGenerating = !!(liveGen && liveGen.active);

  // Reset state when chapter changes
  useEffect(() => {
    // Abort any in-flight scene generation when switching chapters
    sceneAbortRef.current?.abort();
    sceneAbortRef.current = null;
    charRefStreamRef.current?.abort();
    charRefStreamRef.current = null;
    chapterLoadRequestRef.current++;
    setImages([]);
    // Don't downgrade phase if there's an ongoing generation for this new chapter;
    // the derived `generating` flag below will reflect it via genStore.
    setPhase('idle');
    setProgress({ current: 0, total: DEFAULT_IMAGE_COUNT });
    setStatusMsg('');
    setErrorMsg('');
    setLightboxIdx(-1);
    onWorkspacePreviewModeChange?.(false);
    setRefPreviewImage(null);
    setImageEditTarget(null);
    setScenes([]);
    setSanitizedSceneIdxs([]);
    setScenesFromSelectionFlag(false);
    setEditingIdx(-1);
    setFailedSceneIdx(-1);
    setRegenIdx(-1);
    setCharText('');
    setCharSource('none');
    setCharEditing(false);
    setCharExpanded(false);
    setExpandedAppearanceCards({});
    setRefImages([]);
    setRefSource('none');
    setAssetModalOpen(false);
    setStoryboardImportOpen(false);
    setAutoAssetExtractionEnabled(true);
    setAutoAssetExtractionTypes(['character', 'scene', 'prop']);
    setColorModeState('bw');
    setImageCountState(DEFAULT_IMAGE_COUNT);
    let persistedStyle: { presetName?: string; referenceUrl?: string | null } | null = null;
    if (chapter?.id) {
      try {
        const rawStyle = localStorage.getItem(`storycanvas.mangaStyle.${chapter.id}`);
        persistedStyle = rawStyle ? JSON.parse(rawStyle) : null;
      } catch {
        persistedStyle = null;
      }
    }
    setSelectedStylePresetName(typeof persistedStyle?.presetName === 'string' ? persistedStyle.presetName : '');
    setStyleReferenceImageUrl(typeof persistedStyle?.referenceUrl === 'string' ? persistedStyle.referenceUrl : null);
    styleSelectionTouchedRef.current = persistedStyle !== null;
    setShowColorMenu(false);
    setIgnorePersistedImages(false);
    setImageLoadStates({});
    setImageLoadSrcs({});
    setRefLoadStates({});
    setRefLoadSrcs({});
    imagePreloadAttemptsRef.current = {};
    refPreloadAttemptsRef.current = {};
  }, [chapter?.id, onWorkspacePreviewModeChange]);

  const syncChapterImagesFromServer = useCallback(async (chapterId: number) => {
    const latest = await getChapter(chapterId);
    const latestImages: ImageItem[] = latest.images.map((img) => ({
      image_number: img.image_number,
      image_path: img.image_path,
      prompt: img.prompt || '',
    }));
    setImages(latestImages);
    setIgnorePersistedImages(false);
    return latestImages;
  }, []);

  // ── 后台任务轮询 ──

  const startBackendTaskPolling = useCallback((chapterId: number) => {
    // 清除已有的轮询定时器
    if (backendTaskPollRef.current) {
      clearInterval(backendTaskPollRef.current);
      backendTaskPollRef.current = null;
    }
    backendTaskPollRef.current = setInterval(async () => {
      try {
        const status = await getMangaGenerationStatus(chapterId);
        if (status.status === 'succeeded') {
          // 后台任务完成，停止轮询并刷新数据
          if (backendTaskPollRef.current) {
            clearInterval(backendTaskPollRef.current);
            backendTaskPollRef.current = null;
          }
          genStore.finish(chapterId);
          await syncChapterImagesFromServer(chapterId);
          onChapterRefresh?.(chapterId);
          setTimeout(() => genStore.clear(chapterId), 800);
        } else if (status.status === 'failed') {
          // 后台任务失败
          if (backendTaskPollRef.current) {
            clearInterval(backendTaskPollRef.current);
            backendTaskPollRef.current = null;
          }
          const baseMessage = normalizeErrorMessage(status.error_message, '后台漫画生成失败，请重试');
          const message = status.suggestion ? `${baseMessage}。${status.suggestion}` : baseMessage;
          setErrorMsg(message);
          genStore.finish(chapterId, message);
        } else if (status.status === 'cancelled') {
          if (backendTaskPollRef.current) {
            clearInterval(backendTaskPollRef.current);
            backendTaskPollRef.current = null;
          }
          setErrorMsg('');
          setStatusMsg('漫画生成任务已取消');
          genStore.finish(chapterId);
          setTimeout(() => genStore.clear(chapterId), 800);
        } else if (status.status === 'running' || status.status === 'pending' || status.status === 'retrying' || status.status === 'cancel_requested') {
          // 后台任务仍在进行，更新进度
          const message = status.message || (
            status.status === 'cancel_requested'
              ? '正在取消漫画生成任务...'
              : status.status === 'retrying'
                ? `上游较慢，正在自动重试 ${status.retry_count ?? 0}/${status.max_retries ?? 0}`
              : `后台正在生成漫画 (${status.progress}/${status.total})`
          );
          setProgress({ current: status.progress, total: status.total });
          setStatusMsg(message);
          genStore.patch(chapterId, { current: status.progress, total: status.total, statusMsg: message });
        }
      } catch (err) {
        console.error('后端任务轮询错误:', err);
        setErrorMsg(normalizeErrorMessage(err, '无法获取漫画任务状态，请检查网络后重试'));
      }
    }, 3000);
  }, [syncChapterImagesFromServer, onChapterRefresh]);

  // ── 检查后台漫画生成状态 ──

  const checkBackendMangaStatus = useCallback(async (chapterId: number) => {
    try {
      const status = await getMangaGenerationStatus(chapterId);
      if (status.status === 'running' || status.status === 'pending' || status.status === 'retrying' || status.status === 'cancel_requested') {
        // 后台有正在运行的任务，恢复进度显示并开始轮询
        const message = status.message || (
          status.status === 'cancel_requested'
            ? '正在取消漫画生成任务...'
            : status.status === 'retrying'
              ? `上游较慢，正在自动重试 ${status.retry_count ?? 0}/${status.max_retries ?? 0}`
            : `后台正在生成漫画 (${status.progress}/${status.total})`
        );
        setProgress({ current: status.progress, total: status.total });
        setStatusMsg(message);
        genStore.start(chapterId, status.total, []);
        genStore.patch(chapterId, { current: status.progress, total: status.total, statusMsg: message });
        startBackendTaskPolling(chapterId);
      } else if (status.status === 'succeeded') {
        // 后台任务已经完成，同步最新图片
        await syncChapterImagesFromServer(chapterId);
        onChapterRefresh?.(chapterId);
      } else if (status.status === 'failed') {
        // 后台任务失败，显示错误信息
        const baseMessage = normalizeErrorMessage(status.error_message, '后台漫画生成失败，请重试');
        setErrorMsg(status.suggestion ? `${baseMessage}。${status.suggestion}` : baseMessage);
      } else if (status.status === 'cancelled') {
        setErrorMsg('');
        setStatusMsg('漫画生成任务已取消');
        genStore.clear(chapterId);
      }
    } catch (err) {
      console.error('检查后端漫画状态失败:', err);
      setErrorMsg(normalizeErrorMessage(err, '无法检查漫画任务状态，请刷新页面重试'));
    }
  }, [syncChapterImagesFromServer, onChapterRefresh, startBackendTaskPolling]);
  useEffect(() => {
    checkBackendMangaStatusRef.current = checkBackendMangaStatus;
  }, [checkBackendMangaStatus]);

  // Load existing scenes and characters if available
  useEffect(() => {
    const requestId = ++chapterLoadRequestRef.current;
    if (chapter) {
      getChapterRefImages(chapter.id).then((r) => {
        if (chapterLoadRequestRef.current !== requestId) return;
        setRefImages(r.images);
        setRefSource(r.source ?? (r.images.length ? 'chapter' : 'none'));
        setRefMax(r.max);
      }).catch(() => {});
      getColorMode(chapter.id).then((m) => {
        if (chapterLoadRequestRef.current === requestId) setColorModeState(m);
      }).catch(() => {});
      getImageCount(chapter.id).then((c) => {
        if (chapterLoadRequestRef.current === requestId) setImageCountState(c);
      }).catch(() => {});
      listStylePresets().then((result) => {
        if (chapterLoadRequestRef.current === requestId) {
          setStylePresets(result.presets);
          const availablePresets = result.presets.filter((preset) => Boolean(preset.image_url));
          let persistedPresetName = '';
          try {
            const rawStyle = localStorage.getItem(`storycanvas.mangaStyle.${chapter.id}`);
            const parsedStyle = rawStyle ? JSON.parse(rawStyle) as { presetName?: unknown } : null;
            persistedPresetName = typeof parsedStyle?.presetName === 'string' ? parsedStyle.presetName : '';
          } catch {
            persistedPresetName = '';
          }
          const persistedPreset = persistedPresetName
            ? result.presets.find((preset) => preset.name === persistedPresetName)
            : null;
          if (persistedPresetName && !persistedPreset?.image_url) {
            setSelectedStylePresetName('');
            localStorage.removeItem(`storycanvas.mangaStyle.${chapter.id}`);
            styleSelectionTouchedRef.current = false;
          }
          // 默认只选中已配置参考图的预设
          if (availablePresets.length > 0 && !styleSelectionTouchedRef.current) {
            const animePreset = availablePresets.find(p => p.name === '日式动漫风')
              || availablePresets.find(p => p.category === 'anime')
              || availablePresets[0];
            setSelectedStylePresetName(animePreset.name);
          }
        }
      }).catch(() => {});
      getScenes(chapter.id).then((result) => {
        if (chapterLoadRequestRef.current !== requestId) return;
        if (result.scenes.length > 0) {
          setScenes(result.scenes);
          setSanitizedSceneIdxs(result.sanitized_indices ?? []);
          setPhase('editing-scenes');
        }
      }).catch(() => {});
      getCharacters(chapter.id).then((r) => {
        if (chapterLoadRequestRef.current !== requestId) return;
        setCharText(r.characters || '');
        setCharSource(r.source);
      }).catch(() => {});
      // 检查是否有正在运行的后台漫画生成任务
      checkBackendMangaStatusRef.current?.(chapter.id);
    }
  }, [chapter?.id]);

  // 组件卸载时清理后台任务轮询
  useEffect(() => {
    return () => {
      if (backendTaskPollRef.current) {
        clearInterval(backendTaskPollRef.current);
        backendTaskPollRef.current = null;
      }
    };
  }, []);

  // Load existing images from chapter
  const existingImages: ImageItem[] =
    chapter?.images.map((img) => ({
      image_number: img.image_number,
      image_path: img.image_path,
      prompt: img.prompt || '',
    })) ?? [];
  const persistedImages = ignorePersistedImages ? [] : existingImages;

  // While generation is running for this chapter, prefer live images from the store
  const displayImages = isLiveGenerating
    ? mergeImages(persistedImages, liveGen!.images)
    : images.length > 0
      ? mergeImages(persistedImages, images)
      : persistedImages;
  const imageByNumber = new Map(displayImages.map((img) => [img.image_number, img]));
  const gallerySlots = scenes.length > 0
    ? scenes.map((scene, idx) => ({
      image_number: idx + 1,
      scene,
      img: imageByNumber.get(idx + 1),
    }))
    : displayImages.map((img) => ({
      image_number: img.image_number,
      scene: img.prompt || '',
      img,
    }));
  const lightboxImg = lightboxIdx >= 0 ? displayImages[lightboxIdx] : null;
  const showWorkspacePreview = Boolean(lightboxImg && isWorkspacePreviewMode);
  const imageReadyMap = useMemoValue(
    () =>
      new Map(
        displayImages.map((img) => [
          img.image_path,
          imageLoadStates[img.image_path] === 'ready',
        ]),
      ),
    [displayImages, imageLoadStates],
  );

  useEffect(() => {
    const pendingTimers: number[] = [];
    displayImages.forEach((img) => {
      const key = img.image_path;
      if (!key || imageLoadStates[key] === 'ready' || imageLoadStates[key] === 'loading') return;
      if (imageLoadStates[key] === 'error' && (imagePreloadAttemptsRef.current[key] ?? 0) >= 8) return;

      setImageLoadStates((prev) => (prev[key] ? prev : { ...prev, [key]: 'loading' }));

      const attempt = (tryIndex: number) => {
        const preload = new window.Image();
        preload.onload = () => {
          const resolvedSrc = mangaImageUrl(img.image_path);
          imagePreloadAttemptsRef.current[key] = tryIndex;
          setImageLoadSrcs((prev) => (prev[key] === resolvedSrc ? prev : { ...prev, [key]: resolvedSrc }));
          setImageLoadStates((prev) => ({ ...prev, [key]: 'ready' }));
        };
        preload.onerror = () => {
          if (tryIndex < 5) {
            const timer = window.setTimeout(() => attempt(tryIndex + 1), 450);
            pendingTimers.push(timer);
            return;
          }
          imagePreloadAttemptsRef.current[key] = tryIndex;
          setImageLoadSrcs((prev) => {
            if (!(key in prev)) return prev;
            const next = { ...prev };
            delete next[key];
            return next;
          });
          setImageLoadStates((prev) => ({ ...prev, [key]: 'error' }));
        };
        preload.src = mangaImageUrl(img.image_path);
      };

      const nextAttempt = (imagePreloadAttemptsRef.current[key] ?? 0) + 1;
      imagePreloadAttemptsRef.current[key] = nextAttempt;
      attempt(nextAttempt);
    });

    return () => pendingTimers.forEach((timer) => window.clearTimeout(timer));
  }, [displayImages, imageLoadStates]);

  useEffect(() => {
    const pendingTimers: number[] = [];
    refImages.forEach((img) => {
      const key = img.image_path;
      if (!key || refLoadStates[key] === 'ready' || refLoadStates[key] === 'loading') return;
      if (refLoadStates[key] === 'error' && (refPreloadAttemptsRef.current[key] ?? 0) >= 6) return;

      setRefLoadStates((prev) => (prev[key] ? prev : { ...prev, [key]: 'loading' }));

      const attempt = (tryIndex: number) => {
        const preload = new window.Image();
        preload.onload = () => {
          const resolvedSrc = refImageSrc(img.image_path);
          refPreloadAttemptsRef.current[key] = tryIndex;
          setRefLoadSrcs((prev) => (prev[key] === resolvedSrc ? prev : { ...prev, [key]: resolvedSrc }));
          setRefLoadStates((prev) => ({ ...prev, [key]: 'ready' }));
        };
        preload.onerror = () => {
          if (tryIndex < 4) {
            const timer = window.setTimeout(() => attempt(tryIndex + 1), 350);
            pendingTimers.push(timer);
            return;
          }
          refPreloadAttemptsRef.current[key] = tryIndex;
          setRefLoadStates((prev) => ({ ...prev, [key]: 'error' }));
        };
        preload.src = refImageSrc(img.image_path);
      };

      const nextAttempt = (refPreloadAttemptsRef.current[key] ?? 0) + 1;
      refPreloadAttemptsRef.current[key] = nextAttempt;
      attempt(nextAttempt);
    });

    return () => pendingTimers.forEach((timer) => window.clearTimeout(timer));
  }, [refImages, refLoadStates, refImageSrc]);

  // 鈹€鈹€ Scene generation 鈹€鈹€
  const handleGenerateScenes = async () => {
    if (!chapter) return;
    if ((!chapter.messages || chapter.messages.length === 0) && !chapter.novel_content) {
      toast.error('请先在左侧进行对话或手动编写正文');
      return;
    }
    setScenesFromSelectionFlag(false);
    setPhase('generating-scenes');
    setErrorMsg('');
    const controller = new AbortController();
    sceneAbortRef.current = controller;
    const requestId = chapterLoadRequestRef.current;
    const hadScenes = scenes.length > 0;
    const hadImages = existingImages.length > 0 || images.length > 0;
    const previousScenes = scenes;
    const previousSanitizedIndices = sanitizedSceneIdxs;
    // 重新生成期间先移除旧分镜，避免新旧内容叠加造成“没有刷新”的错觉。
    setScenes([]);
    setSanitizedSceneIdxs([]);
    setFailedSceneIdx(-1);
    try {
      const result = await generateScenes(chapter.id, controller.signal);
      if (chapterLoadRequestRef.current !== requestId) return;
      if (hadImages) {
        // 分镜重生成后，旧图片已不再对应新脚本，必须从数据库和本地状态中一并清除。
        await resetMangaImages(chapter.id);
        setImages([]);
        setIgnorePersistedImages(true);
        genStore.clear(chapter.id);
        onChapterRefresh?.(chapter.id);
      }
      setScenes(result.scenes);
      setSanitizedSceneIdxs(result.sanitized_indices ?? []);
      setFailedSceneIdx(-1);
      setPhase('editing-scenes');
    } catch (err: any) {
      if (chapterLoadRequestRef.current !== requestId) return;
      if (err.name === 'AbortError') {
        setScenes(previousScenes);
        setSanitizedSceneIdxs(previousSanitizedIndices);
        setPhase(hadScenes ? 'editing-scenes' : 'idle');
      } else {
        setScenes(previousScenes);
        setSanitizedSceneIdxs(previousSanitizedIndices);
        setErrorMsg(err.message);
        setPhase(hadScenes ? 'editing-scenes' : 'idle');
      }
    } finally {
      if (sceneAbortRef.current === controller) {
        sceneAbortRef.current = null;
      }
    }
  };

  const handleAbortScenes = () => {
    sceneAbortRef.current?.abort();
    sceneAbortRef.current = null;
  };

  // 鈹€鈹€ Selection-based scene generation 鈹€鈹€
  const handleGenerateFromSelection = async () => {
    if (!chapter || !selectedText) return;
    setSelectionLoading(true);
    setErrorMsg('');
    setScenesFromSelectionFlag(true);
    try {
      const result = await scenesFromSelection(chapter.id, {
        selected_text: selectedText,
        character_profiles: chapterContext?.characters,
      });
      setScenes(result.scenes);
      setSanitizedSceneIdxs(result.sanitized_indices ?? []);
      setFailedSceneIdx(-1);
      setPhase('editing-scenes');
      onClearSelection?.();
    } catch (err: any) {
      setErrorMsg(err.message);
      setScenesFromSelectionFlag(false);
    } finally {
      setSelectionLoading(false);
    }
  };

  // 鈹€鈹€ Scene editing 鈹€鈹€
  const handleSceneEdit = (idx: number) => {
    setEditingIdx(idx);
    setFailedSceneIdx(-1);
    setEditText(scenes[idx]);
  };

  const handleSceneSave = (idx: number) => {
    const updated = [...scenes];
    updated[idx] = editText;
    setScenes(updated);
    setSanitizedSceneIdxs((prev) => prev.filter((item) => item !== idx));
    setEditingIdx(-1);
    setFailedSceneIdx(-1);
  };

  const handleOptimizeFailedScene = (idx: number, optimizedPrompt?: string) => {
    if (idx < 0 || idx >= scenes.length) return;
    if (optimizedPrompt) {
      const next = [...scenes];
      next[idx] = optimizedPrompt;
      setScenes(next);
      setSanitizedSceneIdxs((prev) => Array.from(new Set([...prev, idx])).sort((a, b) => a - b));
      setEditText(optimizedPrompt);
    } else {
      setEditText(scenes[idx]);
    }
    setFailedSceneIdx(idx);
    setEditingIdx(idx);
    setPhase('editing-scenes');
  };

  const handleSaveAllScenes = async () => {
    if (!chapter) return;
    setSavingScenes(true);
    try {
      await updateScenes(chapter.id, scenes);
      setFailedSceneIdx(-1);
      toast.success('保存成功');
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setSavingScenes(false);
    }
  };

  // 鈹€鈹€ Single image regeneration 鈹€鈹€
  const handleRegenImage = async (imageNumber: number) => {
    if (!chapter) return;
    const prompt = scenes[imageNumber - 1];
    if (!prompt) return;
    setRegenIdx(imageNumber);
    setErrorMsg('');
    try {
      // Save scenes first
      await updateScenes(chapter.id, scenes);
      const result = await regenerateImage(chapter.id, imageNumber, prompt, { size: ASPECT_RATIO_OPTIONS.find(o => o.label === aspectRatio)?.size, stylePresetName: selectedStylePresetName || undefined, styleRefUrl: styleReferenceImageUrl || undefined });
      // Update in images list
      const newItem: ImageItem = {
        image_number: result.image_number,
        image_path: result.image_path,
        prompt: result.prompt,
      };
      setImages((prev) => {
        const updated = prev.length > 0 ? [...prev] : [...existingImages];
        const idx = updated.findIndex((i) => i.image_number === imageNumber);
        if (idx >= 0) updated[idx] = newItem;
        else updated.push(newItem);
        return updated.sort((a, b) => a.image_number - b.image_number);
      });
    } catch (err: any) {
      setErrorMsg(`第 ${imageNumber} 张重新生成失败：${err.message}`);
    } finally {
      setRegenIdx(-1);
    }
  };

  const handleGeneratePanel = async (imageNumber: number) => {
    setPanelGenLoading((prev) => [...prev, imageNumber]);
    try {
      await handleRegenImage(imageNumber);
    } finally {
      setPanelGenLoading((prev) => prev.filter((n) => n !== imageNumber));
    }
  };

  const openCharacterRefModal = (charName: string) => {
    const refImage = refImageByLabel.get(charName) || null;
    setCharRefModalCharName(charName);
    setCharRefModalImage(refImage);
    setCharRefModalOpen(true);
  };

  const handleUploadCharacterRef = async (file: File) => {
    if (!chapter || !charRefModalCharName) return;

    setCharRefModalUploading(true);
    try {
      const reader = new FileReader();
      const base64 = await new Promise<string>((resolve, reject) => {
        reader.onload = () => resolve(reader.result as string);
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });

      const hasExisting = charRefModalImage !== null;
      let replaceExisting = false;

      if (hasExisting) {
        const choice = window.confirm(
          '该角色已有参考图，是否替换？\n\n点击"确定"替换，点击"取消"保留两者。'
        );
        replaceExisting = choice;
      }

      const result = await uploadCharacterRefImage(
        chapter.story_id,
        charRefModalCharName,
        base64,
        replaceExisting
      );

      setRefImages(result.images);
      setRefSource('story');
      setRefMax(result.max);
      setCharRefModalOpen(false);
    } catch (err) {
      console.error('上传角色参考图失败:', err);
      alert('上传失败，请重试');
    } finally {
      setCharRefModalUploading(false);
    }
  };

  const handleDeleteCharacterRef = async () => {
    if (!chapter || !charRefModalImage) return;

    const confirmed = window.confirm('确定要删除该参考图吗？');
    if (!confirmed) return;

    try {
      const result = await deleteCharacterRefImage(
        chapter.story_id,
        charRefModalImage.filename
      );

      setRefImages(result.images);
      setRefSource('story');
      setCharRefModalOpen(false);
    } catch (err) {
      console.error('删除角色参考图失败:', err);
      alert('删除失败，请重试');
    }
  };

  const handleGenerateCharacterRefImage = async (characterName: string, overwrite = false) => {
    if (!chapter) return;
    if (charRefStreamRef.current) {
      charRefStreamRef.current.abort();
    }
    setCharRefGeneratingKey(characterName);
    setErrorMsg('');
    charRefStreamRef.current = generateStoryCharRefStream(
      chapter.story_id,
      { character_name: characterName, overwrite },
      (event) => {
        if (event.type === 'snapshot' || event.type === 'image') {
          setRefImages(event.data.images);
          setRefSource('story');
          setRefMax(event.data.max);
        } else if (event.type === 'done') {
          setRefImages(event.data.images);
          setRefSource('story');
          setRefMax(event.data.max);
          setCharRefGeneratingKey('');
          charRefStreamRef.current = null;
        } else if (event.type === 'error') {
          setErrorMsg(`角色参考图生成失败：${event.data.error}`);
          setCharRefGeneratingKey('');
          charRefStreamRef.current = null;
        }
      },
    );
  };

  const openMangaRedraw = useCallback((imageNumber: number) => {
    const img = displayImages.find((item) => item.image_number === imageNumber);
    const scene = scenes[imageNumber - 1] || '';
    setImageEditTarget({
      kind: 'manga',
      title: img ? `第 ${imageNumber} 格漫画重绘` : `第 ${imageNumber} 格漫画生成`,
      imageSrc: img ? (imageLoadSrcs[img.image_path] || mangaImageUrl(img.image_path)) : '',
      prompt: scene || img?.prompt || '',
      imageNumber,
      isNewImage: !img,
    });
  }, [displayImages, imageLoadSrcs, scenes]);

  const openRefRedraw = useCallback((img: RefImage, fallbackTitle?: string) => {
    if (!chapter) return;
    const owner = refSource === 'story' ? 'story' : 'chapter';
    setImageEditTarget({
      kind: 'ref',
      title: fallbackTitle || `${img.label || '角色参考图'}重绘`,
      imageSrc: refLoadSrcs[img.image_path] || refImageSrc(img.image_path),
      prompt: img.label
        ? `保持${img.label}的人物五官、发型、服装与气质一致，按我的要求重新绘制。`
        : '保持主体核心特征一致，按我的要求重新绘制。',
      filename: img.filename,
      owner,
    });
  }, [chapter, refImageSrc, refLoadSrcs, refSource]);

  const buildRefPreviewPrompt = useCallback((img: RefImage) => {
    const matchedCard = img.label ? parsedCharacterCards.find((card) => card.name === img.label) : null;
    if (matchedCard?.raw) return matchedCard.raw;
    if (img.label) return `角色名：${img.label}\n请保持该角色的五官、发型、服装与气质一致。`;
    return '请保持主体核心特征一致，必要时再进入重绘。';
  }, [parsedCharacterCards]);

  const handleApplyImageRedraw = useCallback(async (payload: { prompt: string; mode: ImageRedrawMode; mask?: string }) => {
    if (!chapter || !imageEditTarget) return;
    if (imageEditTarget.kind === 'manga') {
      setRegenIdx(imageEditTarget.imageNumber);
      setErrorMsg('');
      try {
        await updateScenes(chapter.id, scenes);
        const result = await regenerateImage(chapter.id, imageEditTarget.imageNumber, payload.prompt, { ...payload, size: ASPECT_RATIO_OPTIONS.find(o => o.label === aspectRatio)?.size, stylePresetName: selectedStylePresetName || undefined, styleRefUrl: styleReferenceImageUrl || undefined });
        const newItem: ImageItem = {
          image_number: result.image_number,
          image_path: result.image_path,
          prompt: result.prompt,
        };
        setImages((prev) => {
          const updated = prev.length > 0 ? [...prev] : [...existingImages];
          const idx = updated.findIndex((i) => i.image_number === imageEditTarget.imageNumber);
          if (idx >= 0) updated[idx] = newItem;
          else updated.push(newItem);
          return updated.sort((a, b) => a.image_number - b.image_number);
        });
        setScenes((prev) => {
          const next = [...prev];
          if (imageEditTarget.imageNumber - 1 < next.length) next[imageEditTarget.imageNumber - 1] = result.prompt;
          return next;
        });
        setImageEditTarget(null);
      } catch (err: any) {
        setErrorMsg(`第 ${imageEditTarget.imageNumber} 格重绘失败：${err.message}`);
      } finally {
        setRegenIdx(-1);
      }
      return;
    }

    setRefUploading(true);
    setErrorMsg('');
    try {
      const result = imageEditTarget.owner === 'story'
        ? await redrawStoryRefImage(chapter.story_id, imageEditTarget.filename, payload)
        : await redrawChapterRefImage(chapter.id, imageEditTarget.filename, payload);
      setRefImages(result.images);
      setRefSource((result.source ?? imageEditTarget.owner) as RefSource);
      setRefMax(result.max);
      setRefImageVersion(Date.now());
      setImageEditTarget(null);
    } catch (err: any) {
      setErrorMsg(`参考图重绘失败：${err.message}`);
    } finally {
      setRefUploading(false);
    }
  }, [chapter, imageEditTarget, scenes, existingImages, aspectRatio]);

  // 鈹€鈹€ Close color menu on outside click 鈹€鈹€
  useEffect(() => {
    if (!showColorMenu) return;
    const handler = (e: MouseEvent) => {
      if (colorMenuRef.current && !colorMenuRef.current.contains(e.target as Node)) {
        setShowColorMenu(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showColorMenu]);

  useEffect(() => {
    if (!assetConfigOpen) return;
    const handler = (event: MouseEvent) => {
      if (assetConfigRef.current && !assetConfigRef.current.contains(event.target as Node)) {
        setAssetConfigOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [assetConfigOpen]);

  // 鈹€鈹€ Color mode selection 鈹€鈹€
  const handleSelectColorMode = async (mode: ColorMode) => {
    if (!chapter) return;
    setShowColorMenu(false);
    await setColorMode(chapter.id, mode);
    setColorModeState(mode);
  };

  useEffect(() => {
    if (imageCount > maxImagesPerChapter) {
      setImageCountState(maxImagesPerChapter);
    }
  }, [imageCount, maxImagesPerChapter]);

  const reconcileGenerationAfterStreamIssue = useCallback(
    async (chapterId: number, targetTotal: number, fallbackImages: ImageItem[], fallbackError: string) => {
      try {
        const latestImages = await syncChapterImagesFromServer(chapterId);
        if (latestImages.length >= targetTotal) {
          setErrorMsg('');
          setFailedSceneIdx(-1);
          genStore.finish(chapterId);
          onChapterRefresh?.(chapterId);
          window.setTimeout(() => genStore.clear(chapterId), 800);
          return;
        }

        const mergedImages = mergeImages(fallbackImages, latestImages);
        setImages(mergedImages);
        genStore.finish(chapterId, fallbackError);
        onChapterRefresh?.(chapterId);
      } catch {
        setImages(fallbackImages);
        if (fallbackImages.length > 0) setIgnorePersistedImages(false);
        genStore.finish(chapterId, fallbackError);
        onChapterRefresh?.(chapterId);
      }
    },
    [onChapterRefresh, syncChapterImagesFromServer],
  );

  // ── Image generation ──

  const startMangaGeneration = async (mode: 'continue' | 'restart' = 'continue') => {
    if (!chapter) return;
    if (genStore.get(chapter.id)?.active) return;
    if (scenes.length !== imageCount) {
      setErrorMsg('当前分镜数与生成张数不一致，请先重新生成分镜。');
      return;
    }

    try {
      await updateScenes(chapter.id, scenes);
    } catch (err: any) {
      setErrorMsg(`保存分镜失败: ${err.message}`);
      return;
    }

    setErrorMsg('');
    setFailedSceneIdx(-1);
    const targetId = chapter.id;
    const targetTotal = imageCount;
    let seedImages = ignorePersistedImages ? [...images] : mergeImages(existingImages, images);

    if (mode === 'restart' && seedImages.length > 0) {
      try {
        await resetMangaImages(targetId);
      } catch (err: any) {
        setErrorMsg(`重置已生成图片失败: ${err.message}`);
        return;
      }
      setIgnorePersistedImages(true);
      seedImages = [];
      setImages([]);
      genStore.clear(targetId);
      onChapterRefresh?.(targetId);
    } else {
      setIgnorePersistedImages(false);
      setImages(seedImages);
    }

    genStore.start(targetId, targetTotal, seedImages);

    const currentSize = ASPECT_RATIO_OPTIONS.find(o => o.label === aspectRatio)?.size;
    const currentStylePresetName = selectedStylePresetName || undefined;
    const currentStyleRefUrl = styleReferenceImageUrl || undefined;
    const currentAssetExtraction = {
      enabled: autoAssetExtractionEnabled && autoAssetExtractionTypes.length > 0,
      types: autoAssetExtractionTypes,
    };
    const controller = generateMangaStream(targetId, (event: MangaProgress) => {
      switch (event.type) {
        case 'status':
          if (event.data.message) {
            setStatusMsg(event.data.message);
            genStore.patch(targetId, { statusMsg: event.data.message });
          }
          break;
        case 'progress': {
          const progressMessage = event.data.message || (
            event.data.retry_count > 0
              ? `上游较慢，正在自动重试 ${event.data.retry_count}/${event.data.max_retries ?? 0}`
              : `正在生成第 ${event.data.current}/${event.data.total} 张漫画`
          );
          setStatusMsg(progressMessage);
          genStore.patch(targetId, {
            current: event.data.current,
            total: event.data.total,
            statusMsg: progressMessage,
          });
          break;
        }
        case 'image':
          genStore.pushImage(targetId, {
            image_number: event.data.image_number,
            image_path: event.data.image_path,
            prompt: event.data.prompt,
          });
          if (event.data.image_number >= targetTotal) {
            mangaAbortRef.current.delete(targetId);
            genStore.finish(targetId);
            onChapterRefresh?.(targetId);
            setTimeout(() => genStore.clear(targetId), 800);
          }
          break;
        case 'done':
          mangaAbortRef.current.delete(targetId);
          setImages(genStore.get(targetId)?.images ?? seedImages);
          setIgnorePersistedImages(false);
          setErrorMsg('');
          setFailedSceneIdx(-1);
          genStore.finish(targetId);
          onChapterRefresh?.(targetId);
          void syncChapterImagesFromServer(targetId);
          setTimeout(() => genStore.clear(targetId), 800);
          break;
        case 'error': {
          mangaAbortRef.current.delete(targetId);
          const generatedImages = genStore.get(targetId)?.images ?? seedImages;
          setImages(generatedImages);
          if (generatedImages.length > 0) setIgnorePersistedImages(false);
          if (typeof event.data.image_number === 'number') {
            const failedIdx = event.data.image_number - 1;
            setFailedSceneIdx(failedIdx);
            if (event.data.optimized_prompt && scenes[failedIdx] !== event.data.optimized_prompt) {
              setScenes((prev) => {
                const next = [...prev];
                if (failedIdx >= 0 && failedIdx < next.length) next[failedIdx] = event.data.optimized_prompt;
                return next;
              });
              setSanitizedSceneIdxs((prev) => Array.from(new Set([...prev, failedIdx])).sort((a, b) => a - b));
            }
            handleOptimizeFailedScene(failedIdx, event.data.optimized_prompt);
          }
          const errorParts = [event.data.error || '未知错误'];
          if (event.data.suggestion) errorParts.push(event.data.suggestion);
          const nextError = errorParts.join(' ');
          setErrorMsg(nextError);
          void reconcileGenerationAfterStreamIssue(targetId, targetTotal, generatedImages, nextError);
          break;
        }
      }
    }, currentSize, currentStylePresetName, currentStyleRefUrl, currentAssetExtraction);
    mangaAbortRef.current.set(targetId, controller);
  };

  const handleGenerateImages = () => startMangaGeneration('continue');

  const handleRestartManga = () => startMangaGeneration('restart');

  const handleAbortManga = async () => {
    if (!chapter) return;
    const targetId = chapter.id;
    const state = genStore.get(targetId);

    // 1) 通知后端取消后台任务（先触发，不等完成即可中止 SSE）
    cancelMangaGeneration(targetId).catch(() => {
      // 即使后端取消 API 调用失败（如任务已结束），仍继续本地清理
    });

    // 2) 中止本地 SSE 流连接
    mangaAbortRef.current.get(targetId)?.abort();
    mangaAbortRef.current.delete(targetId);

    // 3) 清理本地状态
    if (state?.images.length) {
      setImages(mergeImages(existingImages, state.images));
      setIgnorePersistedImages(false);
    }
    setErrorMsg('');
    genStore.finish(targetId, '已中止生成');
    window.setTimeout(() => onChapterRefresh?.(targetId), 700);
  };

  // 鈹€鈹€ Lightbox keyboard/scroll navigation 鈹€鈹€
  const handleLightboxNav = useCallback((dir: 'prev' | 'next') => {
    setLightboxIdx((cur) => {
      if (dir === 'prev' && cur > 0) return cur - 1;
      if (dir === 'next' && cur < displayImages.length - 1) return cur + 1;
      return cur;
    });
  }, [displayImages.length]);

  useEffect(() => {
    if (lightboxIdx < 0) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') { e.preventDefault(); handleLightboxNav('prev'); }
      if (e.key === 'ArrowDown' || e.key === 'ArrowRight') { e.preventDefault(); handleLightboxNav('next'); }
      if (e.key === 'Escape') closeWorkspacePreview(setLightboxIdx, onWorkspacePreviewModeChange);
    };
    window.addEventListener('keydown', handler);
    return () => {
      window.removeEventListener('keydown', handler);
    };
  }, [lightboxIdx, handleLightboxNav, onWorkspacePreviewModeChange]);

  useEffect(() => {
    if (!refPreviewImage) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeRefWorkspacePreview(setRefPreviewImage, onWorkspacePreviewModeChange);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [refPreviewImage, onWorkspacePreviewModeChange]);

  // 错误信息改为 toast 弹窗显示（替代常驻 banner）
  const prevErrorMsgRef = useRef('');
  useEffect(() => {
    const msg = liveGen?.errorMsg || errorMsg;
    if (msg && msg !== prevErrorMsgRef.current) {
      toast.error(msg);
      prevErrorMsgRef.current = msg;
    }
    if (!msg) {
      prevErrorMsgRef.current = '';
    }
  }, [errorMsg, liveGen?.errorMsg]);

  const scrollToSceneDetail = useCallback((sceneIdx: number) => {
    const target = sceneDetailRefs.current[sceneIdx];
    if (!target) return;
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  const generating = isLiveGenerating || phase === 'generating-images';

  // Tick every 1s while generating so the stall indicator re-renders.
  const [nowTick, setNowTick] = useState(0);
  useEffect(() => {
    if (!generating) return;
    const updateNow = () => setNowTick(Date.now());
    updateNow();
    const id = window.setInterval(updateNow, 1000);
    return () => window.clearInterval(id);
  }, [generating]);

  const stallSeconds = isLiveGenerating && liveGen
    ? Math.max(0, Math.floor((nowTick - liveGen.lastEventAt) / 1000))
    : 0;
  const isStalled = isLiveGenerating && stallSeconds >= 30;

  const liveProgress = isLiveGenerating
    ? { current: liveGen!.current, total: liveGen!.total }
    : progress;
  const liveStatusMsg = isLiveGenerating ? liveGen!.statusMsg : statusMsg;
  const hasImages = displayImages.length > 0;
  const canChangeImageCount = !generating && (phase === 'idle' || phase === 'editing-scenes');
  const activeImageCount = liveProgress.total || imageCount;
  const completedImageCount = displayImages.length;
  const hasPartialImages = completedImageCount > 0 && completedImageCount < imageCount;
  const canContinueGeneration = !generating && phase === 'editing-scenes' && scenes.length > 0;
  const sceneCountMatchesImageCount = scenes.length === imageCount;
  const canRestartGeneration = canContinueGeneration && hasImages;
  const activeSceneIdx = scenes.length > 0
    ? Math.min(
      Math.max((liveProgress.current || Math.min(completedImageCount + 1, scenes.length)) - 1, 0),
      scenes.length - 1,
    )
    : -1;

  return (
    <>
    <div className="flex flex-col h-full bg-[#fcfcfa]">
      {/* Header */}
      <div className="space-y-3 px-4 py-3 md:px-5 border-b border-[#d9dfd7] bg-white">
        {/* 第一行：标题 + 垫图 + 张数 + 下载 */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-slate-900">
              第 {chapter?.chapter_number ?? '-'} 话 · 漫画生成
            </h2>
            <p className="mt-0.5 text-xs text-slate-500">分镜、画面与角色参考在同一画布内完成</p>
          </div>
          <div className="flex items-center gap-1.5 md:gap-2 flex-wrap justify-end">
            {onOpenSourceViewer ? (
              <button
                type="button"
                onClick={onOpenSourceViewer}
                className="flex items-center gap-1.5 rounded-md border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 transition-colors hover:bg-blue-100"
              >
                <BookOpen size={13} />
                查看正文与分镜脚本
              </button>
            ) : null}
            {/* Reference images */}
            <div className="flex items-center gap-1">
              <input
                ref={refFileRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file || !chapter) return;
                  setRefUploading(true);
                  try {
                    const reader = new FileReader();
                    const b64 = await new Promise<string>((resolve) => {
                      reader.onload = () => resolve((reader.result as string).split(',')[1]);
                      reader.readAsDataURL(file);
                    });
                    const r = await addChapterRefImage(chapter.id, b64);
                    setRefImages(r.images);
                    setRefSource(r.source ?? 'chapter');
                    setRefMax(r.max);
                  } catch (err: any) {
                    setErrorMsg(`上传垫图失败: ${err.message}`);
                  } finally {
                    setRefUploading(false);
                    e.target.value = '';
                  }
                }}
              />
              <button
                onClick={() => setAssetModalOpen(true)}
                disabled={!chapter}
                className={`flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-md transition-colors
                  ${refImages.length > 0
                    ? 'bg-emerald-900/50 hover:bg-emerald-800 text-emerald-300 border border-emerald-700'
                    : 'bg-[#f3f5f0] hover:bg-[#e8ece6] text-slate-700'
                  } disabled:opacity-40`}
                title="管理角色、场景、道具和风格资产"
              >
                <ImagePlus size={13} />
                资产管理
              </button>
            </div>
            {/* Image count selector */}
            {!generating && (phase === 'idle' || phase === 'editing-scenes') && (
              <select
                value={imageCount}
                onChange={async (e) => {
                  const count = Number(e.target.value);
                  const previous = imageCount;
                  setImageCountState(count);
                  if (chapter) {
                    try {
                      const savedCount = await setImageCount(chapter.id, count);
                      setImageCountState(savedCount);
                    } catch (err: any) {
                      setImageCountState(previous);
                      setErrorMsg(`保存生成张数失败: ${err.message}`);
                    }
                  }
                }}
                disabled={!canChangeImageCount}
                className="px-2 py-1.5 text-xs font-medium rounded-md bg-[#f3f5f0] text-slate-700 border border-[#d9dfd7] outline-none focus:border-[#1f5f58] transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                title={canChangeImageCount ? '生成张数，下次生成分镜时生效' : '生成中暂不能修改生成张数'}
              >
                {selectableImageCounts.map((n) => (
                  <option key={n} value={n}>{n}张</option>
                ))}
              </select>
            )}
            {hasImages && (
              <button
                onClick={() => {
                  displayImages.forEach((img) => {
                    const a = document.createElement('a');
                    a.href = mangaImageUrl(img.image_path);
                    a.download = `panel_${img.image_number.toString().padStart(2, '0')}.png`;
                    a.click();
                  });
                }}
                className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-md
                           bg-[#f3f5f0] hover:bg-[#e8ece6] text-slate-700 transition-colors"
              >
                <Download size={13} />
                下载
              </button>
            )}
            {!generating && (phase === 'idle' || phase === 'editing-scenes') && (
              <button
                type="button"
                onClick={() => setStoryboardImportOpen(true)}
                disabled={!chapter}
                className="flex items-center gap-1.5 rounded-md border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 transition-colors hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Upload size={13} />
                导入分镜
              </button>
            )}
            {!generating && (phase === 'idle' || phase === 'editing-scenes') && (
              <button
                onClick={handleGenerateScenes}
                disabled={!chapter || (!chapter?.messages?.length && !chapter?.novel_content)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md
                           bg-[#1f5f58] hover:bg-[#184c46] text-white disabled:opacity-40
                           disabled:cursor-not-allowed transition-colors"
              >
                <RefreshCw size={13} />
                {scenes.length > 0 ? '重新生成分镜' : '生成分镜'}
              </button>
            )}
          </div>
        </div>
        {/* 第二行：风格/比例/彩色/生成按钮 */}
        {canContinueGeneration && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[#e5edf8] bg-[#f8fbff] px-3 py-2.5">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="mr-1 text-xs font-semibold text-slate-600">生成配置</span>
            {/* Color mode selector */}
            <div className="relative" ref={colorMenuRef}>
              <button
                onClick={() => setShowColorMenu((v) => !v)}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors
                  ${colorMode === 'color'
                    ? 'bg-pink-900/50 hover:bg-pink-800 text-pink-300 border border-pink-700'
                    : 'bg-[#f3f5f0] hover:bg-[#e8ece6] text-slate-700'}`}
              >
                {colorMode === 'color' ? (
                  <span className="w-3 h-3 rounded-full bg-gradient-to-br from-pink-400 via-blue-400 to-green-400 shrink-0" />
                ) : (
                  <span className="w-3 h-3 rounded-full bg-gradient-to-br from-white to-gray-600 shrink-0" />
                )}
                {colorMode === 'color' ? '彩色' : '黑白'}
                <ChevronDown size={11} className={`transition-transform ${showColorMenu ? 'rotate-180' : ''}`} />
              </button>
              {showColorMenu && (
                <div className="absolute right-0 top-full mt-1 w-40 rounded-lg border border-[#d9dfd7] bg-white shadow-xl z-50 overflow-hidden">
                  <button
                    onClick={() => handleSelectColorMode('bw')}
                    className={`w-full flex items-center gap-2 px-3 py-2.5 text-xs transition-colors hover:bg-[#f3f5f0]
                      ${colorMode === 'bw' ? 'text-amber-400 font-semibold' : 'text-slate-700'}`}
                  >
                    <span className="w-4 h-4 rounded border-2 border-gray-500 bg-gradient-to-br from-white to-gray-900 shrink-0" />
                    黑白漫画
                    {colorMode === 'bw' && <Check size={12} className="ml-auto text-amber-400" />}
                  </button>
                  <button
                    onClick={() => handleSelectColorMode('color')}
                    className={`w-full flex items-center gap-2 px-3 py-2.5 text-xs transition-colors hover:bg-[#f3f5f0]
                      ${colorMode === 'color' ? 'text-amber-400 font-semibold' : 'text-slate-700'}`}
                  >
                    <span className="w-4 h-4 rounded border-2 border-gray-500 bg-gradient-to-br from-pink-400 via-blue-400 to-green-400 shrink-0" />
                    彩色漫画
                    {colorMode === 'color' && <Check size={12} className="ml-auto text-amber-400" />}
                  </button>
                </div>
              )}
            </div>
            {/* 比例选择器 */}
            <select
              value={aspectRatio}
              onChange={(e) => setAspectRatio(e.target.value)}
              className="px-2 py-1.5 text-xs font-medium rounded-md border border-[#d9dfd7] bg-white text-slate-700 outline-none cursor-pointer focus:border-[#1f5f58]"
            >
              {ASPECT_RATIO_OPTIONS.map((opt) => (
                <option key={opt.label} value={opt.label}>
                  {opt.label}
                </option>
              ))}
            </select>
            {/* 风格预设选择器 */}
            <button
              onClick={() => setStyleSelectorOpen(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-[#d9dfd7] bg-white hover:bg-slate-50 transition-colors"
            >
              <Palette size={14} className={selectedStylePresetName || styleReferenceImageUrl ? 'text-blue-500' : 'text-slate-400'} />
              <span className={selectedStylePresetName || styleReferenceImageUrl ? 'text-slate-900' : 'text-slate-500'}>
                {selectedStylePresetName || (styleReferenceImageUrl ? '自定义风格' : '选择风格')}
              </span>
              {(selectedStylePresetName || styleReferenceImageUrl) && (
                <span className="text-[10px] text-blue-500">(已选)</span>
              )}
            </button>
            {/* 自动资产提取配置 */}
            <div className="relative" ref={assetConfigRef}>
              <button
                type="button"
                onClick={() => setAssetConfigOpen((value) => !value)}
                className={`flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors ${autoAssetExtractionEnabled ? 'border-blue-200 bg-blue-50 text-blue-700' : 'border-[#d9dfd7] bg-white text-slate-500'}`}
                aria-expanded={assetConfigOpen}
              >
                <Settings2 size={13} />
                <span>
                  {autoAssetExtractionEnabled
                    ? `自动资产 · ${autoAssetExtractionTypes.length === 3 ? '全部' : autoAssetExtractionTypes.map((key) => MANGA_ASSET_EXTRACTION_OPTIONS.find((item) => item.key === key)?.label).filter(Boolean).join('、') || '未选择'}`
                    : '不提取资产'}
                </span>
                <ChevronDown size={11} className={`transition-transform ${assetConfigOpen ? 'rotate-180' : ''}`} />
              </button>
              {assetConfigOpen && (
                <div className="absolute right-0 top-full z-50 mt-1 w-56 rounded-lg border border-slate-200 bg-white p-3 shadow-xl">
                  <label className="flex cursor-pointer items-center gap-2 border-b border-slate-100 pb-2 text-xs font-semibold text-slate-700">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-blue-600"
                      checked={autoAssetExtractionEnabled}
                      onChange={(event) => {
                        const enabled = event.target.checked;
                        setAutoAssetExtractionEnabled(enabled);
                        if (enabled && autoAssetExtractionTypes.length === 0) setAutoAssetExtractionTypes(['character', 'scene', 'prop']);
                      }}
                    />
                    自动提取资产图
                  </label>
                  <div className="mt-2 space-y-1">
                    {MANGA_ASSET_EXTRACTION_OPTIONS.map((option) => {
                      const checked = autoAssetExtractionTypes.includes(option.key);
                      const Icon = option.key === 'character' ? UserRound : option.key === 'scene' ? MapPinned : Package;
                      return (
                        <label key={option.key} className={`flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1.5 text-xs ${autoAssetExtractionEnabled ? 'text-slate-700 hover:bg-slate-50' : 'text-slate-400'}`}>
                          <input
                            type="checkbox"
                            className="h-4 w-4 accent-blue-600"
                            checked={checked}
                            disabled={!autoAssetExtractionEnabled}
                            onChange={() => {
                              const next = checked
                                ? autoAssetExtractionTypes.filter((key) => key !== option.key)
                                : [...autoAssetExtractionTypes, option.key];
                              setAutoAssetExtractionTypes(next);
                              setAutoAssetExtractionEnabled(next.length > 0);
                            }}
                          />
                          <Icon size={13} />
                          {option.label}
                        </label>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
            {/* Generate button */}
            <button
              onClick={handleGenerateImages}
              disabled={!sceneCountMatchesImageCount}
              className="flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium rounded-md
                         bg-amber-500 hover:bg-amber-400 text-slate-900 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              title={sceneCountMatchesImageCount ? undefined : '当前分镜数与生成张数不一致，请先重新生成分镜'}
            >
              <Sparkles size={13} />
              {hasPartialImages ? '继续生成漫画' : '生成漫画'}
            </button>
            {canRestartGeneration && (
              <button
                onClick={handleRestartManga}
                disabled={!sceneCountMatchesImageCount}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md
                           bg-[#f3f5f0] hover:bg-[#e8ece6] text-slate-800 border border-[#d9dfd7] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                title="清空已生成图片，从第 1 张重新开始"
              >
                <RefreshCw size={13} />
                重新生成全部
              </button>
            )}
            </div>
          </div>
        )}
          {phase === 'generating-scenes' && (
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1.5 text-xs text-slate-600">
                <Loader2 size={13} className="animate-spin" />
                AI 生成分镜中...
              </span>
              <button
                onClick={handleAbortScenes}
                className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-md
                           bg-red-900/50 hover:bg-red-800 text-red-300 border border-red-700 transition-colors"
                title="停止生成分镜"
              >
                <Square size={11} />
                停止
              </button>
            </div>
          )}
        </div>

      <div className={`${showWorkspacePreview ? 'hidden' : 'flex flex-col flex-1 min-h-0'}`}>
      {/* Progress bar */}
      {generating && (
        <div className="px-5 py-4 border-b border-[#d9dfd7] bg-white">
          <div className="flex items-center justify-between text-xs mb-3 gap-3">
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-slate-700 font-medium truncate">{liveStatusMsg}</span>
              {isStalled && (
                <span
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/40 text-amber-300 text-[10px] font-medium whitespace-nowrap animate-pulse"
                  title="图片服务响应较慢，正在继续等待"
                >
                  <Loader2 size={10} className="animate-spin" />
                  等待中 {stallSeconds}s
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={handleAbortManga}
                className="flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded-md
                           bg-red-900/50 hover:bg-red-800 text-red-300 border border-red-700 transition-colors"
                title="停止生成漫画"
              >
                <Square size={10} />
                停止
              </button>
              <span className="text-amber-400 font-mono font-bold">
                {Math.round((liveProgress.current / liveProgress.total) * 100)}%
              </span>
            </div>
          </div>
          <div className="w-full h-3 bg-[#f3f5f0] rounded-full overflow-hidden relative">
            <div
              className="h-full rounded-full transition-all duration-700 ease-out relative overflow-hidden"
              style={{
                width: `${Math.max((liveProgress.current / liveProgress.total) * 100, 2)}%`,
                background: 'linear-gradient(90deg, #f59e0b, #fbbf24, #f59e0b)',
                boxShadow: '0 0 12px rgba(245, 158, 11, 0.5)',
              }}
            >
              <div
                className="absolute inset-0 animate-[barbershop_1s_linear_infinite]"
                style={{
                  backgroundImage:
                    'repeating-linear-gradient(115deg, transparent, transparent 8px, rgba(255,255,255,0.15) 8px, rgba(255,255,255,0.15) 16px)',
                }}
              />
            </div>
          </div>
          <div className="flex justify-between mt-2 text-[10px] text-slate-500">
            {Array.from({ length: liveProgress.total }, (_, i) => (
              <span key={i} className={i < liveProgress.current ? 'text-amber-500' : ''}>
                {i + 1}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Main content area */}
      <div className="flex-1 overflow-y-auto px-3 md:px-5 py-4">
        {/* Selection-based scene generation banner */}
        {selectedText && phase !== 'generating-scenes' && (
          <div className="mb-4 p-3 rounded-lg border border-amber-700/50 bg-amber-900/20">
            <div className="flex items-start gap-3">
              <div className="flex-1 min-w-0">
                <p className="text-xs text-amber-300/80 mb-1 leading-relaxed line-clamp-2">
                  &ldquo;{selectedText.slice(0, 80)}{selectedText.length > 80 ? '...' : ''}&rdquo;
                </p>
              </div>
              <button
                onClick={handleGenerateFromSelection}
                disabled={selectionLoading}
                className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md
                           bg-amber-600 hover:bg-amber-500 text-white disabled:opacity-40
                           disabled:cursor-not-allowed transition-colors whitespace-nowrap"
              >
                {selectionLoading ? (
                  <><Loader2 size={13} className="animate-spin" /> 生成中...</>
                ) : (
                  <>从选中文字生成分镜</>
                )}
              </button>
            </div>
          </div>
        )}

        {/* Character profiles card */}
        {(phase === 'idle' || phase === 'editing-scenes') && (
          <div className="hidden mb-4 rounded-lg border border-[#d9dfd7] bg-white overflow-hidden">
            <button
              onClick={() => setCharExpanded((v) => !v)}
              className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold text-slate-600 uppercase tracking-wide hover:bg-[#f3f5f0]/40 transition-colors"
            >
              <span className="flex items-center gap-1.5">
                 角色外貌卡
                {charText && charSource === 'story' && (
                  <span className="text-[10px] font-normal normal-case px-1.5 py-0.5 rounded bg-blue-900/50 text-blue-400 border border-blue-800/50">继承全局</span>
                )}
                {charText && charSource === 'chapter' && (
                  <span className="text-[10px] font-normal normal-case px-1.5 py-0.5 rounded bg-emerald-900/50 text-emerald-400 border border-emerald-800/50">本话自定义</span>
                )}
                {!charText && '（未设定）'}
              </span>
              {charExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
            {charExpanded && (
              <div className="px-3 pb-3">
                {charEditing ? (
                  <>
                    <textarea
                      value={charDraft}
                      onChange={(e) => setCharDraft(e.target.value)}
                      className="w-full bg-[#f3f5f0] text-xs text-slate-800 rounded p-2 resize-none outline-none border border-[#d9dfd7] focus:border-[#1f5f58] leading-relaxed"
                      rows={12}
                      placeholder={`角色名：示例角色\n性别：女\n发色与发型：银灰色长发\n可补充服装、体型、气质与标志性特征`}
                      autoFocus
                    />
                    <div className="flex justify-end gap-2 mt-2">
                      <button
                        onClick={() => setCharEditing(false)}
                        className="px-2 py-1 text-xs rounded text-slate-500 hover:text-slate-700 hover:bg-[#e8ece6] transition-colors"
                      >取消</button>
                      <button
                        disabled={charSaving}
                        onClick={async () => {
                          if (!chapter) return;
                          setCharSaving(true);
                          try {
                            await saveCharacters(chapter.id, charDraft);
                            setCharText(charDraft);
                            setCharSource('chapter');
                            setCharEditing(false);
                            toast.success('保存成功');
                          } catch (err: any) {
                            setErrorMsg(err.message);
                          } finally {
                            setCharSaving(false);
                          }
                        }}
                        className="px-3 py-1 text-xs rounded bg-[#1f5f58] hover:bg-[#184c46] text-white disabled:opacity-40 transition-colors"
                      >{charSaving ? '保存中...' : '保存（本话覆盖）'}</button>
                    </div>
                  </>
                ) : charText ? (
                  <>
                    <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                      {parsedCharacterCards.length > 0 ? (
                        parsedCharacterCards.map((card, idx) => {
                          const cardKey = `${card.name}-${idx}`;
                          const expanded = isAppearanceCardExpanded(cardKey);
                          const refImage = refImageByLabel.get(card.name);
                          const generatingRef = charRefGeneratingKey === card.name;
                          return (
                            <div key={cardKey} className="rounded-lg border border-[#d9dfd7] bg-[#fcfcfa]/60">
                              <div className="flex items-center justify-between gap-2 px-3 py-2">
                                <button
                                  type="button"
                                  onClick={() => setExpandedAppearanceCards((prev) => ({ ...prev, [cardKey]: !expanded }))}
                                  className="flex-1 min-w-0 text-left hover:bg-white transition-colors rounded px-1 py-0.5"
                                >
                                  <div className="min-w-0">
                                    {editingCardIdx === idx ? (
                                      <div className="flex items-center gap-1">
                                        <input
                                          type="text"
                                          value={editingCardName}
                                          onChange={(e) => setEditingCardName(e.target.value)}
                                          className="flex-1 text-sm font-semibold text-slate-900 border border-[#1d4ed8] rounded px-1 outline-none"
                                          autoFocus
                                          onKeyDown={(e) => {
                                            if (e.key === 'Enter') {
                                              const newName = editingCardName.trim();
                                              if (newName && newName !== card.name) {
                                                const newText = renameCharacterCard(charText, card.name, newName);
                                                setCharText(newText);
                                                setCharDraft(newText);
                                                if (chapter) {
                                                  saveCharacters(chapter.id, newText).catch((error) => {
                                                    toast.error(normalizeErrorMessage(error, '保存角色名称失败，请重试'));
                                                  });
                                                }
                                              }
                                              setEditingCardIdx(null);
                                            } else if (e.key === 'Escape') {
                                              setEditingCardIdx(null);
                                            }
                                          }}
                                        />
                                        <button
                                          type="button"
                                          onClick={() => {
                                            const newName = editingCardName.trim();
                                            if (newName && newName !== card.name) {
                                              const newText = renameCharacterCard(charText, card.name, newName);
                                              setCharText(newText);
                                              setCharDraft(newText);
                                              if (chapter) {
                                                saveCharacters(chapter.id, newText).catch((error) => {
                                                  toast.error(normalizeErrorMessage(error, '保存角色名称失败，请重试'));
                                                });
                                              }
                                            }
                                            setEditingCardIdx(null);
                                          }}
                                          className="text-emerald-500 hover:text-emerald-600"
                                        >
                                          <Check size={14} />
                                        </button>
                                        <button
                                          type="button"
                                          onClick={() => setEditingCardIdx(null)}
                                          className="text-slate-400 hover:text-slate-600"
                                        >
                                          <X size={14} />
                                        </button>
                                      </div>
                                    ) : (
                                      <h4 className="truncate text-sm font-semibold text-slate-900">{card.name}</h4>
                                    )}
                                    <div className="text-[10px] text-slate-500">角色卡 {idx + 1}</div>
                                  </div>
                                </button>
                                {editingCardIdx !== idx && (
                                  <button
                                    type="button"
                                    onClick={() => {
                                      setEditingCardIdx(idx);
                                      setEditingCardName(card.name);
                                    }}
                                    className="p-1 text-slate-400 hover:text-slate-600 transition-colors"
                                    title="重命名角色"
                                  >
                                    <Pencil size={12} />
                                  </button>
                                )}
                                <button
                                  type="button"
                                  onClick={() => setExpandedAppearanceCards((prev) => ({ ...prev, [cardKey]: !expanded }))}
                                  className="p-1 text-slate-500 hover:text-slate-700 transition-colors"
                                >
                                  {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                                </button>
                              </div>
                              {expanded && (
                                <div className="border-t border-[#d9dfd7] px-3 py-3 space-y-2">
                  {refImage ? (
                                    <div className="rounded-lg border border-emerald-900/60 bg-emerald-950/20 p-2 space-y-2">
                                      <div className="text-[10px] font-medium uppercase tracking-wide text-emerald-400">角色参考图</div>
                                      <button
                                        type="button"
                                        onClick={() => {
                                          setRefPreviewImage({
                                            image: refImage,
                                            title: `${card.name} 角色参考图`,
                                            prompt: buildRefPreviewPrompt(refImage),
                                            redrawTitle: `${card.name} 角色参考图重绘`,
                                          });
                                        }}
                                        className="group block w-full text-left"
                                      >
                                        <div className="overflow-hidden rounded-md border border-emerald-900/40 bg-[#08111d]">
                                          {refLoadStates[refImage.image_path] === 'ready' ? (
                                            <img
                                              src={refLoadSrcs[refImage.image_path] || refImageSrc(refImage.image_path)}
                                              alt={`${card.name} 角色参考图`}
                                              className="h-[240px] w-full object-contain bg-[#08111d] transition-transform group-hover:scale-[1.01]"
                                              loading="lazy"
                                              decoding="async"
                                            />
                                          ) : (
                                            <div className="flex h-[240px] w-full items-center justify-center bg-[linear-gradient(180deg,_#08111d_0%,_#111827_100%)] text-emerald-200/80">
                                              <Loader2 size={20} className="animate-spin" />
                                            </div>
                                          )}
                                        </div>
                                        <div className="mt-1 text-[10px] text-emerald-300/90">点击全屏查看和重绘</div>
                                      </button>
                                      <div className="flex justify-end">
                                        <button
                                          type="button"
                                          onClick={() => openRefRedraw(refImage, `${card.name} 角色参考图重绘`)}
                                          className="text-[10px] text-emerald-300 transition-colors hover:text-emerald-200"
                                        >
                                          重绘此参考图
                                        </button>
                                      </div>
                                    </div>
                                  ) : (
                                    <div className="rounded-lg border border-dashed border-[#d9dfd7] px-3 py-4 text-xs text-slate-500">
                                      还没有该角色的参考图，生成后本话及后续生图会优先引用角色图。
                                    </div>
                                  )}
                                  {card.fields.map((field, fieldIdx) => (
                                    <div key={`${field.label}-${fieldIdx}`} className="space-y-0.5">
                                      <div className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
                                        {field.label}
                                      </div>
                                      <div className="whitespace-pre-wrap text-xs leading-relaxed text-slate-700">
                                        {field.value}
                                      </div>
                                    </div>
                                  ))}
                                  {chapter && (
                                    <div className="flex items-center gap-3 pt-1">
                                      <button
                                        onClick={() => openCharacterRefModal(card.name)}
                                        className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 transition-colors"
                                      >
                                        <Upload size={11} />
                                        上传参考图
                                      </button>
                                      <button
                                        onClick={() => handleGenerateCharacterRefImage(card.name, !!refImage)}
                                        disabled={!!charRefGeneratingKey}
                                        className="flex items-center gap-1 text-xs text-amber-400 hover:text-amber-300 disabled:opacity-40 transition-colors"
                                      >
                                        {generatingRef ? <Loader2 size={11} className="animate-spin" /> : <ImageIcon size={11} />}
                                        {generatingRef ? '生成中...' : refImage ? '重生成参考图' : '生成参考图'}
                                      </button>
                                      {refImage && (
                                        <button
                                          onClick={() => setAssetModalOpen(true)}
                                          className="flex items-center gap-1 text-xs text-emerald-400 hover:text-emerald-300 transition-colors"
                                        >
                                          <ImagePlus size={11} />
                                          查看垫图
                                        </button>
                                      )}
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          );
                        })
                      ) : (
                        <pre className="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap">{charText}</pre>
                      )}
                    </div>
                    <div className="mt-2 flex items-center gap-2 flex-wrap">
                      {chapter && (
                        <button
                          onClick={async () => {
                            setCharGenerating(true);
                            try {
                              const result = await generateStoryCharactersFromFramework(chapter.story_id);
                              setCharText(result.characters || '');
                              setCharSource(result.characters ? 'story' : 'none');
                            } catch (err: any) {
                              setErrorMsg(err.message);
                            } finally {
                              setCharGenerating(false);
                            }
                          }}
                          disabled={charGenerating || charSaving}
                          className="flex items-center gap-1 text-xs text-amber-400 hover:text-amber-300 disabled:opacity-40 transition-colors"
                        ><Sparkles size={11} /> {charGenerating ? '生成中...' : '根据角色设定重生成'}</button>
                      )}
                          {chapter && parsedCharacterCards.length > 0 && (
                            <button
                              onClick={async () => {
                                if (charRefStreamRef.current) {
                                  charRefStreamRef.current.abort();
                                }
                                setCharRefGeneratingKey('__all__');
                                setErrorMsg('');
                                charRefStreamRef.current = generateStoryCharRefStream(
                                  chapter.story_id,
                                  { overwrite: false },
                                  (event) => {
                                    if (event.type === 'snapshot' || event.type === 'image') {
                                      setRefImages(event.data.images);
                                      setRefSource('story');
                                      setRefMax(event.data.max);
                                    } else if (event.type === 'done') {
                                      setRefImages(event.data.images);
                                      setRefSource('story');
                                      setRefMax(event.data.max);
                                      setCharRefGeneratingKey('');
                                      charRefStreamRef.current = null;
                                    } else if (event.type === 'error') {
                                      setErrorMsg(`生成角色参考图失败：${event.data.error}`);
                                      setCharRefGeneratingKey('');
                                      charRefStreamRef.current = null;
                                    }
                                  },
                                );
                              }}
                              disabled={!!charRefGeneratingKey}
                          className="flex items-center gap-1 text-xs text-emerald-400 hover:text-emerald-300 disabled:opacity-40 transition-colors"
                        >
                          {charRefGeneratingKey === '__all__' ? <Loader2 size={11} className="animate-spin" /> : <ImagePlus size={11} />}
                          {charRefGeneratingKey === '__all__' ? '生成中...' : '生成全部参考图'}
                        </button>
                      )}
                      <button
                        onClick={() => { setCharDraft(charText); setCharEditing(true); }}
                        className="flex items-center gap-1 text-xs text-[#1f5f58] hover:text-[#1f5f58] transition-colors"
                      ><Pencil size={11} /> 编辑</button>
                      {charSource === 'chapter' && (
                        <button
                          onClick={async () => {
                            if (!chapter) return;
                            try {
                              await resetChapterCharacters(chapter.id);
                              const r = await getCharacters(chapter.id);
                              setCharText(r.characters || '');
                              setCharSource(r.source);
                            } catch (err: any) {
                              setErrorMsg(err.message);
                            }
                          }}
                          className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 transition-colors"
                        ><RefreshCw size={11} /> 恢复全局设定</button>
                      )}
                    </div>
                  </>
                ) : (
                  <div className="flex flex-col items-start gap-2">
                    {chapter && (
                      <button
                        onClick={async () => {
                          setCharGenerating(true);
                          try {
                            const result = await generateStoryCharactersFromFramework(chapter.story_id);
                            setCharText(result.characters || '');
                            setCharSource(result.characters ? 'story' : 'none');
                          } catch (err: any) {
                            setErrorMsg(err.message);
                          } finally {
                            setCharGenerating(false);
                          }
                        }}
                        disabled={charGenerating}
                        className="inline-flex items-center gap-1 text-xs text-amber-400 hover:text-amber-300 disabled:opacity-40 transition-colors"
                      >
                        {charGenerating ? <Loader2 size={11} className="animate-spin" /> : <Sparkles size={11} />}
                        {charGenerating ? '正在生成角色外貌卡...' : '根据 AI 角色设定生成角色卡'}
                      </button>
                    )}
                    <button
                      onClick={() => { setCharDraft(''); setCharEditing(true); }}
                      className="text-xs text-[#1f5f58] hover:text-[#1f5f58] transition-colors"
                    >+ 添加角色卡（粘贴 AI 生成的角色外貌描述）</button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Scene-only editor (when no images yet) */}
        {scenes.length > 0 && displayImages.length === 0 && !generating && (
          <>
          <div className="mb-4 flex items-center justify-between gap-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-xs text-emerald-800">
            <div className="min-w-0">
              <p className="font-semibold">分镜已生成</p>
              <p className="mt-0.5 truncate text-emerald-700">共 {scenes.length} 格，可点击顶部“查看正文与分镜脚本”查看或编辑完整内容。</p>
            </div>
            {onOpenSourceViewer ? (
              <button
                type="button"
                onClick={onOpenSourceViewer}
                className="inline-flex shrink-0 items-center gap-1 rounded-md border border-emerald-300 bg-white px-2.5 py-1.5 font-medium text-emerald-700 transition hover:bg-emerald-100"
              >
                <BookOpen size={13} />
                打开查看器
              </button>
            ) : null}
          </div>
          <div className="hidden">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide flex items-center gap-2">
                分镜脚本（可编辑）
                {scenesFromSelectionFlag && (
                  <span className="text-[10px] font-normal normal-case px-1.5 py-0.5 rounded bg-amber-900/50 text-amber-400 border border-amber-800/50">
                    基于选中文字
                  </span>
                )}
              </h3>
              <button
                onClick={handleSaveAllScenes}
                disabled={savingScenes}
                className="text-xs text-[#1f5f58] hover:text-[#1f5f58] transition-colors"
              >
                {savingScenes ? '保存中...' : '保存修改'}
              </button>
            </div>
            <div className="space-y-2">
              {scenes.map((scene, idx) => (
                (() => {
                  const isSanitized = sanitizedSceneIdxs.includes(idx);
                  return (
                <div
                  key={idx}
                  className={`rounded-lg border overflow-hidden ${
                    failedSceneIdx === idx ? 'border-red-700 bg-red-950/20' : 'border-[#d9dfd7] bg-white'
                  }`}
                >
                  <div className="flex items-start gap-2 p-3">
                    <span className="shrink-0 w-6 h-6 flex items-center justify-center rounded bg-[#f3f5f0] text-[10px] text-slate-600 font-mono mt-0.5">
                      {idx + 1}
                    </span>
                    {editingIdx === idx ? (
                      <textarea
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        className="flex-1 bg-[#f3f5f0] text-sm text-slate-800 rounded p-2 resize-none outline-none border border-[#d9dfd7] focus:border-[#1f5f58]"
                        rows={4}
                        autoFocus
                      />
                    ) : (
                      <p
                        className="min-w-0 flex-1 cursor-default text-xs leading-relaxed text-slate-600 line-clamp-2 overflow-hidden"
                        title={scene}
                      >
                        {scene}
                      </p>
                    )}
                    <div className="shrink-0 flex gap-1">
                      {isSanitized && editingIdx !== idx && (
                        <span className="px-2 py-1 rounded bg-amber-900/40 text-[10px] text-amber-300 border border-amber-800/60">
                          已自动降敏
                        </span>
                      )}
                      {editingIdx === idx ? (
                        <>
                          <button onClick={() => handleSceneSave(idx)} className="p-1 rounded hover:bg-[#e8ece6] text-green-400 transition-colors"><Check size={14} /></button>
                          <button onClick={() => setEditingIdx(-1)} className="p-1 rounded hover:bg-[#e8ece6] text-slate-500 transition-colors"><X size={14} /></button>
                        </>
                      ) : (
                        <>
                          {failedSceneIdx === idx && (
                            <button
                              onClick={() => handleOptimizeFailedScene(idx)}
                              className="px-2 py-1 rounded bg-red-900/40 hover:bg-red-800 text-[10px] text-red-200 transition-colors"
                            >
                              重新优化降敏
                            </button>
                          )}
                          <button onClick={() => handleSceneEdit(idx)} className="p-1 rounded hover:bg-[#e8ece6] text-slate-500 hover:text-slate-700 transition-colors"><Pencil size={12} /></button>
                        </>
                      )}
                    </div>
                  </div>
                </div>
                  );
                })()
              ))}
            </div>
          </div>
          </>
        )}

        {scenes.length > 0 && (
          <div className="mb-4 overflow-hidden rounded-lg border border-[#d7e3f4] bg-[rgba(255,255,255,0.9)]">
            <div className="flex items-center justify-between px-3 py-2 border-b border-[#d9dfd7]">
              <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide">
                分镜总览
              </h3>
              <span className={`text-[10px] ${generating ? 'text-blue-600' : 'text-slate-500'}`}>
                {generating ? '生成中也可查看全部分镜' : '全部分镜始终可见'}
              </span>
            </div>
            <div className="p-2">
              <div className="flex flex-wrap gap-1.5">
              {scenes.map((_scene, idx) => {
                const isCurrent = idx === activeSceneIdx;
                const isDone = idx < completedImageCount;
                const isSanitized = sanitizedSceneIdxs.includes(idx);
                return (
                  <button
                    key={`generating-scene-${idx}`}
                    type="button"
                    onClick={() => scrollToSceneDetail(idx)}
                    className={`min-w-[68px] flex-[0_0_auto] rounded-lg border px-2 py-1.5 text-left transition-colors ${
                      failedSceneIdx === idx
                        ? 'border-red-200 bg-red-50'
                        : isCurrent
                          ? 'border-blue-300 bg-blue-50'
                          : isDone
                            ? 'border-emerald-200 bg-emerald-50'
                            : 'border-slate-200 bg-white hover:border-blue-200 hover:bg-blue-50/40'
                    }`}
                    title={`定位到第 ${idx + 1} 格详情`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className={`shrink-0 w-8 h-8 flex items-center justify-center rounded-lg text-[10px] font-mono font-semibold ${
                        failedSceneIdx === idx
                          ? 'bg-red-100 text-red-700'
                          : isDone
                            ? 'bg-emerald-100 text-emerald-700'
                            : isCurrent
                              ? 'bg-blue-100 text-blue-700'
                              : 'bg-slate-100 text-slate-600'
                      }`}>
                        {idx + 1}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="text-[10px] font-medium text-slate-800">
                          第 {idx + 1} 格
                        </div>
                        <div className="mt-1 flex items-center gap-1 flex-wrap">
                          {failedSceneIdx === idx && (
                            <span className="px-1.5 py-0.5 rounded-full bg-red-100 text-[10px] font-medium text-red-700 border border-red-200">
                              失败
                            </span>
                          )}
                          {isCurrent && failedSceneIdx !== idx && <span className="px-1.5 py-0.5 rounded-full bg-blue-100 text-[10px] font-medium text-blue-700 border border-blue-200">当前</span>}
                          {isDone && failedSceneIdx !== idx && <span className="px-1.5 py-0.5 rounded-full bg-emerald-100 text-[10px] font-medium text-emerald-700 border border-emerald-200">完成</span>}
                          {isSanitized && (
                            <span className="px-1.5 py-0.5 rounded-full bg-amber-100 text-[10px] font-medium text-amber-700 border border-amber-200">
                              降敏
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
            </div>
          </div>
        )}

        {/* Empty state */}
        {displayImages.length === 0 && !generating && scenes.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-3">
            <ImageIcon size={48} strokeWidth={1} />
            <span className="text-sm">点击右上方按钮生成分镜</span>
          </div>
        )}

        {/* Images gallery with inline scene editor */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6">
          {gallerySlots.map(({ image_number, scene, img }) => {
            const sceneIdx = image_number - 1;
            const isEditing = editingIdx === sceneIdx;
            const isRegenerating = regenIdx === image_number;
            const isSanitized = sanitizedSceneIdxs.includes(sceneIdx);
            const imgReady = img ? imageReadyMap.get(img.image_path) === true : false;
            const imgLoadFailed = img ? imageLoadStates[img.image_path] === 'error' : false;
            const resolvedImgSrc = img ? (imageLoadSrcs[img.image_path] || mangaImageUrl(img.image_path)) : '';
            return (
              <div
                key={image_number}
                className="group scroll-mt-4 min-w-0"
                ref={(node) => {
                  sceneDetailRefs.current[sceneIdx] = node;
                }}
              >
                {img && imgReady ? (
                <div
                  className="relative aspect-[9/16] rounded-xl overflow-hidden border border-[#d9dfd7] bg-white cursor-pointer
                             hover:border-[#d9dfd7] transition-colors"
                  onClick={() => openMangaRedraw(image_number)}
                >
                  <img
                    src={resolvedImgSrc}
                    alt={`Panel ${image_number}`}
                    className={`h-full w-full object-cover ${isRegenerating ? 'opacity-30' : ''}`}
                    loading="lazy"
                    decoding="async"
                  />
                  <div className="absolute top-3 left-3 px-2 py-0.5 bg-black/70 rounded text-[10px] text-slate-700 font-mono">
                    {image_number}/{imageCount}
                  </div>
                  {isRegenerating && (
                    <div className="absolute inset-0 flex items-center justify-center">
                      <div className="flex flex-col items-center gap-2">
                        <Loader2 size={32} className="animate-spin text-amber-400" />
                        <span className="text-sm text-slate-700">重新生成中...</span>
                      </div>
                    </div>
                  )}
                  {!isRegenerating && (
                    <div className="absolute inset-0 bg-black/0 hover:bg-black/10 transition-colors flex items-center justify-center opacity-0 hover:opacity-100">
                      <span className="bg-black/60 text-white text-xs px-3 py-1 rounded-full">点击放大</span>
                    </div>
                  )}
                </div>
                ) : (
                <div className="relative aspect-[9/16] rounded-xl overflow-hidden border border-dashed border-[#d9dfd7] bg-[#f7f8f5] flex items-center justify-center">
                  <div className="absolute top-3 left-3 px-2 py-0.5 bg-black/50 rounded text-[10px] text-slate-600 font-mono">
                    {image_number}/{imageCount}
                  </div>
                  <div className="flex flex-col items-center gap-2 text-slate-500">
                    {img ? (
                      imgLoadFailed ? <ImageIcon size={28} strokeWidth={1.5} /> : <Loader2 size={24} className="animate-spin" />
                    ) : (
                      generating ? <Loader2 size={24} className="animate-spin" /> : <ImageIcon size={28} strokeWidth={1.5} />
                    )}
                    <span className="text-xs">
                      {img ? (imgLoadFailed ? '图片加载失败，稍后会自动同步' : '图片载入中...') : (generating ? '等待生成...' : '未生成')}
                    </span>
                    {!img && !generating && scene && (
                      <button
                        onClick={() => handleGeneratePanel(image_number)}
                        disabled={panelGenLoading.includes(image_number)}
                        className={`mt-1 flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                          panelGenLoading.includes(image_number)
                            ? 'bg-amber-300 text-amber-700 cursor-wait'
                            : 'bg-amber-500 hover:bg-amber-400 text-slate-900'
                        }`}
                      >
                        {panelGenLoading.includes(image_number) ? (
                          <Loader2 size={12} className="animate-spin" />
                        ) : (
                          <Sparkles size={12} />
                        )}
                        {panelGenLoading.includes(image_number) ? '生成中...' : '生成此格'}
                      </button>
                    )}
                  </div>
                </div>
                )}
                {/* Inline scene editor under image */}
                {scene && (
                  <div
                    className={`mt-2 rounded-lg border p-2.5 ${
                      failedSceneIdx === sceneIdx ? 'border-red-700 bg-red-950/20' : 'border-[#d9dfd7] bg-[#fbfcf8]'
                    }`}
                  >
                    <div className="flex items-start gap-2">
                      {isEditing ? (
                        <textarea
                          value={editText}
                          onChange={(e) => setEditText(e.target.value)}
                          className="flex-1 bg-[#f3f5f0] text-xs text-slate-800 rounded p-2 resize-none outline-none border border-[#d9dfd7] focus:border-[#1f5f58] leading-relaxed"
                          rows={3}
                          autoFocus
                          onClick={(e) => e.stopPropagation()}
                        />
                      ) : (
                        <p
                          className="min-w-0 flex-1 overflow-hidden text-xs leading-relaxed text-slate-500 line-clamp-2"
                          title={scene}
                        >
                          {scene}
                        </p>
                      )}
                      <div className="shrink-0 flex items-center gap-1">
                        {isSanitized && !isEditing && (
                          <span className="px-2 py-1 rounded bg-amber-50 text-[10px] text-amber-700 border border-amber-200">
                            已自动降敏
                          </span>
                        )}
                        {isEditing ? (
                          <>
                            <button onClick={() => handleSceneSave(sceneIdx)} className="p-1 rounded hover:bg-[#e8ece6] text-emerald-600 transition-colors" title="保存"><Check size={13} /></button>
                            <button onClick={() => setEditingIdx(-1)} className="p-1 rounded hover:bg-[#e8ece6] text-slate-500 transition-colors" title="取消"><X size={13} /></button>
                          </>
                        ) : (
                          <>
                            {failedSceneIdx === sceneIdx && (
                              <button
                                onClick={() => handleOptimizeFailedScene(sceneIdx)}
                                className="px-2 py-1 rounded bg-red-50 hover:bg-red-100 text-[10px] text-red-700 border border-red-200 transition-colors"
                                title="重新修改并优化当前失败分镜"
                              >
                                优化降敏
                              </button>
                            )}
                            <button onClick={() => handleSceneEdit(sceneIdx)} className="p-1 rounded hover:bg-[#e8ece6] text-slate-500 hover:text-slate-700 transition-colors" title="编辑分镜"><Pencil size={12} /></button>
                            <button
                              onClick={() => openMangaRedraw(image_number)}
                              disabled={isRegenerating || generating}
                              className="p-1 rounded hover:bg-[#e8ece6] text-slate-500 hover:text-blue-600 disabled:opacity-30 transition-colors"
                              title="局部重绘 / 整图重绘"
                            >
                              <ImageIcon size={12} />
                            </button>
                            <button
                              onClick={() => handleRegenImage(image_number)}
                              disabled={isRegenerating || generating}
                              className="p-1 rounded hover:bg-[#e8ece6] text-slate-500 hover:text-amber-400 disabled:opacity-30 transition-colors"
                              title="重新生成此图"
                            >
                              <RefreshCw size={12} />
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Loading placeholders */}
        {generating && scenes.length === 0 && displayImages.length < activeImageCount && (
          <div className="mt-6 space-y-6">
            {Array.from({ length: Math.max(activeImageCount - displayImages.length, 0) }, (_, i) => (
              <div
                key={`placeholder-${i}`}
                className="rounded-xl border border-[#d9dfd7] bg-white h-64 flex items-center justify-center"
              >
                <div className="flex flex-col items-center gap-2 text-slate-700">
                  <Loader2 size={24} className="animate-spin" />
                  <span className="text-xs">等待生成...</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      </div>

      {/* Workspace preview mode */}
      {showWorkspacePreview && (
        <div
          ref={lightboxRef}
          className="flex h-full min-h-[calc(100vh-150px)] flex-col overflow-hidden rounded-[28px] border border-[#d7e3f4] bg-[linear-gradient(180deg,_#0b1220_0%,_#111827_100%)] shadow-[0_24px_64px_rgba(15,23,42,0.28)]"
        >
          <div className="flex items-center justify-between gap-4 border-b border-white/10 px-5 py-4 text-white">
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => closeWorkspacePreview(setLightboxIdx, onWorkspacePreviewModeChange)}
                className="rounded-full border border-white/15 bg-white/8 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-white/14"
              >
                返回工作台
              </button>
              <div className="rounded-full bg-white/10 px-3 py-1 text-sm font-mono">
                {lightboxImg!.image_number} / {imageCount}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => closeWorkspacePreview(setLightboxIdx, onWorkspacePreviewModeChange)}
                className="rounded-full bg-white/10 p-2 text-white transition-colors hover:bg-white/20"
              >
                <X size={20} />
              </button>
            </div>
          </div>

          <div className="flex flex-1 items-center justify-between gap-3 overflow-hidden px-4 py-4">
            <button
              type="button"
              disabled={lightboxIdx <= 0}
              onClick={() => handleLightboxNav('prev')}
              className="shrink-0 rounded-full bg-white/10 p-3 text-white transition hover:bg-white/20 disabled:cursor-not-allowed disabled:opacity-30"
            >
              <ChevronUp size={22} className="-rotate-90" />
            </button>

            <div className="flex-1 h-full overflow-hidden rounded-[24px] bg-black/20 px-4 py-5">
              <ImageZoomView
                src={imageLoadSrcs[lightboxImg!.image_path] || mangaImageUrl(lightboxImg!.image_path)}
                alt={`Panel ${lightboxImg!.image_number}`}
                className="h-full w-full rounded-xl"
              />
            </div>

            <button
              type="button"
              disabled={lightboxIdx >= displayImages.length - 1}
              onClick={() => handleLightboxNav('next')}
              className="shrink-0 rounded-full bg-white/10 p-3 text-white transition hover:bg-white/20 disabled:cursor-not-allowed disabled:opacity-30"
            >
              <ChevronDown size={22} className="-rotate-90" />
            </button>
          </div>
        </div>
      )}

      {/* 历史垫图弹窗已下线，仅保留兼容代码以避免旧任务中的引用预览失效。 */}
      {legacyReferenceUiEnabled && refModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={() => setRefModalOpen(false)}
        >
          <div
            className="w-full max-w-2xl bg-white border border-[#d9dfd7] rounded-xl shadow-2xl max-h-[85vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-3 border-b border-[#d9dfd7]">
              <div className="flex items-center gap-2">
                <ImagePlus size={16} className="text-emerald-400" />
                <h3 className="text-sm font-semibold text-slate-800">漫画资产管理</h3>
                <span className="text-xs text-slate-500">
                  {refImages.length}/{refMax} 张
                  {refSource === 'story' && refImages.length > 0 && (
                    <span className="ml-2 text-blue-400">· 继承自全局</span>
                  )}
                </span>
              </div>
              <button
                onClick={() => setRefModalOpen(false)}
                className="p-1 text-slate-500 hover:text-slate-900 rounded transition-colors"
              >
                <X size={16} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-5">
              <p className="text-xs text-slate-500 mb-4 leading-relaxed">
                为本章绑定角色、场景、道具与风格资产；生成时会按分镜文本标签匹配并作为参考图输入。
                {refSource === 'story' && refImages.length > 0 && (
                  <> 当前显示首页设置的全局垫图；上传新图将创建本话专属垫图覆盖全局。</>
                )}
              </p>
              <div className="mb-5 rounded-xl border border-[#d7e3f4] bg-[#f8fbff] p-3">
                <div className="mb-2 flex items-center justify-between text-xs font-semibold text-slate-700"><span>故事资产与本章绑定</span><span className="text-slate-400">角色 / 场景 / 道具 / 风格</span></div>
                {assetsLoading ? <div className="py-4 text-center text-xs text-slate-400">正在加载资产...</div> : mangaAssets.length === 0 ? <div className="py-3 text-xs text-slate-500">暂无已迁移资产。下方上传的参考图仍会兼容参与本章生成。</div> : <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {mangaAssets.map((asset) => {
                    const bound = assetBindings.some((binding) => binding.asset_id === asset.id);
                    return <label key={asset.id} className={`flex cursor-pointer items-center gap-2 rounded-lg border p-2 text-xs ${bound ? 'border-blue-300 bg-blue-50' : 'border-slate-200 bg-white'}`}><input type="checkbox" checked={bound} onChange={async () => { if (!chapter) return; const next = bound ? assetBindings.filter((binding) => binding.asset_id !== asset.id) : [...assetBindings, { id: 0, asset_id: asset.id, binding_role: asset.asset_type.replace('_reference', ''), label: asset.name, priority: 0, is_required: false }]; try { const saved = await saveMangaAssetBindings(chapter.id, next.map(({ asset_id, binding_role, label, priority, is_required }) => ({ asset_id, binding_role, label, priority, is_required }))); setAssetBindings(saved.bindings); } catch (error: any) { setErrorMsg(`保存资产绑定失败: ${error.message}`); } }} /><span className="min-w-0 truncate"><b>{asset.name}</b><span className="ml-1 text-slate-400">{asset.asset_type.replace('_reference', '')}</span></span></label>;
                  })}
                </div>}
              </div>
              {refImages.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-slate-500 text-sm gap-2 border border-dashed border-[#d9dfd7] rounded-lg">
                  <ImagePlus size={32} className="opacity-50" />
                  <span>还没有垫图，点击下方按钮上传</span>
                </div>
              ) : (
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                  {refImages.map((img) => (
                    <div
                      key={img.filename}
                      className="relative group aspect-square rounded-lg overflow-hidden border border-[#d9dfd7] bg-[#fcfcfa]"
                    >
                      <button
                        type="button"
                        onClick={() => {
                          setRefPreviewImage({
                            image: img,
                            title: img.label ? `${img.label} 参考图` : '参考图预览',
                            prompt: buildRefPreviewPrompt(img),
                            redrawTitle: img.label ? `${img.label} 参考图重绘` : '参考图重绘',
                          });
                        }}
                        className="block h-full w-full"
                      >
                        {refLoadStates[img.image_path] === 'ready' ? (
                          <img
                            src={refLoadSrcs[img.image_path] || refImageSrc(img.image_path)}
                            alt={img.filename}
                            className="w-full h-full object-cover transition-transform group-hover:scale-[1.03]"
                            loading="lazy"
                            decoding="async"
                          />
                        ) : (
                          <div className="flex h-full w-full items-center justify-center bg-[linear-gradient(180deg,_#0f172a_0%,_#111827_100%)] text-white/70">
                            <Loader2 size={18} className="animate-spin" />
                          </div>
                        )}
                      </button>
                      <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors flex items-end justify-between p-2 pointer-events-none">
                        <span className="text-[10px] text-white/80 bg-black/60 px-1.5 py-0.5 rounded">
                          {img.size_kb} KB
                        </span>
                        <span className="text-[10px] text-white/90 bg-black/60 px-1.5 py-0.5 rounded">
                          点击放大
                        </span>
                      </div>
                      <button
                        type="button"
                        onClick={() => openRefRedraw(img)}
                        className="absolute top-1.5 left-1.5 rounded-md bg-slate-900/70 px-2 py-1 text-[10px] text-white opacity-0 transition-opacity group-hover:opacity-100"
                        title="整图或局部重绘"
                      >
                        重绘
                      </button>
                      {refSource === 'chapter' && chapter && (
                        <button
                          onClick={async () => {
                            try {
                              const r = await deleteChapterRefImage(chapter.id, img.filename);
                              setRefImages(r.images);
                              setRefSource(r.source ?? (r.images.length ? 'chapter' : 'none'));
                              setRefMax(r.max);
                              if (r.images.length === 0) {
                                // After deleting last chapter ref, reload to pick up story fallback
                                const next = await getChapterRefImages(chapter.id);
                                setRefImages(next.images);
                                setRefSource(next.source ?? (next.images.length ? 'chapter' : 'none'));
                              }
                            } catch (err: any) {
                              setErrorMsg(`删除垫图失败: ${err.message}`);
                            }
                          }}
                          className="absolute top-1.5 right-1.5 p-1 rounded-md bg-red-600/80 hover:bg-red-500 text-white opacity-0 group-hover:opacity-100 transition-opacity"
                          title="删除"
                        >
                          <Trash2 size={12} />
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="px-5 py-3 border-t border-[#d9dfd7] flex items-center justify-between gap-2">
              <span className="text-xs text-slate-500">
                {refSource === 'chapter'
                  ? '本话自定义垫图（覆盖全局）'
                  : refSource === 'story'
                    ? '当前显示全局垫图'
                    : '尚未上传垫图'}
              </span>
              <button
                onClick={() => refFileRef.current?.click()}
                disabled={!chapter || refUploading || refImages.length >= refMax && refSource === 'chapter'}
                className="flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium rounded-md
                           bg-[#1f5f58] hover:bg-[#184c46] text-white
                           disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                title={
                  refImages.length >= refMax && refSource === 'chapter'
                    ? `已达上限 ${refMax} 张`
                    : '上传一张垫图'
                }
              >
                {refUploading ? <Loader2 size={13} className="animate-spin" /> : <ImagePlus size={13} />}
                {refSource === 'story' && refImages.length > 0 ? '上传本话垫图（覆盖全局）' : '添加垫图'}
              </button>
            </div>
          </div>
        </div>
      )}

      {assetModalOpen && chapter && (
        <MangaAssetManagementModal
          storyId={chapter.story_id}
          chapterId={chapter.id}
          onClose={() => setAssetModalOpen(false)}
          onAssetsChanged={() => onChapterRefresh?.(chapter.id)}
        />
      )}

      {storyboardImportOpen && chapter ? (
        <MangaStoryboardImportModal
          chapterId={chapter.id}
          chapterTitle={`第 ${chapter.chapter_number} 话 · ${chapter.title || '未命名章节'}`}
          onClose={() => setStoryboardImportOpen(false)}
          onImported={async (result) => {
            setScenes(result.scenes);
            setSanitizedSceneIdxs([]);
            setImageCountState(result.scene_count);
            setFailedSceneIdx(-1);
            setEditingIdx(-1);
            setPhase('editing-scenes');
            if (result.stale_image_indices.length > 0) {
              toast.warning(`已导入 ${result.scene_count} 格分镜；第 ${result.stale_image_indices.join('、')} 格图片需要重新生成`);
            } else {
              toast.success(`已导入 ${result.scene_count} 格分镜`);
            }
            await onChapterRefresh?.(chapter.id);
          }}
        />
      ) : null}

      {refPreviewImage && (
        <RefPreviewModal
          target={refPreviewImage}
          busy={refUploading}
          imageSrc={refLoadSrcs[refPreviewImage.image.image_path] || refImageSrc(refPreviewImage.image.image_path)}
          ready={refLoadStates[refPreviewImage.image.image_path] === 'ready'}
          onClose={() => closeRefWorkspacePreview(setRefPreviewImage, onWorkspacePreviewModeChange)}
          onStartRedraw={() => {
            const current = refPreviewImage;
            closeRefWorkspacePreview(setRefPreviewImage, onWorkspacePreviewModeChange);
            if (!current) return;
            const redrawTitle = current.redrawTitle || `${current.title}重绘`;
            const prompt = current.prompt.trim();
            setImageEditTarget({
              kind: 'ref',
              title: redrawTitle,
              imageSrc: refLoadSrcs[current.image.image_path] || refImageSrc(current.image.image_path),
              prompt: prompt || (current.image.label
                ? `保持${current.image.label}的人物五官、发型、服装与气质一致，按我的要求重新绘制。`
                : '保持主体核心特征一致，按我的要求重新绘制。'),
              filename: current.image.filename,
              owner: refSource === 'story' ? 'story' : 'chapter',
            });
          }}
          onUploadReplace={async (file: File) => {
            if (!chapter) return;
            const current = refPreviewImage;
            if (!current) return;

            setRefUploading(true);
            try {
              const reader = new FileReader();
              const base64 = await new Promise<string>((resolve, reject) => {
                reader.onload = () => resolve(reader.result as string);
                reader.onerror = reject;
                reader.readAsDataURL(file);
              });

              const characterName = current.image.label || '';
              if (characterName) {
                const result = await uploadCharacterRefImage(
                  chapter.story_id,
                  characterName,
                  base64,
                  true
                );
                setRefImages(result.images);
                setRefSource('story');
                setRefMax(result.max);
              } else {
                const b64 = base64.split(',')[1] || base64;
                const result = await addChapterRefImage(chapter.id, b64);
                setRefImages(result.images);
                setRefSource(result.source ?? 'chapter');
                setRefMax(result.max);
              }

              setRefImageVersion(Date.now());
              closeRefWorkspacePreview(setRefPreviewImage, onWorkspacePreviewModeChange);
            } catch (err: any) {
              setErrorMsg(`上传替换失败: ${err.message}`);
            } finally {
              setRefUploading(false);
            }
          }}
        />
      )}

      {imageEditTarget && (
        <ImageRedrawModal
          imageSrc={imageEditTarget.imageSrc}
          title={imageEditTarget.title}
          prompt={imageEditTarget.prompt}
          busy={refUploading || regenIdx === (imageEditTarget.kind === 'manga' ? imageEditTarget.imageNumber : -999)}
          onClose={() => setImageEditTarget(null)}
          onSubmit={handleApplyImageRedraw}
        />
      )}

      {charRefModalOpen && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50">
          <div className="bg-[#f8fbff] rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-[#d7e3f4]">
              <h3 className="text-lg font-semibold text-[#0b1220]">
                角色参考图管理 - {charRefModalCharName}
              </h3>
              <button
                onClick={() => setCharRefModalOpen(false)}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="px-6 py-4">
              <div className="mb-4">
                {charRefModalImage ? (
                  <div className="relative">
                    <img
                      src={refLoadSrcs[charRefModalImage.image_path] || refImageSrc(charRefModalImage.image_path)}
                      alt={`${charRefModalCharName} 参考图`}
                      className="w-full h-48 object-contain rounded-lg border border-[#d7e3f4]"
                    />
                    <div className="absolute top-2 right-2 text-xs text-gray-500 bg-white/80 px-2 py-1 rounded">
                      {charRefModalImage.kind === 'character_generated' ? 'AI 生成' : '用户上传'}
                    </div>
                  </div>
                ) : (
                  <div className="w-full h-48 flex items-center justify-center bg-gray-50 rounded-lg border-2 border-dashed border-[#d7e3f4]">
                    <div className="text-center text-gray-400">
                      <ImageIcon className="w-12 h-12 mx-auto mb-2" />
                      <p>暂无参考图</p>
                    </div>
                  </div>
                )}
              </div>
              <div className="flex gap-3">
                <button
                  onClick={() => charRefFileRef.current?.click()}
                  disabled={charRefModalUploading}
                  className="flex-1 px-4 py-2 bg-[#1d4ed8] text-white rounded-lg hover:bg-[#1e40af] disabled:opacity-50"
                >
                  {charRefModalUploading ? '上传中...' : '上传参考图'}
                </button>
                {charRefModalImage && (
                  <button
                    onClick={handleDeleteCharacterRef}
                    className="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600"
                  >
                    删除
                  </button>
                )}
              </div>
              <input
                ref={charRefFileRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) {
                    handleUploadCharacterRef(file);
                    e.target.value = '';
                  }
                }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
    {createPortal(
      <StyleSelectorModal
        isOpen={styleSelectorOpen}
        onClose={() => setStyleSelectorOpen(false)}
        presets={stylePresets}
        selectedStyleName={selectedStylePresetName}
        styleReferenceImageUrl={styleReferenceImageUrl}
        requireReferenceImage
        onFileUpload={chapter ? (file) => uploadMangaStyleReference(chapter.id, file).then(r => r.style_reference_image_url) : undefined}
        onStyleSelect={(styleName, refUrl) => {
          styleSelectionTouchedRef.current = true;
          setSelectedStylePresetName(styleName);
          setStyleReferenceImageUrl(refUrl);
          if (chapter) {
            localStorage.setItem(`storycanvas.mangaStyle.${chapter.id}`, JSON.stringify({ presetName: styleName, referenceUrl: refUrl }));
          }
        }}
      />,
      document.body
    )}
    </>
  );
})



function RefPreviewModal({
  target,
  imageSrc,
  ready,
  busy,
  onClose,
  onStartRedraw,
  onUploadReplace,
}: {
  target: RefPreviewTarget;
  imageSrc: string;
  ready: boolean;
  busy: boolean;
  onClose: () => void;
  onStartRedraw: () => void;
  onUploadReplace: (file: File) => void;
}) {
  const uploadRef = useRef<HTMLInputElement>(null);

  const modal = (
    <div className="fixed inset-0 z-[68] flex items-center justify-center bg-[rgba(15,23,42,0.62)] p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className="flex h-[88vh] w-[min(1400px,94vw)] flex-col overflow-hidden rounded-[30px] border border-[#d7e3f4] bg-white shadow-[0_30px_90px_rgba(15,23,42,0.28)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[#e5edf8] px-6 py-4">
          <div>
            <div className="text-lg font-semibold text-slate-900">{target.title}</div>
            <div className="mt-1 text-sm text-slate-500">左侧查看角色大图，右侧查看人物提示词并决定是否进入重绘。</div>
          </div>
          <button onClick={onClose} className="rounded-full bg-slate-100 p-2 text-slate-600 transition hover:bg-slate-200">
            <X size={18} />
          </button>
        </div>
        <div className="grid flex-1 gap-0 overflow-hidden lg:grid-cols-[minmax(0,1.5fr)_420px]">
          <div className="overflow-hidden bg-[linear-gradient(180deg,_#0f172a_0%,_#111827_100%)] p-6">
            <div className="mb-4 flex items-center justify-between text-white/80">
              <div className="text-sm font-medium">角色参考图</div>
              <div className="flex items-center gap-1.5 rounded-full bg-white/10 px-3 py-1.5 text-xs text-white/60">
                <MousePointer size={12} />
                <span>滚轮缩放 · 拖拽平移</span>
              </div>
            </div>
            <div className="mx-auto flex h-[62vh] w-full items-center justify-center rounded-[24px] border border-white/10 bg-black/20 p-4">
              {ready ? (
                <ImageZoomView
                  src={imageSrc}
                  alt={target.image.filename}
                  className="h-full w-full rounded-xl"
                />
              ) : (
                <div className="flex min-h-[420px] min-w-[320px] items-center justify-center rounded-xl bg-[linear-gradient(180deg,_#08111d_0%,_#111827_100%)] text-white/70">
                  <Loader2 size={24} className="animate-spin" />
                </div>
              )}
            </div>
          </div>
          <div className="overflow-auto border-l border-[#e5edf8] bg-[#f8fbff] p-6">
            <div className="space-y-5">
              <div className="rounded-2xl border border-[#d7e3f4] bg-white p-4">
                <div className="text-sm font-medium text-slate-800">人物提示词</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">这里展示当前角色卡提示词。确认后可直接进入和漫画相同的重绘工作区。</div>
                <textarea
                  value={target.prompt}
                  readOnly
                  rows={16}
                  className="mt-3 w-full rounded-2xl border border-[#d7e3f4] bg-[#f8fbff] px-3 py-3 text-sm leading-6 text-slate-900 outline-none"
                />
              </div>
              <div className="rounded-2xl border border-[#d7e3f4] bg-white p-4">
                <div className="text-sm font-medium text-slate-800">后续操作</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">如果只想查看，直接关闭即可；如果要修改角色图，点击下方按钮进入整图/局部重绘。</div>
                <div className="mt-4 flex gap-3">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={onStartRedraw}
                    className="rounded-2xl bg-[#1d4ed8] px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
                  >
                    {busy ? '处理中...' : '开始重绘'}
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => uploadRef.current?.click()}
                    className="rounded-2xl bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
                  >
                    上传替换
                  </button>
                  <button
                    type="button"
                    onClick={onClose}
                    className="rounded-2xl border border-[#d7e3f4] bg-white px-4 py-2 text-sm font-medium text-slate-700"
                  >
                    关闭
                  </button>
                </div>
                <input
                  ref={uploadRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) {
                      onUploadReplace(file);
                      e.target.value = '';
                    }
                  }}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(modal, document.body);
}
