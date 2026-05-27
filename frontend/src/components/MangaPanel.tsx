import { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronUp, ChevronDown, Download, ImageIcon, Loader2, Sparkles, Pencil, RefreshCw, Check, X, ImagePlus, Trash2, Square } from 'lucide-react';
import { useMemo as useMemoValue } from 'react';
import { createPortal } from 'react-dom';
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
  type ImageRedrawMode,
  type Chapter,
  type MangaProgress,
  type ColorMode,
  type EntitlementResponse,
  type RefSource,
  type RefImage,
  type CharRefEvent,
} from '../api';
import { genStore } from '../genStore';

interface Props {
  chapter: Chapter | null;
  entitlements?: EntitlementResponse | null;
  onChapterRefresh?: (chapterId: number) => void;
  selectedText?: string;
  chapterContext?: { characters?: any[] };
  isWorkspacePreviewMode?: boolean;
  onWorkspacePreviewModeChange?: (expanded: boolean) => void;
  onClearSelection?: () => void;
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
const DEFAULT_IMAGE_COUNT = 10;

function entitlementNumber(entitlements: EntitlementResponse | null | undefined, key: string, fallback: number): number {
  const raw = entitlements?.entitlements?.[key];
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw;
  if (typeof raw === 'string') {
    const parsed = Number(raw);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

function entitlementBool(entitlements: EntitlementResponse | null | undefined, key: string, fallback = false): boolean {
  const raw = entitlements?.entitlements?.[key];
  if (typeof raw === 'boolean') return raw;
  if (typeof raw === 'string') {
    const normalized = raw.trim().toLowerCase();
    if (normalized === 'true') return true;
    if (normalized === 'false') return false;
  }
  if (typeof raw === 'number') return raw !== 0;
  return fallback;
}

export default function MangaPanel({
  chapter,
  entitlements,
  onChapterRefresh,
  selectedText,
  chapterContext,
  isWorkspacePreviewMode = false,
  onWorkspacePreviewModeChange,
  onClearSelection,
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
  const [refModalOpen, setRefModalOpen] = useState(false);
  const [colorMode, setColorModeState] = useState<ColorMode>('bw');
  const [imageCount, setImageCountState] = useState(DEFAULT_IMAGE_COUNT);
  const [showColorMenu, setShowColorMenu] = useState(false);
  const colorMenuRef = useRef<HTMLDivElement>(null);
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
  const [lightboxZoom, setLightboxZoom] = useState<1 | 1.35 | 1.7>(1.35);
  const [refPreviewImage, setRefPreviewImage] = useState<RefPreviewTarget | null>(null);
  const [refPreviewZoom, setRefPreviewZoom] = useState<1 | 1.35 | 1.7>(1.35);
  const [imageEditTarget, setImageEditTarget] = useState<ImageEditTarget | null>(null);
  const [refImageVersion, setRefImageVersion] = useState(0);
  const mangaAbortRef = useRef<Map<number, AbortController>>(new Map());
  const imagePreloadAttemptsRef = useRef<Record<string, number>>({});
  const refPreloadAttemptsRef = useRef<Record<string, number>>({});
  const parsedCharacterCards = useMemoValue(() => parseCharacterAppearanceCards(charText), [charText]);
  const maxImagesPerChapter = useMemoValue(() => {
    const configured = entitlementNumber(entitlements, 'manga.max_image_count_per_chapter', DEFAULT_IMAGE_COUNT);
    const allowedCounts = ALLOWED_IMAGE_COUNTS.filter((count) => count <= configured);
    return allowedCounts.length > 0 ? allowedCounts[allowedCounts.length - 1] : ALLOWED_IMAGE_COUNTS[0];
  }, [entitlements]);
  const allowColorMode = useMemoValue(
    () => entitlementBool(entitlements, 'manga.allow_color_mode', false),
    [entitlements],
  );
  const selectableImageCounts = useMemoValue(
    () => ALLOWED_IMAGE_COUNTS.filter((count) => count <= maxImagesPerChapter),
    [maxImagesPerChapter],
  );
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
    const requestId = ++chapterLoadRequestRef.current;
    setImages([]);
    // Don't downgrade phase if there's an ongoing generation for this new chapter;
    // the derived `generating` flag below will reflect it via genStore.
    setPhase('idle');
    setProgress({ current: 0, total: DEFAULT_IMAGE_COUNT });
    setStatusMsg('');
    setErrorMsg('');
    setLightboxIdx(-1);
    onWorkspacePreviewModeChange?.(false);
    setLightboxZoom(1.35);
    setRefPreviewImage(null);
    setRefPreviewZoom(1.35);
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
    setRefModalOpen(false);
    setColorModeState('bw');
    setImageCountState(DEFAULT_IMAGE_COUNT);
    setShowColorMenu(false);
    setIgnorePersistedImages(false);
    setImageLoadStates({});
    setImageLoadSrcs({});
    setRefLoadStates({});
    setRefLoadSrcs({});
    imagePreloadAttemptsRef.current = {};
    refPreloadAttemptsRef.current = {};
    // Load existing scenes and characters if available
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
    }
  }, [chapter?.id]);

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
          const resolvedSrc = mangaImageUrl(img.image_path, tryIndex);
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
        preload.src = mangaImageUrl(img.image_path, tryIndex);
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
      alert('请先在左侧进行对话或手动编写正文');
      return;
    }
    setScenesFromSelectionFlag(false);
    setPhase('generating-scenes');
    setErrorMsg('');
    const controller = new AbortController();
    sceneAbortRef.current = controller;
    const requestId = chapterLoadRequestRef.current;
    const hadScenes = scenes.length > 0;
    try {
      const result = await generateScenes(chapter.id, controller.signal);
      if (chapterLoadRequestRef.current !== requestId) return;
      setScenes(result.scenes);
      setSanitizedSceneIdxs(result.sanitized_indices ?? []);
      setFailedSceneIdx(-1);
      setPhase('editing-scenes');
    } catch (err: any) {
      if (chapterLoadRequestRef.current !== requestId) return;
      if (err.name === 'AbortError') {
        setPhase(hadScenes ? 'editing-scenes' : 'idle');
      } else {
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
      const result = await regenerateImage(chapter.id, imageNumber, prompt);
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
    if (!img) return;
    setImageEditTarget({
      kind: 'manga',
      title: `第 ${imageNumber} 格漫画重绘`,
      imageSrc: imageLoadSrcs[img.image_path] || mangaImageUrl(img.image_path),
      prompt: scenes[imageNumber - 1] || img.prompt || '',
      imageNumber,
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
        const result = await regenerateImage(chapter.id, imageEditTarget.imageNumber, payload.prompt, payload);
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
  }, [chapter, imageEditTarget, scenes, existingImages]);

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

  // 鈹€鈹€ Color mode selection 鈹€鈹€
  const handleSelectColorMode = async (mode: ColorMode) => {
    if (!chapter) return;
    if (mode === 'color' && !allowColorMode) {
      setShowColorMenu(false);
      setColorModeState('bw');
      setErrorMsg('当前套餐不支持彩色漫画');
      return;
    }
    setShowColorMenu(false);
    await setColorMode(chapter.id, mode);
    setColorModeState(mode);
  };

  useEffect(() => {
    if (imageCount > maxImagesPerChapter) {
      setImageCountState(maxImagesPerChapter);
    }
  }, [imageCount, maxImagesPerChapter]);

  useEffect(() => {
    if (colorMode === 'color' && !allowColorMode) {
      setColorModeState('bw');
      setShowColorMenu(false);
    }
  }, [allowColorMode, colorMode]);

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

  // 鈹€鈹€ Image generation 鈹€鈹€

  const startMangaGeneration = async (mode: 'continue' | 'restart' = 'continue') => {
    if (!chapter) return;
    if (genStore.get(chapter.id)?.active) return;

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
    let seedImages = mergeImages(existingImages, images);

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

    const controller = generateMangaStream(targetId, (event: MangaProgress) => {
      switch (event.type) {
        case 'status':
          genStore.patch(targetId, { statusMsg: event.data.message });
          break;
        case 'progress':
          genStore.patch(targetId, {
            current: event.data.current,
            total: event.data.total,
            statusMsg: `正在生成第 ${event.data.current}/${event.data.total} 张漫画`,
          });
          break;
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
    });
    mangaAbortRef.current.set(targetId, controller);
  };

  const handleGenerateImages = () => startMangaGeneration('continue');

  const handleRestartManga = () => startMangaGeneration('restart');

  const handleAbortManga = () => {
    if (!chapter) return;
    const targetId = chapter.id;
    const state = genStore.get(targetId);
    mangaAbortRef.current.get(targetId)?.abort();
    mangaAbortRef.current.delete(targetId);
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

  const scrollToSceneDetail = useCallback((sceneIdx: number) => {
    const target = sceneDetailRefs.current[sceneIdx];
    if (!target) return;
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  const generating = isLiveGenerating || phase === 'generating-images';
  const lightboxImageClass = isWorkspacePreviewMode
    ? (lightboxZoom === 1
      ? 'max-w-[94%] max-h-none'
      : lightboxZoom === 1.35
        ? 'max-w-none w-[1120px]'
        : 'max-w-none w-[1420px]')
    : (lightboxZoom === 1
      ? 'max-w-[92vw] max-h-[82vh]'
      : lightboxZoom === 1.35
        ? 'max-w-[110vw] max-h-[96vh]'
        : 'max-w-[128vw] max-h-[118vh]');

  // Tick every 1s while generating so the stall indicator re-renders.
  const [, setNowTick] = useState(0);
  useEffect(() => {
    if (!generating) return;
    const id = window.setInterval(() => setNowTick((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, [generating]);

  const stallSeconds = isLiveGenerating && liveGen
    ? Math.max(0, Math.floor((Date.now() - liveGen.lastEventAt) / 1000))
    : 0;
  const isStalled = isLiveGenerating && stallSeconds >= 30;

  const liveProgress = isLiveGenerating
    ? { current: liveGen!.current, total: liveGen!.total }
    : progress;
  const liveStatusMsg = isLiveGenerating ? liveGen!.statusMsg : statusMsg;
  const liveErrorMsg = liveGen?.errorMsg || errorMsg;
  const hasImages = displayImages.length > 0;
  const canChangeImageCount = !generating && scenes.length === 0 && !hasImages;
  const activeImageCount = liveProgress.total || imageCount;
  const completedImageCount = displayImages.length;
  const hasPartialImages = completedImageCount > 0 && completedImageCount < imageCount;
  const canContinueGeneration = !generating && phase === 'editing-scenes' && scenes.length > 0;
  const canRestartGeneration = canContinueGeneration && hasImages;
  const activeSceneIdx = scenes.length > 0
    ? Math.min(
      Math.max((liveProgress.current || Math.min(completedImageCount + 1, scenes.length)) - 1, 0),
      scenes.length - 1,
    )
    : -1;

  return (
    <div className="flex flex-col h-full bg-[#fcfcfa]">
      {/* Header */}
      <div className="px-3 md:px-5 py-3 border-b border-[#d9dfd7] flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-800 tracking-wide uppercase shrink-0 hidden md:block">
          第 {chapter?.chapter_number ?? '-'} 话 · 漫画
        </h2>
        <div className="flex items-center gap-1.5 md:gap-2 flex-wrap justify-end">
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
              onClick={() => setRefModalOpen(true)}
              disabled={!chapter}
              className={`flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-md transition-colors
                ${refImages.length > 0
                  ? 'bg-emerald-900/50 hover:bg-emerald-800 text-emerald-300 border border-emerald-700'
                  : 'bg-[#f3f5f0] hover:bg-[#e8ece6] text-slate-700'
                } disabled:opacity-40`}
              title={
                refImages.length > 0
                  ? refSource === 'story'
                    ? `全局垫图 ${refImages.length} 张，点击查看/管理`
                    : `已设置 ${refImages.length} 张垫图，点击查看/管理`
                  : '点击上传垫图参考'
              }
            >
              <ImagePlus size={13} />
              {refImages.length > 0
                ? refSource === 'story'
                  ? `全局垫图 ${refImages.length}`
                  : `已垫图 ${refImages.length}`
                : '垫图'}
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
                    await setImageCount(chapter.id, count);
                  } catch (err: any) {
                    setImageCountState(previous);
                    setErrorMsg(`保存生成张数失败: ${err.message}`);
                  }
                }
              }}
              disabled={!canChangeImageCount}
              className="px-2 py-1.5 text-xs font-medium rounded-md bg-[#f3f5f0] text-slate-700 border border-[#d9dfd7] outline-none focus:border-[#1f5f58] transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
              title={canChangeImageCount ? '生成张数' : '已有分镜或图片时不能修改生成张数'}
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
          {canContinueGeneration && (
            <>
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
                    {allowColorMode && (
                      <button
                        onClick={() => handleSelectColorMode('color')}
                        className={`w-full flex items-center gap-2 px-3 py-2.5 text-xs transition-colors hover:bg-[#f3f5f0]
                          ${colorMode === 'color' ? 'text-amber-400 font-semibold' : 'text-slate-700'}`}
                      >
                        <span className="w-4 h-4 rounded border-2 border-gray-500 bg-gradient-to-br from-pink-400 via-blue-400 to-green-400 shrink-0" />
                        彩色漫画
                        {colorMode === 'color' && <Check size={12} className="ml-auto text-amber-400" />}
                      </button>
                    )}
                  </div>
                )}
              </div>
              {/* Generate button */}
              <button
                onClick={handleGenerateImages}
                className="flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium rounded-md
                           bg-amber-500 hover:bg-amber-400 text-slate-900 transition-colors"
              >
                <Sparkles size={13} />
                {hasPartialImages ? '继续生成漫画' : '生成漫画'}
              </button>
              {canRestartGeneration && (
                <button
                  onClick={handleRestartManga}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md
                             bg-[#f3f5f0] hover:bg-[#e8ece6] text-slate-800 border border-[#d9dfd7] transition-colors"
                  title="清空已生成图片，从第 1 张重新开始"
                >
                  <RefreshCw size={13} />
                  重新生成全部
                </button>
              )}
            </>
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

      {/* Error banner */}
      {liveErrorMsg && (
        <div className="mx-5 mt-3 px-4 py-3 rounded-lg bg-red-900/30 border border-red-800 text-red-300 text-sm flex items-start gap-2">
          <span className="shrink-0 mt-0.5">⚠</span>
          <div className="flex-1 min-w-0">
            <div className="font-medium mb-0.5">生成出错</div>
            <div className="text-xs text-red-400">{liveErrorMsg}</div>
            {phase === 'editing-scenes' && scenes.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  onClick={handleGenerateImages}
                  className="px-3 py-1.5 rounded-md bg-amber-500 hover:bg-amber-400 text-slate-900 text-xs font-medium transition-colors"
                >
                  {hasPartialImages ? '继续生成剩余图片' : '再试一次'}
                </button>
                {hasImages && (
                  <button
                    onClick={handleRestartManga}
                    className="px-3 py-1.5 rounded-md bg-[#f3f5f0] hover:bg-[#e8ece6] text-slate-800 text-xs font-medium border border-[#d9dfd7] transition-colors"
                  >
                    重新生成全部
                  </button>
                )}
              </div>
            )}
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
          <div className="mb-4 rounded-lg border border-[#d9dfd7] bg-white overflow-hidden">
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
                              <button
                                type="button"
                                onClick={() => setExpandedAppearanceCards((prev) => ({ ...prev, [cardKey]: !expanded }))}
                                className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-white transition-colors"
                              >
                                <div className="min-w-0">
                                  <h4 className="truncate text-sm font-semibold text-slate-900">{card.name}</h4>
                                  <div className="text-[10px] text-slate-500">角色卡 {idx + 1}</div>
                                </div>
                                {expanded ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
                              </button>
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
                                        onClick={() => handleGenerateCharacterRefImage(card.name, !!refImage)}
                                        disabled={!!charRefGeneratingKey}
                                        className="flex items-center gap-1 text-xs text-amber-400 hover:text-amber-300 disabled:opacity-40 transition-colors"
                                      >
                                        {generatingRef ? <Loader2 size={11} className="animate-spin" /> : <ImageIcon size={11} />}
                                        {generatingRef ? '生成中...' : refImage ? '重生成参考图' : '生成参考图'}
                                      </button>
                                      {refImage && (
                                        <button
                                          onClick={() => setRefModalOpen(true)}
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
          <div className="mb-6">
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
                      <p className="flex-1 text-xs text-slate-600 leading-relaxed line-clamp-2 hover:line-clamp-none cursor-default">
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
        )}

        {scenes.length > 0 && (
          <div className="mb-6 rounded-xl border border-[#d7e3f4] bg-[rgba(255,255,255,0.9)] overflow-hidden shadow-[0_12px_30px_rgba(59,130,246,0.08)]">
            <div className="flex items-center justify-between px-3 py-2 border-b border-[#d9dfd7]">
              <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide">
                分镜总览
              </h3>
              <span className={`text-[10px] ${generating ? 'text-blue-600' : 'text-slate-500'}`}>
                {generating ? '生成中也可查看全部分镜' : '全部分镜始终可见'}
              </span>
            </div>
            <div className="p-3">
              <div className="flex flex-wrap gap-2">
              {scenes.map((_scene, idx) => {
                const isCurrent = idx === activeSceneIdx;
                const isDone = idx < completedImageCount;
                const isSanitized = sanitizedSceneIdxs.includes(idx);
                return (
                  <button
                    key={`generating-scene-${idx}`}
                    type="button"
                    onClick={() => scrollToSceneDetail(idx)}
                    className={`min-w-[82px] flex-[0_0_auto] rounded-xl border px-2.5 py-2 text-left transition-colors ${
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
                        <div className="text-[11px] font-medium text-slate-800">
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
            <span className="text-sm">对话后点击上方按钮生成分镜</span>
          </div>
        )}

        {/* Images gallery with inline scene editor */}
        <div className="space-y-6">
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
                className="group scroll-mt-4"
                ref={(node) => {
                  sceneDetailRefs.current[sceneIdx] = node;
                }}
              >
                {img && imgReady ? (
                <div
                  className="relative rounded-xl overflow-hidden border border-[#d9dfd7] bg-white cursor-pointer
                             hover:border-[#d9dfd7] transition-colors"
                  onClick={() => openMangaRedraw(image_number)}
                >
                  <img
                    src={resolvedImgSrc}
                    alt={`Panel ${image_number}`}
                    className={`w-full object-contain ${isRegenerating ? 'opacity-30' : ''}`}
                    loading="eager"
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
                <div className="relative rounded-xl overflow-hidden border border-dashed border-[#d9dfd7] bg-[#f7f8f5] h-64 flex items-center justify-center">
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
                        <p className="flex-1 text-xs text-slate-500 leading-relaxed line-clamp-2 group-hover:line-clamp-none">
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
              <span className="text-xs text-white/60">缩放</span>
              {[1, 1.35, 1.7].map((zoom) => (
                <button
                  key={zoom}
                  type="button"
                  onClick={() => setLightboxZoom(zoom as 1 | 1.35 | 1.7)}
                  className={`rounded-full px-3 py-1.5 text-xs transition-colors ${
                    lightboxZoom === zoom ? 'bg-white text-slate-900' : 'bg-white/10 text-white hover:bg-white/20'
                  }`}
                >
                  {Math.round(zoom * 100)}%
                </button>
              ))}
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

            <div className="flex-1 h-full overflow-auto rounded-[24px] bg-black/20 px-4 py-5">
              <img
                src={imageLoadSrcs[lightboxImg!.image_path] || mangaImageUrl(lightboxImg!.image_path)}
                alt={`Panel ${lightboxImg!.image_number}`}
                className={`mx-auto h-auto object-contain rounded-xl shadow-2xl ${lightboxImageClass}`}
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

      {/* Reference images management modal */}
      {refModalOpen && (
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
                <h3 className="text-sm font-semibold text-slate-800">垫图管理</h3>
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
                上传角色参考图，AI 生成漫画时会保持人物外貌一致性。
                {refSource === 'story' && refImages.length > 0 && (
                  <> 当前显示首页设置的全局垫图；上传新图将创建本话专属垫图覆盖全局。</>
                )}
              </p>
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

      {refPreviewImage && (
        <RefPreviewModal
          target={refPreviewImage}
          zoom={refPreviewZoom}
          busy={refUploading}
          imageSrc={refLoadSrcs[refPreviewImage.image.image_path] || refImageSrc(refPreviewImage.image.image_path)}
          ready={refLoadStates[refPreviewImage.image.image_path] === 'ready'}
          onZoomChange={setRefPreviewZoom}
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
        />
      )}

      {imageEditTarget && (
        <ImageRedrawModal
          target={imageEditTarget}
          busy={refUploading || regenIdx === (imageEditTarget.kind === 'manga' ? imageEditTarget.imageNumber : -999)}
          onClose={() => setImageEditTarget(null)}
          onSubmit={handleApplyImageRedraw}
        />
      )}
    </div>
  );
}

function ImageRedrawModal({
  target,
  busy,
  onClose,
  onSubmit,
}: {
  target: ImageEditTarget;
  busy: boolean;
  onClose: () => void;
  onSubmit: (payload: { prompt: string; mode: ImageRedrawMode; mask?: string }) => Promise<void>;
}) {
  const [mode, setMode] = useState<ImageRedrawMode>('full');
  const [prompt, setPrompt] = useState(target.prompt);
  const [brushSize, setBrushSize] = useState(36);
  const [drawing, setDrawing] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const drawingRef = useRef(false);
  const lastPointRef = useRef<{ x: number; y: number } | null>(null);
  const [canvasReady, setCanvasReady] = useState(false);

  useEffect(() => {
    setPrompt(target.prompt);
    setMode('full');
    setImageLoaded(false);
    setCanvasReady(false);
  }, [target]);

  const syncCanvasSize = useCallback(() => {
    const img = imageRef.current;
    const canvas = canvasRef.current;
    if (!img || !canvas) return;
    const rect = img.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) return;
    canvas.width = Math.round(rect.width);
    canvas.height = Math.round(rect.height);
    canvas.style.width = `${Math.round(rect.width)}px`;
    canvas.style.height = `${Math.round(rect.height)}px`;
    setCanvasReady(true);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(syncCanvasSize, 50);
    window.addEventListener('resize', syncCanvasSize);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener('resize', syncCanvasSize);
    };
  }, [syncCanvasSize]);

  useEffect(() => {
    if (mode !== 'partial') return;
    const timer = window.setTimeout(syncCanvasSize, 30);
    return () => window.clearTimeout(timer);
  }, [mode, target.imageSrc, syncCanvasSize]);

  const drawAt = useCallback((x: number, y: number) => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;
    ctx.fillStyle = 'rgba(239, 68, 68, 0.45)';
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.beginPath();
    ctx.arc(x, y, brushSize / 2, 0, Math.PI * 2);
    ctx.fill();
  }, [brushSize]);

  const drawSegment = useCallback((from: { x: number; y: number }, to: { x: number; y: number }) => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;
    ctx.strokeStyle = 'rgba(239, 68, 68, 0.45)';
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.lineWidth = brushSize;
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x, to.y);
    ctx.stroke();
  }, [brushSize]);

  const getCanvasPoint = (event: any) => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  };

  const stopDrawing = useCallback(() => {
    drawingRef.current = false;
    lastPointRef.current = null;
    setDrawing(false);
  }, []);

  const handlePointerDown = useCallback((event: React.PointerEvent<HTMLCanvasElement>) => {
    event.preventDefault();
    const point = getCanvasPoint(event);
    if (!point) return;
    drawingRef.current = true;
    lastPointRef.current = point;
    setDrawing(true);
    event.currentTarget.setPointerCapture(event.pointerId);
    drawAt(point.x, point.y);
  }, [drawAt]);

  const handlePointerMove = useCallback((event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawingRef.current) return;
    event.preventDefault();
    const point = getCanvasPoint(event);
    if (!point) return;
    if (lastPointRef.current) {
      drawSegment(lastPointRef.current, point);
    } else {
      drawAt(point.x, point.y);
    }
    lastPointRef.current = point;
  }, [drawAt, drawSegment]);

  const handlePointerUp = useCallback((event: React.PointerEvent<HTMLCanvasElement>) => {
    event.preventDefault();
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    stopDrawing();
  }, [stopDrawing]);

  const exportMask = useCallback(() => {
    const overlay = canvasRef.current;
    const img = imageRef.current;
    if (!overlay || !img || !canvasReady) return '';
    const raw = overlay.getContext('2d')?.getImageData(0, 0, overlay.width, overlay.height);
    if (!raw) return '';
    let hasPaint = false;
    for (let i = 3; i < raw.data.length; i += 4) {
      if (raw.data[i] > 10) {
        hasPaint = true;
        break;
      }
    }
    if (!hasPaint) return '';

    const maskCanvas = document.createElement('canvas');
    maskCanvas.width = overlay.width;
    maskCanvas.height = overlay.height;
    const maskCtx = maskCanvas.getContext('2d');
    if (!maskCtx) return '';
    maskCtx.fillStyle = 'rgba(255,255,255,1)';
    maskCtx.fillRect(0, 0, maskCanvas.width, maskCanvas.height);
    const maskData = maskCtx.getImageData(0, 0, maskCanvas.width, maskCanvas.height);
    for (let i = 0; i < raw.data.length; i += 4) {
      const alpha = raw.data[i + 3];
      maskData.data[i] = 255;
      maskData.data[i + 1] = 255;
      maskData.data[i + 2] = 255;
      maskData.data[i + 3] = alpha > 10 ? 0 : 255;
    }
    maskCtx.putImageData(maskData, 0, 0);

    if (img.naturalWidth && img.naturalHeight && (img.naturalWidth !== overlay.width || img.naturalHeight !== overlay.height)) {
      const scaledCanvas = document.createElement('canvas');
      scaledCanvas.width = img.naturalWidth;
      scaledCanvas.height = img.naturalHeight;
      const scaledCtx = scaledCanvas.getContext('2d');
      if (!scaledCtx) return maskCanvas.toDataURL('image/png');
      scaledCtx.drawImage(maskCanvas, 0, 0, scaledCanvas.width, scaledCanvas.height);
      return scaledCanvas.toDataURL('image/png');
    }
    return maskCanvas.toDataURL('image/png');
  }, [canvasReady]);

  const modal = (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-[rgba(15,23,42,0.62)] p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className="flex h-[88vh] w-[min(1400px,94vw)] flex-col overflow-hidden rounded-[30px] border border-[#d7e3f4] bg-white shadow-[0_30px_90px_rgba(15,23,42,0.28)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[#e5edf8] px-6 py-4">
          <div>
            <div className="text-lg font-semibold text-slate-900">{target.title}</div>
            <div className="mt-1 text-sm text-slate-500">左侧查看和涂抹图片，右侧填写重绘说明并提交。</div>
          </div>
          <button onClick={onClose} className="rounded-full bg-slate-100 p-2 text-slate-600 transition hover:bg-slate-200">
            <X size={18} />
          </button>
        </div>
        <div className="grid flex-1 gap-0 overflow-hidden lg:grid-cols-[minmax(0,1.5fr)_420px]">
          <div className="overflow-auto bg-[linear-gradient(180deg,_#0f172a_0%,_#111827_100%)] p-6">
            <div className="mb-4 flex items-center justify-between text-white/80">
              <div className="text-sm font-medium">选中图片</div>
              <div className="text-xs">{mode === 'partial' ? '在左图直接涂抹需要修改的区域' : '整图将按右侧说明整体重绘'}</div>
            </div>
            <div className="mx-auto flex min-h-[62vh] w-full items-center justify-center rounded-[24px] border border-white/10 bg-black/20 p-4">
              <div className="relative inline-block">
                <img
                  ref={imageRef}
                  src={target.imageSrc}
                  alt={target.title}
                  onLoad={() => {
                    setImageLoaded(true);
                    syncCanvasSize();
                  }}
                  draggable={false}
                  className={`block max-h-[72vh] max-w-full rounded-2xl object-contain shadow-2xl ${imageLoaded ? 'opacity-100' : 'opacity-0'}`}
                />
                {!imageLoaded && (
                  <div className="absolute inset-0 flex min-h-[420px] min-w-[320px] items-center justify-center rounded-2xl bg-[linear-gradient(180deg,_#08111d_0%,_#111827_100%)] text-white/70">
                    <Loader2 size={24} className="animate-spin" />
                  </div>
                )}
                {mode === 'partial' && (
                  <canvas
                    ref={canvasRef}
                    className={`absolute inset-0 h-full w-full rounded-2xl touch-none ${drawing ? 'cursor-grabbing' : 'cursor-crosshair'}`}
                    onPointerDown={handlePointerDown}
                    onPointerMove={handlePointerMove}
                    onPointerUp={handlePointerUp}
                    onPointerCancel={stopDrawing}
                    onLostPointerCapture={stopDrawing}
                  />
                )}
              </div>
            </div>
          </div>
          <div className="overflow-auto border-l border-[#e5edf8] bg-[#f8fbff] p-6">
            <div className="space-y-5">
              <div>
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">重绘方式</div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setMode('full')}
                    className={`rounded-2xl px-3 py-2 text-sm transition ${mode === 'full' ? 'bg-[#1d4ed8] text-white' : 'bg-white text-slate-700 border border-[#d7e3f4]'}`}
                  >
                    整图重绘
                  </button>
                  <button
                    type="button"
                    onClick={() => setMode('partial')}
                    className={`rounded-2xl px-3 py-2 text-sm transition ${mode === 'partial' ? 'bg-[#1d4ed8] text-white' : 'bg-white text-slate-700 border border-[#d7e3f4]'}`}
                  >
                    局部重绘
                  </button>
                </div>
              </div>

              {mode === 'partial' && (
                <div className="rounded-2xl border border-[#d7e3f4] bg-white p-4">
                  <div className="text-sm font-medium text-slate-800">局部涂抹区域</div>
                  <div className="mt-1 text-xs leading-5 text-slate-500">在左侧图片上直接涂抹需要修改的区域，未涂抹部分会尽量保持不变。</div>
                  <div className="mt-3">
                    <div className="mb-1 flex items-center justify-between text-xs text-slate-500">
                      <span>画笔大小</span>
                      <span>{brushSize}px</span>
                    </div>
                    <input type="range" min={12} max={120} value={brushSize} onChange={(e) => setBrushSize(Number(e.target.value))} className="w-full" />
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      const canvas = canvasRef.current;
                      const ctx = canvas?.getContext('2d');
                      if (canvas && ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
                    }}
                    className="mt-3 rounded-xl border border-[#d7e3f4] bg-[#f8fbff] px-3 py-2 text-xs text-slate-700"
                  >
                    清空涂抹
                  </button>
                </div>
              )}

              <div>
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">修改提示</div>
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  rows={12}
                  className="w-full rounded-2xl border border-[#d7e3f4] bg-white px-3 py-3 text-sm text-slate-900 outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe]"
                  placeholder="描述你想调整的局部或整图效果，例如：保留人物五官不变，把衣服改成黑色风衣，并增强光影层次。"
                />
              </div>

              <div className="flex gap-3">
                <button
                  type="button"
                  disabled={busy}
                  onClick={async () => {
                    const payload: { prompt: string; mode: ImageRedrawMode; mask?: string } = { prompt: prompt.trim(), mode };
                    if (mode === 'partial') {
                      const mask = exportMask();
                      if (!mask) {
                        alert('请先在左侧图片上涂抹需要修改的区域。');
                        return;
                      }
                      payload.mask = mask;
                    }
                    await onSubmit(payload);
                  }}
                  className="rounded-2xl bg-[#1d4ed8] px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
                >
                  {busy ? '处理中...' : '开始重绘'}
                </button>
                <button
                  type="button"
                  onClick={onClose}
                  className="rounded-2xl border border-[#d7e3f4] bg-white px-4 py-2 text-sm font-medium text-slate-700"
                >
                  取消
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(modal, document.body);
}

function RefPreviewModal({
  target,
  imageSrc,
  ready,
  busy,
  zoom,
  onZoomChange,
  onClose,
  onStartRedraw,
}: {
  target: RefPreviewTarget;
  imageSrc: string;
  ready: boolean;
  busy: boolean;
  zoom: 1 | 1.35 | 1.7;
  onZoomChange: (zoom: 1 | 1.35 | 1.7) => void;
  onClose: () => void;
  onStartRedraw: () => void;
}) {
  const previewImageClass = zoom === 1
    ? 'max-w-[92%] max-h-none'
    : zoom === 1.35
      ? 'max-w-none w-[780px]'
      : 'max-w-none w-[940px]';

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
          <div className="overflow-auto bg-[linear-gradient(180deg,_#0f172a_0%,_#111827_100%)] p-6">
            <div className="mb-4 flex items-center justify-between text-white/80">
              <div className="text-sm font-medium">角色参考图</div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-white/60">缩放</span>
                {[1, 1.35, 1.7].map((value) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => onZoomChange(value as 1 | 1.35 | 1.7)}
                    className={`rounded-full px-3 py-1.5 text-xs transition-colors ${
                      zoom === value ? 'bg-white text-slate-900' : 'bg-white/10 text-white hover:bg-white/20'
                    }`}
                  >
                    {Math.round(value * 100)}%
                  </button>
                ))}
              </div>
            </div>
            <div className="mx-auto flex min-h-[62vh] w-full items-center justify-center rounded-[24px] border border-white/10 bg-black/20 p-4">
              <div className="rounded-[24px] bg-[#0b1220] p-4 shadow-2xl">
                {ready ? (
                  <img
                    src={imageSrc}
                    alt={target.image.filename}
                    className={`mx-auto h-auto object-contain rounded-xl shadow-2xl ${previewImageClass}`}
                  />
                ) : (
                  <div className="flex min-h-[420px] min-w-[320px] items-center justify-center rounded-xl bg-[linear-gradient(180deg,_#08111d_0%,_#111827_100%)] text-white/70">
                    <Loader2 size={24} className="animate-spin" />
                  </div>
                )}
              </div>
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
                    onClick={onClose}
                    className="rounded-2xl border border-[#d7e3f4] bg-white px-4 py-2 text-sm font-medium text-slate-700"
                  >
                    关闭
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(modal, document.body);
}


