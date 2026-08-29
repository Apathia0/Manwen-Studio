import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react';
import { Bot, Boxes, Check, ChevronLeft, FileText, Loader2, PanelLeft, Pencil, Plus, Save, Search, SplitSquareHorizontal, Trash2, Upload, X } from 'lucide-react';
import {
  applyVideoCanvasPlan,
  cancelVideoCanvasRun,
  confirmVideoCanvasPlan,
  confirmVideoCanvasRun,
  createVideoCanvas,
  deleteVideoCanvas,
  getVideoCanvas,
  getVideoCanvasRun,

  compileScenes,
  generateDirectorPlan,
  screenplaySplit,
  listVideoCanvasPlans,
  listVideoCanvasNodeCatalog,
  listVideoCanvases,
  runVideoCanvas,
  syncVideoCanvasPlanWorkflow,
  saveVideoCanvasGraph,
  saveVideoCanvasLayout,
  updateVideoCanvas,
  validateVideoCanvas,
  getAiModels,
  createVideoAsset,
  replaceVideoAsset,
  toPublicVideoAssetUrl,
  type ChapterVideoWorkflow,
  type AiModelItem,
  type VideoAsset,
  type VideoCanvas,
  type VideoCanvasGraph,
  type VideoCanvasNodeCatalogItem,
  type VideoCanvasPlan,
  type VideoCanvasRun,
  type VideoStylePreset,
  type DirectorPlan,
  type CompiledSceneUnit,
} from '../api';
import { confirm } from '../lib/confirm';
import { normalizeErrorMessage } from '../lib/errors';
import { toast } from '../lib/toast';
import {
  useCanvasInteractions,
  screenPoint,
  type CanvasSceneEdge,
  type CanvasSceneNode,
  type CanvasTool,
  type CanvasViewport,
  type ContextMenuState,
} from './video-canvas/useCanvasInteractions';
import CanvasSurface from './video-canvas/CanvasSurface';
import CanvasConnectionLayer from './video-canvas/CanvasConnectionLayer';
import CanvasNodeView from './video-canvas/CanvasNodeView';
import CanvasZoomControls from './video-canvas/CanvasZoomControls';
import CanvasMiniMap from './video-canvas/CanvasMiniMap';
import CanvasContextMenu from './video-canvas/CanvasContextMenu';
import CanvasCreateMenu from './video-canvas/CanvasCreateMenu';
import CanvasNodePropertyPanel from './video-canvas/CanvasNodePropertyPanel';
import CanvasBottomToolbar from './video-canvas/CanvasBottomToolbar';
import ChapterImportDialog from './video-canvas/ChapterImportDialog';
import SceneListNodeView from './video-canvas/SceneListNodeView';
import { layoutDirectorUnits, unitNodeId } from './video-canvas/directorLayout';
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
const CANVAS_NODE_TYPES = new Set(['text', 'screenplay', 'scene', 'image', 'video']);
const CANVAS_CATALOG: VideoCanvasNodeCatalogItem[] = [
  { type: 'text', label: '文本', category: '创作', icon: 'Type', inputs: [{ key: 'source', type: 'any', multiple: true, required: false }], outputs: [{ key: 'text', type: 'any' }] },
  { type: 'screenplay', label: '剧本', category: '创作', icon: 'FileText', inputs: [{ key: 'source', type: 'any', multiple: true, required: false }], outputs: [{ key: 'screenplay', type: 'any' }] },
  { type: 'scene', label: '场景', category: '创作', icon: 'Clapperboard', inputs: [{ key: 'screenplay', type: 'any', multiple: true, required: false }], outputs: [{ key: 'shot', type: 'any' }] },
  { type: 'image', label: '图片', category: '媒体', icon: 'Image', inputs: [{ key: 'prompt', type: 'any', multiple: true, required: false }, { key: 'references', type: 'any', multiple: true, required: false }], outputs: [{ key: 'image', type: 'any' }] },
  { type: 'video', label: '视频', category: '媒体', icon: 'Film', inputs: [{ key: 'prompt', type: 'any', multiple: true, required: false }, { key: 'image', type: 'any', multiple: true, required: false }], outputs: [{ key: 'video', type: 'any' }] },
];



function toCanvasNodes(graph: VideoCanvasGraph): CanvasNode[] {
  return graph.nodes.map((node) => ({
    id: node.id,
    type: node.type,
    position: node.position || { x: 0, y: 0 },
    data: { ...node.data, nodeType: node.type },
  }));
}

function toGraph(nodes: CanvasNode[], edges: CanvasEdge[]): VideoCanvasGraph {
  return {
    schema_version: 1,
    nodes: nodes.map((node) => ({ id: node.id, type: node.type, position: node.position, data: { ...node.data, label: node.data.label, config: node.data.config || {}, origin: node.data.origin } })),
    edges: edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target, sourceHandle: edge.sourceHandle, targetHandle: edge.targetHandle, data: edge.data })),
    groups: [],
    metadata: {},
  } as VideoCanvasGraph;
}

/**
 * 将画布运行结果回显到节点：把 run 中已成功节点的 output_snapshot
 * 按 node_id 合并进画布节点 data.result（供节点视图渲染生成结果图/视频）。
 * 未匹配到任何输出时原样返回，避免无谓的 state 更新。
 */
function mergeRunOutputs(run: VideoCanvasRun | null, currentNodes: CanvasNode[]): CanvasNode[] {
  if (!run) return currentNodes;
  const outputByNodeId = new Map<string, Record<string, unknown>>();
  for (const runNode of run.nodes) {
    if (runNode.status === 'succeeded' && runNode.output_snapshot && typeof runNode.output_snapshot === 'object') {
      outputByNodeId.set(runNode.node_id, runNode.output_snapshot as Record<string, unknown>);
    }
  }
  if (outputByNodeId.size === 0) return currentNodes;
  return currentNodes.map((node) => {
    const output = outputByNodeId.get(node.id);
    return output ? { ...node, data: { ...node.data, result: output } } : node;
  });
}

function NodeResultPreview({ url, isVideo }: { url: string; isVideo: boolean }) {
  const [ready, setReady] = useState(false);

  useEffect(() => { setReady(false); }, [url]);

  if (isVideo) return <video src={url} className="h-full w-full object-cover" controls preload="metadata" />;
  return <>
    {!ready && <div className="absolute inset-0 animate-pulse bg-[#2a2e33]" />}
    <img src={url} alt="生成结果" decoding="async" className={`h-full w-full object-cover transition-opacity duration-200 ${ready ? 'opacity-100' : 'opacity-0'}`} onLoad={(event) => {
      const image = event.currentTarget;
      const complete = () => setReady(true);
      if (typeof image.decode === 'function') void image.decode().catch(() => undefined).finally(complete); else complete();
    }} onError={() => setReady(true)} />
  </>;
}

function createNode(item: VideoCanvasNodeCatalogItem, position: { x: number; y: number }): CanvasNode {
  return {
    id: `${item.type}-${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`,
    type: item.type,
    position,
    data: { label: item.label, config: {}, nodeType: item.type },
  };
}

function projectLegacyNode(node: CanvasNode): CanvasNode {
  if (CANVAS_NODE_TYPES.has(node.type)) return node;
  const legacyConfig = node.data.config || {};
  const isVideo = node.type === 'video_generation' || node.type === 'video_asset' || node.type === 'concat';
  const isImage = node.type === 'image_generation' || node.type === 'storyboard' || node.type === 'asset';
  const type = isVideo ? 'video' : isImage ? 'image' : 'text';
  const textParts = [legacyConfig.content, legacyConfig.story_summary, legacyConfig.dialogue, legacyConfig.camera_plan, legacyConfig.motion_plan, legacyConfig.storyboard_prompt, legacyConfig.video_prompt].filter((value) => String(value || '').trim());
  const config = type === 'text'
    ? { ...legacyConfig, content: textParts.join('\n\n') }
    : { ...legacyConfig, prompt: String(legacyConfig.prompt || legacyConfig.storyboard_prompt || legacyConfig.video_prompt || '') };
  return { ...node, type, data: { ...node.data, label: node.data.label || (type === 'text' ? '文本' : type === 'image' ? '图片' : '视频'), config } };
}

