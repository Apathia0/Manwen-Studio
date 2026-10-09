import { PUBLIC_CANVAS_NODE_TYPES as CANVAS_NODE_TYPES, projectLegacyGraph } from './video-canvas/canvasGraph';
import ContainerNodeView, { type ContainerNodeConfig } from './video-canvas/ContainerNodeView';
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react';
import { Bot, Boxes, History, Maximize2, MoreHorizontal, RefreshCw, Check, ChevronLeft, ChevronRight, FileText, Loader2, Pencil, Plus, Save, SplitSquareHorizontal, Trash2, Upload, X } from 'lucide-react';
import {
  applyVideoCanvasPlan,
  cancelVideoCanvasRun,
  confirmVideoCanvasPlan,
  confirmVideoCanvasRun,
  createVideoCanvas,
  deleteVideoCanvas,
  cancelCanvasPipeline,
  getCanvasPipeline,
  startCanvasPipeline,
  type CanvasPipelineTask,
  estimateVideoCanvasCost,
  getCanvasNodeResults,
  getVideoCanvas,
  getVideoCanvasRun,

  compileScenes,
  generateDirectorPlan,
  analyzeCanvasAssets,
  screenplaySplit,
  listVideoCanvasPlans,
  listVideoCanvasNodeCatalog,
  listVideoCanvases,
  runVideoCanvas,
  syncVideoCanvasPlanWorkflow,
  saveVideoCanvasSnapshot,
  updateVideoCanvas,
  validateVideoCanvas,
  getAiModels,
  createVideoAsset,
  createStoryVideoAsset,
  replaceVideoAsset,
  toPublicVideoAssetUrl,
  type ChapterVideoWorkflow,
  type AiModelItem,
  type VideoAsset,
  type VideoCanvas,
  type CanvasCostEstimate,
  type CanvasNodeCandidate,
  type VideoCanvasGraph,
  type VideoCanvasNodeCatalogItem,
  type VideoCanvasPlan,
  type VideoCanvasRun,
  type VideoStylePreset,
  type DirectorPlan,
  type CompiledSceneUnit,
  type CanvasSceneAsset,
  type AssetCandidate,
  type CanvasPermissionMode,
} from '../api';
import { confirm } from '../lib/confirm';
import { useIsDesktop } from '../lib/useMediaQuery';
import { normalizeErrorMessage } from '../lib/errors';
import { toast } from '../lib/toast';
import CanvasVersionHistoryModal from './video-canvas/CanvasVersionHistoryModal';
import {
  useCanvasInteractions,
  canConnectPorts,
  screenPoint,
  type CanvasSceneEdge,
  type CanvasSceneNode,
  type CanvasTool,
  type CanvasViewport,
  type ContextMenuState,
} from './video-canvas/useCanvasInteractions';
import CanvasSurface from './video-canvas/CanvasSurface';
import { nodeSize } from './video-canvas/useCanvasInteractions';
import CanvasConnectionLayer from './video-canvas/CanvasConnectionLayer';
import CanvasNodeView from './video-canvas/CanvasNodeView';
import CanvasMiniMap from './video-canvas/CanvasMiniMap';
import CanvasContextMenu from './video-canvas/CanvasContextMenu';
import CanvasCreateMenu from './video-canvas/CanvasCreateMenu';
import CanvasNodePropertyPanel from './video-canvas/CanvasNodePropertyPanel';
import CanvasBottomToolbar from './video-canvas/CanvasBottomToolbar';
import ChapterImportDialog from './video-canvas/ChapterImportDialog';
import CanvasPipelineBar from './video-canvas/CanvasPipelineBar';
import CanvasReviewPanel from './video-canvas/CanvasReviewPanel';
import NodeGenerateCost from './video-canvas/NodeGenerateCost';
import type { GhostEdge } from './video-canvas/CanvasConnectionLayer';
import CanvasEmptyGuide, { type ShotDurationMode } from './video-canvas/CanvasEmptyGuide';
import NodeCandidates from './video-canvas/NodeCandidates';
import CanvasAssetPanel from './video-canvas/CanvasAssetPanel';
import CanvasPlanCapsule from './video-canvas/CanvasPlanCapsule';
import MediaLightbox from './video-canvas/MediaLightbox';
import { pickMediaWidth, type MediaWidth } from '../lib/mediaVariant';
import { useProgressiveImage } from '../lib/useProgressiveImage';
import BatchStartDialog, { type BatchStartInfo } from './video-canvas/BatchStartDialog';
import StyleControl from './video-canvas/StyleControl';
import { anyFollowsCanvasStyle, inconsistentNodeIds, presetToCanvasStyle, styleKeyOfConfig, readCanvasStyle, referenceToCanvasStyle, sameStyle, type CanvasStyle } from './video-canvas/canvasStyle';
import { buildReferenceEdges, collectAssets, summarizeAssets, type AssetKind } from './video-canvas/assetLibrary';
import { nextAssetSlot } from './video-canvas/assetLayout';
import { computeAutoLayout } from './video-canvas/autoLayout';
import { collectProduction, generationAncestors, planBatchWaves, type BatchEdge, type BatchNode } from './video-canvas/batchPlan';
import type { BatchProgress } from './video-canvas/CanvasAssetPanel';
import { computePipeline, continuePrompt, formatCostLine } from './video-canvas/canvasPipeline';
import SceneListNodeView from './video-canvas/SceneListNodeView';
import { layoutDirectorUnits, unitNodeId } from './video-canvas/directorLayout';
import { syncCanvasMediaReferences, collectConnectedReferencePreviews, collectReferenceCandidates } from './video-canvas/canvasReferenceSync';
import {
  computeGroupBounds,
  expandGroupMove,
  getContainerMemberIds,
  orderNodesForRender,
  refitContainerBounds,
  remapContainerMembership,
  stripContainerMembership,
} from './video-canvas/containerGroup';
import { clampOverlayPosition, computeFocusViewport } from './video-canvas/overlayPlacement';
import { supportsNodeInspector } from './video-canvas/inspectorGate';
import { mergeCanvasGraphs } from './video-canvas/canvasMerge';
import { canvasDraftKey, isNewerCanvasDraft, readCanvasDraft, writeCanvasDraft, removeCanvasDraft } from './video-canvas/canvasDraftStore';
import AssetReferenceSelector from './AssetReferenceSelector';
import StyleSelectorModal from './StyleSelectorModal';

const AgentPanel = lazy(() => import('./AgentPanel/AgentPanel'));

interface Props {
  storyId: number;
  chapterId?: number;
  workflow?: ChapterVideoWorkflow | null;
  assets?: VideoAsset[];
  stylePresets?: VideoStylePreset[];
  onDirtyChange?: (dirty: boolean) => void;
  onAssetsChanged?: () => void;
  onOpenAssetManagement?: () => void;
}

type ViewportTransform = { x: number; y: number; k: number };
type CanvasNodeData = { label?: string; config?: Record<string, unknown>; origin?: Record<string, unknown>; nodeType?: string; ui?: { width?: number; height?: number }; [key: string]: unknown };
type CanvasNode = { id: string; type: string; position: { x: number; y: number }; data: CanvasNodeData };
type CanvasEdge = { id: string; source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null; data?: Record<string, unknown> };
const SCREENPLAY_SPLIT_MAX_UNITS = 30;
const NODE_WIDTH = 300;
const CANVAS_CATALOG: VideoCanvasNodeCatalogItem[] = [
  { type: 'text', label: '文本', category: '内容', icon: 'text', inputs: [{ key: 'content', type: 'text', required: false }], outputs: [{ key: 'text', type: 'text' }] },
  { type: 'screenplay', label: '剧本', category: '创作', icon: 'file-text', inputs: [{ key: 'source', type: 'text', required: false }], outputs: [{ key: 'screenplay', type: 'screenplay' }] },
  { type: 'scene', label: '场景', category: '创作', icon: 'clapperboard', inputs: [{ key: 'screenplay', type: 'screenplay', required: false }], outputs: [{ key: 'shot', type: 'shot' }] },
  { type: 'image', label: '图片', category: '媒体', icon: 'image', inputs: [{ key: 'prompt', type: 'text', required: true }, { key: 'references', type: 'image', multiple: true }], outputs: [{ key: 'image', type: 'image' }] },
  { type: 'video', label: '视频', category: '媒体', icon: 'video', inputs: [{ key: 'prompt', type: 'text', required: true }, { key: 'image', type: 'image', multiple: true }, { key: 'audio', type: 'audio', multiple: true }], outputs: [{ key: 'video', type: 'video' }] },
  { type: 'audio', label: '音频', category: '媒体', icon: 'music', inputs: [], outputs: [{ key: 'audio', type: 'audio' }] },
  { type: 'concat', label: '合片', category: '后处理', icon: 'combine', inputs: [{ key: 'videos', type: 'video', multiple: true, required: true }], outputs: [{ key: 'video', type: 'video' }] },
  { type: 'container', label: '节点组', category: '管理', icon: 'folder', inputs: [{ key: 'items', type: 'any', multiple: true }], outputs: [{ key: 'assets', type: 'any', multiple: true }], executable: false },
];



function toCanvasNodes(graph: VideoCanvasGraph): CanvasNode[] {
  return graph.nodes.map((node) => ({
    id: node.id,
    type: node.type,
    position: node.position || { x: 0, y: 0 },
    data: { ...node.data, nodeType: node.type },
  }));
}

/** 开场卡片设置的画布级设置（画幅、固定15秒）：同步记在引用里，不依赖 React 状态的更新时序；所有外发的图都叠加它们。 */
function withGuideSettings(graph: VideoCanvasGraph, settings: Record<string, string>): VideoCanvasGraph {
  if (Object.keys(settings).length === 0) return graph;
  const metadata = (graph.metadata || {}) as Record<string, unknown>;
  const production = { ...((metadata.production_settings || {}) as Record<string, unknown>), ...settings };
  return { ...graph, metadata: { ...metadata, production_settings: production } } as VideoCanvasGraph;
}

function toGraph(nodes: CanvasNode[], edges: CanvasEdge[], base: VideoCanvasGraph): VideoCanvasGraph {
  return {
    ...base,
    schema_version: base.schema_version,
    nodes: nodes.map((node) => ({ id: node.id, type: node.type, position: node.position, data: { ...node.data, label: node.data.label, config: node.data.config || {}, origin: node.data.origin } })),
    edges: edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target, sourceHandle: edge.sourceHandle, targetHandle: edge.targetHandle, data: edge.data })),
    groups: base.groups || [],
    metadata: base.metadata || {},
  } as VideoCanvasGraph;
}

/**
 * 将画布运行结果回显到节点：把 run 中已成功节点的 output_snapshot
 * 按 node_id 合并进画布节点 data.result（供节点视图渲染生成结果图/视频）。
 * 未匹配到任何输出时原样返回，避免无谓的 state 更新。
 */
/**
 * 提交运行；若因定义版本号落后被拒绝（保存、助手或后台编排在两次提交之间改过画布），取最新版本号重试一次。
 * 批量生成会连续提交多波，期间版本号随时可能前进，不能一直拿第一次的版本号。
 */
async function submitRunWithFreshRevision(canvasId: number, payload: Parameters<typeof runVideoCanvas>[1]) {
  try {
    return await runVideoCanvas(canvasId, payload);
  } catch (error) {
    if (!normalizeErrorMessage(error, '').includes('画布定义已更新')) throw error;
    const latest = await getVideoCanvas(canvasId);
    return runVideoCanvas(canvasId, { ...payload, expected_definition_revision: latest.definition_revision });
  }
}

function mergeRunOutputs(run: VideoCanvasRun | null, currentNodes: CanvasNode[], edges: CanvasEdge[] = [], assets: VideoAsset[] = []): CanvasNode[] {
  if (!run) return currentNodes;
  const outputByNodeId = new Map<string, Record<string, unknown>>();
  const styleKeyByNodeId = new Map<string, string>();
  for (const runNode of run.nodes) {
    if (runNode.status === 'succeeded' && runNode.output_snapshot && typeof runNode.output_snapshot === 'object') {
      outputByNodeId.set(runNode.node_id, runNode.output_snapshot as Record<string, unknown>);
      // 运行时注入了画布画风的配置就存在输入快照里：记下这张图生成时用的画风，供"一键统一画风"比对。
      styleKeyByNodeId.set(runNode.node_id, styleKeyOfConfig((runNode.input_snapshot as { config?: Record<string, unknown> } | null | undefined)?.config));
    }
  }
  const withOutputs = currentNodes.map((node) => {
    const output = outputByNodeId.get(node.id);
    return output ? { ...node, data: { ...node.data, result: output, result_style_key: styleKeyByNodeId.get(node.id) ?? '' } } : node;
  });
  return syncCanvasMediaReferences(withOutputs, edges, assets) as CanvasNode[];
}

/** 按画布隔离结果缓存，避免不同画布的同名节点串用媒体。 */
const nodeResultUrlCache = new Map<string, { url: string; isVideo: boolean }>();
function rememberResultUrl(canvasId: number, nodeId: string, url: string, isVideo: boolean) {
  nodeResultUrlCache.set(`${canvasId}:${nodeId}`, { url, isVideo });
  if (nodeResultUrlCache.size > 400) {
    const firstKey = nodeResultUrlCache.keys().next().value;
    if (firstKey !== undefined) nodeResultUrlCache.delete(firstKey);
  }
}

function NodeResultPreview({ url, isVideo, interactive = true, displayWidth = NODE_WIDTH, onExpand, onNaturalSize }: { url: string; isVideo: boolean; /** 视频播放控件是否可操作；节点未选中时关闭，让按下的手势交给节点（可直接拖动 / 选中） */ interactive?: boolean; /** 节点在屏幕上的显示宽度（CSS 像素），用来挑选缩略图档位；只升不降，避免缩放时反复换图 */ displayWidth?: number; onExpand?: () => void; onNaturalSize?: (width: number, height: number) => void }) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [near, setNear] = useState(false);
  const wantedWidth = pickMediaWidth(displayWidth);
  const [bucket, setBucket] = useState<MediaWidth>(wantedWidth);
  const effectiveWidth = wantedWidth > bucket ? wantedWidth : bucket;
  useEffect(() => { if (wantedWidth > bucket) setBucket(wantedWidth); }, [wantedWidth, bucket]);

  // 视口外的节点不发请求：靠近视口（预留 800px）才开始加载，加载后保持不卸载
  useEffect(() => {
    const element = rootRef.current;
    if (isVideo || near) return undefined;
    if (!element || typeof IntersectionObserver === 'undefined') { setNear(true); return undefined; }
    const observer = new IntersectionObserver((entries) => { if (entries.some((entry) => entry.isIntersecting)) { setNear(true); observer.disconnect(); } }, { rootMargin: '800px' });
    observer.observe(element);
    return () => observer.disconnect();
  }, [isVideo, near]);

  // 节点展示用缩略图（后端按需生成 WebP）；放大查看再加载原图。缩略图保持原图宽高比，节点适配比例不受影响
  const image = useProgressiveImage(isVideo ? null : url, effectiveWidth, near);
  const naturalSizeRef = useRef(onNaturalSize);
  useEffect(() => { naturalSizeRef.current = onNaturalSize; });
  const naturalWidth = image.naturalSize?.width;
  const naturalHeight = image.naturalSize?.height;
  useEffect(() => { if (naturalWidth && naturalHeight) naturalSizeRef.current?.(naturalWidth, naturalHeight); }, [naturalWidth, naturalHeight]);

  const expandButton = onExpand && (
    <button type="button" title="放大查看" aria-label="放大查看" onPointerDown={(event) => event.stopPropagation()} onDoubleClick={(event) => event.stopPropagation()} onClick={(event) => { event.stopPropagation(); onExpand(); }}
      className="absolute right-1.5 top-1.5 z-10 grid h-6 w-6 place-items-center rounded-md bg-black/55 text-white/80 opacity-70 hover:bg-black/75 hover:opacity-100"><Maximize2 className="h-3.5 w-3.5" /></button>
  );
  if (isVideo) return <>
    <video src={url} draggable={false} className={`h-full w-full bg-black object-contain ${interactive ? '' : 'pointer-events-none'}`} controls disablePictureInPicture disableRemotePlayback preload="metadata" onLoadedMetadata={(event) => onNaturalSize?.(event.currentTarget.videoWidth, event.currentTarget.videoHeight)} />
    {expandButton}
  </>;
  return <div ref={rootRef} className="absolute inset-0">
    {image.src
      ? <img src={image.src} alt="生成结果" draggable={false} onDoubleClick={(event) => { event.stopPropagation(); onExpand?.(); }} className="h-full w-full bg-[#15171a] object-contain" />
      : image.failed
        ? <button type="button" onPointerDown={(event) => event.stopPropagation()} onClick={(event) => { event.stopPropagation(); image.retry(); }} className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 bg-[#23262b] text-[11px] text-[#9aa4af] hover:text-white"><RefreshCw className="h-4 w-4" /><span>图片加载失败，点击重试</span></button>
        : <div className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 bg-gradient-to-br from-[#2a2e33] via-[#3a4048] to-[#2a2e33] text-[11px] text-[#8b95a1] animate-pulse"><Loader2 className="h-5 w-5 animate-spin" /><span>图片加载中</span></div>}
    {expandButton}
  </div>;
}

function createNode(item: VideoCanvasNodeCatalogItem, position: { x: number; y: number }): CanvasNode {
  return {
    id: `${item.type}-${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`,
    type: item.type,
    position,
    data: { label: item.label, config: {}, nodeType: item.type },
  };
}





export default function VideoCanvasPanel({ storyId, chapterId, workflow: _workflow, assets = [], stylePresets = [], onDirtyChange, onAssetsChanged, onOpenAssetManagement }: Props) {
  const [catalog, setCatalog] = useState<VideoCanvasNodeCatalogItem[]>([]);
  const [splittingNodeId, setSplittingNodeId] = useState<string | null>(null);
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  /** 开场引导里点“导入小说章节”时选定的助手工作方式：导入完成后据此自动开启编排 */
  const importModeRef = useRef<CanvasPermissionMode | null>(null);
  const [compilingNodeId, setCompilingNodeId] = useState<string | null>(null);
  const [planBusyNodeId, setPlanBusyNodeId] = useState<string | null>(null);
  const [directorError, setDirectorError] = useState<string | null>(null);
  const [assetAnalysisNodeId, setAssetAnalysisNodeId] = useState<string | null>(null);
  const [models, setModels] = useState<AiModelItem[]>([]);
  const [canvas, setCanvas] = useState<VideoCanvas | null>(null);
  /** 始终指向最新的画布状态：保存要用最新的版本号，不能用闭包里捕获的旧值 */
  const latestCanvasRef = useRef<VideoCanvas | null>(null);
  const guideSettingsRef = useRef<Record<string, string>>({});
  useEffect(() => { latestCanvasRef.current = canvas; }, [canvas]);
  const guideCanvasIdRef = useRef<number | null>(null);
  useEffect(() => {
    if (canvas && guideCanvasIdRef.current !== canvas.id) { guideCanvasIdRef.current = canvas.id; guideSettingsRef.current = {}; }
  }, [canvas]);
  const [canvasList, setCanvasList] = useState<VideoCanvas[]>([]);
  const [nodes, setNodes] = useState<CanvasNode[]>([]);
  const [edges, setEdges] = useState<CanvasEdge[]>([]);
  const [viewport, setViewport] = useState<ViewportTransform>({ x: 260, y: 120, k: 1 });
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
  // 发送给助手时取最新选中的节点（回调不应随选中变化重建）。
  const selectedNodeIdsRef = useRef<string[]>([]);
  useEffect(() => {
    selectedNodeIdsRef.current = selectedNodeIds;
  }, [selectedNodeIds]);
  const [versionHistoryOpen, setVersionHistoryOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploadingNodeAsset, setUploadingNodeAsset] = useState(false);
  const [uploadingNodeId, setUploadingNodeId] = useState<string | null>(null);
  const [nodeUploadAccept, setNodeUploadAccept] = useState('image/*');
  const [running, setRunning] = useState(false);
  const [submittingNodeId, setSubmittingNodeId] = useState<string | null>(null);
  const [latestRun, setLatestRun] = useState<VideoCanvasRun | null>(null);
  // 同时在跑的所有运行：每次点生成都是一次独立运行，不能只跟踪最新一次，否则先提交的节点会丢失加载状态和结果回显。
  const [ghostEdges, setGhostEdges] = useState<GhostEdge[]>([]);
  // 手动刷新画布：转圈状态，以及让节点结果、质检重新拉取的计数
  const [refreshingCanvas, setRefreshingCanvas] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const [trackedRuns, setTrackedRuns] = useState<VideoCanvasRun[]>([]);
  const isDesktop = useIsDesktop();
  // 进入画布默认展开助手（桌面端侧栏）；手机端助手是全屏浮层，默认收起以免挡住画布
  const [agentOpen, setAgentOpen] = useState(isDesktop);
  const [plans, setPlans] = useState<VideoCanvasPlan[]>([]);
  const [plansLoading, setPlansLoading] = useState(false);
  const [applyingPlanId, setApplyingPlanId] = useState<number | null>(null);
  const [editingCanvasName, setEditingCanvasName] = useState(false);
  const [canvasNameDraft, setCanvasNameDraft] = useState('');
  const [renamingCanvas, setRenamingCanvas] = useState(false);
  const [assetSelectorNodeId, setAssetSelectorNodeId] = useState<string | null>(null);
  const [styleSelectorNodeId, setStyleSelectorNodeId] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [canvasSize, setCanvasSize] = useState({ width: 0, height: 0 });
  const [tool, setTool] = useState<CanvasTool>('select');
  const [miniMapOpen, setMiniMapOpen] = useState(false);
  const [nodeMenu, setNodeMenu] = useState<{ x: number; y: number; nodeId: string } | null>(null);
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const nodeUploadInputRef = useRef<HTMLInputElement | null>(null);
  const focusRestoreRef = useRef<ViewportTransform | null>(null);
  const focusAnimationRef = useRef<number | null>(null);
  const pointerGestureRef = useRef({ down: false, moved: false, x: 0, y: 0 });
  /** 正在按住某个节点（可能要拖动）：此期间不弹出节点输入框，松手后再出现，避免一按下面板就弹出来挡住拖动。 */
  const [inspectorHeld, setInspectorHeld] = useState(false);
  const uploadTargetNodeRef = useRef<string | null>(null);
  const uploadModeRef = useRef<'node' | 'reference' | 'style_reference'>('node');
  const uploadMediaKindRef = useRef<'image' | 'video' | 'audio'>('image');
  const viewportRef = useRef(viewport);
  const initialCreateKeyRef = useRef(crypto.randomUUID());
  const loadRequestRef = useRef(0);
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  const historyRef = useRef<Array<{ nodes: CanvasNode[]; edges: CanvasEdge[]; viewport: ViewportTransform }>>([]);
  const redoRef = useRef<Array<{ nodes: CanvasNode[]; edges: CanvasEdge[]; viewport: ViewportTransform }>>([]);
  const [historyFlags, setHistoryFlags] = useState({ canUndo: false, canRedo: false });
  const changeVersionRef = useRef(0);
  // 仅统计节点/连线内容编辑（不含视口平移），用于判断 Agent 运行期间用户是否改过画布内容。
  const contentEditRef = useRef(0);
  // 已保存（或已与服务端一致）时的内容编辑计数：和当前计数不同就说明本地有未保存的节点/连线修改。
  const savedEditRef = useRef(0);
  const canvasRevisionRef = useRef(0);
  const [agentStreaming, setAgentStreaming] = useState(false);
  const [assetPanelOpen, setAssetPanelOpen] = useState(false);
  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  const [canvasStyleModalOpen, setCanvasStyleModalOpen] = useState(false);
  const [batchDialog, setBatchDialog] = useState<{ info: BatchStartInfo; resolve: (accepted: boolean) => void } | null>(null);
  const pendingStyleReferenceRef = useRef<CanvasStyle | null>(null);
  const [nodePreview, setNodePreview] = useState<{ url: string; isVideo: boolean; title: string } | null>(null);
  const [batch, setBatch] = useState<BatchProgress | null>(null);
  const [pipelineTask, setPipelineTask] = useState<CanvasPipelineTask | null>(null);
  const pipelineActive = Boolean(pipelineTask && ['pending', 'running', 'retrying', 'cancel_requested'].includes(pipelineTask.status));
  const [batchStatuses, setBatchStatuses] = useState<Map<string, string>>(new Map());
  const batchCancelRef = useRef(false);
  const batchRunIdsRef = useRef<Set<number>>(new Set());
  const [costEstimate, setCostEstimate] = useState<CanvasCostEstimate | null>(null);
  const [externalPrompt, setExternalPrompt] = useState<{ id: number; text: string; mode?: CanvasPermissionMode } | null>(null);
  const canvasEpochRef = useRef(0);
  const plansRequestRef = useRef(0);
  const currentCanvasIdRef = useRef<number | null>(null);
  const savingRef = useRef(false);
  const dirtyRef = useRef(dirty);
  const moveCaptureRef = useRef(false);
  const dragOriginsRef = useRef<Map<string, { x: number; y: number }> | null>(null);
  const clientRevisionRef = useRef(0);
  // 刷新页面后 clientRevision 会从 0 重新计数；幂等键带上本次页面会话标识，避免命中上次会话的旧保存结果（返回过期版本号）。
  const saveSessionRef = useRef(crypto.randomUUID().slice(0, 8));
  const draftTimerRef = useRef<number | undefined>(undefined);
  const canvasSelectionKey = `storycanvas.video-canvas.${storyId}.${chapterId ?? 'story'}`;
  useEffect(() => { viewportRef.current = viewport; }, [viewport]);
  useEffect(() => { nodesRef.current = nodes; }, [nodes]);
  useEffect(() => { dirtyRef.current = dirty; }, [dirty]);
  useEffect(() => { edgesRef.current = edges; }, [edges]);
  // Reference snapshots are derived from the complete current graph. Reconcile
  // after every graph mutation so deleting/replacing an upstream edge cannot
  // leave stale references in the target config.
  useEffect(() => {
    const synchronized = syncCanvasMediaReferences(nodes, edges, assets) as CanvasNode[];
    if (synchronized.some((node, index) => node !== nodes[index])) setNodes(synchronized);
  }, [assets, edges, nodes]);
  const persistLocalDraft = useCallback(() => {
    if (!canvas) return;
    const graph = toGraph(nodesRef.current, edgesRef.current, canvas.version.graph);
    const layout = { nodes: Object.fromEntries(nodesRef.current.map((node) => [node.id, node.position])), viewport: { x: viewportRef.current.x, y: viewportRef.current.y, zoom: viewportRef.current.k } };
    writeCanvasDraft(canvasDraftKey(storyId, chapterId, canvas.id), {
      version: 1,
      storyId,
      chapterId,
      canvasId: canvas.id,
      baseDefinitionRevision: canvas.definition_revision,
      baseLayoutRevision: canvas.layout_revision,
      clientRevision: clientRevisionRef.current,
      graph,
      layout,
      updatedAt: Date.now(),
    });
  }, [canvas, chapterId, storyId]);
  const scheduleLocalDraft = useCallback(() => {
    clientRevisionRef.current += 1;
    window.clearTimeout(draftTimerRef.current);
    draftTimerRef.current = window.setTimeout(persistLocalDraft, 300);
  }, [persistLocalDraft]);
  useEffect(() => () => { window.clearTimeout(draftTimerRef.current); }, []);
  useEffect(() => {
    const element = surfaceRef.current;
    if (!element) return;
    let timer: number | undefined;
    const measure = () => { window.clearTimeout(timer); timer = window.setTimeout(() => { const rect = element.getBoundingClientRect(); setCanvasSize({ width: rect.width, height: rect.height }); }, 80); };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => { window.clearTimeout(timer); observer.disconnect(); };
  }, [loading]);

  // 素材列表会在上传风格图、资产分析等操作后整体换新引用；hydrateCanvas / applyServerCanvas 只通过 ref 读取最新值，
  // 绝不能把 assets 放进它们的依赖——否则 load 随之换引用，整张画布被重新加载（弹窗和未提交的状态一并丢失）。
  const assetsRef = useRef(assets);
  useEffect(() => { assetsRef.current = assets; });
  const hydrateCanvas = useCallback((nextCanvas: VideoCanvas) => {
    savedEditRef.current = contentEditRef.current;
    canvasEpochRef.current += 1;
    currentCanvasIdRef.current = nextCanvas.id;
    changeVersionRef.current = 0;
    historyRef.current = [];
    redoRef.current = [];
    setHistoryFlags({ canUndo: false, canRedo: false });
    setCanvas(nextCanvas);
    setPlans([]);
    setPlansLoading(false);
    setApplyingPlanId(null);
    setNodeMenu(null);
    setAssetSelectorNodeId(null);
    setStyleSelectorNodeId(null);
    const draft = readCanvasDraft(canvasDraftKey(storyId, chapterId, nextCanvas.id));
    const useDraft = draft ? isNewerCanvasDraft(draft, nextCanvas) : false;
    const sourceGraph = useDraft ? draft!.graph : nextCanvas.version.graph;
    const layoutNodes = useDraft ? draft!.layout.nodes : (nextCanvas.layout.nodes || {});
    const projectedGraph = projectLegacyGraph(sourceGraph);
    clientRevisionRef.current = useDraft ? draft!.clientRevision : 0;
    if (useDraft) { setDirty(true); contentEditRef.current += 1; } // 恢复的本地草稿比服务端新，算未保存内容
    // 合并所有 run 的输出（旧→新），切换/刷新后每个节点的历史结果都能恢复显示
    const projectedEdges = projectedGraph.edges as CanvasEdge[];
    let hydratedNodes = toCanvasNodes(projectedGraph).map((node) => ({ ...node, position: layoutNodes[node.id] || node.position }));
    for (const run of [...(nextCanvas.runs || [])].reverse()) {
      hydratedNodes = mergeRunOutputs(run, hydratedNodes, projectedEdges, assetsRef.current);
    }
    setNodes(hydratedNodes);    setEdges(projectedEdges);
    setLatestRun(nextCanvas.runs?.[0] || null);
    setTrackedRuns([...(nextCanvas.runs || [])].sort((a, b) => a.id - b.id).slice(-30));
    const savedViewport = useDraft ? draft!.layout.viewport : nextCanvas.layout.viewport;
    setViewport({ x: savedViewport?.x ?? 260, y: savedViewport?.y ?? 120, k: savedViewport?.zoom ?? 1 });
    setSelectedNodeId(null);
    setSelectedNodeIds([]);
  }, []);

  const load = useCallback(async () => {
    const requestId = ++loadRequestRef.current;
    setLoading(true);
    try {
      const [catalogResult, imageModels, videoModels] = await Promise.all([listVideoCanvasNodeCatalog(), getAiModels('image'), getAiModels('video')]);
      if (loadRequestRef.current !== requestId) return;
      // 端口协议以服务端为准，避免历史画布在前端被额外拒绝。
      const publicCatalog = catalogResult.node_types.filter(item => CANVAS_NODE_TYPES.has(item.type));
      setCatalog(publicCatalog.length ? publicCatalog : CANVAS_CATALOG);
      setModels([...imageModels.models, ...videoModels.models]);
      const canvases = await listVideoCanvases(storyId, chapterId);
      if (loadRequestRef.current !== requestId) return;
      setCanvasList(canvases.canvases);
      const rememberedId = Number(window.localStorage.getItem(canvasSelectionKey) || 0);
      let initialCanvas = canvases.canvases.find((item) => item.id === rememberedId);
      if (!initialCanvas) {
        initialCanvas = await createVideoCanvas({ story_id: storyId, default_chapter_id: chapterId ?? null, name: chapterId ? '章节视频画布' : '视频创作画布', idempotency_key: initialCreateKeyRef.current });
        if (loadRequestRef.current !== requestId) return;
        setCanvasList((current) => [initialCanvas!, ...current.filter((item) => item.id !== initialCanvas!.id)]);
      }
      window.localStorage.setItem(canvasSelectionKey, String(initialCanvas.id));
      hydrateCanvas(initialCanvas);
      setSelectedNodeId(null);
      setSelectedNodeIds([]);
    } catch (error) {
      if (loadRequestRef.current === requestId) toast.error(normalizeErrorMessage(error, '加载视频画布失败'));
    } finally {
      if (loadRequestRef.current === requestId) setLoading(false);
    }
  }, [canvasSelectionKey, chapterId, hydrateCanvas, storyId]);

  useEffect(() => { void load(); return () => { loadRequestRef.current += 1; canvasEpochRef.current += 1; }; }, [load]);
  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);
  // 进行中的运行都要轮询。依赖只取画布 ID 和"进行中运行 ID 列表"：画布对象 / 运行对象每次保存或刷新都会换新引用，
  // 若依赖它们，定时器会被反复重置，期间生成完成的结果就迟迟不回显到节点上。
  const trackRuns = useCallback((runs: VideoCanvasRun[]) => {
    setTrackedRuns((current) => {
      const byId = new Map(current.map((run) => [run.id, run]));
      runs.forEach((run) => byId.set(run.id, run));
      return [...byId.values()].sort((a, b) => a.id - b.id).slice(-30);
    });
  }, []);
  // 提交 / 确认 / 取消之后接手这次运行：既是最新一次，也加入跟踪列表。
  const adoptRun = useCallback((run: VideoCanvasRun) => { setLatestRun(run); trackRuns([run]); }, [trackRuns]);
  const pollCanvasId = canvas?.id ?? null;
  const activeRunKey = trackedRuns.filter((run) => ['queued', 'running', 'cancel_requested'].includes(run.status)).map((run) => run.id).join(',');
  useEffect(() => {
    if (pollCanvasId === null || !activeRunKey) return undefined;
    const runIds = activeRunKey.split(',').map(Number);
    let active = true;
    const pending = new Set<number>();
    const epoch = canvasEpochRef.current;
    const timer = window.setInterval(() => {
      runIds.forEach((runId) => {
        if (pending.has(runId)) return;
        pending.add(runId);
        void getVideoCanvasRun(pollCanvasId, runId).then((result) => {
          if (!active || canvasEpochRef.current !== epoch) return;
          trackRuns([result.run]);
          setLatestRun((current) => (current && current.id === result.run.id ? result.run : current));
          setNodes((current) => mergeRunOutputs(result.run, current, edgesRef.current, assetsRef.current));
        }).catch(() => undefined).finally(() => { pending.delete(runId); });
      });
    }, 1500);
    return () => { active = false; window.clearInterval(timer); };
  }, [pollCanvasId, activeRunKey, trackRuns]);

  // 补全节点的生成结果回显：画布只带最近 20 次运行，且未保存的本地草稿里没有结果。
  // 按节点汇总全部历史运行里最近一次成功的产出，只补没有结果的节点（不改动画布内容，不算未保存修改）。
  useEffect(() => {
    if (pollCanvasId === null) return undefined;
    let alive = true;
    const epoch = canvasEpochRef.current;
    void getCanvasNodeResults(pollCanvasId).then(({ results }) => {
      if (!alive || canvasEpochRef.current !== epoch) return;
      setNodes((current) => current.map((node) => {
        const found = results[node.id];
        const existing = (node.data.result as { url?: string } | undefined)?.url;
        if (!found || existing || !['image', 'video', 'concat'].includes(node.type)) return node;
        return { ...node, data: { ...node.data, result: found } };
      }));
    }).catch(() => undefined);
    return () => { alive = false; };
  }, [pollCanvasId, refreshTick]);

  const selectedNode = useMemo(() => nodes.find((node) => node.id === selectedNodeId) || null, [nodes, selectedNodeId]);

  const canDiscardChanges = useCallback(async () => {
    if (savingRef.current) { toast.info('画布正在保存，请稍后切换'); return false; }
    return !dirtyRef.current || confirm({ title: '未保存的画布修改', message: '切换工作区将放弃当前未保存的节点、连线和配置修改。', confirmText: '放弃修改', danger: true });
  }, []);
  const markDirty = useCallback(() => { changeVersionRef.current += 1; contentEditRef.current += 1; setDirty(true); scheduleLocalDraft(); }, [scheduleLocalDraft]);
  // 组框几何始终由成员推导：增删/移动/粘贴/自动整理后由内到外重算（幂等）。
  useEffect(() => {
    if (!nodes.some((node) => node.type === 'container')) return;
    const result = refitContainerBounds(nodes, edges);
    if (result.changed) setNodes(result.nodes);
    if (result.pruned) markDirty();
  }, [nodes, edges, markDirty]);
  const updateViewport = useCallback((next: ViewportTransform) => { changeVersionRef.current += 1; setViewport(next); setDirty(true); }, []);
  const captureHistory = useCallback(() => {
    historyRef.current = [...historyRef.current.slice(-49), { nodes: nodesRef.current, edges: edgesRef.current, viewport: viewportRef.current }];
    redoRef.current = [];
    setHistoryFlags({ canUndo: true, canRedo: false });
  }, []);
  const undo = useCallback(() => {
    const previous = historyRef.current.pop();
    if (!previous) return;
    changeVersionRef.current += 1;
    contentEditRef.current += 1;
    redoRef.current.push({ nodes: nodesRef.current, edges: edgesRef.current, viewport: viewportRef.current });
    setNodes(previous.nodes); setEdges(previous.edges); setViewport(previous.viewport); setDirty(true);
    setHistoryFlags({ canUndo: historyRef.current.length > 0, canRedo: true });
  }, []);
  const redo = useCallback(() => {
    const next = redoRef.current.pop();
    if (!next) return;
    changeVersionRef.current += 1;
    contentEditRef.current += 1;
    historyRef.current.push({ nodes: nodesRef.current, edges: edgesRef.current, viewport: viewportRef.current });
    setNodes(next.nodes); setEdges(next.edges); setViewport(next.viewport); setDirty(true);
    setHistoryFlags({ canUndo: true, canRedo: redoRef.current.length > 0 });
  }, []);

  const addCatalogNode = useCallback((item: VideoCanvasNodeCatalogItem, position?: { x: number; y: number }) => {
    const rect = surfaceRef.current?.getBoundingClientRect();
    const view = viewportRef.current;
    const base = position || (rect ? { x: (rect.width / 2 - view.x) / view.k - NODE_WIDTH / 2, y: (rect.height / 2 - view.y) / view.k - 90 } : { x: 300, y: 200 });
    // 连续从节点库添加时自动寻找空位，避免后添加节点完全覆盖源节点端口。
    const nodeWidth = ['image_generation', 'storyboard', 'video_generation', 'video_asset', 'asset'].includes(item.type) ? 420 : 300;
    const nodeHeight = ['image_generation', 'storyboard', 'video_generation', 'video_asset', 'asset'].includes(item.type) ? 236 : 174;
    const occupied = nodes.map((node) => ({ x: node.position.x, y: node.position.y, width: Number(node.data.ui?.width) || (['image_generation', 'storyboard', 'video_generation', 'video_asset', 'asset'].includes(node.type) ? 420 : 300), height: Number(node.data.ui?.height) || (['image_generation', 'storyboard', 'video_generation', 'video_asset', 'asset'].includes(node.type) ? 236 : 174) }));
    const overlaps = (candidate: { x: number; y: number }) => occupied.some((itemRect) => candidate.x < itemRect.x + itemRect.width + 32 && candidate.x + nodeWidth + 32 > itemRect.x && candidate.y < itemRect.y + itemRect.height + 32 && candidate.y + nodeHeight + 32 > itemRect.y);
    const candidates = position ? [base] : [base, ...Array.from({ length: 24 }, (_, index) => {
      const ring = Math.floor(index / 8) + 1;
      const slot = index % 8;
      const offsets = [[ring, 0], [0, ring], [-ring, 0], [0, -ring], [ring, ring], [-ring, ring], [ring, -ring], [-ring, -ring]][slot];
      return { x: base.x + offsets[0] * 380, y: base.y + offsets[1] * 270 };
    })];
    const center = candidates.find((candidate) => !overlaps(candidate)) || base;
    const node = createNode(item, center);
    setNodes((current) => [...current, node]);
    setSelectedNodeId(node.id);
    setSelectedNodeIds([node.id]);
    markDirty();
  }, [markDirty, nodes]);

  const updateNode = useCallback((nodeId: string, patch: Partial<CanvasNodeData>) => {
    setNodes((current) => current.map((node) => node.id === nodeId ? { ...node, data: { ...node.data, ...patch } } : node));
    markDirty();
  }, [markDirty]);
  const updateNodeConfig = useCallback((nodeId: string, key: string, value: unknown) => {
    setNodes((current) => current.map((node) => node.id === nodeId ? { ...node, data: { ...node.data, config: { ...node.data.config, [key]: value } } } : node));
    markDirty();
  }, [markDirty]);
  const selectAsset = useCallback((nodeId: string, assetId: number | null) => {
    const asset = assets.find((item) => item.id === assetId);
    const node = nodes.find((item) => item.id === nodeId);
    if (!node) return;
    const isAssetNode = node.type === 'asset' || node.type === 'video_asset';
    const config = node.data.config || {};
    const next = asset ? { ...config, ...(isAssetNode ? { asset_id: asset.id, asset_revision: asset.revision, asset_type: asset.asset_type } : { reference_asset_ids: [asset.id], reference_asset_revisions: [{ asset_id: asset.id, revision: asset.revision }] }) } : (isAssetNode ? { ...config, asset_id: null, asset_revision: null } : { ...config, reference_asset_ids: [], reference_asset_revisions: [] });
    updateNode(nodeId, { config: next });
  }, [assets, nodes, updateNode]);
  const selectAssets = useCallback((nodeId: string, assetIds: number[]) => {
    const node = nodes.find((item) => item.id === nodeId);
    if (!node) return;
    const config = node.data.config || {};
    const selected = assetIds.map((id) => assets.find((asset) => asset.id === id)).filter((asset): asset is VideoAsset => Boolean(asset));
    if (node.type === 'asset' || node.type === 'video_asset') {
      const asset = selected[0];
      updateNode(nodeId, { config: asset ? { ...config, asset_id: asset.id, asset_revision: asset.revision, asset_type: asset.asset_type } : { ...config, asset_id: null, asset_revision: null } });
      return;
    }
    updateNode(nodeId, { config: { ...config, reference_asset_ids: selected.map((asset) => asset.id), reference_asset_revisions: selected.map((asset) => ({ asset_id: asset.id, revision: asset.revision })) } });
  }, [assets, nodes, updateNode]);

  const handleNodeFileUpload = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    const nodeId = uploadTargetNodeRef.current;
    event.target.value = '';
    if (!file || !nodeId) return;
    const node = nodesRef.current.find((item) => item.id === nodeId);
    if (!node || (node.type !== 'image' && node.type !== 'video' && node.type !== 'audio')) return;
    const assetType = file.type.startsWith('image/') ? 'image' : file.type.startsWith('video/') ? 'video' : file.type.startsWith('audio/') ? 'audio' : null;
    const isNodeUpload = uploadModeRef.current === 'node';
    const isStyleReferenceUpload = uploadModeRef.current === 'style_reference';
    const isValidReference = assetType === 'image';
    if (!assetType || assetType !== uploadMediaKindRef.current || (isNodeUpload ? assetType !== node.type : !isValidReference)) {
      toast.error(isNodeUpload ? (node.type === 'video' ? '视频节点仅支持视频文件' : node.type === 'audio' ? '音频节点仅支持音频文件（mp3、wav、m4a、aac、ogg）' : '图片节点仅支持图片文件') : '画布生成节点参考素材仅支持图片文件');
      return;
    }
    setUploadingNodeAsset(true);
    setUploadingNodeId(nodeId);
    try {
      const created = chapterId
        ? await createVideoAsset(chapterId, {
          story_id: storyId,
          asset_type: assetType,
          name: file.name,
          file_path: '',
          provider: 'manual_upload',
        })
        : await createStoryVideoAsset(storyId, {
          asset_type: assetType,
          name: file.name,
          file_path: '',
          provider: 'manual_upload',
        });
      const replaced = await replaceVideoAsset(created.id, file);
      const filePath = replaced.asset.file_path;
      const mediaUrl = toPublicVideoAssetUrl(filePath) || '';
      const config = node.data.config || {};
      const previousStyleReferenceId = Number(config.style_reference_asset_id);
      const hasPreviousStyleReference = isStyleReferenceUpload && Number.isFinite(previousStyleReferenceId);
      const previousReferenceIds = Array.isArray(config.reference_asset_ids) ? config.reference_asset_ids.map(Number).filter(Number.isFinite) : [];
      const previousReferenceRevisions = Array.isArray(config.reference_asset_revisions) ? config.reference_asset_revisions : [];
      const previousReferencePreviews = Array.isArray(config.reference_previews) ? config.reference_previews.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')) : [];
      const retainedReferenceIds = hasPreviousStyleReference ? previousReferenceIds.filter((assetId) => assetId !== previousStyleReferenceId) : previousReferenceIds;
      const retainedReferenceRevisions = hasPreviousStyleReference ? previousReferenceRevisions.filter((item) => Number((item as Record<string, unknown>).asset_id) !== previousStyleReferenceId) : previousReferenceRevisions;
      const retainedReferencePreviews = hasPreviousStyleReference ? previousReferencePreviews.filter((item) => Number(item.asset_id) !== previousStyleReferenceId) : previousReferencePreviews;
      const nextConfig = isNodeUpload
        ? { ...config, asset_id: replaced.asset.id, asset_revision: replaced.asset.revision, asset_type: assetType, existing_url: mediaUrl, ...(assetType === 'audio' ? { file_name: file.name } : {}) }
        : {
          ...config,
          reference_asset_ids: [...retainedReferenceIds, replaced.asset.id],
          reference_asset_revisions: [...retainedReferenceRevisions, { asset_id: replaced.asset.id, revision: replaced.asset.revision }],
          reference_previews: [...retainedReferencePreviews, { asset_id: replaced.asset.id, url: mediaUrl, kind: assetType }],
          ...(isStyleReferenceUpload ? { style_reference_asset_id: replaced.asset.id, style_reference_url: mediaUrl } : {}),
        };
      captureHistory();
      updateNode(nodeId, isNodeUpload ? { config: nextConfig, result: { asset_id: replaced.asset.id, url: mediaUrl, file_path: filePath, reused: true } } : { config: nextConfig });
      if (isNodeUpload) {
        // 上传得到的结果同样要沿已有连线同步到下游参考配置（此前只在连线创建/运行合并时同步）。
        setNodes((current) => syncCanvasMediaReferences(current, edgesRef.current, assets) as CanvasNode[]);
      }
      setSelectedNodeIds([nodeId]);
      setSelectedNodeId(nodeId);
      onAssetsChanged?.();
      toast.success(isNodeUpload ? `${assetType === 'image' ? '图片' : assetType === 'audio' ? '音频' : '视频'}已上传到当前节点` : isStyleReferenceUpload ? '风格参考图已绑定到当前节点' : `${assetType === 'image' ? '图片' : assetType === 'video' ? '视频' : '音频'}已上传为参考素材`);
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '本地素材上传失败，请重试'));
    } finally {
      uploadTargetNodeRef.current = null;
      uploadModeRef.current = 'node';
      setUploadingNodeAsset(false);
      setUploadingNodeId(null);
    }
  }, [assets, captureHistory, chapterId, onAssetsChanged, storyId, updateNode]);
  const openNodeFileUpload = useCallback((nodeId: string, mediaKind: 'image' | 'video' | 'audio') => {
    const node = nodesRef.current.find((item) => item.id === nodeId);
    if (!node || (node.type !== 'image' && node.type !== 'video' && node.type !== 'audio') || (node.type === 'image' && mediaKind !== 'image') || (node.type === 'audio' && mediaKind !== 'audio')) return;
    uploadTargetNodeRef.current = nodeId;
    uploadModeRef.current = 'node';
    uploadMediaKindRef.current = mediaKind;
    setNodeUploadAccept(`${mediaKind}/*`);
    nodeUploadInputRef.current?.click();
  }, []);
  const openReferenceFileUpload = useCallback((nodeId: string, mediaKind: 'image') => {
    const node = nodesRef.current.find((item) => item.id === nodeId);
    if (!node || (node.type !== 'image' && node.type !== 'video') || (node.type === 'image' && mediaKind !== 'image')) return;
    uploadTargetNodeRef.current = nodeId;
    uploadModeRef.current = 'reference';
    uploadMediaKindRef.current = mediaKind;
    setNodeUploadAccept(`${mediaKind}/*`);
    nodeUploadInputRef.current?.click();
  }, []);
  const selectStyle = useCallback((nodeId: string, styleId: number | null) => {
    const style = stylePresets.find((item) => item.id === styleId);
    const node = nodes.find((item) => item.id === nodeId);
    if (!node) return;
    const config = node.data.config || {};
    const previousStyleId = Number(config.style_reference_asset_id);
    const referenceIds = Array.isArray(config.reference_asset_ids) ? config.reference_asset_ids.map(Number).filter(Number.isFinite) : [];
    const referenceRevisions = Array.isArray(config.reference_asset_revisions) ? config.reference_asset_revisions : [];
    const previews = Array.isArray(config.reference_previews) ? config.reference_previews.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')) : [];
    updateNode(nodeId, { config: style ? {
      ...config,
      style_preset_id: style.id,
      style_snapshot: { name: style.name, prompt_template: style.prompt_template || '', image_style_params: style.image_style_params || {}, video_style_params: style.video_style_params || {}, image_url: style.image_url || null },
      style_reference_asset_id: null,
      style_reference_url: null,
      reference_asset_ids: referenceIds.filter((id) => id !== previousStyleId),
      reference_asset_revisions: referenceRevisions.filter((item) => Number((item as Record<string, unknown>).asset_id) !== previousStyleId),
      reference_previews: previews.filter((item) => Number(item.asset_id) !== previousStyleId),
    } : { ...config, style_preset_id: null, style_snapshot: null } });
  }, [nodes, stylePresets, updateNode]);
  const uploadNodeStyleReference = useCallback(async (nodeId: string, file: File): Promise<string> => {
    const node = nodesRef.current.find((item) => item.id === nodeId);
    if (!node || (node.type !== 'image' && node.type !== 'video')) throw new Error('当前节点不支持风格参考图');
    setUploadingNodeAsset(true);
    setUploadingNodeId(nodeId);
    try {
      const created = chapterId
        ? await createVideoAsset(chapterId, {
          story_id: storyId,
          asset_type: 'style_reference',
          name: file.name,
          file_path: '',
          provider: 'manual_upload',
        })
        : await createStoryVideoAsset(storyId, {
          asset_type: 'style_reference',
          name: file.name,
          file_path: '',
          provider: 'manual_upload',
        });
      const replaced = await replaceVideoAsset(created.id, file);
      const url = toPublicVideoAssetUrl(replaced.asset.file_path) || '';
      const config = node.data.config || {};
      const previousStyleId = Number(config.style_reference_asset_id);
      const referenceIds = Array.isArray(config.reference_asset_ids) ? config.reference_asset_ids.map(Number).filter(Number.isFinite) : [];
      const referenceRevisions = Array.isArray(config.reference_asset_revisions) ? config.reference_asset_revisions : [];
      const previews = Array.isArray(config.reference_previews) ? config.reference_previews.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')) : [];
      captureHistory();
      updateNode(nodeId, {
        config: {
          ...config,
          style_preset_id: null,
          style_snapshot: null,
          style_reference_asset_id: replaced.asset.id,
          style_reference_url: url,
          reference_asset_ids: [...referenceIds.filter((id) => id !== previousStyleId), replaced.asset.id],
          reference_asset_revisions: [...referenceRevisions.filter((item) => Number((item as Record<string, unknown>).asset_id) !== previousStyleId), { asset_id: replaced.asset.id, revision: replaced.asset.revision }],
          reference_previews: [...previews.filter((item) => Number(item.asset_id) !== previousStyleId), { asset_id: replaced.asset.id, url, kind: 'image' }],
        },
      });
      onAssetsChanged?.();
      return url;
    } finally {
      setUploadingNodeAsset(false);
      setUploadingNodeId(null);
    }
  }, [captureHistory, chapterId, onAssetsChanged, storyId, updateNode]);
  const handleStyleModalFileUpload = useCallback((file: File) => {
    if (!styleSelectorNodeId) return Promise.reject(new Error('未选择风格节点'));
    return uploadNodeStyleReference(styleSelectorNodeId, file);
  }, [styleSelectorNodeId, uploadNodeStyleReference]);
  const handleStyleModalSelect = useCallback((styleName: string) => {
    if (!styleSelectorNodeId) return;
    const preset = stylePresets.find((item) => item.name === styleName);
    if (!preset) return;
    captureHistory();
    selectStyle(styleSelectorNodeId, preset.id);
  }, [captureHistory, selectStyle, stylePresets, styleSelectorNodeId]);

  const saveCanvas = async (showSuccess = true): Promise<VideoCanvas | null> => {
    // 取“最新”的画布做保存基准，而不是闭包里捕获的那一份：发送前保存会先等进行中的自动保存结束，
    // 再调用旧闭包里的 saveCanvas，旧闭包里的版本号已经落后一版，必然 409，整次“开始创作”就被取消了。
    const baseCanvas = latestCanvasRef.current ?? canvas;
    if (!baseCanvas || savingRef.current) return null;
    savingRef.current = true;
    const epoch = canvasEpochRef.current;
    const saveVersion = changeVersionRef.current;
    const saveEdit = contentEditRef.current;
    const graphNodes = nodesRef.current;
    const graphEdges = edgesRef.current;
    const saveViewport = viewportRef.current;
    setSaving(true);
    try {
      const layout = { nodes: Object.fromEntries(graphNodes.map((node) => [node.id, node.position])), viewport: { x: saveViewport.x, y: saveViewport.y, zoom: saveViewport.k } };
      const submit = (target: VideoCanvas) => saveVideoCanvasSnapshot(target.id, {
        graph: withGuideSettings(toGraph(graphNodes, graphEdges, target.version.graph), guideSettingsRef.current),
        layout,
        expected_definition_revision: target.definition_revision,
        expected_layout_revision: target.layout_revision,
        client_revision: clientRevisionRef.current,
        idempotency_key: `canvas-${target.id}-${saveSessionRef.current}-client-${clientRevisionRef.current}`,
      });
      let synchronized: VideoCanvas;
      let mergedFromServer = false;
      try {
        synchronized = await submit(baseCanvas);
      } catch (error) {
        if ((error as { status?: number }).status !== 409) throw error;
        // 版本冲突：服务端的图比本地新（后台编排 / 助手 / 其他窗口改过）。绝不能拿本地旧图覆盖——
        // 曾经因此把后台刚生成的整批资产冲掉。做三方合并：以上次同步的图为基准，分别合入本地和服务端各自的修改。
        const latest = await getVideoCanvas(baseCanvas.id);
        const localGraph = withGuideSettings(toGraph(graphNodes, graphEdges, baseCanvas.version.graph), guideSettingsRef.current);
        const { graph: mergedGraph, conflicts } = mergeCanvasGraphs(baseCanvas.version.graph, localGraph, latest.version.graph);
        synchronized = await saveVideoCanvasSnapshot(latest.id, {
          graph: mergedGraph,
          layout,
          expected_definition_revision: latest.definition_revision,
          expected_layout_revision: latest.layout_revision,
          client_revision: clientRevisionRef.current,
          idempotency_key: `canvas-${latest.id}-${saveSessionRef.current}-merge-${latest.definition_revision}-${clientRevisionRef.current}`,
        });
        mergedFromServer = true;
        if (conflicts.length) toast.info(`后台更新和你的修改有 ${conflicts.length} 处冲突，已以后台为准：${conflicts.slice(0, 3).join('、')}${conflicts.length > 3 ? '…' : ''}`);
      }
      latestCanvasRef.current = synchronized;
      if (mergedFromServer && canvasEpochRef.current === epoch && changeVersionRef.current === saveVersion) {
        // 合并后的图里带有后台的新内容：本地节点和连线也要换成合并结果，否则下一次保存又会冲突
        applyServerCanvas({ ...synchronized, layout: synchronized.layout || layout, runs: baseCanvas.runs || [] });
        savedEditRef.current = saveEdit;
        if (showSuccess) toast.success('画布已保存');
        return synchronized;
      }
      if (canvasEpochRef.current !== epoch) return null;
      setCanvas((current) => {
        if (!synchronized) return current;
        const next = { ...synchronized, layout: synchronized.layout || layout, runs: current?.runs || [] };
        if (changeVersionRef.current === saveVersion || !current) return next;
        // 保存进行期间用户又改了开场设置（画幅、固定15秒、画风）：服务端返回的是保存前的版本，不能把这些设置冲掉
        const localMetadata = (current.version.graph.metadata || {}) as Record<string, unknown>;
        const serverMetadata = (next.version.graph.metadata || {}) as Record<string, unknown>;
        const production = { ...((serverMetadata.production_settings || {}) as Record<string, unknown>), ...((localMetadata.production_settings || {}) as Record<string, unknown>) };
        return { ...next, version: { ...next.version, graph: { ...next.version.graph, metadata: { ...serverMetadata, ...(localMetadata.canvas_style !== undefined ? { canvas_style: localMetadata.canvas_style } : {}), production_settings: production } } } };
      });
      savedEditRef.current = saveEdit;
      if (changeVersionRef.current === saveVersion) {
        setDirty(false);
        removeCanvasDraft(canvasDraftKey(storyId, chapterId, baseCanvas.id));
      }
      if (showSuccess) toast.success('画布已保存');
      return synchronized;
    } catch (error) {
      if (canvasEpochRef.current !== epoch) return null;
      markDirty();
      toast.error(normalizeErrorMessage(error, '保存画布失败，请刷新后重试'));
      return null;
    } finally { savingRef.current = false; setSaving(false); }
  };

  useEffect(() => {
    const flush = () => {
      persistLocalDraft();
      if (dirtyRef.current && !savingRef.current) void saveCanvas(false);
    };
    const onVisibility = () => { if (document.visibilityState === 'hidden') flush(); };
    window.addEventListener('pagehide', flush);
    document.addEventListener('visibilitychange', onVisibility);
    return () => { window.removeEventListener('pagehide', flush); document.removeEventListener('visibilitychange', onVisibility); };
  }, [persistLocalDraft]);

  const runCanvas = async (targetNodeId?: string, forceRerun = false, retried = false) => {
    if (!canvas || running) return;
    const epoch = canvasEpochRef.current;
    setRunning(true);
    setSubmittingNodeId(targetNodeId || null);
    try {
      // 服务端版本可能已被后台编排 / 助手 / 质检更新：本地没有未保存修改时，先对齐到最新版本，
      // 否则带着旧版本号提交会被 409「画布定义已更新」拒绝。
      let base = canvas;
      if (!dirty && !hasUnsavedContent()) {
        const latest = await getVideoCanvas(canvas.id).catch(() => null);
        if (canvasEpochRef.current !== epoch) return;
        if (latest && latest.definition_revision !== canvas.definition_revision && !hasUnsavedContent()) { applyServerCanvas(latest); base = latest; }
      }
      const synchronized = dirty ? await saveCanvas(false) : base;
      if (!synchronized) return;
      const validation = await validateVideoCanvas(synchronized.id);
      if (canvasEpochRef.current !== epoch) return;
      if (!validation.valid) throw new Error(validation.errors.map((item) => item.message).join('；'));
      // 运行前成本预估：积分不足直接拦截；批量生成需用户确认花费。预估失败不阻断（后端仍会预留并校验积分）。
      const estimate = await estimateVideoCanvasCost(synchronized.id, { target_node_ids: targetNodeId ? [targetNodeId] : [], rerun_node_ids: forceRerun && targetNodeId ? [targetNodeId] : [] }).catch(() => null);
      if (canvasEpochRef.current !== epoch) return;
      if (estimate && estimate.items.length > 0) {
        if (estimate.credential_mode === 'platform' && estimate.sufficient === false && estimate.items.every((item) => item.priced)) throw new Error(`积分不足：${formatCostLine(estimate)}`);
        if (!targetNodeId || estimate.items.length > 1) {
          const accepted = await confirm({ title: '确认提交生成', message: `${formatCostLine(estimate)}。已生成且未修改的节点会自动复用，不重复计费。`, confirmText: '确认生成' });
          if (!accepted || canvasEpochRef.current !== epoch) return;
        }
      }

      const result = await runVideoCanvas(synchronized.id, { target_node_ids: targetNodeId ? [targetNodeId] : [], expected_definition_revision: synchronized.definition_revision, idempotency_key: crypto.randomUUID(), ...(forceRerun && targetNodeId ? { rerun_node_ids: [targetNodeId] } : {}) });
      if (canvasEpochRef.current !== epoch) return;
      let run = result.run;
      if (run.status === 'awaiting_approval') {
        const confirmed = await confirmVideoCanvasRun(synchronized.id, run.id);
        if (canvasEpochRef.current !== epoch) return;
        run = confirmed.run;
      }
      if (canvasEpochRef.current !== epoch) return;
      adoptRun(run);
      setNodes((current) => mergeRunOutputs(run, current, edgesRef.current, assets));
      toast.success(run.status === 'succeeded' ? '画布执行完成' : '生成任务已提交');
    } catch (error) {
      const message = normalizeErrorMessage(error, '运行画布失败');
      // 提交时版本号落后于服务端（保存之后又有后台写入）：本地内容已经保存，对齐到最新版本后自动重试一次。
      if (!retried && canvasEpochRef.current === epoch && message.includes('画布定义已更新')) {
        const latest = await getVideoCanvas(canvas.id).catch(() => null);
        if (latest && canvasEpochRef.current === epoch && !hasUnsavedContent()) {
          applyServerCanvas(latest);
          window.setTimeout(() => void runCanvasRef.current(targetNodeId, forceRerun, true), 50);
          return;
        }
      }
      toast.error(message);
    } finally { setRunning(false); setSubmittingNodeId(null); }
  };
  const runCanvasRef = useRef(runCanvas);
  useEffect(() => { runCanvasRef.current = runCanvas; });
  // 固定某个历史结果为节点当前结果；下游节点依赖变化后会按定义指纹自动判断是否需要重新生成。
  const pinCandidate = useCallback((nodeId: string, candidate: CanvasNodeCandidate) => {
    captureHistory();
    const node = nodesRef.current.find((item) => item.id === nodeId);
    if (!node) return;
    const config = { ...(node.data.config || {}), asset_id: candidate.asset_id };
    delete (config as Record<string, unknown>)._reused_definition_hash;
    updateNode(nodeId, { config, result: { ...(node.data.result as Record<string, unknown> | undefined), asset_id: candidate.asset_id, url: candidate.url } });
    toast.success('已切换到所选结果');
  }, [captureHistory, updateNode]);
  // 再生成一个候选：先取消固定的素材，再强制重跑该节点；旧结果保留在候选列表里。
  const regenerateNode = useCallback((nodeId: string) => {
    captureHistory();
    const node = nodesRef.current.find((item) => item.id === nodeId);
    if (!node) return;
    const config = { ...(node.data.config || {}) } as Record<string, unknown>;
    delete config.asset_id;
    delete config._reused_definition_hash;
    updateNode(nodeId, { config });
    // 等状态提交并同步到 nodesRef 后再运行，保存的才是取消固定后的图。
    window.setTimeout(() => void runCanvasRef.current(nodeId, true), 80);
  }, [captureHistory, updateNode]);
  // 节点是否已经有生成结果（图片 / 视频）
  const nodeHasResult = (node: CanvasNode | null | undefined) => Boolean(node && (node.type === 'image' || node.type === 'video') && (node.data.config?.asset_id || (node.data.result as { url?: string } | undefined)?.url));
  // 输入框里的发送键：节点已有结果时与「再生成一个」走同一条路径（强制重新生成、旧结果留在候选里、锁定的不动），
  // 否则内容没变时会被判定为“可复用”，点了没有任何反应；没有结果时才是首次生成。
  const generateFromPanel = (nodeId: string) => {
    const node = nodesRef.current.find((item) => item.id === nodeId);
    if (!node) return;
    if (nodeHasResult(node)) {
      if (node.data.config?.locked) { toast.info('该节点已锁定，请先解锁再重新生成'); return; }
      regenerateNode(nodeId);
      return;
    }
    void runCanvas(nodeId);
  };
  const assetEntries = useMemo(() => collectAssets(nodes, edges), [nodes, edges]);
  const assetSummary = useMemo(() => summarizeAssets(assetEntries), [assetEntries]);
  // 锁定后重新分析、一键返工和"再生成一个"都不会改动该资产。
  // 未入选的场景/道具候选：汇总所有场景节点上保存的候选，去掉画布上已有同名资产的。
  const assetCandidates = useMemo(() => {
    const existing = new Set(assetEntries.map((entry) => `${entry.kind}:${entry.name}`));
    const seen = new Set<string>();
    const list: Array<AssetCandidate & { sceneNodeId: string }> = [];
    for (const node of nodes) {
      const raw = (node.data.config as Record<string, unknown> | undefined)?.asset_candidates;
      if (node.type !== 'scene' || !Array.isArray(raw)) continue;
      for (const item of raw as AssetCandidate[]) {
        const key = `${item.role}:${item.name}`;
        if (!item?.name || existing.has(key) || seen.has(key)) continue;
        seen.add(key);
        list.push({ ...item, sceneNodeId: node.id });
      }
    }
    return list;
  }, [nodes, assetEntries]);
  const addCandidateAsset = useCallback((candidate: AssetCandidate & { sceneNodeId?: string }) => {
    const sceneNode = nodesRef.current.find((node) => node.id === candidate.sceneNodeId) || nodesRef.current.find((node) => node.type === 'scene');
    if (!sceneNode) return;
    const kind: AssetKind = candidate.role;
    const nameHash = Math.abs([...candidate.name].reduce((hash, char) => (hash * 31 + (char.codePointAt(0) || 0)), 7) % 2176782336).toString(36).slice(0, 6);
    const id = `ast-${sceneNode.id}-${kind}-${nameHash}`.slice(0, 64);
    if (nodesRef.current.some((node) => node.id === id)) return;
    const existingAssets = nodesRef.current
      .filter((node) => (node.data.config as Record<string, unknown> | undefined)?.asset_scene_node === sceneNode.id)
      .map((node) => ({ kind: (node.data.config as Record<string, unknown>).asset_role as AssetKind, position: node.position }))
      .filter((item) => item.kind === 'character' || item.kind === 'scene' || item.kind === 'prop');
    const position = nextAssetSlot({ position: sceneNode.position, width: Number(sceneNode.data.ui?.width) || undefined }, kind, existingAssets);
    const kindLabel = kind === 'character' ? '角色' : kind === 'scene' ? '场景' : '道具';
    const prompt = kind === 'character' ? `角色设定参考图：${candidate.name}。${candidate.desc}。全身正面站姿，干净背景，画面风格统一。` : kind === 'scene' ? `空镜场景参考图：${candidate.name}。${candidate.desc}。无人物，画面统一。` : `道具参考图：${candidate.name}。${candidate.desc}。单个物体特写，干净背景。`;
    captureHistory();
    setNodes((current) => [...current, {
      id,
      type: 'image',
      position,
      data: {
        label: `${kindLabel}·${candidate.name}`,
        nodeType: 'image',
        config: { node_role: 'asset', manual_added: true, asset_role: kind, asset_name: candidate.name, asset_scene_node: sceneNode.id, source_scene_node: sceneNode.id, scene_ids: (candidate.scene_ids || []).map(String), prompt, size: '1920x1080', aspect_ratio: '16:9' },
      },
    }]);
    markDirty();
    toast.success(`已添加${kindLabel}资产「${candidate.name}」，可在资产面板生成图片`);
  }, [captureHistory, markDirty]);
  const toggleAssetLock = useCallback((nodeId: string) => {
    captureHistory();
    const node = nodesRef.current.find((item) => item.id === nodeId);
    if (!node) return;
    updateNodeConfig(nodeId, 'locked', !node.data.config?.locked);
  }, [captureHistory, updateNodeConfig]);
  const editAssetSetting = useCallback((nodeId: string, kind: AssetKind, text: string) => {
    captureHistory();
    const node = nodesRef.current.find((item) => item.id === nodeId);
    if (!node) return;
    const config = node.data.config || {};
    // 角色写入人物档案并标记手改（重新分析不再覆盖）；场景与道具的设定就是生成提示词。
    updateNode(nodeId, { config: kind === 'character' ? { ...config, profile: text, profile_edited: true } : { ...config, prompt: text } });
  }, [captureHistory, updateNode]);
  const linkAssetToShots = useCallback((nodeId: string, shotIds: string[]) => {
    const created = buildReferenceEdges(nodeId, shotIds, edgesRef.current as CanvasEdge[]);
    if (!created.length) return;
    captureHistory();
    const nextEdges = [...edgesRef.current, ...created] as CanvasEdge[];
    setNodes(syncCanvasMediaReferences(nodesRef.current, nextEdges, assets) as CanvasNode[]);
    setEdges(nextEdges);
    markDirty();
    toast.success(`已为 ${created.length} 个镜头补齐资产引用`);
  }, [assets, captureHistory, markDirty]);
  const focusNode = useCallback((nodeId: string) => {
    const node = nodesRef.current.find((item) => item.id === nodeId);
    const rect = surfaceRef.current?.getBoundingClientRect();
    if (!node || !rect) return;
    setSelectedNodeId(nodeId);
    setSelectedNodeIds([nodeId]);
    const k = viewportRef.current.k;
    updateViewport({ x: rect.width / 2 - (node.position.x + 150) * k, y: rect.height / 2 - (node.position.y + 90) * k, k });
  }, [updateViewport]);
  // 批量生成：按依赖分波次，同一波次内每个节点各提交一个运行，由后台并行执行；
  // 上游没生成的资产会先于下游生成，避免多个运行重复生成同一个上游节点。
  const runBatch = async (requestedIds: string[], options: { regenerate?: boolean } = {}) => {
    if (!canvas || running || batch) return;
    const epoch = canvasEpochRef.current;
    const regenerate = Boolean(options.regenerate);
    const plan = planBatchWaves(nodesRef.current as BatchNode[], edgesRef.current as BatchEdge[], requestedIds, { regenerate });
    const ids = plan.waves.flat();
    if (!ids.length) { toast.info('所选节点都已生成'); return; }
    setRunning(true);
    const sleep = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms));
    try {
      // 先预估并让用户确认（含就地选画风），确认后再保存并提交，这样画风选择会一并保存进画布。
      const estimateGraph = toGraph(nodesRef.current, edgesRef.current, canvas.version.graph);
      const estimate = await estimateVideoCanvasCost(canvas.id, { target_node_ids: ids, graph: estimateGraph }).catch(() => null);
      if (canvasEpochRef.current !== epoch) return;
      if (estimate && estimate.credential_mode === 'platform' && estimate.sufficient === false && estimate.items.every((item) => item.priced)) throw new Error(`积分不足：${formatCostLine(estimate)}`);
      const accepted = await new Promise<boolean>((resolve) => setBatchDialog({
        resolve,
        info: {
          total: ids.length, waves: plan.waves.length, added: plan.added.length, regenerate,
          costLine: estimate ? formatCostLine(estimate).replace(/^待生成：/, '') : null,
          costWarnings: estimate?.warnings || [],
          needsStyle: anyFollowsCanvasStyle(nodesRef.current as BatchNode[], ids),
        },
      }));
      setBatchDialog(null);
      if (!accepted || canvasEpochRef.current !== epoch) return;

      if (regenerate) {
        // 重新生成：去掉固定的素材与复用标记，本次才会真正重跑这些节点。
        const target = new Set(ids);
        const next = nodesRef.current.map((node) => {
          if (!target.has(node.id)) return node;
          const config = { ...(node.data.config || {}) } as Record<string, unknown>;
          delete config.asset_id;
          delete config._reused_definition_hash;
          return { ...node, data: { ...node.data, config } };
        });
        nodesRef.current = next;
        setNodes(next);
        markDirty();
      }
      const synchronized = dirtyRef.current || regenerate ? await saveCanvas(false) : canvas;
      if (!synchronized) return;
      const validation = await validateVideoCanvas(synchronized.id);
      if (canvasEpochRef.current !== epoch) return;
      if (!validation.valid) throw new Error(validation.errors.map((item) => item.message).join('；'));

      batchCancelRef.current = false;
      batchRunIdsRef.current = new Set();
      const statuses = new Map<string, string>(ids.map((id) => [id, 'queued']));
      const progress: BatchProgress = { total: ids.length, done: 0, failed: 0 };
      const failedIds = new Set<string>();
      const failureReasons: string[] = [];
      const publish = () => { setBatchStatuses(new Map(statuses)); setBatch({ ...progress }); };
      publish();

      const markFailed = (id: string, reason?: string) => {
        statuses.set(id, 'failed');
        failedIds.add(id);
        progress.done += 1;
        progress.failed += 1;
        if (reason && failureReasons.length < 3) failureReasons.push(reason);
      };

      for (const wave of plan.waves) {
        if (batchCancelRef.current || canvasEpochRef.current !== epoch) break;
        // 上游失败的节点没有可用输入，直接跳过并计为失败。
        const runnable = wave.filter((id) => {
          const blocked = [...generationAncestors(id, nodesRef.current as BatchNode[], edgesRef.current as BatchEdge[])].some((ancestor) => failedIds.has(ancestor));
          if (blocked) markFailed(id, '上游节点生成失败，已跳过');
          return !blocked;
        });
        publish();
        const submitted = await Promise.allSettled(runnable.map(async (id) => {
          const created = await submitRunWithFreshRevision(synchronized.id, { target_node_ids: [id], expected_definition_revision: synchronized.definition_revision, idempotency_key: crypto.randomUUID(), ...(regenerate ? { rerun_node_ids: [id] } : {}) });
          let run = created.run;
          if (run.status === 'awaiting_approval') run = (await confirmVideoCanvasRun(synchronized.id, run.id)).run;
          batchRunIdsRef.current.add(run.id);
          return { id, runId: run.id };
        }));
        const waiting = new Map<string, number>();
        submitted.forEach((result, index) => {
          if (result.status === 'fulfilled') waiting.set(result.value.id, result.value.runId);
          else markFailed(runnable[index], normalizeErrorMessage(result.reason, '提交失败'));
        });
        publish();

        while (waiting.size && !batchCancelRef.current && canvasEpochRef.current === epoch) {
          await sleep(2000);
          await Promise.all([...waiting].map(async ([nodeId, runId]) => {
            const result = await getVideoCanvasRun(synchronized.id, runId).catch(() => null);
            if (!result || canvasEpochRef.current !== epoch) return;
            const run = result.run;
            setNodes((current) => mergeRunOutputs(run, current, edgesRef.current, assets));
            if (run.status === 'succeeded') {
              statuses.set(nodeId, 'succeeded');
              waiting.delete(nodeId);
              progress.done += 1;
            } else if (['failed', 'cancelled'].includes(run.status)) {
              const reason = run.nodes.find((item) => item.status === 'failed')?.error_message || run.error_message || undefined;
              waiting.delete(nodeId);
              markFailed(nodeId, reason || undefined);
              statuses.set(nodeId, run.status);
            } else {
              statuses.set(nodeId, run.nodes.find((item) => item.node_id === nodeId)?.status === 'running' ? 'running' : 'queued');
            }
          }));
          publish();
        }
        if (batchCancelRef.current) break;
      }
      const cancelled = batchCancelRef.current;
      const succeeded = progress.done - progress.failed;
      if (canvasEpochRef.current === epoch) {
        if (cancelled) toast.info(`已取消批量生成：完成 ${succeeded} 个`);
        else if (progress.failed > 0) toast.error(`批量生成结束：成功 ${succeeded} 个，失败 ${progress.failed} 个${failureReasons.length ? `。${failureReasons.join('；')}` : ''}`);
        else toast.success(`批量生成完成：${succeeded} 个节点`);
      }
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '批量生成失败'));
    } finally {
      setBatchDialog(null);
      setBatch(null);
      setBatchStatuses(new Map());
      batchRunIdsRef.current = new Set();
      setRunning(false);
    }
  };
  // 供 useCallback 里的回调调用最新的 runBatch，避免拿到过期的 running / batch 状态。
  const runBatchRef = useRef(runBatch);
  useEffect(() => { runBatchRef.current = runBatch; });
  const cancelBatch = async () => {
    if (!canvas) return;
    batchCancelRef.current = true;
    await Promise.allSettled([...batchRunIdsRef.current].map((runId) => cancelVideoCanvasRun(canvas.id, runId)));
  };
  const productionEntries = useMemo(() => collectProduction(nodes as BatchNode[]), [nodes]);
  // 结果加载后让节点按图片比例调整高度（限制在 140~240，避免压住下一行），每个结果地址只调整一次。
  const fitNodeToMedia = useCallback((nodeId: string, url: string, width: number, height: number) => {
    if (!width || !height) return;
    const node = nodesRef.current.find((item) => item.id === nodeId);
    if (!node) return;
    const ui = (node.data.ui || {}) as { width?: number; height?: number; fitUrl?: string };
    if (ui.fitUrl === url) return;
    const nodeWidth = Number(ui.width) || NODE_WIDTH;
    const fitted = Math.round(Math.min(240, Math.max(140, (nodeWidth * height) / width)));
    setNodes((current) => current.map((item) => item.id === nodeId ? { ...item, data: { ...item.data, ui: { ...(item.data.ui || {}), height: fitted, fitUrl: url } } } : item));
  }, []);
  // ---- 画布级风格：写在图的 metadata.canvas_style，未单独设置风格的资产、分镜和视频都会使用 ----
  const canvasStyle = useMemo(() => readCanvasStyle(canvas?.version.graph), [canvas?.version.graph]);
  // 画布级画面比例（开局选定，存在 metadata.production_settings.aspect_ratio）；助手和自动编排都沿用它，单个节点仍可手动改。
  const canvasAspect = String(((canvas?.version.graph.metadata?.production_settings as Record<string, unknown> | undefined)?.aspect_ratio) || '16:9');
  const setCanvasAspect = useCallback((next: string) => {
    if (!canvas) return;
    guideSettingsRef.current = { ...guideSettingsRef.current, aspect_ratio: next };
    setCanvas((current) => {
      if (!current) return current;
      const metadata = current.version.graph.metadata || {};
      const production = (metadata.production_settings || {}) as Record<string, unknown>;
      return { ...current, version: { ...current.version, graph: { ...current.version.graph, metadata: { ...metadata, production_settings: { ...production, aspect_ratio: next } } } } };
    });
    markDirty();
  }, [canvas, markDirty]);
  // 分镜时长模式（开局选定，存在 metadata.production_settings.shot_duration_mode）：flexible 灵活剪切 / fixed15 固定 15 秒；后端导演据此控制时长。
  const shotDurationMode: ShotDurationMode = ((canvas?.version.graph.metadata?.production_settings as Record<string, unknown> | undefined)?.shot_duration_mode) === 'fixed15' ? 'fixed15' : 'flexible';
  const setShotDurationMode = useCallback((next: ShotDurationMode) => {
    if (!canvas) return;
    guideSettingsRef.current = { ...guideSettingsRef.current, shot_duration_mode: next };
    setCanvas((current) => {
      if (!current) return current;
      const metadata = current.version.graph.metadata || {};
      const production = (metadata.production_settings || {}) as Record<string, unknown>;
      return { ...current, version: { ...current.version, graph: { ...current.version.graph, metadata: { ...metadata, production_settings: { ...production, shot_duration_mode: next } } } } };
    });
    markDirty();
  }, [canvas, markDirty]);
  const setCanvasStyle = useCallback((next: CanvasStyle | null, options: { silent?: boolean } = {}) => {
    if (!canvas || sameStyle(next, readCanvasStyle(canvas.version.graph))) return;
    setCanvas((current) => current ? { ...current, version: { ...current.version, graph: { ...current.version.graph, metadata: { ...(current.version.graph.metadata || {}), canvas_style: next } } } } : current);
    markDirty();
    if (options.silent) return;
    // 已生成的画面是按旧画风出的，与新画风不一致：问一次是否按新画风重新生成（锁定的不动）。
    const outdated = inconsistentNodeIds(nodesRef.current as BatchNode[], next);
    if (outdated.length === 0) { toast.success(next ? '画风已更新，之后生成的图片和视频都会使用它' : '已取消画布画风'); return; }
    void confirm({
      title: '画风已更新',
      message: `有 ${outdated.length} 个图片或视频的画风与新设置不一致（已锁定的不受影响）。要现在重新生成它们吗？会产生费用，下一步可以看到预估。你也可以稍后点"一键统一"。`,
      confirmText: '现在统一',
    }).then((accepted) => { if (accepted) void runBatchRef.current(outdated, { regenerate: true }); });
  }, [canvas, markDirty]);
  // 与当前画风不一致的已生成节点，以及一键统一（走批量重新生成，含费用预估与确认）。
  const inconsistentIds = useMemo(() => inconsistentNodeIds(nodes as BatchNode[], canvasStyle), [nodes, canvasStyle]);
  const unifyStyle = useCallback(() => { void runBatchRef.current(inconsistentIds, { regenerate: true }); }, [inconsistentIds]);
  const toggleCanvasStyle = useCallback((enabled: boolean) => {
    const current = readCanvasStyle(canvas?.version.graph);
    if (current) setCanvasStyle({ ...current, enabled });
  }, [canvas?.version.graph, setCanvasStyle]);
  const uploadCanvasStyleReference = useCallback(async (file: File): Promise<string> => {
    // 上传后先暂存，用户在弹窗里点"确定"才真正设为画布风格。
    const created = chapterId
      ? await createVideoAsset(chapterId, { story_id: storyId, asset_type: 'style_reference', name: file.name, file_path: '', provider: 'manual_upload' })
      : await createStoryVideoAsset(storyId, { asset_type: 'style_reference', name: file.name, file_path: '', provider: 'manual_upload' });
    const replaced = await replaceVideoAsset(created.id, file);
    const url = toPublicVideoAssetUrl(replaced.asset.file_path) || '';
    pendingStyleReferenceRef.current = referenceToCanvasStyle(replaced.asset.id, url);
    onAssetsChanged?.();
    return url;
  }, [chapterId, onAssetsChanged, storyId]);
  const handleCanvasStyleSelect = useCallback((styleName: string) => {
    const preset = stylePresets.find((item) => item.name === styleName);
    if (preset) setCanvasStyle(presetToCanvasStyle(preset));
    else if (pendingStyleReferenceRef.current) setCanvasStyle(pendingStyleReferenceRef.current);
    pendingStyleReferenceRef.current = null;
  }, [setCanvasStyle, stylePresets]);
  const confirmRun = async () => {
    if (!canvas || !latestRun || !['awaiting_approval', 'failed'].includes(latestRun.status) || running) return;
    const epoch = canvasEpochRef.current;
    if (latestRun.status === 'failed' && !(await confirm({ title: '恢复执行', message: '继续执行该任务原先冻结的画布版本，保留成功节点并查询已有生成任务。当前画布的新修改不会加入；如需使用新修改，请重新运行节点。', confirmText: '继续原任务' }))) return;
    if (canvasEpochRef.current !== epoch) return;
    setRunning(true);
    try {
      const result = await confirmVideoCanvasRun(canvas.id, latestRun.id);
      if (canvasEpochRef.current !== epoch) return;
      adoptRun(result.run);
      setNodes((current) => mergeRunOutputs(result.run, current, edgesRef.current, assets));
      toast.success(latestRun.status === 'failed' ? '已恢复执行，任务已进入队列' : '生成任务已提交');
    } catch (error) { toast.error(normalizeErrorMessage(error, '确认画布生成失败')); } finally { setRunning(false); }
  };
  // 某个节点当前所在的进行中运行（节点输入框的停止键只停它自己那次，不影响其他节点正在跑的运行）。
  const activeRunForNode = (nodeId: string) => [...trackedRuns].reverse().find((run) => ['queued', 'running'].includes(run.status) && run.nodes.some((item) => item.node_id === nodeId && ['queued', 'running'].includes(item.status))) || null;
  const stopNodeRun = async (nodeId: string) => {
    const run = activeRunForNode(nodeId);
    if (!canvas || !run) return;
    const epoch = canvasEpochRef.current;
    try {
      const result = await cancelVideoCanvasRun(canvas.id, run.id);
      if (canvasEpochRef.current !== epoch) return;
      adoptRun(result.run);
      toast.success('已请求停止该节点的生成');
    } catch (error) { if (canvasEpochRef.current === epoch) toast.error(normalizeErrorMessage(error, '停止生成失败')); }
  };
  const createBlankCanvas = async () => {
    const epoch = canvasEpochRef.current;
    const version = changeVersionRef.current;
    if (!(await canDiscardChanges())) return;
    if (canvasEpochRef.current !== epoch || changeVersionRef.current !== version || savingRef.current) return;
    const requestId = ++loadRequestRef.current;
    try {
      const result = await createVideoCanvas({ story_id: storyId, default_chapter_id: chapterId ?? null, name: chapterId ? '章节视频画布' : '视频创作画布' });
      if (loadRequestRef.current !== requestId || canvasEpochRef.current !== epoch || savingRef.current || changeVersionRef.current !== version) return;
      hydrateCanvas(result);
      window.localStorage.setItem(canvasSelectionKey, String(result.id));
      setCanvasList(current => [result, ...current.filter(item => item.id !== result.id)]);
      setDirty(false);
      toast.success('空白画布已创建');
    } catch (error) { if (loadRequestRef.current === requestId) toast.error(normalizeErrorMessage(error, '创建画布失败')); }
  };
  const loadCanvasPlans = async () => {
    if (!canvas) return;
    const epoch = canvasEpochRef.current;
    const requestId = ++plansRequestRef.current;
    const isCurrent = () => canvasEpochRef.current === epoch && plansRequestRef.current === requestId;
    setPlansLoading(true);
    try { const result = await listVideoCanvasPlans(canvas.id); if (isCurrent()) setPlans(result.plans); }
    catch (error) { if (isCurrent()) toast.error(normalizeErrorMessage(error, '读取创作计划失败')); }
    finally { if (isCurrent()) setPlansLoading(false); }
  };
  const confirmCanvasPlan = async (plan: VideoCanvasPlan) => {
    if (!canvas || plan.status !== 'ready') return;
    const epoch = canvasEpochRef.current;
    setApplyingPlanId(plan.id);
    try {
      const approved = await confirmVideoCanvasPlan(canvas.id, plan.id, plan.revision);
      if (canvasEpochRef.current !== epoch) return;
      setPlans((current) => current.map((item) => item.id === approved.id ? approved : item));
      toast.success('创作计划已确认');
    } catch (error) { toast.error(normalizeErrorMessage(error, '确认创作计划失败')); }
    finally { if (canvasEpochRef.current === epoch) setApplyingPlanId(null); }
  };
  const applyCanvasPlan = async (plan: VideoCanvasPlan) => {
    if (!canvas || plan.status !== 'approved') return;
    const epoch = canvasEpochRef.current;
    const version = changeVersionRef.current;
    if (!(await canDiscardChanges())) return;
    if (canvasEpochRef.current !== epoch || changeVersionRef.current !== version || savingRef.current) return;
    setApplyingPlanId(plan.id);
    try {
      const result = await applyVideoCanvasPlan(canvas.id, plan.id, {
        expected_plan_revision: plan.revision,
        expected_definition_revision: canvas.definition_revision,
      });
      if (canvasEpochRef.current !== epoch) return;
      if (changeVersionRef.current !== version || savingRef.current) { toast.info('计划已应用到服务端，本地新增修改已保留，请重新打开画布查看'); return; }
      hydrateCanvas(result.canvas);
      setDirty(false);
      setPlans((current) => [result.plan, ...current.filter(item => item.id !== result.plan.id)]);
      toast.success('创作计划已应用到画布');
    } catch (error) { toast.error(normalizeErrorMessage(error, '应用创作计划失败')); }
    finally { if (canvasEpochRef.current === epoch) setApplyingPlanId(null); }
  };
  const syncPlanWorkflow = async (plan: VideoCanvasPlan) => {
    if (!canvas || !['approved', 'applied'].includes(plan.status) || plan.workflow_id) return;
    const epoch = canvasEpochRef.current;
    setApplyingPlanId(plan.id);
    try {
      const result = await syncVideoCanvasPlanWorkflow(canvas.id, plan.id, plan.revision);
      if (canvasEpochRef.current !== epoch) return;
      setPlans((current) => [result.plan, ...current.filter(item => item.id !== result.plan.id)]);
      toast.success(`已同步 ${result.shot_count} 个镜头到章节视频工作流`);
    } catch (error) { toast.error(normalizeErrorMessage(error, '同步章节视频工作流失败')); }
    finally { if (canvasEpochRef.current === epoch) setApplyingPlanId(null); }
  };
  useEffect(() => { if (agentOpen) void loadCanvasPlans(); }, [agentOpen, canvas?.id]);
  const beginCanvasRename = () => { if (!canvas) return; setCanvasNameDraft(canvas.name); setEditingCanvasName(true); };
  const cancelCanvasRename = () => { setEditingCanvasName(false); setCanvasNameDraft(''); };
  const renameCanvas = async () => {
    if (!canvas) return;
    const name = canvasNameDraft.trim();
    if (!name) { toast.error('请输入画布名称'); return; }
    if (name === canvas.name) { cancelCanvasRename(); return; }
    setRenamingCanvas(true);
    try {
      const updated = await updateVideoCanvas(canvas.id, { name });
      setCanvas((current) => current?.id === updated.id ? { ...current, name: updated.name, description: updated.description } : current);
      setCanvasList((current) => current.map((item) => item.id === updated.id ? { ...item, name: updated.name, description: updated.description } : item));
      cancelCanvasRename();
      toast.success('画布名称已更新');
    } catch (error) { toast.error(normalizeErrorMessage(error, '更新画布名称失败')); } finally { setRenamingCanvas(false); }
  };
  const deleteCurrentCanvas = async () => {
    const epoch = canvasEpochRef.current;
    const version = changeVersionRef.current;
    if (savingRef.current) { toast.info('画布正在保存，请稍后删除'); return; }
    if (!canvas || !(await confirm({ title: '删除画布', message: '该画布将从当前列表移除，历史运行记录和已生成媒体会被保留。', confirmText: '删除画布', danger: true }))) return;
    if (canvasEpochRef.current !== epoch || changeVersionRef.current !== version || savingRef.current) return;
    try {
      await deleteVideoCanvas(canvas.id);
      if (canvasEpochRef.current !== epoch || changeVersionRef.current !== version || savingRef.current) return;
      const remaining = canvasList.filter((item) => item.id !== canvas.id);
      setCanvasList(remaining);
      setDirty(false);
      const next = remaining[0];
      if (next) {
        const nextCanvas = await getVideoCanvas(next.id);
        if (canvasEpochRef.current !== epoch || changeVersionRef.current !== version || savingRef.current) return;
        hydrateCanvas(nextCanvas);
        window.localStorage.setItem(canvasSelectionKey, String(next.id));
      } else {
        window.localStorage.removeItem(canvasSelectionKey);
        const created = await createVideoCanvas({ story_id: storyId, default_chapter_id: chapterId ?? null, name: chapterId ? '章节视频画布' : '视频创作画布' });
        if (canvasEpochRef.current !== epoch || changeVersionRef.current !== version || savingRef.current) return;
        hydrateCanvas(created);
        setCanvasList([created]);
        window.localStorage.setItem(canvasSelectionKey, String(created.id));
      }
      toast.success('画布已删除');
    } catch (error) { toast.error(normalizeErrorMessage(error, '删除画布失败')); }
  };
  const selectCanvas = async (canvasId: number) => {
    const epoch = canvasEpochRef.current;
    const version = changeVersionRef.current;
    if (canvas?.id === canvasId || !(await canDiscardChanges())) return;
    if (canvasEpochRef.current !== epoch || changeVersionRef.current !== version || savingRef.current) return;
    const requestId = ++loadRequestRef.current;
    try {
      const selected = await getVideoCanvas(canvasId);
      if (loadRequestRef.current !== requestId || canvasEpochRef.current !== epoch || savingRef.current || changeVersionRef.current !== version) return;
      hydrateCanvas(selected);
      window.localStorage.setItem(canvasSelectionKey, String(selected.id));
      setDirty(false);
    } catch (error) { if (loadRequestRef.current === requestId) toast.error(normalizeErrorMessage(error, '打开视频画布失败')); }
  };
  // 增量应用服务端画布：只替换节点/连线/运行结果，保留视口、选中态和本地节点位置，不重置页面。
  const applyServerCanvas = useCallback((next: VideoCanvas) => {
    const projected = projectLegacyGraph(next.version.graph);
    const projectedEdges = projected.edges as CanvasEdge[];
    const localPositions = new Map(nodesRef.current.map((node) => [node.id, node.position]));
    const layoutNodes = next.layout.nodes || {};
    let merged = toCanvasNodes(projected).map((node) => ({ ...node, position: localPositions.get(node.id) || layoutNodes[node.id] || node.position }));
    for (const run of [...(next.runs || [])].reverse()) merged = mergeRunOutputs(run, merged, projectedEdges, assetsRef.current);
    const alive = new Set(merged.map((node) => node.id));
    setCanvas(next);
    setNodes(merged);
    setEdges(projectedEdges);
    setLatestRun(next.runs?.[0] || null);
    setTrackedRuns([...(next.runs || [])].sort((a, b) => a.id - b.id).slice(-30));
    setSelectedNodeId((current) => (current && alive.has(current) ? current : null));
    setSelectedNodeIds((current) => current.filter((id) => alive.has(id)));
    setCanvasList((current) => current.map((item) => item.id === next.id ? next : item));
    setDirty(false);
    savedEditRef.current = contentEditRef.current;
  }, []);
  // 本地有没有还没保存的节点/连线修改（只平移视口不算）。有的话绝不能用服务端画布覆盖本地。
  const hasUnsavedContent = () => contentEditRef.current !== savedEditRef.current;
  // 发给助手前先把未保存的修改存到服务端，助手才能看到和操作同一份画布。
  const flushBeforeAgent = useCallback(async (): Promise<boolean> => {
    for (let attempt = 0; attempt < 20 && savingRef.current; attempt += 1) await new Promise((resolve) => window.setTimeout(resolve, 250));
    if (contentEditRef.current === savedEditRef.current) return true;
    const saved = await saveCanvas(false);
    if (!saved || contentEditRef.current !== savedEditRef.current) {
      toast.error('画布保存失败，已取消发送。请先处理保存问题后再让助手继续。');
      return false;
    }
    return true;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canvas]);
  const refreshCanvas = async () => {
    if (!canvas || currentCanvasIdRef.current !== canvas.id) return;
    void refreshPipeline();
    if (savingRef.current || hasUnsavedContent()) { toast.info('助手已更新服务端画布；本地修改已保留，请先处理未保存修改再重新打开画布'); return; }
    const epoch = canvasEpochRef.current;
    try {
      const refreshed = await getVideoCanvas(canvas.id);
      if (canvasEpochRef.current !== epoch || savingRef.current || hasUnsavedContent()) return;
      applyServerCanvas(refreshed);
    } catch (error) { if (canvasEpochRef.current === epoch) toast.error(normalizeErrorMessage(error, '刷新视频画布失败')); }
  };
  // 手动刷新：以服务端为准重新读取画布内容、运行记录、节点结果、自动编排进度和质检。
  // 有未保存的修改时必须先确认，因为刷新会放弃它们（助手 / 后台编排写入的内容、其他窗口的修改才会被读进来）。
  const reloadCanvasManually = async () => {
    if (!canvas || refreshingCanvas) return;
    if (savingRef.current) { toast.info('画布正在保存，请稍后再刷新'); return; }
    if (hasUnsavedContent() || dirtyRef.current) {
      const accepted = await confirm({ title: '刷新画布', message: '画布有未保存的修改，刷新会放弃它们并读取服务端最新内容。', confirmText: '放弃修改并刷新', danger: true });
      if (!accepted) return;
    }
    const epoch = canvasEpochRef.current;
    setRefreshingCanvas(true);
    try {
      const fresh = await getVideoCanvas(canvas.id);
      if (canvasEpochRef.current !== epoch) return;
      applyServerCanvas(fresh);
      removeCanvasDraft(canvasDraftKey(storyId, chapterId, canvas.id));
      setRefreshTick((tick) => tick + 1);
      void refreshPipeline();
      toast.success('画布已刷新');
    } catch (error) {
      if (canvasEpochRef.current === epoch) toast.error(normalizeErrorMessage(error, '刷新画布失败'));
    } finally {
      setRefreshingCanvas(false);
    }
  };
  // 打开版本历史前先保存本地未保存的修改，保证历史包含当前内容、恢复不会悄悄丢弃草稿。
  const openVersionHistory = async () => {
    setMoreMenuOpen(false);
    if (savingRef.current) { toast.info('画布正在保存，请稍后再打开版本历史'); return; }
    if (hasUnsavedContent() || dirtyRef.current) {
      const saved = await saveCanvas(false);
      if (!saved) { toast.error('画布保存失败，无法打开版本历史'); return; }
    }
    setVersionHistoryOpen(true);
  };
  const reloadAfterVersionRestore = async () => {
    if (!canvas) return;
    const fresh = await getVideoCanvas(canvas.id);
    applyServerCanvas(fresh);
    removeCanvasDraft(canvasDraftKey(storyId, chapterId, canvas.id));
    setRefreshTick((tick) => tick + 1);
  };
  const refreshCanvasRef = useRef(refreshCanvas);
  useEffect(() => { refreshCanvasRef.current = refreshCanvas; });
  // 空画布引导与流水线"继续"都通过助手发送指令；同时展开助手面板让用户看到进展。
  /** 从开场引导以自动模式开始创作：助手这一轮结束后若后台编排没有自动启动，由前端补启动一次（兜底） */
  const autoStartWatchRef = useRef<{ sawBusy: boolean } | null>(null);
  const sendToAgent = useCallback((text: string, mode?: CanvasPermissionMode) => {
    if (mode === 'auto') autoStartWatchRef.current = { sawBusy: false };
    setAgentOpen(true);
    setExternalPrompt((current) => ({ id: (current?.id ?? 0) + 1, text, mode }));
  }, []);
  const pipelineSummary = useMemo(() => computePipeline(nodes, latestRun, agentStreaming || pipelineActive), [nodes, latestRun, agentStreaming, pipelineActive]);
  // 待生成节点变化后防抖预估成本，用于进度条展示；Agent 编排期间不请求。
  const pendingGeneration = pipelineSummary.pendingImages + pipelineSummary.pendingVideos;
  useEffect(() => {
    if (!canvas || agentStreaming || pipelineActive || pendingGeneration === 0) { setCostEstimate(null); return undefined; }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      estimateVideoCanvasCost(canvas.id, { graph: toGraph(nodesRef.current, edgesRef.current, canvas.version.graph) }, controller.signal)
        .then(setCostEstimate)
        .catch(() => { if (!controller.signal.aborted) setCostEstimate(null); });
    }, 800);
    return () => { window.clearTimeout(timer); controller.abort(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canvas?.id, agentStreaming, pipelineActive, pendingGeneration, nodes, edges]);

  // ---- 服务端自动编排：后台跑完 拆分 → 导演 → 资产 → 分镜编排，关掉页面也会继续 ----
  const refreshPipeline = useCallback(async () => {
    const canvasId = currentCanvasIdRef.current;
    if (!canvasId) return null;
    try {
      const { task } = await getCanvasPipeline(canvasId);
      if (currentCanvasIdRef.current === canvasId) setPipelineTask(task);
      return task;
    } catch { return null; }
  }, []);
  useEffect(() => { setPipelineTask(null); void refreshPipeline(); }, [canvas?.id, refreshPipeline]);
  useEffect(() => {
    if (!pipelineActive) return undefined;
    const timer = window.setInterval(() => { void refreshPipeline(); }, 2500);
    return () => window.clearInterval(timer);
  }, [pipelineActive, refreshPipeline]);
  // 运行器结束时拉一次最新画布，并告诉用户结果（含系统自动处理的问题）
  const previousPipelineStatusRef = useRef<string | null>(null);
  useEffect(() => {
    const status = pipelineTask?.status || null;
    const previous = previousPipelineStatusRef.current;
    previousPipelineStatusRef.current = status;
    if (!previous || !['pending', 'running', 'retrying', 'cancel_requested'].includes(previous) || !status || status === previous) return;
    if (['pending', 'running', 'retrying', 'cancel_requested'].includes(status)) return;
    void refreshCanvasRef.current();
    if (status === 'succeeded') toast.success(pipelineTask?.auto_fixes.length ? `自动编排完成，系统自动处理了 ${pipelineTask.auto_fixes.length} 个问题。检查节点后即可提交出图和视频` : '自动编排完成，检查节点后即可提交出图和视频');
    else if (status === 'failed') toast.error(`自动编排已停止：${pipelineTask?.error || pipelineTask?.message || '未知原因'}`, 8000);
  }, [pipelineTask]);
  const runPipeline = async () => {
    if (!canvas || pipelineActive) return;
    if (!(await flushBeforeAgent())) return;
    try {
      const { task } = await startCanvasPipeline(canvas.id);
      setPipelineTask(task);
    } catch (error) { toast.error(normalizeErrorMessage(error, '启动自动编排失败')); }
  };
  const runPipelineRef = useRef(runPipeline);
  useEffect(() => { runPipelineRef.current = runPipeline; });
  const pipelineSummaryRef = useRef(pipelineSummary);
  useEffect(() => { pipelineSummaryRef.current = pipelineSummary; });
  useEffect(() => {
    const watch = autoStartWatchRef.current;
    if (!watch) return undefined;
    if (agentStreaming) { watch.sawBusy = true; return undefined; }
    if (!watch.sawBusy || pipelineActive) return undefined;
    // 助手这一轮已结束。稍等一会儿让它写入的节点同步到画布，再看后台编排是不是已经自己跑起来了；
    // 没有的话（服务端启动失败、保存冲突等），自动模式不能停在半路，由这里补启动一次。
    const timer = window.setTimeout(() => {
      const current = autoStartWatchRef.current;
      if (!current) return;
      autoStartWatchRef.current = null;
      const next = pipelineSummaryRef.current.next;
      const scriptReady = pipelineSummaryRef.current.stages[0]?.state === 'done';
      if (scriptReady && next && ['split', 'director', 'assets', 'compile'].includes(next.key)) void runPipelineRef.current();
    }, 2500);
    return () => window.clearTimeout(timer);
  }, [agentStreaming, pipelineActive]);
  const cancelPipeline = async () => {
    if (!canvas) return;
    try { const { task } = await cancelCanvasPipeline(canvas.id); setPipelineTask(task); toast.info('当前这一步完成后会停下，已完成的节点保留'); }
    catch (error) { toast.error(normalizeErrorMessage(error, '取消自动编排失败')); }
  };
  // 自动保存：节点/连线修改停止 1.5 秒后自动存到服务端，用户不必惦记"保存"；
  // 助手运行、后台编排、批量生成期间暂停，避免和服务端写入互相覆盖。
  useEffect(() => {
    if (!canvas || !dirty || agentStreaming || pipelineActive || batch || running) return undefined;
    const timer = window.setTimeout(() => {
      if (savingRef.current || !hasUnsavedContent()) return;
      void saveCanvas(false);
    }, 1500);
    return () => window.clearTimeout(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges, dirty, agentStreaming, pipelineActive, batch, running, canvas?.id]);
  useEffect(() => { canvasRevisionRef.current = canvas?.definition_revision ?? 0; }, [canvas]);
  // Agent 运行期间轮询服务端画布版本：每完成一个阶段（版本递增）就把新节点渲染出来。
  useEffect(() => {
    if ((!agentStreaming && !pipelineActive) || !canvas) return undefined;
    const canvasId = canvas.id;
    let active = true;
    let busy = false;
    const timer = window.setInterval(() => {
      if (busy) return;
      busy = true;
      void getVideoCanvas(canvasId).then((next) => {
        if (!active || currentCanvasIdRef.current !== canvasId || savingRef.current) return;
        if (next.definition_revision === canvasRevisionRef.current) return;
        if (hasUnsavedContent()) return;
        applyServerCanvas(next);
      }).catch(() => undefined).finally(() => { busy = false; });
    }, 2500);
    return () => { active = false; window.clearInterval(timer); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentStreaming, pipelineActive, canvas?.id, applyServerCanvas]);

  const createConnection = useCallback((sourceNodeId: string, sourceHandle: string, targetNodeId: string, targetHandle: string) => {
    if (sourceNodeId === targetNodeId) return;
    const source = nodesRef.current.find((node) => node.id === sourceNodeId);
    const target = nodesRef.current.find((node) => node.id === targetNodeId);
    const sourceCatalog = catalog.find((item) => item.type === source?.type);
    const targetCatalog = catalog.find((item) => item.type === target?.type);
    const sourcePort = sourceCatalog?.outputs.find((port) => port.key === sourceHandle);
    const targetPort = targetCatalog?.inputs.find((port) => port.key === targetHandle);
    if (!sourcePort || !targetPort || !canConnectPorts({ side: 'output', dataType: sourcePort.type }, { side: 'input', dataType: targetPort.type })) { toast.error('这两个端口类型不兼容'); return; }
    const alreadyConnected = edgesRef.current.some((edge) => edge.source === sourceNodeId && edge.target === targetNodeId && edge.sourceHandle === sourcePort.key && edge.targetHandle === targetPort.key);
    captureHistory();
    const nextEdges = alreadyConnected
      ? edgesRef.current
      : [...edgesRef.current, { id: `edge-${crypto.randomUUID()}`, source: sourceNodeId, target: targetNodeId, sourceHandle: sourcePort.key, targetHandle: targetPort.key }];
    const syncedNodes = syncCanvasMediaReferences(nodesRef.current, nextEdges, assets) as CanvasNode[];
    setNodes(syncedNodes);
    setEdges(nextEdges);
    const syncedReference = syncedNodes.some((node) => node.id === targetNodeId && Array.isArray(node.data.config?.reference_asset_ids) && node.data.config.reference_asset_ids.length > 0);
    markDirty();
    toast.success(syncedReference ? '连线已创建，资源已同步到参考素材' : '连线已创建');
  }, [assets, catalog, captureHistory, markDirty]);

  const duplicateNode = useCallback((nodeId: string) => {
    const node = nodesRef.current.find((item) => item.id === nodeId);
    if (!node) return;
    captureHistory();
    const base = { ...node, id: `${node.type}-${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`, position: { x: node.position.x + 42, y: node.position.y + 42 }, data: { ...node.data, config: { ...node.data.config } } };
    // 组框副本剥离成员关系（否则副本会跟着拖动原成员）
    const copy = stripContainerMembership(base);
    setNodes((current) => [...current, copy]);
    setSelectedNodeId(copy.id);
    setSelectedNodeIds([copy.id]);
    markDirty();
  }, [captureHistory, markDirty]);

  const removeNodes = useCallback((ids: string[]) => {
    if (!ids.length) return;
    captureHistory();
    setNodes((current) => current.filter((node) => !ids.includes(node.id)));
    setEdges((current) => current.filter((edge) => !ids.includes(edge.source) && !ids.includes(edge.target)));
    setSelectedNodeIds([]); setSelectedNodeId(null); markDirty();
  }, [captureHistory, markDirty]);

  const deleteConnection = useCallback((connectionId: string) => {
    captureHistory();
    setEdges((current) => current.filter((edge) => edge.id !== connectionId));
    markDirty();
  }, [captureHistory, markDirty]);

  const clipboardRef = useRef<{ nodes: CanvasNode[]; edges: CanvasEdge[] } | null>(null);
  const handleCopy = useCallback((ids: string[]) => {
    if (!ids.length) return;
    const idSet = new Set(ids);
    const copiedNodes = nodesRef.current.filter((node) => idSet.has(node.id));
    if (!copiedNodes.length) return;
    clipboardRef.current = { nodes: copiedNodes, edges: edgesRef.current.filter((edge) => idSet.has(edge.source) && idSet.has(edge.target)) };
    toast.success(`已复制 ${copiedNodes.length} 个节点`);
  }, []);
  const handlePaste = useCallback(() => {
    const clip = clipboardRef.current;
    if (!clip || !clip.nodes.length) return;
    captureHistory();
    const idMap = new Map<string, string>();
    for (const node of clip.nodes) idMap.set(node.id, `${node.type}-${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`);
    const created = clip.nodes.map((node) => {
      const newId = idMap.get(node.id)!;
      const base = { ...node, id: newId, position: { x: node.position.x + 42, y: node.position.y + 42 }, data: { ...node.data, config: { ...node.data.config }, ui: { ...(node.data.ui || {}) } } };
      // 组框成员名单经 idMap 重映射；没一起复制的成员丢弃
      return remapContainerMembership(base, idMap);
    });
    const createdEdges = clip.edges.map((edge) => ({ id: `edge-${crypto.randomUUID()}`, source: idMap.get(edge.source)!, target: idMap.get(edge.target)!, sourceHandle: edge.sourceHandle, targetHandle: edge.targetHandle, data: edge.data }));
    setNodes((current) => [...current, ...created]);
    setEdges((current) => [...current, ...createdEdges]);
    setSelectedNodeIds(created.map((node) => node.id));
    setSelectedNodeId(created.length === 1 ? created[0].id : null);
    markDirty();
  }, [captureHistory, markDirty]);

  const handleNodeMove = useCallback((initialNodes: { id: string; x: number; y: number }[], delta: { x: number; y: number }) => {
    if ((delta.x !== 0 || delta.y !== 0) && !moveCaptureRef.current) {
      moveCaptureRef.current = true;
      captureHistory();
      // 捕获拖拽闭包的起始位置：拖组框时把成员（含嵌套）一起纳入，后续帧用固定起点避免叠加
      const expanded = new Set(expandGroupMove(initialNodes.map((item) => item.id), nodesRef.current, edgesRef.current));
      const origins = new Map<string, { x: number; y: number }>();
      for (const node of nodesRef.current) {
        if (expanded.has(node.id)) origins.set(node.id, { x: node.position.x, y: node.position.y });
      }
      for (const item of initialNodes) origins.set(item.id, { x: item.x, y: item.y });
      dragOriginsRef.current = origins;
    }
    const origins = dragOriginsRef.current;
    setNodes((current) => current.map((node) => {
      const origin = origins?.get(node.id) || initialNodes.find((item) => item.id === node.id);
      return origin ? { ...node, position: { x: origin.x + delta.x, y: origin.y + delta.y } } : node;
    }));
    markDirty();
  }, [captureHistory, markDirty]);

  const handleNodeResize = useCallback((nodeId: string, width: number, height: number, position: { x: number; y: number }) => {
    setNodes((current) => current.map((node) => node.id === nodeId ? { ...node, position, data: { ...node.data, ui: { width, height } } } : node));
    markDirty();
  }, [markDirty]);

  const handleNodeResizeEnd = useCallback((nodeId: string) => {
    void nodeId;
  }, []);

  /**
   * 本地成组：框选/对话框选中的节点收纳进一个组框（container）。
   * 组框包住成员、成员边指向组框（后端运行时沿边聚合素材），全程走本地状态可撤销。
   */
  const createGroupFromSelection = useCallback((memberIds?: string[], name?: string) => {
    const idList = Array.from(new Set(memberIds ?? selectedNodeIds));
    const members = nodesRef.current.filter((node) => idList.includes(node.id));
    if (members.length < 1) { toast.info('请先框选要收纳进组的节点'); return; }
    const bounds = computeGroupBounds(members);
    if (!bounds) return;
    captureHistory();
    const containerId = `container-${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`;
    const groupName = (name || '').trim() || `节点组 ${nodesRef.current.filter((node) => node.type === 'container').length + 1}`;
    const groupNode: CanvasNode = {
      id: containerId,
      type: 'container',
      position: { x: bounds.x, y: bounds.y },
      data: {
        label: groupName,
        config: { node_role: 'container', node_label: groupName, member_ids: members.map((member) => member.id) },
        ui: { width: bounds.width, height: bounds.height },
      },
    };
    const memberEdges: CanvasEdge[] = members.flatMap((member) => {
      const outputKey = catalog.find((item) => item.type === member.type)?.outputs?.[0]?.key;
      if (!outputKey) return [];
      return [{
        id: `edge-${crypto.randomUUID()}`,
        source: member.id,
        target: containerId,
        sourceHandle: outputKey,
        targetHandle: 'items',
        data: { member: true },
      }];
    });
    setNodes((current) => [...current, groupNode]);
    setEdges((current) => [...current, ...memberEdges]);
    setSelectedNodeId(containerId);
    setSelectedNodeIds([containerId]);
    markDirty();
    toast.success(`已将 ${members.length} 个节点收纳为「${groupName}」`);
  }, [captureHistory, catalog, markDirty, selectedNodeIds]);

  const applyLocalCanvasGraph = useCallback((graph: VideoCanvasGraph, incomingRevision = 0) => {
    if (!graph || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) return;
    if (incomingRevision < clientRevisionRef.current) return;
    const projected = projectLegacyGraph(graph);
    const projectedEdges = projected.edges as CanvasEdge[];
    setNodes(toCanvasNodes(projected) as CanvasNode[]);
    setEdges(projectedEdges);
    clientRevisionRef.current = Math.max(clientRevisionRef.current, incomingRevision) + 1;
    markDirty();
    window.setTimeout(persistLocalDraft, 0);
    // 兼容仍返回 local 写模式的旧服务端：先更新界面草稿，再非阻塞地落库，避免网关下一阶段只读数据库时看不到节点。
    window.setTimeout(() => { void saveCanvas(false); }, 0);
  }, [markDirty, persistLocalDraft, saveCanvas]);

  const interaction = useCanvasInteractions({
    containerRef: surfaceRef,
    nodes: nodes as CanvasSceneNode[],
    catalog,
    viewport: { x: viewport.x, y: viewport.y, scale: viewport.k },
    selectedNodeIds,
    tool,
    canUndo: historyFlags.canUndo,
    canRedo: historyFlags.canRedo,
    onViewportChange: (next) => updateViewport({ x: next.x, y: next.y, k: next.scale }),
    onSelectionChange: (ids) => { moveCaptureRef.current = false; dragOriginsRef.current = null; setSelectedNodeIds(ids); setSelectedNodeId(ids.length === 1 ? ids[0] : null); },
    onNodeMove: handleNodeMove,
    onCreateConnection: createConnection,
    onDeleteConnection: deleteConnection,
    onDuplicateNode: duplicateNode,
    onDeleteNodes: removeNodes,
    onUndo: undo,
    onRedo: redo,
    onResizeStart: captureHistory,
    onCopyNodes: handleCopy,
    onPasteNodes: handlePaste,
  });

  useEffect(() => {
    const keyDown = (event: KeyboardEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      if (target?.matches('input, textarea, select, [contenteditable="true"]')) return;
      if (event.key.toLowerCase() === 'f' && selectedNodeIds.length) {
        event.preventDefault();
        const selected = nodes.filter((node) => selectedNodeIds.includes(node.id));
        if (selected.length) {
          const minX = Math.min(...selected.map((node) => node.position.x));
          const minY = Math.min(...selected.map((node) => node.position.y));
          updateViewport({ x: 240 - minX * viewport.k, y: 150 - minY * viewport.k, k: viewport.k });
        }
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'g') {
        event.preventDefault();
        createGroupFromSelection();
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'd' && selectedNode) {
        event.preventDefault();
        duplicateNode(selectedNode.id);
      }
    };
    window.addEventListener('keydown', keyDown);
    return () => window.removeEventListener('keydown', keyDown);
  }, [createGroupFromSelection, duplicateNode, nodes, selectedNode, selectedNodeIds, updateViewport, viewport.k]);

  // 聚焦模式：选中带输入框的节点后，画布自动把节点居中到输入框上方；取消选中后恢复进入前的视口
  const focusedNodeId = selectedNodeIds.length === 1 ? (() => { const target = nodes.find((node) => node.id === selectedNodeIds[0]); return target && supportsNodeInspector(target.type) ? target.id : null; })() : null;
  useEffect(() => { focusRestoreRef.current = null; }, [canvas?.id]);
  useEffect(() => {
    const animateTo = (to: ViewportTransform) => {
      if (focusAnimationRef.current !== null) cancelAnimationFrame(focusAnimationRef.current);
      const from = viewportRef.current;
      const startedAt = performance.now();
      const step = (now: number) => {
        const progress = Math.min(1, (now - startedAt) / 220);
        const eased = 1 - Math.pow(1 - progress, 3);
        setViewport({ x: from.x + (to.x - from.x) * eased, y: from.y + (to.y - from.y) * eased, k: from.k + (to.k - from.k) * eased });
        focusAnimationRef.current = progress < 1 ? requestAnimationFrame(step) : null;
      };
      focusAnimationRef.current = requestAnimationFrame(step);
    };
    if (!focusedNodeId) {
      const restore = focusRestoreRef.current;
      focusRestoreRef.current = null;
      if (restore) animateTo(restore);
      return;
    }
    let cancelled = false;
    let observer: ResizeObserver | null = null;
    const focus = () => {
      const target = nodesRef.current.find((node) => node.id === focusedNodeId);
      const rect = surfaceRef.current?.getBoundingClientRect();
      if (cancelled || !target || !rect || rect.width <= 0) return;
      if (!focusRestoreRef.current) focusRestoreRef.current = viewportRef.current;
      // 以输入框实际高度为准预留底部空间（候选结果、参考图会改变其高度）
      const panelRect = surfaceRef.current?.querySelector<HTMLElement>('[data-canvas-inspector]')?.getBoundingClientRect();
      const occupied = panelRect ? Math.max(0, rect.bottom - panelRect.top) : 92 + 330;
      animateTo(computeFocusViewport({
        node: { x: target.position.x, y: target.position.y, ...nodeSize(target as CanvasSceneNode) },
        bounds: { width: rect.width, height: rect.height },
        reserved: { top: 64, bottom: occupied + 16 },
      }));
    };
    const start = () => {
      if (cancelled || pointerGestureRef.current.moved) return;
      focus();
      const panel = surfaceRef.current?.querySelector<HTMLElement>('[data-canvas-inspector]');
      if (panel && typeof ResizeObserver !== 'undefined') {
        let first = true;
        observer = new ResizeObserver(() => { if (first) { first = false; return; } focus(); });
        observer.observe(panel);
      }
    };
    // 等指针抬起后再聚焦：拖拽节点时不移动视口，避免拖拽中画面跳动
    const timer = window.setTimeout(() => {
      if (pointerGestureRef.current.down) window.addEventListener('pointerup', () => window.setTimeout(start, 0), { once: true });
      else start();
    }, 120);
    return () => { cancelled = true; observer?.disconnect(); window.clearTimeout(timer); };
  }, [focusedNodeId]);
  useEffect(() => {
    const onDown = (event: PointerEvent) => {
      pointerGestureRef.current = { down: true, moved: false, x: event.clientX, y: event.clientY };
      const target = event.target instanceof Element ? event.target : null;
      if (target?.closest('[data-node-id]') && !target.closest('[data-canvas-inspector]')) setInspectorHeld(true);
    };
    const onMove = (event: PointerEvent) => { const g = pointerGestureRef.current; if (g.down && Math.hypot(event.clientX - g.x, event.clientY - g.y) > 5) g.moved = true; };
    const onUp = () => { pointerGestureRef.current.down = false; setInspectorHeld(false); };
    window.addEventListener('pointerdown', onDown, true); window.addEventListener('pointermove', onMove, true); window.addEventListener('pointerup', onUp, true);
    window.addEventListener('pointercancel', onUp, true); window.addEventListener('blur', onUp);
    return () => { window.removeEventListener('pointerdown', onDown, true); window.removeEventListener('pointermove', onMove, true); window.removeEventListener('pointerup', onUp, true); window.removeEventListener('pointercancel', onUp, true); window.removeEventListener('blur', onUp); if (focusAnimationRef.current !== null) cancelAnimationFrame(focusAnimationRef.current); };
  }, []);

  if (loading) return <div className="flex h-full items-center justify-center bg-[#111214] text-sm text-white/55"><Loader2 className="mr-2 h-4 w-4 animate-spin" />正在打开创作画布</div>;
  if (!canvas) return <div className="flex h-full items-center justify-center bg-[#111214] p-6 text-white"><div className="w-full max-w-md rounded-xl border border-white/10 bg-[#202226] p-8 text-center"><Boxes className="mx-auto h-10 w-10 text-white/75" /><h2 className="mt-4 text-lg font-semibold">打开一个创作画布</h2><p className="mt-2 text-sm leading-6 text-white/45">从空白节点图开始，或将当前列表工作流导入为可编辑流程。</p><button type="button" onClick={() => void createBlankCanvas()} className="mt-6 inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-semibold text-[#15171a]"><Plus className="h-4 w-4" />新建空白画布</button></div></div>;

  const editorViewport: CanvasViewport = { x: viewport.x, y: viewport.y, scale: viewport.k };
  const inspectorNode = !inspectorHeld && selectedNodeIds.length === 1 ? nodes.find((node) => node.id === selectedNodeIds[0]) || null : null;
  const canvasRect = canvasSize.width > 0 ? canvasSize : null;
  const panelWidth = canvasRect ? Math.min(860, Math.max(280, canvasRect.width - 32)) : 860;
  // 输入框固定在画布底部居中（工具栏上方），节点由聚焦模式移到其上方
  const panelLeft = 16;
  const panelTop = 76;
  const inspectorCandidates = inspectorNode ? collectReferenceCandidates(nodes, edges, inspectorNode.id) : [];
  // 把画布上已有图片的节点连成当前节点的参考图（图片节点走 references 端口，视频节点走 image 端口）
  const connectReference = (sourceId: string, targetId: string) => {
    const source = nodesRef.current.find((node) => node.id === sourceId);
    const target = nodesRef.current.find((node) => node.id === targetId);
    const output = catalog.find((item) => item.type === source?.type)?.outputs.find((port) => port.type === 'image');
    if (!source || !target || !output) { toast.error('这个节点不能作为图片参考'); return; }
    createConnection(sourceId, output.key, targetId, target.type === 'video' ? 'image' : 'references');
  };
  // 只移除这个节点直接连过来的线；来自节点组的参考需要在组里调整
  const disconnectReference = (sourceId: string, targetId: string) => {
    const nextEdges = edgesRef.current.filter((edge) => !(edge.source === sourceId && edge.target === targetId));
    if (nextEdges.length === edgesRef.current.length) { toast.info('这张参考来自节点组，请在节点组里调整'); return; }
    captureHistory();
    setNodes(syncCanvasMediaReferences(nodesRef.current, nextEdges, assets) as CanvasNode[]);
    setEdges(nextEdges);
    markDirty();
  };
  const inspectorConnectedPreviews = inspectorNode ? collectConnectedReferencePreviews(nodes, edges, inspectorNode.id) : [];
  const fitAll = () => {
    const rect = surfaceRef.current?.getBoundingClientRect();
    if (!rect || !nodes.length) { updateViewport({ x: rect ? rect.width / 2 : 260, y: rect ? rect.height / 2 : 120, k: 1 }); return; }
    const left = Math.min(...nodes.map((node) => node.position.x)); const top = Math.min(...nodes.map((node) => node.position.y));
    const right = Math.max(...nodes.map((node) => node.position.x + (node.data.ui?.width || 420))); const bottom = Math.max(...nodes.map((node) => node.position.y + (node.data.ui?.height || 236)));
    const k = Math.min(2, Math.max(.1, Math.min((rect.width - 160) / Math.max(1, right - left), (rect.height - 200) / Math.max(1, bottom - top))));
    updateViewport({ x: (rect.width - (right - left) * k) / 2 - left * k, y: (rect.height - (bottom - top) * k) / 2 - top * k, k });
  };
  const autoLayoutCanvas = () => {
    // 组框不参与分层排版：位置/尺寸由成员推导，整理后由 refit 自动贴回
    const currentNodes = nodesRef.current.filter((node) => node.type !== 'container');
    if (!currentNodes.length) return;
    // 排版规则见 video-canvas/autoLayout.ts：流程节点按连线分层，资产按类型分三栏（角色一列、道具一列、场景一列）
    const positions = computeAutoLayout(
      currentNodes.map((node) => ({ id: node.id, type: node.type, width: nodeSize(node).width, height: nodeSize(node).height, x: node.position.x, y: node.position.y, assetRole: String(node.data.config?.asset_role || '') })),
      edgesRef.current.map((edge) => ({ source: edge.source, target: edge.target })),
    );
    captureHistory();
    setNodes((current) => current.map((node) => ({ ...node, position: positions.get(node.id) || node.position })));
    markDirty();
    toast.success('画布节点已自动整理');
  };
  const addNodeFromTool = (type: string) => { const item = catalog.find((entry) => entry.type === type); if (!item) { toast.info('当前画布仅支持文本、图片、视频节点'); return; } captureHistory(); addCatalogNode(item); };
  // 在剧本审核节点里手动编辑剧本：写回剧本节点和审核节点的对照文本，并标记“场景还是按旧剧本拆的”
  const editScreenplayFromReview = (sceneNodeId: string, text: string) => {
    const scene = nodesRef.current.find((node) => node.id === sceneNodeId);
    if (!scene) return;
    const screenplayId = String(scene.data.config?.source_screenplay_node || '');
    captureHistory();
    setNodes((current) => current.map((node) => {
      if (screenplayId && node.id === screenplayId) return { ...node, data: { ...node.data, config: { ...node.data.config, content: text } } };
      if (node.id === sceneNodeId) return { ...node, data: { ...node.data, config: { ...node.data.config, source_content: text, script_edited: true, ...(node.data.config?.director_plan ? { director_plan_stale: true } : {}) } } };
      return node;
    }));
    markDirty();
    toast.success('剧本已修改。场景还是按旧剧本拆的，点“按最新剧本重新拆分”更新');
  };
  // 剧本节点拆分：调用后端，把视频单元组以网格布局落到画布（可撤销，保存走既有确认流）
  const splitScreenplayNode = async (nodeId: string) => {
    if (!canvas || splittingNodeId) return;
    const sourceNode = nodes.find((node) => node.id === nodeId);
    if (!sourceNode) return;
    setSplittingNodeId(nodeId);
    try {
      // 后端按已保存的图定位剧本节点：拆分前先静默保存当前画布（含未保存的导入/编辑内容）
      let targetCanvas = canvas;
      if (dirty) {
        const saved = await saveCanvas(false);
        if (!saved) return;
        targetCanvas = saved;
      }
      const result = await screenplaySplit(targetCanvas.id, nodeId);
      captureHistory();
      // 起点偏移按源节点实际宽度计算，避免大节点与剧本节点重叠
      const sourceWidth = Number(sourceNode.data.ui?.width) || 300;
      const baseX = sourceNode.position.x + sourceWidth + 80;
      const baseY = sourceNode.position.y;
      // v3.1 流程：拆分产物为单个「场景审核聚合节点」，全部场次垂直排列统一审批
      const scenes = result.units.map((unit) => ({
        scene_id: unit.scene_id ?? unit.unit_index,
        title: unit.title || `场景 ${unit.unit_index}`,
        location: unit.location || '',
        time_of_day: unit.time_of_day || '',
        characters: Array.isArray(unit.characters) ? unit.characters.filter((c) => typeof c === 'string') : [],
        scene_purpose: unit.scene_purpose || '',
        visual_anchors: unit.visual_anchors || '',
        importance: 'medium',
        approved: false,
        duration_seconds: unit.duration_seconds,
        duration_reason: unit.duration_reason || '',
        beats: Array.isArray(unit.beats) ? unit.beats : [],
        transition_to_next_scene: unit.transition_to_next_scene || '',
      }));
      const existingScene = nodes.find((node) => node.type === 'scene' && String(node.data.config?.source_screenplay_node || '') === nodeId);
      const stableSceneNodeId = unitNodeId(nodeId, 'scene-review').replace(/^dir-/, 'split-');
      const sceneNode: CanvasNode = {
        id: existingScene?.id || stableSceneNodeId,
        type: 'scene',
        position: existingScene?.position || { x: baseX, y: baseY },
        data: {
          label: `剧本审核（${scenes.length} 场）`,
          nodeType: 'scene',
          ui: existingScene?.data.ui?.width && existingScene.data.ui.height && existingScene.data.ui.width >= 1100 ? existingScene.data.ui : { width: 1280, height: 800 },
          config: {
            scenes,
            approved: false,
            scene_count: scenes.length,
            source_screenplay_node: nodeId,
            source_content_hash: result.content_hash,
            // 小说改写来的剧本：带上来源章节引用，审核节点据此取回小说原文与剧本对照
            source_refs: Array.isArray((sourceNode.data.config || {}).source_refs) ? (sourceNode.data.config || {}).source_refs : [],
            // 左栏对照用：拆分时的剧本全文（截断保护，避免图 JSON 过大）
            source_content: (() => {
              const raw = String((sourceNode.data.config || {}).content ?? (sourceNode.data.config || {}).screenplay ?? '');
              return raw.length > 30000 ? `${raw.slice(0, 30000)}\n\n[内容过长已截断]` : raw;
            })(),
          },
        },
      };
      const newNodes: CanvasNode[] = [sceneNode];
      const newEdges: CanvasEdge[] = [{
        id: `e-${nodeId}-${sceneNode.id}`,
        source: nodeId,
        sourceHandle: 'screenplay',
        target: sceneNode.id,
        targetHandle: 'screenplay',
      }];
      const matchingSceneIds = nodesRef.current
        .filter((node) => node.type === 'scene' && String(node.data.config?.source_screenplay_node || '') === nodeId)
        .map((node) => node.id);
      const obsoleteIds = new Set([
        ...matchingSceneIds.filter((id) => id !== sceneNode.id),
        ...nodesRef.current
          .filter((node) => matchingSceneIds.includes(String(node.data.config?.source_scene_node || '')))
          .map((node) => node.id),
      ]);
      setNodes((current) => {
        const hasExistingScene = current.some((node) => node.id === sceneNode.id);
        const updated = current
          .filter((node) => !obsoleteIds.has(node.id))
          .map((node) => {
            if (node.id === nodeId) {
              return { ...node, data: { ...node.data, config: { ...(node.data.config || {}), content_hash: result.content_hash } } };
            }
            return node.id === sceneNode.id ? sceneNode : node;
          });
        return hasExistingScene ? updated : [...updated, ...newNodes];
      });
      setEdges((current) => [
        ...current.filter((edge) => !obsoleteIds.has(edge.source) && !obsoleteIds.has(edge.target) && edge.target !== sceneNode.id && edge.source !== sceneNode.id),
        ...newEdges,
      ]);
      markDirty();
      if (result.stale_detected) toast.warning('剧本内容自上次拆分后已被修改，本次按最新内容拆分');
      toast.success(`拆分完成：${result.unit_count} 个场景已放入审核节点${result.truncated ? `（超过上限已截断到 ${SCREENPLAY_SPLIT_MAX_UNITS} 个）` : ''}。统一审批通过后可编译为视频节点`);
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '剧本拆分失败'));
    } finally {
      setSplittingNodeId(null);
    }
  };
  // 章节导入完成：把改写后的剧本落到新剧本节点

  const handleScreenplayImported = (screenplayText: string, sourceRefs: { story_id: number; chapter_id: number; title: string; content_hash: string }[]) => {
    captureHistory();
    const node: CanvasNode = {
      id: `screenplay-import-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
      type: 'screenplay',
      position: (() => { const rect = surfaceRef.current?.getBoundingClientRect(); const view = viewportRef.current; return rect ? { x: (rect.width / 2 - view.x) / view.k - 150, y: (rect.height / 2 - view.y) / view.k - 90 } : { x: 300, y: 200 }; })(),
      data: {
        label: `剧本（导入 ${sourceRefs.length} 章）`,
        nodeType: 'screenplay',
        config: { content: screenplayText, source_refs: sourceRefs, content_hash: '' },
      },
    };
    setNodes((current) => [...current, node]);
    markDirty();
    setImportDialogOpen(false);
    const startMode = importModeRef.current;
    importModeRef.current = null;
    if (startMode === null) {
      toast.success(`已生成剧本节点（${Math.round(screenplayText.length / 100) / 10}k 字），可编辑后点击「AI 拆分」`);
      return;
    }
    // 从开场引导导入：不让用户再去找按钮，自动开启后续流程。自动模式交给后台运行器一路编排；
    // 询问变更模式让助手逐阶段提方案，由用户确认。稍等一拍，让新剧本节点先进入画布并保存。
    toast.success(`已导入剧本（${Math.round(screenplayText.length / 100) / 10}k 字），正在自动开始编排`);
    window.setTimeout(() => {
      if (startMode === 'auto') void runPipelineRef.current();
      else sendToAgent(continuePrompt('split'), startMode);
    }, 300);
  };
  // 场景节点字段写回（partial 合并进 config，含 beats 整体替换）
  // 编辑场景/节拍后导演方案自动过期；生成/应用方案自身的写回不触发过期
  const updateSceneNodeConfig = (nodeId: string, partial: Record<string, unknown>) => {
    captureHistory();
    setNodes((current) => current.map((node) => {
      if (node.id !== nodeId) return node;
      const config = node.data.config || {};
      const hasPlan = Boolean(config.director_plan_hash);
      const stale = 'scenes' in partial && hasPlan;
      return { ...node, data: { ...node.data, config: { ...config, ...partial, ...(stale ? { director_plan_stale: true } : {}) } } };
    }));
    markDirty();
  };
  // AI 导演编排预览：生成可审阅方案并写入场景节点 config（不创建视频节点）
  const generateDirectorPlanForNode = async (nodeId: string) => {
    if (!canvas || planBusyNodeId || compilingNodeId) return;
    const sceneNode = nodes.find((node) => node.id === nodeId);
    if (!sceneNode) return;
    setPlanBusyNodeId(nodeId);
    setDirectorError(null);
    try {
      // 后端按已保存的图定位场景和剧本：编排前先静默保存当前画布
      let targetCanvas = canvas;
      if (dirty) {
        const saved = await saveCanvas(false);
        if (!saved) return;
        targetCanvas = saved;
      }
      const result = await generateDirectorPlan(targetCanvas.id, {
        scene_node_id: nodeId,
        expected_definition_revision: targetCanvas.definition_revision,
      });
      updateSceneNodeConfig(nodeId, {
        director_plan: result.plan,
        director_plan_hash: result.plan_hash,
        director_plan_stale: false,
        director_source_screenplay_hash: result.source_screenplay_hash,
        director_source_scene_revision: result.source_scene_revision,
      });
      toast.success(`导演编排完成：${result.unit_count} 个视频单元，共 ${result.total_duration_seconds} 秒。请审阅后应用`);
    } catch (error) {
      const message = normalizeErrorMessage(error, '导演编排失败');
      setDirectorError(message);
      toast.error(message);
    } finally {
      setPlanBusyNodeId(null);
    }
  };
  // 应用导演方案：编译为视频节点组（稳定节点 ID + sequence 布局，重复应用不叠加）
  // AI 资产分析：剧本 → 角色/场景/道具资产提示词，渲染为画布资产节点（先出参考图，再绑定保证一致性）
  const analyzeAssetsForNode = async (nodeId: string) => {
    if (!canvas || assetAnalysisNodeId) return;
    const sceneNode = nodes.find((node) => node.id === nodeId);
    if (!sceneNode) return;
    setAssetAnalysisNodeId(nodeId);
    try {
      // 后端按已保存的图读取场景与剧本：分析前先静默保存当前画布
      let targetCanvas = canvas;
      if (dirty) {
        const saved = await saveCanvas(false);
        if (!saved) return;
        targetCanvas = saved;
      }
      const result = await analyzeCanvasAssets(targetCanvas.id, nodeId, targetCanvas.definition_revision);
      captureHistory();
      // 按（类型, 名称）对上本场景已有的资产节点——不管是流水线、助手还是上次手动分析创建的：
      // 对得上的原地更新（保留位置、连线、已生成的图，只有提示词变了才清掉旧图）；
      // 对不上的旧节点：没生成过图、没锁定的直接移除（含以前重复分析残留的），生成过的标记过期并保留；新增的追加到各自那一列的末尾。
      const assetKinds = ['character', 'scene', 'prop'];
      const cfgOf = (node: CanvasNode) => (node.data.config || {}) as Record<string, unknown>;
      const previousNodes = nodes.filter((node) => node.id !== nodeId && node.type === 'image' && assetKinds.includes(String(cfgOf(node).asset_role || '')) && (cfgOf(node).asset_scene_node === nodeId || cfgOf(node).source_scene_node === nodeId));
      const keyOf = (role: unknown, name: unknown) => `${String(role)}:${String(name).trim()}`;
      const previousByKey = new Map<string, CanvasNode>();
      for (const node of previousNodes) {
        const key = keyOf(cfgOf(node).asset_role, cfgOf(node).asset_name);
        const existing = previousByKey.get(key);
        if (!existing || (cfgOf(existing).stale && !cfgOf(node).stale)) previousByKey.set(key, node);
      }
      const roleLabels: Record<string, string> = { character: '角色', scene: '场景', prop: '道具' };
      const sceneBox = { position: sceneNode.position, width: Number(sceneNode.data.ui?.width) || undefined };
      const placed: Array<{ kind: AssetKind; position: { x: number; y: number } }> = previousNodes.filter((node) => !cfgOf(node).stale).map((node) => ({ kind: cfgOf(node).asset_role as AssetKind, position: node.position }));
      const matchedIds = new Set<string>();
      const updatedById = new Map<string, CanvasNode>();
      const createdNodes: CanvasNode[] = [];
      for (const asset of result.assets as CanvasSceneAsset[]) {
        const sceneIds = (asset.scene_ids || []).map(String);
        const matched = previousByKey.get(keyOf(asset.role, asset.name));
        if (matched) {
          matchedIds.add(matched.id);
          const config = cfgOf(matched);
          const locked = Boolean(config.locked);
          const promptChanged = !locked && config.prompt !== asset.prompt;
          const nextConfig: Record<string, unknown> = {
            ...config, asset_role: asset.role, asset_name: asset.name, asset_scene_node: nodeId, source_scene_node: nodeId, scene_ids: sceneIds, stale: false,
            ...(locked ? {} : { prompt: asset.prompt }),
            ...(asset.profile && !config.profile_edited ? { profile: asset.profile } : {}),
          };
          if (promptChanged) delete nextConfig.asset_id;
          updatedById.set(matched.id, { ...matched, data: { ...matched.data, config: nextConfig, ...(promptChanged ? { result: undefined } : {}) } });
          continue;
        }
        const nameHash = Math.abs([...asset.name].reduce((hash, char) => (hash * 31 + (char.codePointAt(0) || 0)), 7) % 2176782336).toString(36).slice(0, 6);
        const position = nextAssetSlot(sceneBox, asset.role as AssetKind, placed);
        placed.push({ kind: asset.role as AssetKind, position });
        createdNodes.push({
          id: `ast-${nodeId}-${asset.role}-${nameHash}`.slice(0, 64),
          type: 'image',
          position,
          data: {
            label: `${roleLabels[asset.role] || asset.role}·${asset.name}`,
            nodeType: 'image',
            config: {
              node_role: 'asset',
              asset_role: asset.role,
              asset_name: asset.name,
              asset_scene_node: nodeId,
              source_scene_node: nodeId,
              scene_ids: sceneIds,
              ...(asset.profile ? { profile: asset.profile } : {}),
              prompt: asset.prompt,
              size: '1024x1024',
              aspect_ratio: '1:1',
            },
          },
        });
      }
      const removedIds = new Set<string>();
      const staleIds = new Set<string>();
      for (const node of previousNodes) {
        if (matchedIds.has(node.id) || cfgOf(node).locked) continue;
        if (nodeHasResult(node)) { if (!cfgOf(node).stale) staleIds.add(node.id); } else removedIds.add(node.id);
      }
      setNodes((current) => [
        ...current.filter((node) => !removedIds.has(node.id)).map((node) => updatedById.get(node.id) ?? (staleIds.has(node.id) ? { ...node, data: { ...node.data, config: { ...node.data.config, stale: true } } } : node)),
        ...createdNodes.filter((node) => !current.some((item) => item.id === node.id)),
      ]);
      setEdges((current) => current.filter((edge) => !removedIds.has(edge.source) && !removedIds.has(edge.target)));
      updateSceneNodeConfig(nodeId, { asset_analysis: result.assets, asset_analysis_stale: false, asset_candidates: result.candidates || [] });
      markDirty();
      const counts = (result.assets as CanvasSceneAsset[]).reduce<Record<string, number>>((acc, asset) => { acc[asset.role] = (acc[asset.role] || 0) + 1; return acc; }, {});
      toast.success(`资产分析完成：角色 ${counts.character || 0} · 场景 ${counts.scene || 0} · 道具 ${counts.prop || 0}${result.candidates?.length ? `，另有 ${result.candidates.length} 个次要场景/道具可在资产面板按需添加` : ''}${result.warnings?.length ? `（${result.warnings.length} 条提示）` : ''}`);
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '资产分析失败'));
    } finally {
      setAssetAnalysisNodeId(null);
    }
  };
  const applyDirectorPlan = async (nodeId: string) => {
    if (!canvas || compilingNodeId) return;
    const sceneNode = nodes.find((node) => node.id === nodeId);
    if (!sceneNode) return;
    const config = (sceneNode.data.config || {}) as Record<string, unknown>;
    const directorPlan = config.director_plan as DirectorPlan | undefined;
    const directorPlanHash = typeof config.director_plan_hash === 'string' ? config.director_plan_hash : '';
    if (!directorPlan || !directorPlanHash) {
      toast.error('请先执行 AI 导演编排，再生成视频节点组');
      return;
    }
    if (config.director_plan_stale) {
      toast.error('场景内容已变化，导演方案已过期，请重新编排');
      return;
    }
    setCompilingNodeId(nodeId);
    try {
      // 审批状态和场景编辑先保存到最新画布版本，后端编译才能读取 approved=true。
      let targetCanvas = canvas;
      if (dirty) {
        const saved = await saveCanvas(false);
        if (!saved) return;
        targetCanvas = saved;
      }
      const result = await compileScenes(targetCanvas.id, [nodeId], {
        directorPlan,
        directorPlanHash,
        expectedDefinitionRevision: targetCanvas.definition_revision,
      });
      if (!result.compiled.length) {
        const reason = result.skipped[0]?.reason || '未知原因';
        toast.error(`编译失败：${reason}`);
        return;
      }
      captureHistory();
      // 替换本场景此前编译出的导演节点（分镜图+视频，稳定 ID，不叠加重复组）
      const previousIds = new Set(nodes
        .filter((node) => node.id !== nodeId && (node.data.config as Record<string, unknown> | undefined)?.source_scene_node === nodeId && (node.data.config as Record<string, unknown>).unit_id)
        .map((node) => node.id));
      const compiled: CompiledSceneUnit[] = result.compiled;
      const anchor = { x: sceneNode.position.x + (Number(sceneNode.data.ui?.width) || 300) + 60, y: sceneNode.position.y };
      const existingRects = nodes
        .filter((node) => !previousIds.has(node.id) && node.id !== nodeId)
        .map((node) => ({ x: node.position.x, y: node.position.y, width: Number(node.data.ui?.width) || 420, height: Number(node.data.ui?.height) || 236 }));
      // 生成顺序：分镜图（用户先审核画面）→ 图生视频节点
      const positions = layoutDirectorUnits(
        compiled.map((unit) => ({ sequence: unit.sequence, unit_id: unit.unit_id })),
        anchor,
        existingRects,
        { nodeWidth: 420, nodeHeight: 236, gapX: 40, gapY: 60, maxPerRow: 4 },
      );
      const occupied: { x: number; y: number; width: number; height: number }[] = [
        ...existingRects,
        ...compiled.map((unit) => { const pos = positions.get(unit.unit_id) || anchor; return { x: pos.x, y: pos.y, width: 420, height: 236 }; }),
      ];
      const hits = (rect: { x: number; y: number; width: number; height: number }) => occupied.some((other) => rect.x < other.x + other.width && rect.x + rect.width > other.x && rect.y < other.y + other.height && rect.y + rect.height > other.y);
      const placeStoryboard = (videoPos: { x: number; y: number }) => {
        const candidates = [
          { x: videoPos.x - 456, y: videoPos.y },
          { x: videoPos.x - 456, y: videoPos.y + 296 },
          { x: videoPos.x, y: videoPos.y + 296 },
          { x: videoPos.x + 460, y: videoPos.y },
        ];
        for (let step = 2; step <= 8; step += 1) {
          candidates.push({ x: videoPos.x + 460 * step, y: videoPos.y });
        }
        for (const candidate of candidates) {
          const rect = { ...candidate, width: 420, height: 236 };
          if (!hits(rect)) {
            occupied.push(rect);
            return candidate;
          }
        }
        const fallback = { x: videoPos.x - 456, y: videoPos.y };
        occupied.push({ ...fallback, width: 420, height: 236 });
        return fallback;
      };
      const production = (targetCanvas.version.graph.metadata?.production_settings || {}) as Record<string, unknown>;
      const productionAspect = String(production.aspect_ratio || config.aspect_ratio || "16:9");
      const newNodes: CanvasNode[] = [];
      const newEdges: CanvasEdge[] = [];
      for (const unit of compiled) {
        const videoId = unitNodeId(nodeId, unit.unit_id);
        const storyboardId = `${videoId}-sb`;
        const videoPos = positions.get(unit.unit_id) || anchor;
        const baseConfig = {
          reference_mode: unit.reference_mode || "clean_single_frame",
          source_beats: unit.source_beats || [],
          aspect_ratio: productionAspect,
          duration_seconds: unit.duration_seconds,
          duration_requested: unit.duration_requested ?? null,
          duration_reason: unit.duration_reason || '',
          duration_policy: 'director_dynamic',
          sequence: unit.sequence,
          unit_id: unit.unit_id,
          source_scene_node: nodeId,
          source_scene_ids: unit.source_scene_ids ?? [],
          source_beat_ids: unit.source_beat_ids ?? [],
          characters: unit.characters ?? [],
          visual_anchors: unit.visual_anchors ?? [],
          transition_in: unit.transition_in || '',
          transition_out: unit.transition_out || '',
          continuity: unit.continuity ?? {},
          director_plan_hash: unit.director_plan_hash || directorPlanHash,
        };
        // 分镜图节点：用户先审图确认画面质量，再图生视频
        newNodes.push({
          id: storyboardId,
          type: 'image',
          position: placeStoryboard(videoPos),
          data: {
            label: `分镜 ${unit.sequence}. ${unit.title || unit.unit_id}`,
            nodeType: 'image',
            config: {
              ...baseConfig,
              node_role: 'storyboard',
              prompt: unit.storyboard_prompt || unit.video_prompt,
              storyboard_json: unit.storyboard_json ?? null,
              aspect_ratio: productionAspect,
            },
          },
        });
        newNodes.push({
          id: videoId,
          type: 'video',
          position: videoPos,
          data: {
            label: `${unit.sequence}. ${unit.title || unit.unit_id}`,
            nodeType: 'video',
            config: {
              ...baseConfig,
              node_role: 'video',
              prompt: unit.video_prompt,
              storyboard_prompt: unit.storyboard_prompt || '',
              storyboard_json: unit.storyboard_json ?? null,
              storyboard_node: storyboardId,
            },
          },
        });
        newEdges.push(
          { id: `e-${nodeId}-${storyboardId}`, source: nodeId, sourceHandle: 'shot', target: storyboardId, targetHandle: 'prompt', data: { sequence: unit.sequence, unit_id: unit.unit_id } },
          { id: `e-${storyboardId}-${videoId}`, source: storyboardId, sourceHandle: 'image', target: videoId, targetHandle: 'image', data: { sequence: unit.sequence, unit_id: unit.unit_id } },
          { id: `e-${nodeId}-${videoId}`, source: nodeId, sourceHandle: 'shot', target: videoId, targetHandle: 'prompt', data: { sequence: unit.sequence, unit_id: unit.unit_id } },
        );
      }
      setNodes((current) => [...current.filter((node) => !previousIds.has(node.id)), ...newNodes]);
      setEdges((current) => [...current.filter((edge) => !previousIds.has(edge.source) && !previousIds.has(edge.target)), ...newEdges]);
      updateSceneNodeConfig(nodeId, { director_plan_stale: false });
      markDirty();
      const normalizedCount = compiled.filter((item) => item.duration_requested != null && item.duration_requested !== item.duration_seconds).length;
      const totalSeconds = compiled.reduce((sum, item) => sum + (Number(item.duration_seconds) || 0), 0);
      toast.success(`已生成 ${compiled.length} 张分镜图 + ${compiled.length} 个视频节点（共 ${totalSeconds} 秒${normalizedCount ? `，${normalizedCount} 个时长经模型档位归一` : ''}）。建议先运行分镜图确认画面，再图生视频`);
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '应用导演编排失败'));
    } finally {
      setCompilingNodeId(null);
    }
  };
  const contextMenuState: ContextMenuState = nodeMenu ? { type: 'node', ...nodeMenu } : interaction.state.contextMenu;
  const createMenuPosition = interaction.state.nodeCreatePosition;
  const createMenuScreenPosition = createMenuPosition
    ? clampOverlayPosition(screenPoint(createMenuPosition, editorViewport), { width: 300, height: 330 }, canvasRect || { width: 0, height: 0 }, { top: 72, right: 16, bottom: 92, left: 16 })
    : null;
  const nodeRunStatuses = (() => {
    const isActiveStatus = (status: string) => ['awaiting_approval', 'queued', 'running', 'cancel_requested'].includes(status);
    const runs = latestRun && !trackedRuns.some((run) => run.id === latestRun.id) ? [...trackedRuns, latestRun] : trackedRuns;
    const merged = new Map<string, string>();
    for (const run of [...runs].sort((a, b) => a.id - b.id)) {
      // 本次运行真正要生成的节点 = 用户点的目标 + 明确要求重做的；目标为空表示整张画布（全部算目标）。
      const scope = run.scope as { target_node_ids?: string[]; rerun_node_ids?: string[] } | undefined;
      const targets = new Set(scope?.target_node_ids ?? []);
      const reruns = new Set(scope?.rerun_node_ids ?? []);
      for (const runNode of run.nodes) {
        // 上游已有结果、又不是本次要生成的节点（例如给视频节点生成时连着的分镜图）会被直接复用，
        // 运行记录里它们短暂处于排队 / 运行状态，但画布上不能显示“正在重新生成”，否则会误导用户。
        if (isActiveStatus(runNode.status) && targets.size > 0 && !targets.has(runNode.node_id) && !reruns.has(runNode.node_id)
          && nodeHasResult(nodes.find((item) => item.id === runNode.node_id))) continue;
        const previous = merged.get(runNode.node_id);
        // 后提交的运行覆盖先前的；但另一次运行里"已完成"的同名上游节点，不能盖掉仍在生成中的状态。
        if (previous === undefined || isActiveStatus(runNode.status) || !isActiveStatus(previous)) merged.set(runNode.node_id, runNode.status);
      }
    }
    batchStatuses.forEach((status, id) => merged.set(id, status));
    return merged;
  })();
  const canvasOptions = canvasList.some((item) => item.id === canvas.id) ? canvasList : [canvas, ...canvasList];
  return <div className="relative flex h-full min-h-0 min-w-0 overflow-hidden bg-[#181818] text-white">
    <div className="relative min-h-0 min-w-0 flex-1">
    <CanvasSurface containerRef={surfaceRef} viewport={editorViewport} tool={interaction.state.activeTool} handlers={interaction.handlers} state={interaction.state} onViewportChange={(next) => updateViewport({ x: next.x, y: next.y, k: next.scale })} onDrop={(event, world) => { const type = event.dataTransfer.getData('application/x-storycanvas-node'); const item = catalog.find((entry) => entry.type === type); if (item) { captureHistory(); addCatalogNode(item, world); } }}>
      <CanvasConnectionLayer ghostEdges={ghostEdges} nodes={nodes as CanvasSceneNode[]} edges={edges as CanvasSceneEdge[]} catalog={catalog} connecting={interaction.state.connecting} mouseWorld={interaction.state.mouseWorld} connectionTargetNodeId={interaction.state.connectionTargetNodeId} selectedConnectionId={interaction.state.selectedConnectionId} handlers={interaction.handlers} />
      {interaction.state.selectionBox && (() => { const box = interaction.state.selectionBox; const left = Math.min(box.startWorldX, box.currentWorldX); const top = Math.min(box.startWorldY, box.currentWorldY); return <div className="pointer-events-none absolute rounded-lg border-2 border-[#2f80ff]/80 bg-[#2f80ff]/10" style={{ left, top, width: Math.abs(box.currentWorldX - box.startWorldX), height: Math.abs(box.currentWorldY - box.startWorldY) }} />; })()}
      {orderNodesForRender(nodes, edges).map((node) => <CanvasNodeView key={node.id} node={node as CanvasSceneNode} catalogItem={catalog.find((item) => item.type === node.type) || catalog[0]} selected={selectedNodeIds.includes(node.id)} connecting={interaction.state.connecting} connectionTargetNodeId={interaction.state.connectionTargetNodeId} scale={editorViewport.scale} handlers={interaction.handlers} onResize={handleNodeResize} onResizeEnd={handleNodeResizeEnd} onNodeContextMenu={(event, nodeId) => { event.preventDefault(); event.stopPropagation(); setNodeMenu({ x: event.clientX, y: event.clientY, nodeId }); }} renderContent={(nodeView) => { const result = nodeView.data.result as (Record<string, unknown> & { url?: string }) | undefined; const mediaKindForNode = nodeView.type === 'image' || nodeView.type === 'video' || nodeView.type === 'concat'; const resultUrl = (result?.url as string | undefined) || (mediaKindForNode ? nodeResultUrlCache.get(`${canvas.id}:${nodeView.id}`)?.url : undefined) || ''; const runStatus = nodeRunStatuses.get(nodeView.id); const isBusy = submittingNodeId === nodeView.id || ['awaiting_approval', 'queued', 'running', 'cancel_requested'].includes(String(runStatus || '')); if (resultUrl) { rememberResultUrl(canvas.id, nodeView.id, resultUrl, nodeView.type !== 'image'); const preview = <NodeResultPreview url={resultUrl} isVideo={nodeView.type !== 'image'} interactive={selectedNodeIds.includes(nodeView.id)} displayWidth={(Number((nodeView.data.ui as { width?: number } | undefined)?.width) || NODE_WIDTH) * editorViewport.scale} onExpand={() => setNodePreview({ url: resultUrl, isVideo: nodeView.type !== 'image', title: String(nodeView.data.label || '') })} onNaturalSize={(width, height) => fitNodeToMedia(nodeView.id, resultUrl, width, height)} />; if (!isBusy) return preview; return <div className="relative h-full w-full" aria-busy="true">{preview}<div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 bg-black/60 backdrop-blur-[1px]" aria-label="重新生成中"><Loader2 className="h-8 w-8 animate-spin text-[#73a7ff]" /><span className="rounded-full bg-black/55 px-2.5 py-0.5 text-[11px] text-[#d8e4ff]">{nodeView.type === 'image' ? '重新生成中…' : '视频重新生成中，旧视频暂时保留'}</span></div></div>; } if (isBusy) return <div className="flex h-full w-full items-center justify-center bg-[#202226]" aria-label="生成中"><Loader2 className="h-8 w-8 animate-spin text-[#73a7ff]" /></div>; if (nodeView.type === 'scene') { const config = (nodeView.data.config || {}) as Record<string, unknown>; return (
  <div className="flex h-full w-full flex-col gap-1.5" data-canvas-no-zoom>
    <div className="min-h-0 flex-1 overflow-hidden">
      <SceneListNodeView
        canvasId={canvas?.id}
        onEditScreenplay={(text) => editScreenplayFromReview(nodeView.id, text)}
        onResplit={() => { const screenplayId = String(config.source_screenplay_node || ''); if (screenplayId) void splitScreenplayNode(screenplayId); }}
        // 旧画布的审核节点没有保存来源章节引用：回退到它所属的剧本节点上的引用，旧的小说改写剧本也能对照原文
        config={config.source_refs ? config : { ...config, source_refs: nodes.find((item) => item.id === String(config.source_screenplay_node || ''))?.data.config?.source_refs }}
        onChange={(partial) => updateSceneNodeConfig(nodeView.id, partial)}
        onToggleApproved={() => updateSceneNodeConfig(nodeView.id, { approved: !config.approved })}
        directorPlan={(config.director_plan as DirectorPlan) || null}
        directorPlanLoading={planBusyNodeId === nodeView.id}
        directorPlanError={directorError}
        onGenerateDirectorPlan={() => void generateDirectorPlanForNode(nodeView.id)}
        onApplyDirectorPlan={() => void applyDirectorPlan(nodeView.id)}
        directorPlanStale={Boolean(config.director_plan && config.director_plan_stale)}
        onAnalyzeAssets={() => void analyzeAssetsForNode(nodeView.id)}
        assetAnalysisLoading={assetAnalysisNodeId === nodeView.id}
      />
    </div>
    {config.approved ? null : (
      <p className="shrink-0 px-1 text-center text-[10px] text-slate-500">统一审批通过后可进行 AI 导演编排</p>
    )}
  </div>
); }
if (nodeView.type === 'audio') { const audioConfig = (nodeView.data.config || {}) as Record<string, unknown>; const audioUrl = String((nodeView.data.result as { url?: string } | undefined)?.url || audioConfig.existing_url || ''); return <div className="flex h-full w-full flex-col items-center justify-center gap-2 px-3 py-2" onPointerDown={(event) => event.stopPropagation()}><span className="max-w-full truncate text-xs font-medium text-[#aeb6c5]" title={String(audioConfig.file_name || '')}>{audioUrl ? String(audioConfig.file_name || '已上传音频') : '音频（配音 / 音乐）'}</span>{audioUrl && <audio controls preload="metadata" src={audioUrl} className="h-8 w-full" />}<button type="button" title="上传音频文件" disabled={uploadingNodeAsset} onClick={(event) => { event.stopPropagation(); openNodeFileUpload(nodeView.id, 'audio'); }} className="inline-flex items-center gap-1.5 rounded-lg border border-[#3a3f45] bg-[#2a2e33] px-3 py-1.5 text-xs text-[#aeb6c5] hover:bg-[#353a41] hover:text-white disabled:cursor-wait disabled:opacity-60"><Upload className="h-3.5 w-3.5" />{uploadingNodeId === nodeView.id ? '上传中…' : audioUrl ? '更换音频' : '上传音频'}</button>{!audioUrl && <span className="text-center text-[10px] text-[#7d756e]">连到视频节点的「音频」端口作为参考</span>}</div>; }
if (nodeView.type === 'concat') return <div className="flex h-full flex-col items-center justify-center gap-3 p-4 text-xs"><strong>合片</strong><span>按输入片段顺序制作成片</span><button type="button" disabled={running} onClick={() => void runCanvas(nodeView.id)} className="rounded bg-blue-500 px-3 py-2 text-white disabled:opacity-50">制作成片</button></div>;
if (nodeView.type === 'container') return (
  <ContainerNodeView
    config={(nodeView.data.config || {}) as unknown as ContainerNodeConfig}
    memberCount={getContainerMemberIds(nodes, edges, nodeView.id).length}
    onRename={(next) => { captureHistory(); updateNode(nodeView.id, { label: next, config: { ...(nodeView.data.config || {}), node_label: next } }); }}
    onUngroup={() => removeNodes([nodeView.id])}
  />
);
if (nodeView.type === 'screenplay') { const config = nodeView.data.config || {}; const contentValue = String(config.content ?? config.screenplay ?? ''); return (
  <div className="flex h-full w-full flex-col gap-2 p-2" data-canvas-no-zoom>
    <textarea
      value={contentValue}
      placeholder="输入剧本内容，或通过工具栏「导入小说章节」自动生成…"
      onChange={(event) => { captureHistory(); updateNodeConfig(nodeView.id, 'content', event.target.value); }}
      className="min-h-0 flex-1 resize-none rounded-lg border border-[#3a3f45] bg-[#23262b] p-2 text-[11px] leading-relaxed text-[#d5dae2] outline-none focus:border-[#73a7ff]"
    />
    <button
      type="button"
      disabled={splittingNodeId === nodeView.id || !contentValue.trim()}
      onPointerDown={(event) => event.stopPropagation()}
      onClick={(event) => { event.stopPropagation(); void splitScreenplayNode(nodeView.id); }}
      className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-[#73a7ff] px-2 py-1.5 text-[11px] font-medium text-[#111827] hover:bg-[#8db6ff] disabled:cursor-not-allowed disabled:opacity-50"
    >
      {splittingNodeId === nodeView.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <SplitSquareHorizontal className="h-3.5 w-3.5" />}
      {splittingNodeId === nodeView.id ? 'AI 拆分中…' : 'AI 拆分为视频单元'}
    </button>
  </div>
); }
const mediaKind = nodeView.type === 'image' || nodeView.type === 'video' ? nodeView.type : null; return <div className="flex w-full flex-col items-center justify-center gap-3 px-4 py-2"><span className="text-center text-xs font-medium text-[#aeb6c5]">{String(nodeView.data.label || nodeView.type)}</span>{mediaKind && <button type="button" title={`上传${mediaKind === 'image' ? '图片' : '视频'}到当前节点`} disabled={uploadingNodeAsset} onPointerDown={(event) => event.stopPropagation()} onClick={(event) => { event.stopPropagation(); openNodeFileUpload(nodeView.id, mediaKind); }} className="inline-flex items-center gap-1.5 rounded-lg border border-[#3a3f45] bg-[#2a2e33] px-3 py-1.5 text-xs text-[#aeb6c5] hover:bg-[#353a41] hover:text-white disabled:cursor-wait disabled:opacity-60"><Upload className="h-3.5 w-3.5" />{uploadingNodeId === nodeView.id ? '上传中…' : `上传${mediaKind === 'image' ? '图片' : '视频'}`}</button>}</div>; }} />)}
    </CanvasSurface>
      <CanvasPlanCapsule plans={plans} loading={plansLoading} applyingPlanId={applyingPlanId} onRefresh={() => void loadCanvasPlans()} onConfirm={(plan) => void confirmCanvasPlan(plan)} onSync={(plan) => void syncPlanWorkflow(plan)} onApply={(plan) => void applyCanvasPlan(plan)} />
      <input ref={nodeUploadInputRef} type="file" accept={nodeUploadAccept} className="hidden" disabled={uploadingNodeAsset} onChange={(event) => void handleNodeFileUpload(event)} />
      {inspectorNode && supportsNodeInspector(inspectorNode.type) && <CanvasNodePropertyPanel node={inspectorNode as CanvasSceneNode} assets={assets} models={models} left={panelLeft} top={panelTop} bottom={92} maxWidth={panelWidth} connectedPreviews={inspectorConnectedPreviews} onChange={(key, value) => { captureHistory(); updateNodeConfig(inspectorNode.id, key, value); }} onAssetChange={(assetId) => { captureHistory(); selectAsset(inspectorNode.id, assetId); }} referenceCandidates={inspectorCandidates} onConnectReference={(sourceId) => connectReference(sourceId, inspectorNode.id)} onDisconnectReference={(sourceId) => disconnectReference(sourceId, inspectorNode.id)} onOpenStyleSelector={() => setStyleSelectorNodeId(inspectorNode.id)} onGenerate={() => generateFromPanel(inspectorNode.id)} regenerates={nodeHasResult(inspectorNode)} costSlot={canvas && (inspectorNode.type === 'image' || inspectorNode.type === 'video') ? <NodeGenerateCost canvasId={canvas.id} nodeId={inspectorNode.id} regenerates={nodeHasResult(inspectorNode)} getGraph={() => toGraph(nodesRef.current, edgesRef.current, canvas.version.graph)} refreshKey={`${latestRun?.id ?? 0}:${latestRun?.status ?? ''}:${String(inspectorNode.data.config?.asset_id ?? '')}`} /> : undefined} footer={canvas && (inspectorNode.type === 'image' || inspectorNode.type === 'video') ? <NodeCandidates canvasId={canvas.id} nodeId={inspectorNode.id} isVideo={inspectorNode.type === 'video'} refreshKey={`${latestRun?.id ?? 0}:${latestRun?.status ?? ''}:${String(inspectorNode.data.config?.asset_id ?? '')}`} currentAssetId={Number((inspectorNode.data.result as { asset_id?: number } | undefined)?.asset_id ?? inspectorNode.data.config?.asset_id) || null} onPick={(candidate) => pinCandidate(inspectorNode.id, candidate)} /> : undefined} isGenerating={submittingNodeId === inspectorNode.id || ['queued', 'running', 'cancel_requested'].includes(String(nodeRunStatuses.get(inspectorNode.id) || ''))} onStop={activeRunForNode(inspectorNode.id) ? () => void stopNodeRun(inspectorNode.id) : undefined} isUploading={uploadingNodeId === inspectorNode.id} onUploadReference={(kind) => openReferenceFileUpload(inspectorNode.id, kind)} />}
      {styleSelectorNodeId && (() => {
        const styleNode = nodes.find((node) => node.id === styleSelectorNodeId);
        const config = styleNode?.data.config || {};
        const selectedPreset = stylePresets.find((preset) => preset.id === Number(config.style_preset_id));
        return <StyleSelectorModal
          isOpen
          onClose={() => setStyleSelectorNodeId(null)}
          presets={stylePresets}
          selectedStyleName={selectedPreset?.name || String((config.style_snapshot as Record<string, unknown> | null)?.name || '')}
          styleReferenceImageUrl={String(config.style_reference_url || '') || null}
          onFileUpload={handleStyleModalFileUpload}
          onStyleSelect={handleStyleModalSelect}
        />;
      })()}
      {assetSelectorNodeId && <AssetReferenceSelector availableAssets={assets} selectedIds={(() => { const node = nodes.find((item) => item.id === assetSelectorNodeId); const config = node?.data.config || {}; return node && (node.type === 'asset' || node.type === 'video_asset') ? (config.asset_id ? [Number(config.asset_id)] : []) : (Array.isArray(config.reference_asset_ids) ? config.reference_asset_ids.map(Number) : []); })()} onConfirm={(ids) => { captureHistory(); selectAssets(assetSelectorNodeId, ids); setAssetSelectorNodeId(null); }} onClose={() => setAssetSelectorNodeId(null)} />}
      <div className="pointer-events-none absolute right-4 top-4 z-20 max-w-[calc(100%-2rem)]"><div className="pointer-events-auto flex items-center gap-1 rounded-xl border border-[#393633] bg-[#211f1d]/95 p-1.5 shadow-xl"><span title={dirty ? '有未保存修改' : '已保存'} className={`mx-1.5 h-2 w-2 shrink-0 rounded-full ${dirty ? 'bg-amber-400' : 'bg-emerald-400'}`} />{editingCanvasName ? <div className="flex items-center gap-1"><input autoFocus maxLength={255} value={canvasNameDraft} onChange={(event) => setCanvasNameDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void renameCanvas(); if (event.key === 'Escape') cancelCanvasRename(); }} className="w-[190px] rounded-md border border-[#766d65] bg-[#171513] px-2 py-1.5 text-xs text-white outline-none focus:border-[#eee9e4]" aria-label="画布名称" /><button type="button" title="确认重命名" disabled={renamingCanvas} onClick={() => void renameCanvas()} className="rounded-md p-1.5 text-emerald-300 hover:bg-white/10 disabled:opacity-40"><Check className="h-4 w-4" /></button><button type="button" title="取消重命名" disabled={renamingCanvas} onClick={cancelCanvasRename} className="rounded-md p-1.5 text-[#a49b94] hover:bg-white/10 hover:text-white disabled:opacity-40"><X className="h-4 w-4" /></button></div> : <select value={canvas.id} onChange={(event) => void selectCanvas(Number(event.target.value))} className="max-w-[180px] bg-transparent px-1 text-xs text-[#ded7d0] outline-none" aria-label="切换画布">{canvasOptions.map((item, index) => <option className="bg-[#211f1d]" key={item.id} value={item.id}>{`画布 ${index + 1} · ${item.name}`}</option>)}</select>}<span className="mx-0.5 h-5 w-px bg-[#403c38]" /><StyleControl style={canvasStyle} onPick={() => setCanvasStyleModalOpen(true)} onToggle={toggleCanvasStyle} /><span className="mx-0.5 h-5 w-px bg-[#403c38]" /><button type="button" title="刷新画布：重新读取服务端最新的画布、生成结果和进度" aria-label="刷新画布" disabled={refreshingCanvas} onClick={() => void reloadCanvasManually()} className="grid h-8 w-8 place-items-center rounded-lg text-[#a49b94] hover:bg-white/10 hover:text-white disabled:opacity-60"><RefreshCw className={`h-4 w-4 ${refreshingCanvas ? 'animate-spin' : ''}`} /></button><div className="relative"><button type="button" title="更多操作" aria-haspopup="menu" aria-expanded={moreMenuOpen} onClick={() => setMoreMenuOpen((open) => !open)} className={`grid h-8 w-8 place-items-center rounded-lg hover:bg-white/10 ${moreMenuOpen ? 'bg-white/10 text-white' : 'text-[#a49b94]'}`}><MoreHorizontal className="h-4 w-4" /></button>{moreMenuOpen && <><button type="button" aria-label="关闭菜单" className="fixed inset-0 z-30 cursor-default" onClick={() => setMoreMenuOpen(false)} /><div role="menu" className="absolute right-0 top-full z-40 mt-2 w-44 rounded-xl border border-[#393633] bg-[#25231f] p-1 shadow-2xl"><button type="button" role="menuitem" onClick={() => { setMoreMenuOpen(false); setImportDialogOpen(true); }} className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs text-[#ded7d0] hover:bg-white/10"><FileText className="h-3.5 w-3.5" />导入小说章节</button><button type="button" role="menuitem" onClick={() => { setMoreMenuOpen(false); beginCanvasRename(); }} className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs text-[#ded7d0] hover:bg-white/10"><Pencil className="h-3.5 w-3.5" />重命名画布</button><button type="button" role="menuitem" onClick={() => void openVersionHistory()} className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs text-[#ded7d0] hover:bg-white/10"><History className="h-3.5 w-3.5" />版本历史</button><button type="button" role="menuitem" onClick={() => { setMoreMenuOpen(false); void createBlankCanvas(); }} className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs text-[#ded7d0] hover:bg-white/10"><Plus className="h-3.5 w-3.5" />新建空白画布</button><div className="my-1 h-px bg-[#393633]" /><button type="button" role="menuitem" onClick={() => { setMoreMenuOpen(false); void deleteCurrentCanvas(); }} className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs text-rose-300 hover:bg-white/10"><Trash2 className="h-3.5 w-3.5" />删除当前画布</button></div></>}</div><span className="mx-0.5 h-5 w-px bg-[#403c38]" /><button type="button" title="保存画布" disabled={saving} onClick={() => void saveCanvas()} className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-white px-3.5 text-xs font-semibold text-[#24211f] hover:bg-[#f0ebde] disabled:cursor-wait disabled:opacity-50"><Save className="h-3.5 w-3.5" />{saving ? '保存中' : '保存'}</button>{!isDesktop && <button type="button" title="打开画布 AI 助手" onClick={() => setAgentOpen((open) => !open)} className={`grid h-8 w-8 place-items-center rounded-lg border transition ${agentOpen ? 'border-[#eee9e4] bg-[#eee9e4] text-[#24211f]' : 'border-[#766d65] bg-[#35312e] text-[#f3cf84] hover:border-[#f3cf84] hover:bg-[#423c36]'}`}><Bot className="h-4 w-4" /></button>}</div></div>
      <div className="pointer-events-none absolute bottom-4 right-4 z-20 flex items-center text-[11px] text-[#7d756e] [&_button]:pointer-events-auto">{nodes.length} 节点 · {edges.length} 连线{interaction.state.connecting && ' · 选择兼容输入端口完成连接'}{latestRun && ` · ${latestRun.status}`}{latestRun && latestRun.status === 'failed' && <button type="button" disabled={running} onClick={() => void confirmRun()} className="ml-2 rounded bg-[#eee9e4] px-2 py-1 font-medium text-[#24211f] disabled:opacity-50">恢复执行</button>}</div>
      <CanvasContextMenu menu={contextMenuState} onClose={() => { setNodeMenu(null); interaction.closeContextMenu(); }} onDuplicateNode={(nodeId) => { interaction.closeContextMenu(); duplicateNode(nodeId); }} onDeleteNode={(nodeId) => { interaction.closeContextMenu(); removeNodes([nodeId]); }} onDeleteConnection={(connectionId) => { interaction.closeContextMenu(); deleteConnection(connectionId); }} />
      {createMenuPosition && createMenuScreenPosition && <CanvasCreateMenu position={createMenuScreenPosition} onSelect={(type) => { const item = catalog.find((entry) => entry.type === type); if (item && createMenuPosition) { captureHistory(); addCatalogNode(item, createMenuPosition); } interaction.closeCreateMenu(); }} onClose={interaction.closeCreateMenu} />}
      {miniMapOpen && <CanvasMiniMap nodes={nodes.map((node) => ({ id: node.id, position: node.position, width: node.data.ui?.width, height: node.data.ui?.height, type: node.type }))} viewport={editorViewport} viewportSize={canvasSize} onViewportChange={(next) => updateViewport({ x: next.x, y: next.y, k: next.scale })} />}
      <CanvasBottomToolbar scale={viewport.k} supportsAudio onScaleChange={(k) => updateViewport({ ...viewport, k })} onReset={() => { const rect = surfaceRef.current?.getBoundingClientRect(); updateViewport({ x: rect ? rect.width / 2 : 260, y: rect ? rect.height / 2 : 120, k: 1 }); }} onFit={fitAll} onUndo={undo} onRedo={redo} onAutoLayout={autoLayoutCanvas} onOpenAssetManagement={() => setAssetPanelOpen((open) => !open)} assetPanelOpen={assetPanelOpen} assetAlert={assetSummary.withoutImage > 0 || assetSummary.missingRefs > 0} onGroup={() => createGroupFromSelection()} canGroup={selectedNodeIds.length >= 2} onToggleMiniMap={() => setMiniMapOpen((open) => !open)} miniMapOpen={miniMapOpen} isAssetManagementDisabled={false} onTool={(nextTool) => { if (nextTool === 'select' || nextTool === 'pan') setTool(nextTool); else if (nextTool === 'help') toast.info('空格或中键平移，滚轮缩放，框选多个节点'); }} activeTool={tool} onAddNode={(type) => addNodeFromTool(type)} />
      {assetPanelOpen && canvas && <CanvasAssetPanel canvasId={canvas.id} entries={assetEntries} candidates={assetCandidates} onAddCandidate={(candidate) => addCandidateAsset(candidate as AssetCandidate & { sceneNodeId?: string })} production={productionEntries} statuses={nodeRunStatuses} batch={batch} canvasStyle={canvasStyle} onPickStyle={() => setCanvasStyleModalOpen(true)} onToggleStyle={toggleCanvasStyle} inconsistentCount={inconsistentIds.length} onUnifyStyle={unifyStyle} busy={running} uploadingNodeId={uploadingNodeId} getGraph={() => toGraph(nodesRef.current, edgesRef.current, canvas.version.graph)} onClose={() => setAssetPanelOpen(false)} onToggleLock={toggleAssetLock} onEditSetting={editAssetSetting} onLinkShots={linkAssetToShots} onFocus={focusNode} onGenerate={(nodeId) => void runCanvas(nodeId)} onUpload={(nodeId) => openNodeFileUpload(nodeId, 'image')} onBatchGenerate={(ids) => void runBatch(ids)} onCancelBatch={() => void cancelBatch()} onOpenLibrary={onOpenAssetManagement} />}
      {nodes.length === 0 && !loading && <CanvasEmptyGuide canvasId={canvas.id} onSend={sendToAgent} onImportChapter={(mode) => { importModeRef.current = mode; setImportDialogOpen(true); }} style={canvasStyle} presets={stylePresets} onPickPreset={(preset) => setCanvasStyle(presetToCanvasStyle(preset), { silent: true })} onOpenStyleModal={() => setCanvasStyleModalOpen(true)} onToggleStyle={toggleCanvasStyle} aspect={canvasAspect} onPickAspect={setCanvasAspect} shotMode={shotDurationMode} onPickShotMode={setShotDurationMode} />}
      {nodes.length > 0 && <CanvasPipelineBar summary={pipelineSummary} agentBusy={agentStreaming || pipelineActive} cost={costEstimate} pipelineRun={pipelineTask} onRunPipeline={() => void runPipeline()} onCancelPipeline={() => void cancelPipeline()} onContinue={sendToAgent} onBatch={(ids) => void runBatch(ids)} batchBusy={running || Boolean(batch)} batch={batch} inconsistentCount={inconsistentIds.length} onUnifyStyle={unifyStyle} autoCollapseKey={inspectorNode && supportsNodeInspector(inspectorNode.type) ? inspectorNode.id : null} reviewSlot={<CanvasReviewPanel canvasId={canvas.id} revision={canvas.definition_revision} refreshKey={refreshTick} busy={agentStreaming || pipelineActive || running || Boolean(batch)} onBeforeAction={flushBeforeAgent} onChanged={() => void refreshCanvas()} onRedoStarted={setPipelineTask} onFocusNode={focusNode} onPreviewEdges={setGhostEdges} />} />}
      {batchDialog && <BatchStartDialog info={batchDialog.info} style={canvasStyle} presets={stylePresets} onPickPreset={(preset) => setCanvasStyle(presetToCanvasStyle(preset), { silent: true })} onOpenStyleModal={() => setCanvasStyleModalOpen(true)} onToggleStyle={toggleCanvasStyle} onConfirm={() => batchDialog.resolve(true)} onCancel={() => batchDialog.resolve(false)} />}
      {canvasStyleModalOpen && <StyleSelectorModal isOpen requireReferenceImage onClose={() => { pendingStyleReferenceRef.current = null; setCanvasStyleModalOpen(false); }} presets={stylePresets} selectedStyleName={canvasStyle?.style_snapshot?.name || ''} styleReferenceImageUrl={canvasStyle?.style_reference_url || null} onFileUpload={uploadCanvasStyleReference} onStyleSelect={(styleName) => handleCanvasStyleSelect(styleName)} />}
      {nodePreview && <MediaLightbox url={nodePreview.url} isVideo={nodePreview.isVideo} title={nodePreview.title} onClose={() => setNodePreview(null)} />}
      {versionHistoryOpen && canvas && <CanvasVersionHistoryModal canvasId={canvas.id} onRestored={reloadAfterVersionRestore} onClose={() => setVersionHistoryOpen(false)} />}
      {importDialogOpen && canvas && <ChapterImportDialog canvasId={canvas.id} onClose={() => setImportDialogOpen(false)} onImported={handleScreenplayImported} />}
    </div>
    <aside className={isDesktop
      ? `relative z-30 flex min-h-0 shrink-0 flex-col overflow-hidden border-l border-[#393633] bg-[#211f1d]/[.98] transition-[width] duration-200 ${agentOpen ? 'w-[400px]' : 'w-12'}`
      : agentOpen
        ? 'absolute inset-0 z-40 flex min-h-0 flex-col overflow-hidden bg-[#211f1d]/[.99] shadow-2xl'
        : 'hidden'}>
      <div className={`flex shrink-0 items-center border-b border-[#393633] px-3 py-3 [padding-top:calc(.75rem+var(--safe-area-top))] ${agentOpen ? 'justify-between' : 'justify-center'}`}>
        {agentOpen && <span className="truncate text-sm font-semibold">画布 AI 助手</span>}
        <button type="button" title={agentOpen ? '收起助手' : '展开助手'} aria-label={agentOpen ? '收起助手' : '展开助手'} onClick={() => setAgentOpen((open) => !open)} className="rounded-md p-1.5 text-[#958d86] hover:bg-white/10 hover:text-white">
          {agentOpen ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </button>
      </div>
      <div className={`min-h-0 flex-1 overflow-hidden ${agentOpen ? 'flex' : 'hidden'}`}>
        <div className="flex h-full min-h-0 flex-1">
          <Suspense fallback={<div className="p-4 text-sm text-[#948b84]">正在加载 AI 助手...</div>}><AgentPanel key={canvas.id} storyId={storyId} chapterId={chapterId} workflowType="video_canvas" workflowId={canvas.id} getCanvasGraph={() => withGuideSettings(toGraph(nodesRef.current, edgesRef.current, canvas.version.graph), guideSettingsRef.current)} onBeforeSend={flushBeforeAgent} onStreamingChange={setAgentStreaming} externalPrompt={externalPrompt} getCanvasClientRevision={() => clientRevisionRef.current} getCanvasSelectedNodeIds={() => selectedNodeIdsRef.current} onLocalCanvasGraph={applyLocalCanvasGraph} onContentUpdated={() => void refreshCanvas()} /></Suspense>
        </div>
      </div>
    </aside>
  </div>;

  /* 旧 DOM 画布实现保留在版本历史中，Canvas2D 编辑器已在上方返回。 */
  /*
  return <div className="relative h-full min-h-0 overflow-hidden bg-[#111214] text-white">
    <InfiniteCanvasSurface containerRef={surfaceRef} viewport={viewport} onViewportChange={updateViewport} onBackgroundPointerDown={() => { setSelectedNodeId(null); setConnectionStart(null); }} onDrop={(event, world) => { const type = event.dataTransfer.getData('application/x-storycanvas-node'); const item = catalog.find((entry) => entry.type === type); if (item) addCatalogNode(item, world); }}>
      <svg className="pointer-events-none absolute overflow-visible" width="1" height="1">{edges.map((edge) => <ConnectionPath key={edge.id} edge={edge} source={nodes.find((node) => node.id === edge.source)} target={nodes.find((node) => node.id === edge.target)} sourceCatalog={catalog.find((item) => item.type === nodes.find((node) => node.id === edge.source)?.type)} targetCatalog={catalog.find((item) => item.type === nodes.find((node) => node.id === edge.target)?.type)} />)}</svg>
      {nodes.map((node) => <VideoCanvasNode key={node.id} node={node} catalog={catalog.find((item) => item.type === node.type)} assets={assets} stylePresets={stylePresets} selected={selectedNodeId === node.id} connectingHandle={connectionStart?.nodeId === node.id ? connectionStart.handleKey : null} onSelect={() => setSelectedNodeId(node.id)} onDragStart={(event) => beginNodeDrag(node, event)} onConnectStart={(handleKey) => beginConnection(node.id, handleKey)} onConnectTarget={(handleKey) => finishConnection(node.id, handleKey)} onLabelChange={(value) => updateNode(node.id, { label: value })} onConfigChange={(key, value) => updateNodeConfig(node.id, key, value)} onAssetChange={(assetId) => selectAsset(node.id, assetId)} onStyleChange={(styleId) => selectStyle(node.id, styleId)} onRunNode={() => void runCanvas(node.id)} onDelete={() => { setNodes((current) => current.filter((item) => item.id !== node.id)); setEdges((current) => current.filter((edge) => edge.source !== node.id && edge.target !== node.id)); setSelectedNodeId(null); setConnectionStart(null); markDirty(); }} />)}
    </InfiniteCanvasSurface>

    <div className="pointer-events-none absolute inset-x-0 top-0 z-20 flex items-start justify-between p-4"><div className="pointer-events-auto flex items-center gap-2 rounded-xl border border-white/10 bg-[#1b1d21]/95 px-2 py-2 shadow-2xl"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white text-[#15171a]"><Boxes className="h-4 w-4" /></span><div className="mr-2 min-w-0"><p className="max-w-[170px] truncate text-xs font-semibold text-white/90">{canvas.name}</p><p className={`mt-0.5 text-[10px] ${dirty ? 'text-amber-300' : 'text-emerald-300'}`}>{dirty ? '有未保存修改' : '已保存'}</p></div><select value={canvas.id} onChange={(event) => void selectCanvas(Number(event.target.value))} className="max-w-[150px] rounded-lg border border-white/10 bg-white/[.06] px-2 py-1.5 text-[11px] text-white/75 outline-none"><option className="bg-[#202226]" value={canvas.id}>{canvas.name}</option>{canvasList.filter((item) => item.id !== canvas.id).map((item) => <option className="bg-[#202226]" key={item.id} value={item.id}>{item.name}</option>)}</select><button type="button" title="新建空白画布" onClick={() => void createBlankCanvas()} className="rounded-lg p-2 text-white/55 hover:bg-white/10 hover:text-white"><Plus className="h-4 w-4" /></button><button type="button" title="导入列表分镜" disabled={!workflow} onClick={() => void importWorkflow()} className="rounded-lg p-2 text-white/55 hover:bg-white/10 hover:text-white disabled:opacity-30"><Upload className="h-4 w-4" /></button></div><div className="pointer-events-auto flex items-center gap-1.5 rounded-xl border border-white/10 bg-[#1b1d21]/95 p-2 shadow-2xl"><button type="button" title="显示或隐藏节点库" onClick={() => setSidebarOpen((open) => !open)} className={`rounded-lg p-2 ${sidebarOpen ? 'bg-white/10 text-white' : 'text-white/55 hover:bg-white/10 hover:text-white'}`}><PanelLeft className="h-4 w-4" /></button><span className="mx-1 h-5 w-px bg-white/10" /><button type="button" title="聚焦全部节点" onClick={() => { if (!nodes.length) return; const minX = Math.min(...nodes.map((node) => node.position.x)); const minY = Math.min(...nodes.map((node) => node.position.y)); updateViewport({ x: 160 - minX, y: 110 - minY, k: 1 }); }} className="rounded-lg p-2 text-white/55 hover:bg-white/10 hover:text-white"><Focus className="h-4 w-4" /></button><button type="button" title="缩小" onClick={() => updateViewport({ ...viewport, k: Math.max(.2, viewport.k / 1.15) })} className="rounded-lg p-2 text-white/55 hover:bg-white/10 hover:text-white"><ZoomOut className="h-4 w-4" /></button><button type="button" title="放大" onClick={() => updateViewport({ ...viewport, k: Math.min(2.5, viewport.k * 1.15) })} className="rounded-lg p-2 text-white/55 hover:bg-white/10 hover:text-white"><ZoomIn className="h-4 w-4" /></button><button type="button" title="复制选中节点" disabled={!selectedNode} onClick={() => { if (!selectedNode) return; const copy = { ...selectedNode, id: `${selectedNode.type}-${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`, position: { x: selectedNode.position.x + 42, y: selectedNode.position.y + 42 }, data: { ...selectedNode.data, config: { ...selectedNode.data.config } } }; setNodes((current) => [...current, copy]); setSelectedNodeId(copy.id); markDirty(); }} className="rounded-lg p-2 text-white/55 hover:bg-white/10 hover:text-white disabled:opacity-25"><Copy className="h-4 w-4" /></button><button type="button" title={saving ? '保存中' : '保存画布'} disabled={saving} onClick={() => void saveCanvas()} className="rounded-lg bg-white/10 p-2 text-white/85 hover:bg-white/15 disabled:opacity-40"><Save className="h-4 w-4" /></button><button type="button" title="画布 AI 助手" onClick={() => setAgentOpen((open) => !open)} className={`rounded-lg p-2 ${agentOpen ? 'bg-white text-[#15171a]' : 'text-white/55 hover:bg-white/10 hover:text-white'}`}><Bot className="h-4 w-4" /></button><button type="button" disabled={running} onClick={() => void runCanvas()} className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-2 text-xs font-semibold text-[#15171a] disabled:opacity-40"><CirclePlay className="h-3.5 w-3.5" />{running ? '提交中' : '运行全部'}</button></div></div>

    {sidebarOpen && <aside className="absolute bottom-4 left-4 top-[78px] z-20 flex w-[244px] flex-col overflow-hidden rounded-xl border border-white/10 bg-[#1b1d21]/95 shadow-2xl"><div className="flex items-center justify-between border-b border-white/[.08] px-4 py-3"><div><p className="text-sm font-semibold">节点库</p><p className="mt-0.5 text-[10px] text-white/35">拖入画布或点击添加</p></div><button type="button" title="收起节点库" onClick={() => setSidebarOpen(false)} className="rounded-lg p-1.5 text-white/45 hover:bg-white/10 hover:text-white"><ChevronLeft className="h-4 w-4" /></button></div><div className="border-b border-white/[.08] p-3"><label className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[.04] px-2.5 py-2 text-xs text-white/35"><Search className="h-3.5 w-3.5" /><input value={catalogQuery} onChange={(event) => setCatalogQuery(event.target.value)} placeholder="搜索节点" className="min-w-0 flex-1 bg-transparent text-xs text-white outline-none placeholder:text-white/30" /></label></div><div className="min-h-0 flex-1 overflow-y-auto p-2">{Object.entries(catalogGroups).map(([category, items]) => { const Icon = CATEGORY_ICON[category] || Sparkles; return <div key={category} className="mb-3"><p className="flex items-center gap-2 px-2 py-1.5 text-[10px] font-semibold uppercase tracking-[.13em] text-white/35"><Icon className="h-3 w-3" />{category}</p>{items.map((item) => <button key={item.type} type="button" draggable onDragStart={(event) => event.dataTransfer.setData('application/x-storycanvas-node', item.type)} onClick={() => addCatalogNode(item)} className="group flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left hover:bg-white/[.08]"><span className="flex h-7 w-7 items-center justify-center rounded-md bg-white/[.07] text-white/65"><Icon className="h-3.5 w-3.5" /></span><span className="min-w-0 flex-1"><span className="block truncate text-xs text-white/80">{item.label}</span><span className="mt-0.5 block text-[10px] text-white/30">{item.inputs.length ? `${item.inputs.length} 个输入` : '快速添加'}</span></span><Plus className="h-3.5 w-3.5 text-white/20 group-hover:text-white/80" /></button>)}</div>; })}</div><div className="border-t border-white/[.08] p-3"><button type="button" onClick={() => setNodeMenuOpen((open) => !open)} className="flex w-full items-center justify-between rounded-lg bg-white/[.06] px-3 py-2 text-xs text-white/65 hover:bg-white/[.1]"><span className="inline-flex items-center gap-2"><Plus className="h-3.5 w-3.5" />快捷添加</span><ChevronDown className={`h-3.5 w-3.5 ${nodeMenuOpen ? '' : '-rotate-90'}`} /></button></div></aside>}
    {!sidebarOpen && <button type="button" title="打开节点库" onClick={() => setSidebarOpen(true)} className="absolute left-4 top-20 z-20 rounded-xl border border-white/10 bg-[#1b1d21]/95 p-3 text-white/65 shadow-2xl hover:text-white"><ChevronRight className="h-4 w-4" /></button>}
    {nodeMenuOpen && <div className={`absolute bottom-4 z-30 w-[244px] rounded-xl border border-white/10 bg-[#25272c] p-2 shadow-2xl ${sidebarOpen ? 'left-[272px]' : 'left-4'}`}><div className="flex items-center justify-between px-2 py-2"><p className="text-xs font-semibold text-white/80">添加节点</p><button type="button" title="关闭添加节点菜单" onClick={() => setNodeMenuOpen(false)} className="rounded-md p-1 text-white/35 hover:bg-white/10 hover:text-white"><X className="h-3.5 w-3.5" /></button></div><div className="grid grid-cols-2 gap-1">{catalog.slice(0, 10).map((item) => <button key={item.type} type="button" onClick={() => addCatalogNode(item)} className="flex items-center gap-2 rounded-lg px-2 py-2 text-left text-[11px] text-white/65 hover:bg-white/[.08] hover:text-white"><Plus className="h-3 w-3" />{item.label}</button>)}</div></div>}
    {false && agentOpen && <aside className="absolute bottom-4 right-4 top-[78px] z-30 flex w-[380px] flex-col overflow-hidden rounded-xl border border-white/10 bg-[#1b1d21]/[.98] shadow-2xl"><div className="flex items-center justify-between border-b border-white/[.08] px-4 py-3"><div><p className="text-sm font-semibold">画布 AI 助手</p><p className="mt-0.5 text-[10px] text-white/35">读取当前画布，提出结构建议</p></div><button type="button" onClick={() => setAgentOpen(false)} className="rounded-lg p-1.5 text-white/45 hover:bg-white/10 hover:text-white"><X className="h-4 w-4" /></button></div><div className="min-h-0 flex-1 overflow-hidden"><Suspense fallback={<div className="p-4 text-sm text-white/45">正在加载 AI 助手...</div>}><AgentPanel storyId={storyId} chapterId={chapterId} workflowType="video_canvas" workflowId={canvas.id} canvasBlocked={dirty || saving} onContentUpdated={() => void refreshCanvas()} /></Suspense></div></aside>}
    <div className="absolute bottom-4 right-4 z-20 max-w-[calc(100%-2rem)] rounded-lg border border-white/10 bg-[#1b1d21]/90 px-3 py-2 text-[10px] text-white/45"><span>{nodes.length} 节点 · {edges.length} 连线</span>{connectionStart && <span className="ml-3 text-white/75">选择目标节点的兼容输入端口完成连接</span>}{latestRun && <span className="ml-3 text-white/75">运行：{latestRun.status}</span>}{latestRun && ['queued', 'running', 'cancel_requested'].includes(latestRun.status) && <button type="button" onClick={() => void cancelRun()} className="ml-3 rounded border border-white/20 px-2 py-1 text-[10px] text-white/70">取消运行</button>}</div>
    <div className="absolute bottom-4 left-4 z-10 flex items-center gap-1 rounded-lg border border-white/10 bg-[#1b1d21]/90 p-1 text-white/50"><button type="button" title="缩小" onClick={() => updateViewport({ ...viewport, k: Math.max(.2, viewport.k / 1.15) })} className="rounded-md p-1.5 hover:bg-white/10 hover:text-white"><ZoomOut className="h-3.5 w-3.5" /></button><button type="button" title="放大" onClick={() => updateViewport({ ...viewport, k: Math.min(2.5, viewport.k * 1.15) })} className="rounded-md p-1.5 hover:bg-white/10 hover:text-white"><ZoomIn className="h-3.5 w-3.5" /></button><button type="button" title="适应画布" onClick={() => updateViewport({ x: 200, y: 120, k: 1 })} className="rounded-md p-1.5 hover:bg-white/10 hover:text-white"><Maximize2 className="h-3.5 w-3.5" /></button></div>
  </div>;
  */
}