function projectLegacyGraph(graph: VideoCanvasGraph): VideoCanvasGraph {
  const nodes = graph.nodes.map((node) => projectLegacyNode(node as CanvasNode) as VideoCanvasGraph['nodes'][number]);
  const nodeIds = new Set(nodes.map((node) => node.id));
  const nodeTypeById = new Map(nodes.map((node) => [node.id, node.type]));
  const edges = graph.edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target)).map((edge) => {
    const targetType = nodeTypeById.get(edge.target);
    const sourceType = nodeTypeById.get(edge.source);
    const targetHandle = targetType === 'text' ? 'source' : targetType === 'screenplay' ? 'source' : targetType === 'scene' ? 'screenplay' : targetType === 'video' && edge.targetHandle === 'image' ? 'image' : targetType === 'image' && edge.targetHandle === 'references' ? 'references' : 'prompt';
    const sourceHandle = sourceType === 'text' ? 'text' : sourceType === 'screenplay' ? 'screenplay' : sourceType === 'scene' ? 'shot' : sourceType === 'image' ? 'image' : 'video';
    return { ...edge, sourceHandle, targetHandle };
  });
  return { ...graph, nodes, edges };
}



export default function VideoCanvasPanel({ storyId, chapterId, workflow: _workflow, assets = [], stylePresets = [], onDirtyChange, onAssetsChanged, onOpenAssetManagement }: Props) {
  const [catalog, setCatalog] = useState<VideoCanvasNodeCatalogItem[]>([]);
  const [splittingNodeId, setSplittingNodeId] = useState<string | null>(null);
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [compilingNodeId, setCompilingNodeId] = useState<string | null>(null);
  const [planBusyNodeId, setPlanBusyNodeId] = useState<string | null>(null);
  const [directorError, setDirectorError] = useState<string | null>(null);
  const [models, setModels] = useState<AiModelItem[]>([]);
  const [canvas, setCanvas] = useState<VideoCanvas | null>(null);
  const [canvasList, setCanvasList] = useState<VideoCanvas[]>([]);
  const [nodes, setNodes] = useState<CanvasNode[]>([]);
  const [edges, setEdges] = useState<CanvasEdge[]>([]);
  const [viewport, setViewport] = useState<ViewportTransform>({ x: 260, y: 120, k: 1 });
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploadingNodeAsset, setUploadingNodeAsset] = useState(false);
  const [uploadingNodeId, setUploadingNodeId] = useState<string | null>(null);
  const [nodeUploadAccept, setNodeUploadAccept] = useState('image/*');
  const [running, setRunning] = useState(false);
  const [submittingNodeId, setSubmittingNodeId] = useState<string | null>(null);
  const [latestRun, setLatestRun] = useState<VideoCanvasRun | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [agentOpen, setAgentOpen] = useState(false);
  const [plans, setPlans] = useState<VideoCanvasPlan[]>([]);
  const [plansLoading, setPlansLoading] = useState(false);
  const [applyingPlanId, setApplyingPlanId] = useState<number | null>(null);
  const [editingCanvasName, setEditingCanvasName] = useState(false);
  const [canvasNameDraft, setCanvasNameDraft] = useState('');
  const [renamingCanvas, setRenamingCanvas] = useState(false);
  const [assetSelectorNodeId, setAssetSelectorNodeId] = useState<string | null>(null);
  const [styleSelectorNodeId, setStyleSelectorNodeId] = useState<string | null>(null);
  const [catalogQuery, setCatalogQuery] = useState('');
  const [dirty, setDirty] = useState(false);
  const [canvasSize, setCanvasSize] = useState({ width: 0, height: 0 });
  const [tool, setTool] = useState<CanvasTool>('select');
  const [miniMapOpen, setMiniMapOpen] = useState(false);
  const [nodeMenu, setNodeMenu] = useState<{ x: number; y: number; nodeId: string } | null>(null);
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const nodeUploadInputRef = useRef<HTMLInputElement | null>(null);
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
  const moveCaptureRef = useRef(false);
  const canvasSelectionKey = `storycanvas.video-canvas.${storyId}.${chapterId ?? 'story'}`;
  useEffect(() => { viewportRef.current = viewport; }, [viewport]);
  useEffect(() => { nodesRef.current = nodes; }, [nodes]);
  useEffect(() => { edgesRef.current = edges; }, [edges]);
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

  const hydrateCanvas = useCallback((nextCanvas: VideoCanvas) => {
    changeVersionRef.current = 0;
    historyRef.current = [];
    redoRef.current = [];
    setHistoryFlags({ canUndo: false, canRedo: false });
    setCanvas(nextCanvas);
    const layoutNodes = nextCanvas.layout.nodes || {};
    const projectedGraph = projectLegacyGraph(nextCanvas.version.graph);
    setNodes(mergeRunOutputs(nextCanvas.runs?.[0] || null, toCanvasNodes(projectedGraph).map((node) => ({ ...node, position: layoutNodes[node.id] || node.position }))));
    setEdges(projectedGraph.edges as CanvasEdge[]);
    setLatestRun(nextCanvas.runs?.[0] || null);
    const savedViewport = nextCanvas.layout.viewport;
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
      void catalogResult;
      setCatalog(CANVAS_CATALOG);
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
      setDirty(false);
      setSelectedNodeId(null);
      setSelectedNodeIds([]);
    } catch (error) {
      if (loadRequestRef.current === requestId) toast.error(normalizeErrorMessage(error, '加载视频画布失败'));
    } finally {
      if (loadRequestRef.current === requestId) setLoading(false);
    }
  }, [canvasSelectionKey, chapterId, hydrateCanvas, storyId]);

  useEffect(() => { void load(); return () => { loadRequestRef.current += 1; }; }, [load]);
  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);
  useEffect(() => {
    if (!canvas || !latestRun || !['queued', 'running', 'cancel_requested'].includes(latestRun.status)) return undefined;
    const timer = window.setInterval(() => { void getVideoCanvasRun(canvas.id, latestRun.id).then((result) => { setLatestRun(result.run); setNodes((current) => mergeRunOutputs(result.run, current)); }).catch(() => undefined); }, 3000);
    return () => window.clearInterval(timer);
  }, [canvas, latestRun]);

  const selectedNode = useMemo(() => nodes.find((node) => node.id === selectedNodeId) || null, [nodes, selectedNodeId]);
  const filteredCatalog = useMemo(() => {
    const query = catalogQuery.trim().toLowerCase();
    return query ? catalog.filter((item) => `${item.label} ${item.category} ${item.type}`.toLowerCase().includes(query)) : catalog;
  }, [catalog, catalogQuery]);
  const catalogGroups = useMemo(() => filteredCatalog.reduce<Record<string, VideoCanvasNodeCatalogItem[]>>((groups, item) => { const category = item.category || '其他'; (groups[category] ||= []).push(item); return groups; }, {}), [filteredCatalog]);

  const canDiscardChanges = useCallback(async () => !dirty || confirm({ title: '未保存的画布修改', message: '切换工作区将放弃当前未保存的节点、连线和配置修改。', confirmText: '放弃修改', danger: true }), [dirty]);
  const markDirty = useCallback(() => { changeVersionRef.current += 1; setDirty(true); }, []);
  const updateViewport = useCallback((next: ViewportTransform) => { changeVersionRef.current += 1; setViewport(next); setDirty(true); }, []);
  const captureHistory = useCallback(() => {
    historyRef.current = [...historyRef.current.slice(-49), { nodes: nodesRef.current, edges: edgesRef.current, viewport: viewportRef.current }];
    redoRef.current = [];
    setHistoryFlags({ canUndo: true, canRedo: false });
  }, []);
  const undo = useCallback(() => {
    const previous = historyRef.current.pop();
    if (!previous) return;
    redoRef.current.push({ nodes: nodesRef.current, edges: edgesRef.current, viewport: viewportRef.current });
    setNodes(previous.nodes); setEdges(previous.edges); setViewport(previous.viewport); setDirty(true);
    setHistoryFlags({ canUndo: historyRef.current.length > 0, canRedo: true });
  }, []);
  const redo = useCallback(() => {
    const next = redoRef.current.pop();
    if (!next) return;
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
    if (!node || (node.type !== 'image' && node.type !== 'video')) return;
    const assetType = file.type.startsWith('image/') ? 'image' : file.type.startsWith('video/') ? 'video' : file.type.startsWith('audio/') ? 'audio' : null;
    const isNodeUpload = uploadModeRef.current === 'node';
    const isStyleReferenceUpload = uploadModeRef.current === 'style_reference';
    const isValidReference = assetType === 'image';
    if (!assetType || assetType !== uploadMediaKindRef.current || (isNodeUpload ? assetType !== node.type : !isValidReference)) {
      toast.error(isNodeUpload ? (node.type === 'video' ? '视频节点仅支持视频文件' : '图片节点仅支持图片文件') : '画布生成节点参考素材仅支持图片文件');
      return;
    }
    if (!chapterId) {
      toast.error('当前画布没有章节，无法上传资产');
      return;
    }
    setUploadingNodeAsset(true);
    setUploadingNodeId(nodeId);
    try {
      const created = await createVideoAsset(chapterId, {
        story_id: storyId,
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
        ? { ...config, asset_id: replaced.asset.id, asset_revision: replaced.asset.revision, asset_type: assetType, existing_url: mediaUrl }
        : {
          ...config,
          reference_asset_ids: [...retainedReferenceIds, replaced.asset.id],
          reference_asset_revisions: [...retainedReferenceRevisions, { asset_id: replaced.asset.id, revision: replaced.asset.revision }],
          reference_previews: [...retainedReferencePreviews, { asset_id: replaced.asset.id, url: mediaUrl, kind: assetType }],
          ...(isStyleReferenceUpload ? { style_reference_asset_id: replaced.asset.id, style_reference_url: mediaUrl } : {}),
        };
      captureHistory();
      updateNode(nodeId, isNodeUpload ? { config: nextConfig, result: { asset_id: replaced.asset.id, url: mediaUrl, file_path: filePath, reused: true } } : { config: nextConfig });
      setSelectedNodeIds([nodeId]);
      setSelectedNodeId(nodeId);
      onAssetsChanged?.();
      toast.success(isNodeUpload ? `${assetType === 'image' ? '图片' : '视频'}已上传到当前节点` : isStyleReferenceUpload ? '风格参考图已绑定到当前节点' : `${assetType === 'image' ? '图片' : assetType === 'video' ? '视频' : '音频'}已上传为参考素材`);
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '本地素材上传失败，请重试'));
    } finally {
      uploadTargetNodeRef.current = null;
      uploadModeRef.current = 'node';
      setUploadingNodeAsset(false);
      setUploadingNodeId(null);
    }
  }, [captureHistory, chapterId, onAssetsChanged, storyId, updateNode]);
  const openNodeFileUpload = useCallback((nodeId: string, mediaKind: 'image' | 'video') => {
    const node = nodesRef.current.find((item) => item.id === nodeId);
    if (!node || (node.type !== 'image' && node.type !== 'video') || (node.type === 'image' && mediaKind !== 'image')) return;
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
    if (!chapterId) throw new Error('当前画布没有章节，无法上传风格参考图');
    setUploadingNodeAsset(true);
    setUploadingNodeId(nodeId);
    try {
      const created = await createVideoAsset(chapterId, {
        story_id: storyId,
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

  const saveCanvas = async (showSuccess = true): Promise<VideoCanvas | null> => {
    if (!canvas) return null;
    const saveVersion = changeVersionRef.current;
    const graphNodes = nodesRef.current;
    const graphEdges = edgesRef.current;
    const saveViewport = viewportRef.current;
    setSaving(true);
    try {
      const graph = toGraph(graphNodes, graphEdges);
      const saved = await saveVideoCanvasGraph(canvas.id, { graph, expected_definition_revision: canvas.definition_revision, change_summary: '更新画布节点与连线' });
      setCanvas((current) => current ? { ...saved, layout: current.layout, layout_revision: current.layout_revision, runs: current.runs } : saved);
      const layout = { nodes: Object.fromEntries(graphNodes.map((node) => [node.id, node.position])), viewport: { x: saveViewport.x, y: saveViewport.y, zoom: saveViewport.k } };
      const layoutResult = await saveVideoCanvasLayout(canvas.id, { layout, expected_layout_revision: canvas.layout_revision });
      const synchronized = { ...saved, layout, layout_revision: layoutResult.layout_revision };
      setCanvas(synchronized);
      if (changeVersionRef.current === saveVersion) setDirty(false);
      if (showSuccess) toast.success('画布已保存');
      return synchronized;
    } catch (error) {
      setDirty(true);
      toast.error(normalizeErrorMessage(error, '保存画布失败，请刷新后重试'));
      return null;
    } finally { setSaving(false); }
  };

  const runCanvas = async (targetNodeId?: string) => {
    if (!canvas || running) return;
    setRunning(true);
    setSubmittingNodeId(targetNodeId || null);
    try {
      const synchronized = dirty ? await saveCanvas(false) : canvas;
      if (!synchronized) return;
      const validation = await validateVideoCanvas(synchronized.id);
      if (!validation.valid) throw new Error(validation.errors.map((item) => item.message).join('；'));
      const result = await runVideoCanvas(synchronized.id, { target_node_ids: targetNodeId ? [targetNodeId] : [], expected_definition_revision: synchronized.definition_revision, idempotency_key: crypto.randomUUID() });
      setLatestRun(result.run);
      setNodes((current) => mergeRunOutputs(result.run, current));
      toast.success(result.run.status === 'awaiting_approval' ? '已创建执行计划，请确认后开始生成' : '画布执行完成');
    } catch (error) { toast.error(normalizeErrorMessage(error, '运行画布失败')); } finally { setRunning(false); setSubmittingNodeId(null); }
  };
  const confirmRun = async () => {
    if (!canvas || !latestRun || latestRun.status !== 'awaiting_approval' || running) return;
    setRunning(true);
    try {
      const result = await confirmVideoCanvasRun(canvas.id, latestRun.id);
      setLatestRun(result.run);
      setNodes((current) => mergeRunOutputs(result.run, current));
      toast.success('已确认生成，任务已进入队列');
    } catch (error) { toast.error(normalizeErrorMessage(error, '确认画布生成失败')); } finally { setRunning(false); }
  };
  const cancelRun = async () => { if (!canvas || !latestRun) return; try { const result = await cancelVideoCanvasRun(canvas.id, latestRun.id); setLatestRun(result.run); toast.success('已请求取消画布运行'); } catch (error) { toast.error(normalizeErrorMessage(error, '取消画布运行失败')); } };
  const createBlankCanvas = async () => { if (!(await canDiscardChanges())) return; try { const result = await createVideoCanvas({ story_id: storyId, default_chapter_id: chapterId ?? null, name: chapterId ? '章节视频画布' : '视频创作画布' }); hydrateCanvas(result); window.localStorage.setItem(canvasSelectionKey, String(result.id)); setCanvasList((current) => [result, ...current.filter((item) => item.id !== result.id)]); setDirty(false); toast.success('空白画布已创建'); } catch (error) { toast.error(normalizeErrorMessage(error, '创建画布失败')); } };
  const loadCanvasPlans = async () => {
    if (!canvas) return;
    setPlansLoading(true);
    try { setPlans((await listVideoCanvasPlans(canvas.id)).plans); }
    catch (error) { toast.error(normalizeErrorMessage(error, '读取创作计划失败')); }
    finally { setPlansLoading(false); }
  };
  const confirmCanvasPlan = async (plan: VideoCanvasPlan) => {
    if (!canvas || plan.status !== 'ready') return;
    setApplyingPlanId(plan.id);
    try {
      const approved = await confirmVideoCanvasPlan(canvas.id, plan.id, plan.revision);
      setPlans((current) => current.map((item) => item.id === approved.id ? approved : item));
      toast.success('创作计划已确认');
    } catch (error) { toast.error(normalizeErrorMessage(error, '确认创作计划失败')); }
    finally { setApplyingPlanId(null); }
  };
  const applyCanvasPlan = async (plan: VideoCanvasPlan) => {
    if (!canvas || plan.status !== 'approved') return;
    if (!(await canDiscardChanges())) return;
    setApplyingPlanId(plan.id);
    try {
      const result = await applyVideoCanvasPlan(canvas.id, plan.id, {
        expected_plan_revision: plan.revision,
        expected_definition_revision: canvas.definition_revision,
      });
      hydrateCanvas(result.canvas);
      setPlans((current) => current.map((item) => item.id === result.plan.id ? result.plan : item));
      toast.success('创作计划已应用到画布');
    } catch (error) { toast.error(normalizeErrorMessage(error, '应用创作计划失败')); }
    finally { setApplyingPlanId(null); }
  };
  const syncPlanWorkflow = async (plan: VideoCanvasPlan) => {
    if (!canvas || !['approved', 'applied'].includes(plan.status) || plan.workflow_id) return;
    setApplyingPlanId(plan.id);
    try {
      const result = await syncVideoCanvasPlanWorkflow(canvas.id, plan.id, plan.revision);
      setPlans((current) => current.map((item) => item.id === result.plan.id ? result.plan : item));
      toast.success(`已同步 ${result.shot_count} 个镜头到章节视频工作流`);
    } catch (error) { toast.error(normalizeErrorMessage(error, '同步章节视频工作流失败')); }
    finally { setApplyingPlanId(null); }
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
      setCanvas((current) => current ? { ...current, name: updated.name, description: updated.description } : current);
      setCanvasList((current) => current.map((item) => item.id === updated.id ? { ...item, name: updated.name, description: updated.description } : item));
      cancelCanvasRename();
      toast.success('画布名称已更新');
    } catch (error) { toast.error(normalizeErrorMessage(error, '更新画布名称失败')); } finally { setRenamingCanvas(false); }
  };
  const deleteCurrentCanvas = async () => {
    if (!canvas || !(await confirm({ title: '删除画布', message: '该画布将从当前列表移除，历史运行记录和已生成媒体会被保留。', confirmText: '删除画布', danger: true }))) return;
    try {
      await deleteVideoCanvas(canvas.id);
      const remaining = canvasList.filter((item) => item.id !== canvas.id);
      setCanvasList(remaining);
      setDirty(false);
      const next = remaining[0];
      if (next) {
        const nextCanvas = await getVideoCanvas(next.id);
        hydrateCanvas(nextCanvas);
        window.localStorage.setItem(canvasSelectionKey, String(next.id));
      } else {
        window.localStorage.removeItem(canvasSelectionKey);
        const created = await createVideoCanvas({ story_id: storyId, default_chapter_id: chapterId ?? null, name: chapterId ? '章节视频画布' : '视频创作画布' });
        hydrateCanvas(created);
        setCanvasList([created]);
        window.localStorage.setItem(canvasSelectionKey, String(created.id));
      }
      toast.success('画布已删除');
    } catch (error) { toast.error(normalizeErrorMessage(error, '删除画布失败')); }
  };
  const selectCanvas = async (canvasId: number) => { if (canvas && canvas.id !== canvasId && !(await canDiscardChanges())) return; try { const selected = await getVideoCanvas(canvasId); hydrateCanvas(selected); window.localStorage.setItem(canvasSelectionKey, String(selected.id)); setDirty(false); setSelectedNodeId(null); } catch (error) { toast.error(normalizeErrorMessage(error, '打开视频画布失败')); } };
  const refreshCanvas = async () => { if (!canvas || !(await canDiscardChanges())) return; try { const refreshed = await getVideoCanvas(canvas.id); hydrateCanvas(refreshed); setCanvasList((await listVideoCanvases(storyId, chapterId)).canvases); setDirty(false); setSelectedNodeId(null); } catch (error) { toast.error(normalizeErrorMessage(error, '刷新视频画布失败')); } };

  const createConnection = useCallback((sourceNodeId: string, sourceHandle: string, targetNodeId: string, targetHandle: string) => {
    if (sourceNodeId === targetNodeId) return;
    const source = nodesRef.current.find((node) => node.id === sourceNodeId);
    const target = nodesRef.current.find((node) => node.id === targetNodeId);
    const sourceCatalog = catalog.find((item) => item.type === source?.type);
    const targetCatalog = catalog.find((item) => item.type === target?.type);
    const sourcePort = sourceCatalog?.outputs.find((port) => port.key === sourceHandle);
    const targetPort = targetCatalog?.inputs.find((port) => port.key === targetHandle);
    if (!sourcePort || !targetPort || sourcePort.type !== targetPort.type) { toast.error('这两个端口类型不兼容'); return; }
    const alreadyConnected = edgesRef.current.some((edge) => edge.source === sourceNodeId && edge.target === targetNodeId && edge.sourceHandle === sourcePort.key && edge.targetHandle === targetPort.key);
    captureHistory();
    setEdges((current) => alreadyConnected ? current : [...current, { id: `edge-${crypto.randomUUID()}`, source: sourceNodeId, target: targetNodeId, sourceHandle: sourcePort.key, targetHandle: targetPort.key }]);
    let syncedReference = false;
    if (!alreadyConnected && source && target && (source.type === 'image' || source.type === 'video') && (target.type === 'image' || target.type === 'video')) {
      const sourceConfig = source.data.config || {};
      const sourceResult = source.data.result as Record<string, unknown> | undefined;
      const assetId = Number(sourceConfig.asset_id ?? sourceResult?.asset_id);
      const asset = Number.isFinite(assetId) ? assets.find((item) => item.id === assetId) : undefined;
      const kind = source.type === 'video' ? 'video' : 'image';
      const url = String(sourceResult?.url || sourceConfig.existing_url || (asset ? toPublicVideoAssetUrl(asset.file_path) : '') || '');
      if (asset && url) {
        setNodes((current) => current.map((node) => {
          if (node.id !== targetNodeId) return node;
          const config = node.data.config || {};
          const existingIds = Array.isArray(config.reference_asset_ids) ? config.reference_asset_ids.map(Number).filter(Number.isFinite) : [];
          if (existingIds.includes(asset.id)) return node;
          const existingRevisions = Array.isArray(config.reference_asset_revisions) ? config.reference_asset_revisions : [];
          const existingPreviews = Array.isArray(config.reference_previews) ? config.reference_previews.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')) : [];
          syncedReference = true;
          return { ...node, data: { ...node.data, config: { ...config, reference_asset_ids: [...existingIds, asset.id], reference_asset_revisions: [...existingRevisions, { asset_id: asset.id, revision: asset.revision }], reference_previews: [...existingPreviews, { asset_id: asset.id, url, kind }] } } };
        }));
      }
    }
    markDirty();
    toast.success(syncedReference ? '连线已创建，资源已同步到参考素材' : '连线已创建');
  }, [assets, catalog, captureHistory, markDirty]);

  const duplicateNode = useCallback((nodeId: string) => {
    const node = nodesRef.current.find((item) => item.id === nodeId);
    if (!node) return;
    captureHistory();
    const copy = { ...node, id: `${node.type}-${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`, position: { x: node.position.x + 42, y: node.position.y + 42 }, data: { ...node.data, config: { ...node.data.config } } };
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
    const created = clip.nodes.map((node) => {
      const newId = `${node.type}-${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`;
      idMap.set(node.id, newId);
      return { ...node, id: newId, position: { x: node.position.x + 42, y: node.position.y + 42 }, data: { ...node.data, config: { ...node.data.config }, ui: { ...(node.data.ui || {}) } } };
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
    }
    setNodes((current) => current.map((node) => {
      const origin = initialNodes.find((item) => item.id === node.id);
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
    captureHistory();
  }, [captureHistory]);

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
    onSelectionChange: (ids) => { moveCaptureRef.current = false; setSelectedNodeIds(ids); setSelectedNodeId(ids.length === 1 ? ids[0] : null); },
    onNodeMove: handleNodeMove,
    onCreateConnection: createConnection,
    onDeleteConnection: deleteConnection,
    onDuplicateNode: duplicateNode,
    onDeleteNodes: removeNodes,
    onUndo: undo,
    onRedo: redo,
    onCopyNodes: handleCopy,
    onPasteNodes: handlePaste,
  });

  useEffect(() => {
    const keyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
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
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'd' && selectedNode) {
        event.preventDefault();
        duplicateNode(selectedNode.id);
      }
    };
    window.addEventListener('keydown', keyDown);
    return () => window.removeEventListener('keydown', keyDown);
  }, [duplicateNode, nodes, selectedNode, selectedNodeIds, updateViewport, viewport.k]);

  if (loading) return <div className="flex h-full items-center justify-center bg-[#111214] text-sm text-white/55"><Loader2 className="mr-2 h-4 w-4 animate-spin" />正在打开创作画布</div>;
  if (!canvas) return <div className="flex h-full items-center justify-center bg-[#111214] p-6 text-white"><div className="w-full max-w-md rounded-xl border border-white/10 bg-[#202226] p-8 text-center"><Boxes className="mx-auto h-10 w-10 text-white/75" /><h2 className="mt-4 text-lg font-semibold">打开一个创作画布</h2><p className="mt-2 text-sm leading-6 text-white/45">从空白节点图开始，或将当前列表工作流导入为可编辑流程。</p><button type="button" onClick={() => void createBlankCanvas()} className="mt-6 inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-semibold text-[#15171a]"><Plus className="h-4 w-4" />新建空白画布</button></div></div>;

  const editorViewport: CanvasViewport = { x: viewport.x, y: viewport.y, scale: viewport.k };
  const inspectorNode = selectedNodeIds.length === 1 ? nodes.find((node) => node.id === selectedNodeIds[0]) || null : null;
  const canvasRect = canvasSize.width > 0 ? canvasSize : null;
  const inspectorSize = { width: inspectorNode?.data.ui?.width || 420, height: inspectorNode?.data.ui?.height || 236 };
  const inspectorScreen = inspectorNode ? { x: inspectorNode.position.x * viewport.k + viewport.x, y: inspectorNode.position.y * viewport.k + viewport.y } : null;
  const panelWidth = 860;
  const panelLeft = inspectorScreen && canvasRect ? Math.max(16, Math.min(Math.max(16, canvasRect.width - panelWidth - 16), inspectorScreen.x - 90)) : 16;
  const panelBelow = inspectorScreen ? inspectorScreen.y + inspectorSize.height * viewport.k + 16 : 16;
  const panelTop = Math.max(16, panelBelow);
  const fitAll = () => {
    const rect = surfaceRef.current?.getBoundingClientRect();
    if (!rect || !nodes.length) { updateViewport({ x: rect ? rect.width / 2 : 260, y: rect ? rect.height / 2 : 120, k: 1 }); return; }
    const left = Math.min(...nodes.map((node) => node.position.x)); const top = Math.min(...nodes.map((node) => node.position.y));
    const right = Math.max(...nodes.map((node) => node.position.x + (node.data.ui?.width || 420))); const bottom = Math.max(...nodes.map((node) => node.position.y + (node.data.ui?.height || 236)));
    const k = Math.min(2, Math.max(.1, Math.min((rect.width - 160) / Math.max(1, right - left), (rect.height - 200) / Math.max(1, bottom - top))));
    updateViewport({ x: (rect.width - (right - left) * k) / 2 - left * k, y: (rect.height - (bottom - top) * k) / 2 - top * k, k });
  };
  const autoLayoutCanvas = () => {
    const currentNodes = nodesRef.current;
    if (!currentNodes.length) return;
    const nodeById = new Map(currentNodes.map((node) => [node.id, node]));
    const incomingCount = new Map(currentNodes.map((node) => [node.id, 0]));
    const children = new Map(currentNodes.map((node) => [node.id, [] as string[]]));
    for (const edge of edgesRef.current) {
      if (!nodeById.has(edge.source) || !nodeById.has(edge.target)) continue;
      children.get(edge.source)?.push(edge.target);
      incomingCount.set(edge.target, (incomingCount.get(edge.target) || 0) + 1);
    }
    const layers = new Map<string, number>();
    const queue = currentNodes.filter((node) => (incomingCount.get(node.id) || 0) === 0).map((node) => node.id);
    for (const nodeId of queue) layers.set(nodeId, 0);
    for (let cursor = 0; cursor < queue.length; cursor += 1) {
      const nodeId = queue[cursor];
      const layer = layers.get(nodeId) || 0;
      for (const childId of children.get(nodeId) || []) {
        layers.set(childId, Math.max(layers.get(childId) || 0, layer + 1));
        const remaining = (incomingCount.get(childId) || 1) - 1;
        incomingCount.set(childId, remaining);
        if (remaining === 0) queue.push(childId);
      }
    }
    for (const node of currentNodes) if (!layers.has(node.id)) layers.set(node.id, 0);
    const columns = new Map<number, CanvasNode[]>();
    for (const node of currentNodes) {
      const layer = layers.get(node.id) || 0;
      const column = columns.get(layer) || [];
      column.push(node);
      columns.set(layer, column);
    }
    const positions = new Map<string, { x: number; y: number }>();
    let x = 120;
    for (const [, column] of [...columns.entries()].sort(([left], [right]) => left - right)) {
      let y = 120;
      const columnWidth = Math.max(...column.map((node) => node.data.ui?.width || 360));
      for (const node of column.sort((left, right) => left.position.y - right.position.y)) {
        positions.set(node.id, { x, y });
        y += (node.data.ui?.height || 220) + 80;
      }
      x += columnWidth + 120;
    }
    captureHistory();
    setNodes((current) => current.map((node) => ({ ...node, position: positions.get(node.id) || node.position })));
    markDirty();
    toast.success('画布节点已自动整理');
  };
  const addNodeFromTool = (type: string) => { const item = catalog.find((entry) => entry.type === type); if (!item) { toast.info('当前画布仅支持文本、图片、视频节点'); return; } captureHistory(); addCatalogNode(item); };
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
      const sceneNode: CanvasNode = {
        id: `split-${nodeId}-${Math.random().toString(36).slice(2, 8)}`,
        type: 'scene',
        position: { x: baseX, y: baseY },
        data: {
          label: `剧本审核（${scenes.length} 场）`,
          nodeType: 'scene',
          ui: { width: 1100, height: 680 },
          config: {
            scenes,
            approved: false,
            scene_count: scenes.length,
            source_screenplay_node: nodeId,
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
      setNodes((current) => [...current, ...newNodes]);
      setEdges((current) => [...current, ...newEdges]);
      setDirty(true);
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
    setDirty(true);
    setImportDialogOpen(false);
    toast.success(`已生成剧本节点（${Math.round(screenplayText.length / 100) / 10}k 字），可编辑后点击「AI 拆分」`);
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
    setDirty(true);
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
      const newNodes: CanvasNode[] = [];
      const newEdges: CanvasEdge[] = [];
      for (const unit of compiled) {
        const videoId = unitNodeId(nodeId, unit.unit_id);
        const storyboardId = `${videoId}-sb`;
        const videoPos = positions.get(unit.unit_id) || anchor;
        const baseConfig = {
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
      setDirty(true);
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
  const nodeRunStatuses = new Map((latestRun?.nodes || []).map((runNode) => [runNode.node_id, runNode.status]));
  const canvasOptions = canvasList.some((item) => item.id === canvas.id) ? canvasList : [canvas, ...canvasList];
  return <div className="relative h-full min-h-0 overflow-hidden bg-[#181818] text-white">
    <CanvasSurface containerRef={surfaceRef} viewport={editorViewport} tool={interaction.state.activeTool} handlers={interaction.handlers} state={interaction.state} onViewportChange={(next) => updateViewport({ x: next.x, y: next.y, k: next.scale })} onDrop={(event, world) => { const type = event.dataTransfer.getData('application/x-storycanvas-node'); const item = catalog.find((entry) => entry.type === type); if (item) { captureHistory(); addCatalogNode(item, world); } }}>
      <CanvasConnectionLayer nodes={nodes as CanvasSceneNode[]} edges={edges as CanvasSceneEdge[]} catalog={catalog} connecting={interaction.state.connecting} mouseWorld={interaction.state.mouseWorld} connectionTargetNodeId={interaction.state.connectionTargetNodeId} selectedConnectionId={interaction.state.selectedConnectionId} handlers={interaction.handlers} />
      {interaction.state.selectionBox && (() => { const box = interaction.state.selectionBox; const left = Math.min(box.startWorldX, box.currentWorldX); const top = Math.min(box.startWorldY, box.currentWorldY); return <div className="pointer-events-none absolute rounded-lg border-2 border-[#2f80ff]/80 bg-[#2f80ff]/10" style={{ left, top, width: Math.abs(box.currentWorldX - box.startWorldX), height: Math.abs(box.currentWorldY - box.startWorldY) }} />; })()}
      {nodes.map((node) => <CanvasNodeView key={node.id} node={node as CanvasSceneNode} catalogItem={catalog.find((item) => item.type === node.type) || catalog[0]} selected={selectedNodeIds.includes(node.id)} connecting={interaction.state.connecting} connectionTargetNodeId={interaction.state.connectionTargetNodeId} scale={editorViewport.scale} handlers={interaction.handlers} onResize={handleNodeResize} onResizeEnd={handleNodeResizeEnd} onNodeContextMenu={(event, nodeId) => { event.preventDefault(); event.stopPropagation(); setNodeMenu({ x: event.clientX, y: event.clientY, nodeId }); }} renderContent={(nodeView) => { const result = nodeView.data.result as (Record<string, unknown> & { url?: string }) | undefined; const resultUrl = result?.url; const runStatus = nodeRunStatuses.get(nodeView.id); const isBusy = submittingNodeId === nodeView.id || ['awaiting_approval', 'queued', 'running', 'cancel_requested'].includes(String(runStatus || '')); if (resultUrl) return <NodeResultPreview url={resultUrl} isVideo={nodeView.type === 'video'} />; if (isBusy) return <div className="flex h-full w-full items-center justify-center bg-[#202226]" aria-label="生成中"><Loader2 className="h-8 w-8 animate-spin text-[#73a7ff]" /></div>; if (nodeView.type === 'scene') { const config = (nodeView.data.config || {}) as Record<string, unknown>; return (
  <div className="flex h-full w-full flex-col gap-1.5" data-canvas-no-zoom>
    <div className="min-h-0 flex-1 overflow-hidden">
      <SceneListNodeView
        config={config}
        onChange={(partial) => updateSceneNodeConfig(nodeView.id, partial)}
        onToggleApproved={() => updateSceneNodeConfig(nodeView.id, { approved: !config.approved })}
        directorPlan={(config.director_plan as DirectorPlan) || null}
        directorPlanLoading={planBusyNodeId === nodeView.id}
        directorPlanError={directorError}
        onGenerateDirectorPlan={() => void generateDirectorPlanForNode(nodeView.id)}
        onApplyDirectorPlan={() => void applyDirectorPlan(nodeView.id)}
        directorPlanStale={Boolean(config.director_plan && config.director_plan_stale)}
      />
    </div>
    {config.approved ? null : (
      <p className="shrink-0 px-1 text-center text-[10px] text-slate-500">统一审批通过后可进行 AI 导演编排</p>
    )}
  </div>
); }
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
      {agentOpen && <aside className="absolute left-4 top-20 z-30 w-72 overflow-hidden rounded-xl border border-white/10 bg-[#1b1d21]/[.98] shadow-2xl"><div className="flex items-center justify-between border-b border-white/[.08] px-3 py-2"><div><p className="text-xs font-semibold">创作计划</p><p className="mt-0.5 text-[10px] text-white/35">确认后可分别同步工作流或应用画布</p></div><button type="button" title="刷新创作计划" onClick={() => void loadCanvasPlans()} className="rounded-md p-1 text-white/45 hover:bg-white/10 hover:text-white"><Loader2 className={`h-3.5 w-3.5 ${plansLoading ? 'animate-spin' : ''}`} /></button></div><div className="max-h-52 overflow-y-auto p-2">{plansLoading ? <p className="p-2 text-xs text-white/40">读取计划中</p> : plans.length ? plans.map((plan) => <div key={plan.id} className="border-b border-white/[.08] px-1 py-2 last:border-0"><div className="flex items-center justify-between"><span className="text-xs text-white/80">计划 #{plan.id}</span><span className={`text-[10px] ${plan.status === 'applied' ? 'text-emerald-300' : plan.status === 'approved' ? 'text-sky-300' : plan.status === 'ready' ? 'text-amber-300' : 'text-white/35'}`}>{plan.status === 'applied' ? '已应用' : plan.status === 'approved' ? '已确认' : plan.status === 'ready' ? '待确认' : '草案'}</span></div><p className="mt-1 text-[10px] text-white/35">镜头 {Array.isArray(plan.shots.shots) ? plan.shots.shots.length : 0} · 资产 {Array.isArray(plan.assets.assets) ? plan.assets.assets.length : 0}</p>{plan.status === 'ready' && <button type="button" disabled={applyingPlanId === plan.id} onClick={() => void confirmCanvasPlan(plan)} className="mt-1.5 rounded bg-white px-2 py-1 text-[10px] font-medium text-[#17191c] disabled:opacity-40">确认计划</button>}{['approved', 'applied'].includes(plan.status) && <div className="mt-1.5 flex gap-1.5">{!plan.workflow_id && <button type="button" disabled={applyingPlanId === plan.id} onClick={() => void syncPlanWorkflow(plan)} className="rounded bg-white/10 px-2 py-1 text-[10px] text-white/85 disabled:opacity-40">同步分镜</button>}{plan.status === 'approved' && <button type="button" disabled={applyingPlanId === plan.id} onClick={() => void applyCanvasPlan(plan)} className="rounded bg-[#73a7ff] px-2 py-1 text-[10px] font-medium text-[#111827] disabled:opacity-40">应用画布</button>}</div>}{plan.workflow_id && <p className="mt-1 text-[10px] text-emerald-300/80">已同步工作流 #{plan.workflow_id}</p>}</div>) : <p className="p-2 text-xs leading-5 text-white/40">向助手描述小说正文、剧本或文本节点后，它会在此创建可审阅计划。</p>}</div></aside>}
      <input ref={nodeUploadInputRef} type="file" accept={nodeUploadAccept} className="hidden" disabled={uploadingNodeAsset} onChange={(event) => void handleNodeFileUpload(event)} />
      {inspectorNode && <CanvasNodePropertyPanel node={inspectorNode as CanvasSceneNode} assets={assets} models={models} left={panelLeft} top={panelTop} onChange={(key, value) => { captureHistory(); updateNodeConfig(inspectorNode.id, key, value); }} onAssetChange={(assetId) => { captureHistory(); selectAsset(inspectorNode.id, assetId); }} onOpenAssetSelector={() => setAssetSelectorNodeId(inspectorNode.id)} onOpenStyleSelector={() => setStyleSelectorNodeId(inspectorNode.id)} onGenerate={() => void runCanvas(inspectorNode.id)} isGenerating={submittingNodeId === inspectorNode.id} isUploading={uploadingNodeId === inspectorNode.id} onUploadReference={(kind) => openReferenceFileUpload(inspectorNode.id, kind)} />}
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
          onFileUpload={(file) => uploadNodeStyleReference(styleSelectorNodeId, file)}
          onStyleSelect={(styleName) => {
            const preset = stylePresets.find((item) => item.name === styleName);
            if (!preset) return;
            captureHistory();
            selectStyle(styleSelectorNodeId, preset.id);
          }}
        />;
      })()}
      {assetSelectorNodeId && <AssetReferenceSelector availableAssets={assets} selectedIds={(() => { const node = nodes.find((item) => item.id === assetSelectorNodeId); const config = node?.data.config || {}; return node && (node.type === 'asset' || node.type === 'video_asset') ? (config.asset_id ? [Number(config.asset_id)] : []) : (Array.isArray(config.reference_asset_ids) ? config.reference_asset_ids.map(Number) : []); })()} onConfirm={(ids) => { captureHistory(); selectAssets(assetSelectorNodeId, ids); setAssetSelectorNodeId(null); }} onClose={() => setAssetSelectorNodeId(null)} />}
      {sidebarOpen && <aside className="absolute bottom-20 left-3 top-3 z-20 flex w-56 flex-col overflow-hidden rounded-2xl border border-[#393633] bg-[#211f1d]/95 shadow-2xl backdrop-blur-xl"><div className="flex items-center justify-between border-b border-[#393633] px-4 py-3"><span className="text-sm font-semibold text-[#e8e2dc]">节点库</span><button type="button" title="收起节点库" onClick={() => setSidebarOpen(false)} className="p-1 text-[#938b84] hover:text-white"><ChevronLeft className="h-4 w-4" /></button></div><div className="border-b border-[#393633] p-3"><label className="flex items-center gap-2 rounded-lg bg-[#2a2725] px-2 py-2 text-[#938b84]"><Search className="h-3.5 w-3.5" /><input value={catalogQuery} onChange={(event) => setCatalogQuery(event.target.value)} placeholder="搜索节点" className="min-w-0 flex-1 bg-transparent text-xs text-white outline-none placeholder:text-[#817a74]" /></label></div><div className="min-h-0 flex-1 overflow-y-auto p-2">{Object.entries(catalogGroups).map(([category, items]) => <div key={category} className="mb-3"><p className="px-2 py-1 text-[10px] text-[#817a74]">{category}</p>{items.map((item) => <button key={item.type} type="button" draggable onDragStart={(event) => event.dataTransfer.setData('application/x-storycanvas-node', item.type)} onClick={() => { captureHistory(); addCatalogNode(item); }} className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-xs text-[#d9d2cb] hover:bg-[#34312e]"><Plus className="h-3.5 w-3.5 text-[#958d86]" />{item.label}</button>)}</div>)}</div></aside>}
      {!sidebarOpen && <button type="button" title="打开节点库" onClick={() => setSidebarOpen(true)} className="absolute left-3 top-3 z-20 rounded-xl border border-[#393633] bg-[#211f1d]/95 p-3 text-[#a49b94] shadow-xl hover:text-white"><PanelLeft className="h-4 w-4" /></button>}
      <div className="pointer-events-none absolute right-4 top-4 z-20"><div className="pointer-events-auto flex items-center gap-1.5 rounded-xl border border-[#393633] bg-[#211f1d]/95 p-2 shadow-xl"><span className={`mx-1 h-2 w-2 rounded-full ${dirty ? 'bg-amber-400' : 'bg-emerald-400'}`} />{editingCanvasName ? <div className="flex items-center gap-1"><input autoFocus maxLength={255} value={canvasNameDraft} onChange={(event) => setCanvasNameDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void renameCanvas(); if (event.key === 'Escape') cancelCanvasRename(); }} className="w-[190px] rounded-md border border-[#766d65] bg-[#171513] px-2 py-1.5 text-xs text-white outline-none focus:border-[#eee9e4]" aria-label="画布名称" /><button type="button" title="确认重命名" disabled={renamingCanvas} onClick={() => void renameCanvas()} className="rounded-md p-1.5 text-emerald-300 hover:bg-white/10 disabled:opacity-40"><Check className="h-4 w-4" /></button><button type="button" title="取消重命名" disabled={renamingCanvas} onClick={cancelCanvasRename} className="rounded-md p-1.5 text-[#a49b94] hover:bg-white/10 hover:text-white disabled:opacity-40"><X className="h-4 w-4" /></button></div> : <><select value={canvas.id} onChange={(event) => void selectCanvas(Number(event.target.value))} className="max-w-[200px] bg-transparent px-1 text-xs text-[#ded7d0] outline-none">{canvasOptions.map((item, index) => <option className="bg-[#211f1d]" key={item.id} value={item.id}>{`画布 ${index + 1} · ${item.name}`}</option>)}</select><button type="button" title="重命名当前画布" onClick={beginCanvasRename} className="rounded-lg p-2 text-[#a49b94] hover:bg-white/10 hover:text-white"><Pencil className="h-3.5 w-3.5" /></button></>}<button type="button" title="新建空白画布" onClick={() => void createBlankCanvas()} className="rounded-lg p-2 text-[#a49b94] hover:bg-white/10 hover:text-white"><Plus className="h-4 w-4" /></button><button type="button" title="删除当前画布" onClick={() => void deleteCurrentCanvas()} className="rounded-lg p-2 text-[#a49b94] hover:bg-white/10 hover:text-rose-300"><Trash2 className="h-4 w-4" /></button><span className="mx-1 h-6 w-px bg-[#403c38]" /><button type="button" title="导入小说章节" onClick={() => setImportDialogOpen(true)} className="inline-flex items-center gap-1.5 rounded-lg bg-[#73a7ff] px-2.5 py-2 text-xs text-[#111827] hover:bg-[#8db6ff] hover:text-[#17191c]"><FileText size={12} /> 导入小说章节</button><span className="mx-1 h-6 w-px bg-[#403c38]" /><button type="button" title="保存画布" disabled={saving} onClick={() => void saveCanvas()} className="inline-flex items-center gap-2 rounded-lg bg-white px-4 text-xs font-semibold text-[#24211f] hover:bg-[#f0ebde] disabled:cursor-wait disabled:opacity-50"><Save className="h-4 w-4" />{saving ? '保存中' : '保存'}</button><button type="button" title="打开画布 AI 助手" onClick={() => setAgentOpen((open) => !open)} className={`grid h-10 w-10 place-items-center rounded-xl border transition ${agentOpen ? 'border-[#eee9e4] bg-[#eee9e4] text-[#24211f]' : 'border-[#766d65] bg-[#35312e] text-[#f3cf84] hover:border-[#f3cf84] hover:bg-[#423c36]'}`}><Bot className="h-5 w-5" /></button></div></div>
      {agentOpen && <aside className="absolute bottom-20 right-4 top-20 z-30 flex w-[380px] flex-col overflow-hidden rounded-2xl border border-[#393633] bg-[#211f1d]/[.98] shadow-2xl"><div className="flex items-center justify-between border-b border-[#393633] px-4 py-3"><span className="text-sm font-semibold">画布 AI 助手</span><button type="button" title="关闭助手" onClick={() => setAgentOpen(false)} className="text-[#958d86] hover:text-white"><X className="h-4 w-4" /></button></div><div className="min-h-0 flex-1 overflow-hidden"><Suspense fallback={<div className="p-4 text-sm text-[#948b84]">正在加载 AI 助手...</div>}><AgentPanel storyId={storyId} chapterId={chapterId} workflowType="video_canvas" workflowId={canvas.id} onContentUpdated={() => void refreshCanvas()} /></Suspense></div></aside>}
      <div className="absolute bottom-20 right-4 z-20 rounded-xl border border-[#393633] bg-[#211f1d]/95 px-3 py-2 text-[11px] text-[#a79f98]">{nodes.length} 节点 · {edges.length} 连线{interaction.state.connecting && ' · 选择兼容输入端口完成连接'}{latestRun && ` · ${latestRun.status}`}{latestRun?.status === 'awaiting_approval' && <button type="button" disabled={running} onClick={() => void confirmRun()} className="ml-2 rounded bg-[#eee9e4] px-2 py-1 font-medium text-[#24211f] disabled:opacity-50">确认生成</button>}{latestRun && ['queued', 'running', 'cancel_requested'].includes(latestRun.status) && <button type="button" onClick={() => void cancelRun()} className="ml-2 rounded border border-[#5a534d] px-2 py-1 text-[#d7d0c9]">取消</button>}</div>
      <CanvasContextMenu menu={contextMenuState} onClose={() => { setNodeMenu(null); interaction.closeContextMenu(); }} onDuplicateNode={(nodeId) => { interaction.closeContextMenu(); duplicateNode(nodeId); }} onDeleteNode={(nodeId) => { interaction.closeContextMenu(); removeNodes([nodeId]); }} onDeleteConnection={(connectionId) => { interaction.closeContextMenu(); deleteConnection(connectionId); }} />
      {createMenuPosition && <CanvasCreateMenu position={screenPoint(createMenuPosition, editorViewport)} onSelect={(type) => { const item = catalog.find((entry) => entry.type === type); if (item && createMenuPosition) { captureHistory(); addCatalogNode(item, createMenuPosition); } interaction.closeCreateMenu(); }} onClose={interaction.closeCreateMenu} />}
      {miniMapOpen && <CanvasMiniMap nodes={nodes.map((node) => ({ id: node.id, position: node.position, width: node.data.ui?.width, height: node.data.ui?.height, type: node.type }))} viewport={editorViewport} viewportSize={canvasSize} onViewportChange={(next) => updateViewport({ x: next.x, y: next.y, k: next.scale })} />}
      <CanvasZoomControls scale={viewport.k} onScaleChange={(k) => updateViewport({ ...viewport, k })} onReset={() => { const rect = surfaceRef.current?.getBoundingClientRect(); updateViewport({ x: rect ? rect.width / 2 : 260, y: rect ? rect.height / 2 : 120, k: 1 }); }} isMiniMapOpen={miniMapOpen} onToggleMiniMap={() => setMiniMapOpen((open) => !open)} />
      <CanvasBottomToolbar scale={viewport.k} supportsAudio={false} onScaleChange={(k) => updateViewport({ ...viewport, k })} onReset={() => { const rect = surfaceRef.current?.getBoundingClientRect(); updateViewport({ x: rect ? rect.width / 2 : 260, y: rect ? rect.height / 2 : 120, k: 1 }); }} onFit={fitAll} onUndo={undo} onRedo={redo} onAutoLayout={autoLayoutCanvas} onOpenAssetManagement={() => onOpenAssetManagement?.()} isAssetManagementDisabled={!chapterId && !onOpenAssetManagement} onTool={(nextTool) => { if (nextTool === 'select' || nextTool === 'pan') setTool(nextTool); else if (nextTool === 'help') toast.info('空格或中键平移，滚轮缩放，框选多个节点'); }} activeTool={tool} onAddNode={(type) => addNodeFromTool(type)} />
      {importDialogOpen && canvas && <ChapterImportDialog canvasId={canvas.id} onClose={() => setImportDialogOpen(false)} onImported={handleScreenplayImported} />}
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
    {agentOpen && <aside className="absolute bottom-4 right-4 top-[78px] z-30 flex w-[380px] flex-col overflow-hidden rounded-xl border border-white/10 bg-[#1b1d21]/[.98] shadow-2xl"><div className="flex items-center justify-between border-b border-white/[.08] px-4 py-3"><div><p className="text-sm font-semibold">画布 AI 助手</p><p className="mt-0.5 text-[10px] text-white/35">读取当前画布，提出结构建议</p></div><button type="button" onClick={() => setAgentOpen(false)} className="rounded-lg p-1.5 text-white/45 hover:bg-white/10 hover:text-white"><X className="h-4 w-4" /></button></div><div className="min-h-0 flex-1 overflow-hidden"><Suspense fallback={<div className="p-4 text-sm text-white/45">正在加载 AI 助手...</div>}><AgentPanel storyId={storyId} chapterId={chapterId} workflowType="video_canvas" workflowId={canvas.id} onContentUpdated={() => void refreshCanvas()} /></Suspense></div></aside>}
    <div className="absolute bottom-4 right-4 z-20 rounded-lg border border-white/10 bg-[#1b1d21]/90 px-3 py-2 text-[10px] text-white/45"><span>{nodes.length} 节点 · {edges.length} 连线</span>{connectionStart && <span className="ml-3 text-white/75">选择目标节点的兼容输入端口完成连接</span>}{latestRun && <span className="ml-3 text-white/75">运行：{latestRun.status}</span>}{latestRun?.status === 'awaiting_approval' && <button type="button" onClick={() => void confirmRun()} className="ml-3 rounded bg-white px-2 py-1 text-[10px] font-medium text-[#17191c]">确认生成</button>}{latestRun && ['queued', 'running', 'cancel_requested'].includes(latestRun.status) && <button type="button" onClick={() => void cancelRun()} className="ml-3 rounded border border-white/20 px-2 py-1 text-[10px] text-white/70">取消运行</button>}</div>
    <div className="absolute bottom-4 left-4 z-10 flex items-center gap-1 rounded-lg border border-white/10 bg-[#1b1d21]/90 p-1 text-white/50"><button type="button" title="缩小" onClick={() => updateViewport({ ...viewport, k: Math.max(.2, viewport.k / 1.15) })} className="rounded-md p-1.5 hover:bg-white/10 hover:text-white"><ZoomOut className="h-3.5 w-3.5" /></button><button type="button" title="放大" onClick={() => updateViewport({ ...viewport, k: Math.min(2.5, viewport.k * 1.15) })} className="rounded-md p-1.5 hover:bg-white/10 hover:text-white"><ZoomIn className="h-3.5 w-3.5" /></button><button type="button" title="适应画布" onClick={() => updateViewport({ x: 200, y: 120, k: 1 })} className="rounded-md p-1.5 hover:bg-white/10 hover:text-white"><Maximize2 className="h-3.5 w-3.5" /></button></div>
  </div>;
  */
}
