import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type DragEvent, type PointerEvent as ReactPointerEvent, type RefObject, type ReactNode, type WheelEvent } from 'react';
import { Bot, Boxes, ChevronLeft, Clapperboard, FileText, Film, Image, Layers3, Loader2, Move, Palette, PanelLeft, Play, Plus, Save, Search, Send, Settings2, StickyNote, Trash2, Upload, Wand2, X } from 'lucide-react';
import {
  cancelVideoCanvasRun,
  confirmVideoCanvasRun,
  createVideoCanvas,
  getVideoCanvas,
  getVideoCanvasRun,
  importVideoCanvasListWorkflow,
  listVideoCanvasNodeCatalog,
  listVideoCanvases,
  runVideoCanvas,
  saveVideoCanvasGraph,
  saveVideoCanvasLayout,
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
  type VideoCanvasRun,
  type VideoStylePreset,
} from '../api';
import { confirm } from '../lib/confirm';
import { normalizeErrorMessage } from '../lib/errors';
import { toast } from '../lib/toast';
import CanvasEditorSurface, { type CanvasSceneNode, type CanvasSceneEdge, type CanvasViewport } from './video-canvas/CanvasEditorSurface';
import CanvasNodePropertyPanel from './video-canvas/CanvasNodePropertyPanel';
import CanvasBottomToolbar from './video-canvas/CanvasBottomToolbar';
import AssetReferenceSelector from './AssetReferenceSelector';

const AgentPanel = lazy(() => import('./AgentPanel/AgentPanel'));

interface Props {
  storyId: number;
  chapterId?: number;
  workflow: ChapterVideoWorkflow | null;
  assets: VideoAsset[];
  stylePresets: VideoStylePreset[];
  onDirtyChange?: (dirty: boolean) => void;
  onAssetsChanged?: () => void;
}

type ViewportTransform = { x: number; y: number; k: number };
type CanvasNodeData = { label?: string; config?: Record<string, unknown>; origin?: Record<string, unknown>; nodeType?: string; ui?: { width?: number; height?: number }; [key: string]: unknown };
type CanvasNode = { id: string; type: string; position: { x: number; y: number }; data: CanvasNodeData };
type CanvasEdge = { id: string; source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null; data?: Record<string, unknown> };
type ConnectionStart = { nodeId: string; handleKey: string };

const IMAGE_ASSET_TYPES = new Set(['storyboard_frame', 'character_reference', 'scene_reference', 'prop_reference', 'style_reference', 'image']);
const VIDEO_ASSET_TYPES = new Set(['video_clip', 'video', 'compiled_video', 'final_video']);
const NODE_WIDTH = 330;
const NODE_HEADER_HEIGHT = 76;
const CANVAS_NODE_TYPES = new Set(['text', 'image', 'video']);
const CANVAS_CATALOG: VideoCanvasNodeCatalogItem[] = [
  { type: 'text', label: '文本', category: '创作', icon: 'Type', inputs: [{ key: 'source', type: 'any', multiple: true, required: false }], outputs: [{ key: 'text', type: 'any' }] },
  { type: 'image', label: '图片', category: '媒体', icon: 'Image', inputs: [{ key: 'prompt', type: 'any', multiple: true, required: false }, { key: 'references', type: 'any', multiple: true, required: false }], outputs: [{ key: 'image', type: 'any' }] },
  { type: 'video', label: '视频', category: '媒体', icon: 'Film', inputs: [{ key: 'prompt', type: 'any', multiple: true, required: false }, { key: 'image', type: 'any', multiple: true, required: false }], outputs: [{ key: 'video', type: 'any' }] },
];

const CATEGORY_ICON: Record<string, typeof Image> = {
  '输入': FileText,
  '创作': Clapperboard,
  '资产': Image,
  '风格': Palette,
  '生成': Wand2,
  '画面': Layers3,
  '后处理': Film,
  '输出': Send,
  '辅助': StickyNote,
};

function isVideoAsset(asset: VideoAsset): boolean {
  const type = String(asset.asset_type || '').toLowerCase();
  return VIDEO_ASSET_TYPES.has(type) || /\.(mp4|mov|webm|mkv)$/i.test(asset.file_path || '');
}

function isImageAsset(asset: VideoAsset): boolean {
  const type = String(asset.asset_type || '').toLowerCase();
  return IMAGE_ASSET_TYPES.has(type) || (!isVideoAsset(asset) && /\.(png|jpe?g|webp|gif)$/i.test(asset.file_path || ''));
}

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
    const targetHandle = targetType === 'text' ? 'source' : targetType === 'video' && edge.targetHandle === 'image' ? 'image' : targetType === 'image' && edge.targetHandle === 'references' ? 'references' : 'prompt';
    const sourceHandle = nodeTypeById.get(edge.source) === 'text' ? 'text' : nodeTypeById.get(edge.source) === 'image' ? 'image' : 'video';
    return { ...edge, sourceHandle, targetHandle };
  });
  return { ...graph, nodes, edges };
}

/**
 * 改编自 basketikun/infinite-canvas 的 InfiniteCanvas（MIT，Copyright 2026 basketikun）。
 * 保留其围绕鼠标位置缩放、空格/中键平移和点阵背景的交互模型，并接入本项目的画布数据协议。
 */
function InfiniteCanvasSurface({ containerRef, viewport, onViewportChange, onBackgroundPointerDown, onDrop, children }: {
  containerRef: RefObject<HTMLDivElement | null>;
  viewport: ViewportTransform;
  onViewportChange: (next: ViewportTransform) => void;
  onBackgroundPointerDown: () => void;
  onDrop: (event: DragEvent<HTMLDivElement>, world: { x: number; y: number }) => void;
  children: ReactNode;
}) {
  const panRef = useRef({ active: false, startX: 0, startY: 0, originX: 0, originY: 0 });
  const viewportRef = useRef(viewport);
  const [spacePressed, setSpacePressed] = useState(false);
  useEffect(() => { viewportRef.current = viewport; }, [viewport]);

  useEffect(() => {
    const keyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (event.code === 'Space' && !target?.matches('input, textarea, select, [contenteditable="true"]')) {
        event.preventDefault();
        setSpacePressed(true);
      }
    };
    const keyUp = (event: KeyboardEvent) => { if (event.code === 'Space') setSpacePressed(false); };
    const move = (event: PointerEvent) => {
      if (!panRef.current.active) return;
      onViewportChange({ x: panRef.current.originX + event.clientX - panRef.current.startX, y: panRef.current.originY + event.clientY - panRef.current.startY, k: viewportRef.current.k });
    };
    const up = () => { panRef.current.active = false; document.body.style.cursor = ''; };
    window.addEventListener('keydown', keyDown);
    window.addEventListener('keyup', keyUp);
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
    return () => {
      window.removeEventListener('keydown', keyDown);
      window.removeEventListener('keyup', keyUp);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', up);
    };
  }, [onViewportChange]);

  const handleWheel = (event: WheelEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement | null;
    if (target?.closest('[data-canvas-interactive]')) return;
    event.preventDefault();
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const current = viewportRef.current;
    const factor = Math.pow(1.1, -event.deltaY / 100);
    const k = Math.min(Math.max(current.k * factor, 0.2), 2.5);
    const mouseX = event.clientX - rect.left;
    const mouseY = event.clientY - rect.top;
    const worldX = (mouseX - current.x) / current.k;
    const worldY = (mouseY - current.y) / current.k;
    onViewportChange({ x: mouseX - worldX * k, y: mouseY - worldY * k, k });
  };

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement | null;
    if (target?.closest('[data-node-id], [data-canvas-interactive]')) return;
    const shouldPan = event.button === 1 || spacePressed || event.ctrlKey || event.metaKey;
    if (shouldPan) {
      event.preventDefault();
      panRef.current = { active: true, startX: event.clientX, startY: event.clientY, originX: viewportRef.current.x, originY: viewportRef.current.y };
      document.body.style.cursor = 'grabbing';
      return;
    }
    onBackgroundPointerDown();
  };

  return <div ref={containerRef} className="relative h-full w-full select-none overflow-hidden bg-[#111214]" onPointerDown={handlePointerDown} onWheel={handleWheel} onDragOver={(event) => event.preventDefault()} onDrop={(event) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    onDrop(event, { x: (event.clientX - rect.left - viewport.x) / viewport.k, y: (event.clientY - rect.top - viewport.y) / viewport.k });
  }}>
    <div className="pointer-events-none absolute inset-0 opacity-60" style={{ backgroundImage: 'radial-gradient(circle, #34373d 1px, transparent 1.2px)', backgroundSize: `${48 * viewport.k}px ${48 * viewport.k}px`, backgroundPosition: `${viewport.x % (48 * viewport.k)}px ${viewport.y % (48 * viewport.k)}px` }} />
    <div className="absolute origin-top-left" style={{ transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.k})` }}>{children}</div>
  </div>;
}

function portOffset(index: number, total: number): number {
  if (total <= 1) return NODE_HEADER_HEIGHT / 2;
  return 20 + (36 * index) / (total - 1);
}

function ConnectionPath({ edge, source, target, sourceCatalog, targetCatalog }: { edge: CanvasEdge; source?: CanvasNode; target?: CanvasNode; sourceCatalog?: VideoCanvasNodeCatalogItem; targetCatalog?: VideoCanvasNodeCatalogItem }) {
  if (!source || !target) return null;
  const sourceIndex = sourceCatalog?.outputs.findIndex((port) => port.key === edge.sourceHandle) ?? -1;
  const targetIndex = targetCatalog?.inputs.findIndex((port) => port.key === edge.targetHandle) ?? -1;
  const startX = source.position.x + NODE_WIDTH;
  const startY = source.position.y + portOffset(sourceIndex < 0 ? 0 : sourceIndex, sourceCatalog?.outputs.length || 1);
  const endX = target.position.x;
  const endY = target.position.y + portOffset(targetIndex < 0 ? 0 : targetIndex, targetCatalog?.inputs.length || 1);
  const curve = Math.max(Math.abs(endX - startX) * 0.5, 56);
  return <path d={`M ${startX} ${startY} C ${startX + curve} ${startY}, ${endX - curve} ${endY}, ${endX} ${endY}`} stroke="#78808e" strokeWidth="2" fill="none" />;
}

function VideoCanvasNode({ node, catalog, assets, stylePresets, selected, connectingHandle, onSelect, onDragStart, onConnectStart, onConnectTarget, onLabelChange, onConfigChange, onAssetChange, onStyleChange, onRunNode, onDelete }: {
  node: CanvasNode;
  catalog?: VideoCanvasNodeCatalogItem;
  assets: VideoAsset[];
  stylePresets: VideoStylePreset[];
  selected: boolean;
  connectingHandle: string | null;
  onSelect: () => void;
  onDragStart: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onConnectStart: (handleKey: string) => void;
  onConnectTarget: (handleKey: string) => void;
  onLabelChange: (value: string) => void;
  onConfigChange: (key: string, value: unknown) => void;
  onAssetChange: (assetId: number | null) => void;
  onStyleChange: (styleId: number | null) => void;
  onRunNode: () => void;
  onDelete: () => void;
}) {
  const nodeType = node.type;
  const Icon = CATEGORY_ICON[catalog?.category || '辅助'] || StickyNote;
  const config = node.data.config || {};
  const promptKey = nodeType === 'text' || nodeType === 'screenplay' || nodeType === 'note' ? 'content' : 'prompt';
  const prompt = String(config[nodeType === 'shot' ? 'video_prompt' : promptKey] || '');
  const editableFields = nodeType === 'shot'
    ? [
      { key: 'story_summary', label: '镜头摘要', rows: 3 },
      { key: 'dialogue', label: '对白或旁白', rows: 3 },
      { key: 'camera_plan', label: '镜头设计', rows: 3 },
      { key: 'motion_plan', label: '动作与运动', rows: 3 },
      { key: 'storyboard_prompt', label: '故事版提示词', rows: 4 },
      { key: 'video_prompt', label: '视频提示词', rows: 4 },
    ]
    : [{ key: promptKey, label: promptKey === 'content' ? '内容' : '提示词', rows: 5 }];
  const isAssetNode = nodeType === 'asset' || nodeType === 'video_asset';
  const allowAsset = isAssetNode || nodeType === 'storyboard' || nodeType === 'video_generation';
  const selectableAssets = nodeType === 'video_asset' ? assets.filter(isVideoAsset) : assets.filter(isImageAsset);
  const selectedAssetId = isAssetNode ? config.asset_id : (config.reference_asset_ids as number[] | undefined)?.[0];
  const supportsStyle = nodeType === 'style' || catalog?.inputs.some((input) => input.key === 'style');
  const stop = (event: ReactPointerEvent<HTMLElement>) => event.stopPropagation();

  return <div data-node-id={node.id} className="absolute" style={{ left: node.position.x, top: node.position.y, width: NODE_WIDTH }}>
    <div className={`overflow-hidden rounded-xl border bg-[#202226] shadow-[0_14px_35px_rgba(0,0,0,.32)] ${selected ? 'border-white/65 ring-2 ring-white/10' : 'border-white/15'}`}>
      <div className="flex h-[76px] cursor-grab items-center gap-3 border-b border-white/[.08] px-3 active:cursor-grabbing" onPointerDown={onDragStart} onClick={onSelect}>
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/[.07] text-white/75"><Icon className="h-4 w-4" /></span>
        <div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold text-white/90">{node.data.label || catalog?.label || '节点'}</p><p className="mt-1 text-[10px] text-white/40">{catalog?.category || '自定义节点'} · {catalog?.inputs.length || 0} 输入 / {catalog?.outputs.length || 0} 输出</p></div>
        <Move className="h-4 w-4 text-white/25" />
      </div>
      <div className="min-h-[72px] px-3 py-3" onClick={onSelect}><p className={`text-xs leading-5 ${prompt ? 'text-white/65' : 'text-white/30'}`}>{prompt || '选择该节点后，在节点下方配置输入、素材和生成参数。'}</p></div>
      {catalog?.inputs.map((port, index) => <button key={port.key} data-canvas-interactive type="button" aria-label={`连接到输入端口 ${port.key}`} title={`输入：${port.key}`} style={{ top: `${portOffset(index, catalog.inputs.length) - 8}px` }} onPointerDown={stop} onClick={(event) => { event.stopPropagation(); onConnectTarget(port.key); }} className="absolute -left-2 flex h-4 w-4 items-center justify-center rounded-full border-2 border-[#111214] bg-[#aeb6c5] text-[0]" />)}
      {catalog?.outputs.map((port, index) => <button key={port.key} data-canvas-interactive type="button" aria-label={`从输出端口 ${port.key} 连线`} title={connectingHandle === port.key ? `已选择输出：${port.key}` : `输出：${port.key}`} style={{ top: `${portOffset(index, catalog.outputs.length) - 8}px` }} onPointerDown={stop} onClick={(event) => { event.stopPropagation(); onConnectStart(port.key); }} className={`absolute -right-2 flex h-4 w-4 items-center justify-center rounded-full border-2 border-[#111214] ${connectingHandle === port.key ? 'bg-white' : 'bg-[#aeb6c5]'}`} />)}
    </div>
    {selected && <section data-canvas-interactive className="mt-3 rounded-xl border border-white/15 bg-[#292b2f] p-3 shadow-[0_14px_35px_rgba(0,0,0,.28)]" onPointerDown={stop}>
      <div className="mb-3 flex items-center justify-between"><span className="inline-flex items-center gap-1.5 text-xs font-semibold text-white/85"><Settings2 className="h-3.5 w-3.5" />节点配置</span><button type="button" title="删除节点" onClick={onDelete} className="rounded-md p-1.5 text-white/35 hover:bg-rose-400/10 hover:text-rose-200"><Trash2 className="h-3.5 w-3.5" /></button></div>
      <label className="block text-[10px] font-medium uppercase tracking-[.1em] text-white/40">名称<input value={String(node.data.label || '')} onChange={(event) => onLabelChange(event.target.value)} className="mt-1.5 w-full rounded-lg border border-white/10 bg-black/15 px-2.5 py-2 text-xs text-white outline-none focus:border-white/40" /></label>
      {editableFields.map((field) => <label key={field.key} className="mt-3 block text-[10px] font-medium uppercase tracking-[.1em] text-white/40">{field.label}<textarea rows={field.rows} value={String(config[field.key] || '')} onChange={(event) => onConfigChange(field.key, event.target.value)} className="mt-1.5 w-full resize-y rounded-lg border border-white/10 bg-black/15 p-2.5 text-xs leading-5 text-white outline-none focus:border-white/40" /></label>)}
      {allowAsset && <label className="mt-3 block text-[10px] font-medium uppercase tracking-[.1em] text-white/40">{isAssetNode ? '资产' : '参考资产'}<select value={String(selectedAssetId || '')} onChange={(event) => onAssetChange(event.target.value ? Number(event.target.value) : null)} className="mt-1.5 w-full rounded-lg border border-white/10 bg-[#202226] px-2.5 py-2 text-xs text-white outline-none"><option value="">不选择资产</option>{selectableAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}</select></label>}
      {supportsStyle && <label className="mt-3 block text-[10px] font-medium uppercase tracking-[.1em] text-white/40">风格预设<select value={String(config.style_preset_id || '')} onChange={(event) => onStyleChange(event.target.value ? Number(event.target.value) : null)} className="mt-1.5 w-full rounded-lg border border-white/10 bg-[#202226] px-2.5 py-2 text-xs text-white outline-none"><option value="">使用系统默认风格</option>{stylePresets.map((style) => <option key={style.id} value={style.id}>{style.name}</option>)}</select></label>}
      <button type="button" onClick={onRunNode} className="mt-3 inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-white px-3 py-2 text-xs font-semibold text-[#1b1d20] hover:bg-white/90"><Play className="h-3.5 w-3.5 fill-current" />运行此节点</button>
    </section>}
  </div>;
}

export default function VideoCanvasPanel({ storyId, chapterId, workflow, assets, stylePresets, onDirtyChange, onAssetsChanged }: Props) {
  const [catalog, setCatalog] = useState<VideoCanvasNodeCatalogItem[]>([]);
  const [models, setModels] = useState<AiModelItem[]>([]);
  const [canvas, setCanvas] = useState<VideoCanvas | null>(null);
  const [canvasList, setCanvasList] = useState<VideoCanvas[]>([]);
  const [nodes, setNodes] = useState<CanvasNode[]>([]);
  const [edges, setEdges] = useState<CanvasEdge[]>([]);
  const [viewport, setViewport] = useState<ViewportTransform>({ x: 260, y: 120, k: 1 });
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
  const [connectionStart, setConnectionStart] = useState<ConnectionStart | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploadingNodeAsset, setUploadingNodeAsset] = useState(false);
  const [uploadingNodeId, setUploadingNodeId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [latestRun, setLatestRun] = useState<VideoCanvasRun | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [agentOpen, setAgentOpen] = useState(false);
  const [assetSelectorNodeId, setAssetSelectorNodeId] = useState<string | null>(null);
  const [infoNodeId, setInfoNodeId] = useState<string | null>(null);
  const [syncPreview, setSyncPreview] = useState<{ nodeCount: number; edgeCount: number } | null>(null);
  const [catalogQuery, setCatalogQuery] = useState('');
  const [dirty, setDirty] = useState(false);
  const [canvasSize, setCanvasSize] = useState({ width: 0, height: 0 });
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const nodeUploadInputRef = useRef<HTMLInputElement | null>(null);
  const uploadTargetNodeRef = useRef<string | null>(null);
  const dragNodeRef = useRef<{ nodeId: string; startX: number; startY: number; originX: number; originY: number } | null>(null);
  const viewportRef = useRef(viewport);
  const initialCreateKeyRef = useRef(crypto.randomUUID());
  const loadRequestRef = useRef(0);
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  const historyRef = useRef<Array<{ nodes: CanvasNode[]; edges: CanvasEdge[]; viewport: ViewportTransform }>>([]);
  const redoRef = useRef<Array<{ nodes: CanvasNode[]; edges: CanvasEdge[]; viewport: ViewportTransform }>>([]);
  const gestureOriginRef = useRef<Record<string, { x: number; y: number }> | null>(null);
  const changeVersionRef = useRef(0);
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
    setCanvas(nextCanvas);
    const layoutNodes = nextCanvas.layout.nodes || {};
    const projectedGraph = projectLegacyGraph(nextCanvas.version.graph);
    setNodes(toCanvasNodes(projectedGraph).map((node) => ({ ...node, position: layoutNodes[node.id] || node.position })));
    setEdges(projectedGraph.edges as CanvasEdge[]);
    setLatestRun(nextCanvas.runs?.[0] || null);
    const savedViewport = nextCanvas.layout.viewport;
    setViewport({ x: savedViewport?.x ?? 260, y: savedViewport?.y ?? 120, k: savedViewport?.zoom ?? 1 });
    setSelectedNodeId(null);
    setSelectedNodeIds([]);
    setConnectionStart(null);
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
      setConnectionStart(null);
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
    const move = (event: PointerEvent) => {
      const drag = dragNodeRef.current;
      if (!drag) return;
      const scale = viewportRef.current.k;
      setNodes((current) => current.map((node) => node.id === drag.nodeId ? { ...node, position: { x: drag.originX + (event.clientX - drag.startX) / scale, y: drag.originY + (event.clientY - drag.startY) / scale } } : node));
    };
    const up = () => { if (dragNodeRef.current) setDirty(true); dragNodeRef.current = null; };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
    return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); window.removeEventListener('pointercancel', up); };
  }, []);
  useEffect(() => {
    if (!canvas || !latestRun || !['queued', 'running', 'cancel_requested'].includes(latestRun.status)) return undefined;
    const timer = window.setInterval(() => { void getVideoCanvasRun(canvas.id, latestRun.id).then((result) => setLatestRun(result.run)).catch(() => undefined); }, 3000);
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
  }, []);
  const undo = useCallback(() => {
    const previous = historyRef.current.pop();
    if (!previous) return;
    redoRef.current.push({ nodes: nodesRef.current, edges: edgesRef.current, viewport: viewportRef.current });
    setNodes(previous.nodes); setEdges(previous.edges); setViewport(previous.viewport); setDirty(true);
  }, []);
  const redo = useCallback(() => {
    const next = redoRef.current.pop();
    if (!next) return;
    historyRef.current.push({ nodes: nodesRef.current, edges: edgesRef.current, viewport: viewportRef.current });
    setNodes(next.nodes); setEdges(next.edges); setViewport(next.viewport); setDirty(true);
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
    if (!file.type.startsWith('image/')) {
      toast.error('仅支持上传图片文件');
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
        asset_type: 'image',
        name: file.name,
        file_path: '',
        provider: 'manual_upload',
      });
      const replaced = await replaceVideoAsset(created.id, file);
      const filePath = replaced.asset.file_path;
      const imageUrl = toPublicVideoAssetUrl(filePath) || '';
      const node = nodesRef.current.find((item) => item.id === nodeId);
      if (!node) return;
      const config = node.data.config || {};
      const nextConfig = node.type === 'asset' || node.type === 'video_asset'
        ? {
          ...config,
          asset_id: replaced.asset.id,
          asset_revision: replaced.asset.revision,
          asset_type: 'image',
          existing_url: imageUrl,
          preview_url: imageUrl,
        }
        : {
          ...config,
          reference_asset_ids: [replaced.asset.id],
          reference_asset_revisions: [{ asset_id: replaced.asset.id, revision: replaced.asset.revision }],
          existing_url: imageUrl,
          preview_url: imageUrl,
        };
      captureHistory();
      updateNode(nodeId, { config: nextConfig });
      setSelectedNodeIds([nodeId]);
      setSelectedNodeId(nodeId);
      onAssetsChanged?.();
      toast.success('图片已上传并绑定到当前节点');
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '图片上传失败，请重试'));
    } finally {
      uploadTargetNodeRef.current = null;
      setUploadingNodeAsset(false);
      setUploadingNodeId(null);
    }
  }, [captureHistory, chapterId, onAssetsChanged, storyId, updateNode]);
  const selectStyle = useCallback((nodeId: string, styleId: number | null) => {
    const style = stylePresets.find((item) => item.id === styleId);
    const node = nodes.find((item) => item.id === nodeId);
    if (!node) return;
    const config = node.data.config || {};
    updateNode(nodeId, { config: style ? { ...config, style_preset_id: style.id, style_snapshot: { name: style.name, prompt_template: style.prompt_template || '', image_style_params: style.image_style_params || {}, video_style_params: style.video_style_params || {}, image_url: style.image_url || null } } : { ...config, style_preset_id: null, style_snapshot: null } });
  }, [nodes, stylePresets, updateNode]);

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
    try {
      const synchronized = dirty ? await saveCanvas(false) : canvas;
      if (!synchronized) return;
      const validation = await validateVideoCanvas(synchronized.id);
      if (!validation.valid) throw new Error(validation.errors.map((item) => item.message).join('；'));
      const result = await runVideoCanvas(synchronized.id, { target_node_ids: targetNodeId ? [targetNodeId] : [], expected_definition_revision: synchronized.definition_revision, idempotency_key: crypto.randomUUID() });
      setLatestRun(result.run);
      toast.success(result.run.status === 'succeeded' ? '画布执行完成' : '画布已提交，等待节点确认');
    } catch (error) { toast.error(normalizeErrorMessage(error, '运行画布失败')); } finally { setRunning(false); }
  };
  const confirmRun = async () => { if (!canvas || !latestRun) return; try { const result = await confirmVideoCanvasRun(canvas.id, latestRun.id); setLatestRun(result.run); toast.success('生成计划已确认并进入队列'); } catch (error) { toast.error(normalizeErrorMessage(error, '确认生成计划失败')); } };
  const cancelRun = async () => { if (!canvas || !latestRun) return; try { const result = await cancelVideoCanvasRun(canvas.id, latestRun.id); setLatestRun(result.run); toast.success('已请求取消画布运行'); } catch (error) { toast.error(normalizeErrorMessage(error, '取消画布运行失败')); } };
  const previewWorkflowSync = async () => { if (!canvas || !workflow) return; try { const result = await importVideoCanvasListWorkflow(canvas.id, { source_workflow_id: workflow.id, mode: 'preview' }); setSyncPreview({ nodeCount: result.node_count || 0, edgeCount: result.edge_count || 0 }); } catch (error) { toast.error(normalizeErrorMessage(error, '读取分镜同步预览失败')); } };
  const importWorkflow = async () => { if (!canvas || !workflow || !(await canDiscardChanges())) return; try { const result = await importVideoCanvasListWorkflow(canvas.id, { source_workflow_id: workflow.id, mode: 'merge', expected_definition_revision: canvas.definition_revision, idempotency_key: crypto.randomUUID() }); if (!result.canvas) throw new Error('导入没有返回画布数据'); hydrateCanvas(result.canvas); changeVersionRef.current = 0; setDirty(false); setConnectionStart(null); setSyncPreview(null); toast.success(`已同步 ${result.result?.added_node_count || 0} 个节点`); } catch (error) { toast.error(normalizeErrorMessage(error, '同步分镜到画布失败')); } };
  const createBlankCanvas = async () => { if (!(await canDiscardChanges())) return; try { const result = await createVideoCanvas({ story_id: storyId, default_chapter_id: chapterId ?? null, name: chapterId ? '章节视频画布' : '视频创作画布' }); hydrateCanvas(result); window.localStorage.setItem(canvasSelectionKey, String(result.id)); setCanvasList((current) => [result, ...current.filter((item) => item.id !== result.id)]); setDirty(false); toast.success('空白画布已创建'); } catch (error) { toast.error(normalizeErrorMessage(error, '创建画布失败')); } };
  const selectCanvas = async (canvasId: number) => { if (canvas && canvas.id !== canvasId && !(await canDiscardChanges())) return; try { const selected = await getVideoCanvas(canvasId); hydrateCanvas(selected); window.localStorage.setItem(canvasSelectionKey, String(selected.id)); setDirty(false); setSelectedNodeId(null); setConnectionStart(null); } catch (error) { toast.error(normalizeErrorMessage(error, '打开视频画布失败')); } };
  const refreshCanvas = async () => { if (!canvas || !(await canDiscardChanges())) return; try { const refreshed = await getVideoCanvas(canvas.id); hydrateCanvas(refreshed); setCanvasList((await listVideoCanvases(storyId, chapterId)).canvases); setDirty(false); setSelectedNodeId(null); setConnectionStart(null); } catch (error) { toast.error(normalizeErrorMessage(error, '刷新视频画布失败')); } };

  const beginNodeDrag = (node: CanvasNode, event: ReactPointerEvent<HTMLDivElement>) => { event.preventDefault(); event.stopPropagation(); setSelectedNodeId(node.id); dragNodeRef.current = { nodeId: node.id, startX: event.clientX, startY: event.clientY, originX: node.position.x, originY: node.position.y }; };
  const beginConnection = (nodeId: string, handleKey: string) => { setConnectionStart((current) => current?.nodeId === nodeId && current.handleKey === handleKey ? null : { nodeId, handleKey }); };
  const createConnection = (sourceNodeId: string, sourceHandle: string, targetNodeId: string, targetHandle: string) => {
    if (sourceNodeId === targetNodeId) return;
    const source = nodes.find((node) => node.id === sourceNodeId);
    const target = nodes.find((node) => node.id === targetNodeId);
    const sourceCatalog = catalog.find((item) => item.type === source?.type);
    const targetCatalog = catalog.find((item) => item.type === target?.type);
    const sourcePort = sourceCatalog?.outputs.find((port) => port.key === sourceHandle);
    const targetPort = targetCatalog?.inputs.find((port) => port.key === targetHandle);
    if (!sourcePort || !targetPort || sourcePort.type !== targetPort.type) { toast.error('这两个端口类型不兼容'); return; }
    captureHistory();
    setEdges((current) => current.some((edge) => edge.source === sourceNodeId && edge.target === targetNodeId && edge.sourceHandle === sourcePort.key && edge.targetHandle === targetPort.key) ? current : [...current, { id: `edge-${crypto.randomUUID()}`, source: sourceNodeId, target: targetNodeId, sourceHandle: sourcePort.key, targetHandle: targetPort.key }]);
    setConnectionStart(null);
    markDirty();
    toast.success('连线已创建');
  };
  const finishConnection = (targetNodeId: string, targetHandle: string) => {
    if (!connectionStart || connectionStart.nodeId === targetNodeId) { setConnectionStart(null); return; }
    const source = nodes.find((node) => node.id === connectionStart.nodeId);
    const target = nodes.find((node) => node.id === targetNodeId);
    const sourceCatalog = catalog.find((item) => item.type === source?.type);
    const targetCatalog = catalog.find((item) => item.type === target?.type);
    const sourcePort = sourceCatalog?.outputs.find((port) => port.key === connectionStart.handleKey);
    const targetPort = targetCatalog?.inputs.find((port) => port.key === targetHandle);
    if (!sourcePort || !targetPort || sourcePort.type !== targetPort.type) { toast.error('这两个端口类型不兼容'); setConnectionStart(null); return; }
    captureHistory();
    setEdges((current) => current.some((edge) => edge.source === connectionStart.nodeId && edge.target === targetNodeId && edge.sourceHandle === sourcePort.key && edge.targetHandle === targetPort.key) ? current : [...current, { id: `edge-${crypto.randomUUID()}`, source: connectionStart.nodeId, target: targetNodeId, sourceHandle: sourcePort.key, targetHandle: targetPort.key }]);
    setConnectionStart(null);
    markDirty();
    toast.success('连线已创建');
  };

  useEffect(() => {
    const keyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.matches('input, textarea, select, [contenteditable="true"]')) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a') {
        event.preventDefault();
        setSelectedNodeIds(nodes.map((node) => node.id));
        setSelectedNodeId(nodes[0]?.id || null);
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault();
        if (event.shiftKey) redo(); else undo();
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'y') {
        event.preventDefault(); redo(); return;
      }
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
        const copy = { ...selectedNode, id: `${selectedNode.type}-${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`, position: { x: selectedNode.position.x + 42, y: selectedNode.position.y + 42 }, data: { ...selectedNode.data, config: { ...selectedNode.data.config } } };
        setNodes((current) => [...current, copy]);
        setSelectedNodeId(copy.id);
        setSelectedNodeIds([copy.id]);
        markDirty();
      }
      if ((event.key === 'Delete' || event.key === 'Backspace') && selectedNodeIds.length) {
        event.preventDefault();
        captureHistory();
        setNodes((current) => current.filter((node) => !selectedNodeIds.includes(node.id)));
        setEdges((current) => current.filter((edge) => !selectedNodeIds.includes(edge.source) && !selectedNodeIds.includes(edge.target)));
        setSelectedNodeId(null);
        setSelectedNodeIds([]);
        setConnectionStart(null);
        markDirty();
      }
    };
    window.addEventListener('keydown', keyDown);
    return () => window.removeEventListener('keydown', keyDown);
  }, [captureHistory, markDirty, nodes, redo, selectedNode, selectedNodeId, selectedNodeIds, undo, updateViewport, viewport.k]);

  if (loading) return <div className="flex h-full items-center justify-center bg-[#111214] text-sm text-white/55"><Loader2 className="mr-2 h-4 w-4 animate-spin" />正在打开创作画布</div>;
  if (!canvas) return <div className="flex h-full items-center justify-center bg-[#111214] p-6 text-white"><div className="w-full max-w-md rounded-xl border border-white/10 bg-[#202226] p-8 text-center"><Boxes className="mx-auto h-10 w-10 text-white/75" /><h2 className="mt-4 text-lg font-semibold">打开一个创作画布</h2><p className="mt-2 text-sm leading-6 text-white/45">从空白节点图开始，或将当前列表工作流导入为可编辑流程。</p><button type="button" onClick={() => void createBlankCanvas()} className="mt-6 inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-semibold text-[#15171a]"><Plus className="h-4 w-4" />新建空白画布</button></div></div>;

  const editorViewport: CanvasViewport = { x: viewport.x, y: viewport.y, scale: viewport.k };
  const inspectorNode = selectedNodeIds.length === 1 ? nodes.find((node) => node.id === selectedNodeIds[0]) || null : null;
  const canvasRect = canvasSize.width > 0 ? canvasSize : null;
  const inspectorSize = { width: inspectorNode?.data.ui?.width || 420, height: inspectorNode?.data.ui?.height || 236 };
  const inspectorScreen = inspectorNode ? { x: inspectorNode.position.x * viewport.k + viewport.x, y: inspectorNode.position.y * viewport.k + viewport.y } : null;
  const panelWidth = 700;
  const panelLeft = inspectorScreen && canvasRect ? Math.max(16, Math.min(Math.max(16, canvasRect.width - panelWidth - 16), inspectorScreen.x - 90)) : 16;
  const panelBelow = inspectorScreen ? inspectorScreen.y + inspectorSize.height * viewport.k + 16 : 16;
  const panelTop = Math.max(16, panelBelow);
  const removeNodes = (ids: string[]) => {
    if (!ids.length) return;
    captureHistory();
    setNodes((current) => current.filter((node) => !ids.includes(node.id)));
    setEdges((current) => current.filter((edge) => !ids.includes(edge.source) && !ids.includes(edge.target)));
    setSelectedNodeIds([]); setSelectedNodeId(null); setConnectionStart(null); markDirty();
  };
  const fitAll = () => {
    const rect = surfaceRef.current?.getBoundingClientRect();
    if (!rect || !nodes.length) { updateViewport({ x: rect ? rect.width / 2 : 260, y: rect ? rect.height / 2 : 120, k: 1 }); return; }
    const left = Math.min(...nodes.map((node) => node.position.x)); const top = Math.min(...nodes.map((node) => node.position.y));
    const right = Math.max(...nodes.map((node) => node.position.x + (node.data.ui?.width || 420))); const bottom = Math.max(...nodes.map((node) => node.position.y + (node.data.ui?.height || 236)));
    const k = Math.min(2, Math.max(.1, Math.min((rect.width - 160) / Math.max(1, right - left), (rect.height - 200) / Math.max(1, bottom - top))));
    updateViewport({ x: (rect.width - (right - left) * k) / 2 - left * k, y: (rect.height - (bottom - top) * k) / 2 - top * k, k });
  };
  const addNodeFromTool = (type: string) => { const item = catalog.find((entry) => entry.type === type); if (!item) { toast.info('当前画布仅支持文本、图片、视频节点'); return; } captureHistory(); addCatalogNode(item); };
  // 旧实现仅保留为迁移参考，确保其类型定义在当前模块中可独立复用。
  void InfiniteCanvasSurface;
  void ConnectionPath;
  void VideoCanvasNode;
  void beginNodeDrag;
  return <div className="relative h-full min-h-0 overflow-hidden bg-[#181818] text-white">
    <main ref={surfaceRef} className="relative h-full overflow-hidden" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); const type = event.dataTransfer.getData('application/x-storycanvas-node'); const item = catalog.find((entry) => entry.type === type); const rect = surfaceRef.current?.getBoundingClientRect(); if (item && rect) { captureHistory(); addCatalogNode(item, { x: (event.clientX - rect.left - viewport.x) / viewport.k, y: (event.clientY - rect.top - viewport.y) / viewport.k }); } }}>
      <CanvasEditorSurface containerRef={surfaceRef} nodes={nodes as CanvasSceneNode[]} edges={edges as CanvasSceneEdge[]} catalog={catalog} viewport={editorViewport} selectedNodeIds={selectedNodeIds} connectionStart={connectionStart ? { nodeId: connectionStart.nodeId, handle: connectionStart.handleKey } : null} uploadingNodeId={uploadingNodeId} onViewportChange={(next) => updateViewport({ x: next.x, y: next.y, k: next.scale })} onSelectionChange={(ids) => { setSelectedNodeIds(ids); setSelectedNodeId(ids.length === 1 ? ids[0] : null); if (!ids.length) setConnectionStart(null); }} onGestureStart={(ids) => { captureHistory(); gestureOriginRef.current = Object.fromEntries(ids.map((id) => [id, nodesRef.current.find((node) => node.id === id)?.position || { x: 0, y: 0 }])); }} onNodeMove={(ids, delta) => { const origin = gestureOriginRef.current || {}; setNodes((current) => current.map((node) => ids.includes(node.id) ? { ...node, position: { x: (origin[node.id] || node.position).x + delta.x, y: (origin[node.id] || node.position).y + delta.y } } : node)); markDirty(); }} onNodeResize={(id, size, position) => { setNodes((current) => current.map((node) => node.id === id ? { ...node, position: position || node.position, data: { ...node.data, ui: size } } : node)); markDirty(); }} onStartConnection={(nodeId, handle) => beginConnection(nodeId, handle)} onFinishConnection={(nodeId, handle) => finishConnection(nodeId, handle)} onCreateConnection={createConnection} onCancelConnection={() => setConnectionStart(null)} onOpenInfo={(nodeId) => setInfoNodeId(nodeId)} onDeleteNode={(nodeId) => removeNodes([nodeId])} onUploadNode={(nodeId) => { setSelectedNodeIds([nodeId]); setSelectedNodeId(nodeId); uploadTargetNodeRef.current = nodeId; nodeUploadInputRef.current?.click(); }} />
      <input ref={nodeUploadInputRef} type="file" accept="image/*" className="hidden" disabled={uploadingNodeAsset} onChange={(event) => void handleNodeFileUpload(event)} />
      {inspectorNode && <CanvasNodePropertyPanel node={inspectorNode as CanvasSceneNode} assets={assets} stylePresets={stylePresets} models={models} left={panelLeft} top={panelTop} onChange={(key, value) => { captureHistory(); updateNodeConfig(inspectorNode.id, key, value); }} onAssetChange={(assetId) => { captureHistory(); selectAsset(inspectorNode.id, assetId); }} onOpenAssetSelector={() => setAssetSelectorNodeId(inspectorNode.id)} onStyleChange={(styleId) => { captureHistory(); selectStyle(inspectorNode.id, styleId); }} onTemplateSave={() => toast.info('提示词模板已记录，可在模板管理中继续编辑')} onGenerate={() => void runCanvas(inspectorNode.id)} />}
      {assetSelectorNodeId && <AssetReferenceSelector availableAssets={assets} selectedIds={(() => { const node = nodes.find((item) => item.id === assetSelectorNodeId); const config = node?.data.config || {}; return node && (node.type === 'asset' || node.type === 'video_asset') ? (config.asset_id ? [Number(config.asset_id)] : []) : (Array.isArray(config.reference_asset_ids) ? config.reference_asset_ids.map(Number) : []); })()} onConfirm={(ids) => { captureHistory(); selectAssets(assetSelectorNodeId, ids); setAssetSelectorNodeId(null); }} onClose={() => setAssetSelectorNodeId(null)} />}
      {infoNodeId && (() => { const node = nodes.find((item) => item.id === infoNodeId); if (!node) return null; return <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/55 p-4" onClick={() => setInfoNodeId(null)}><div role="dialog" aria-modal="true" aria-label="节点信息" className="w-[min(520px,calc(100vw-32px))] rounded-2xl border border-[#49433f] bg-[#242220] p-5 text-[#e2ddd7] shadow-2xl" onClick={(event) => event.stopPropagation()}><div className="flex items-center justify-between"><div><h3 className="text-base font-semibold">{node.data.label || node.type}</h3><p className="mt-1 text-xs text-[#9e958d]">节点类型：{node.type}</p></div><button type="button" title="关闭节点信息" onClick={() => setInfoNodeId(null)} className="rounded-lg px-2 py-1 text-[#9e958d] hover:bg-white/10">关闭</button></div><pre className="mt-4 max-h-72 overflow-auto rounded-xl bg-[#1b1918] p-3 text-xs leading-5 text-[#b9b0a8]">{JSON.stringify(node.data.config || {}, null, 2)}</pre></div></div> })()}
      {sidebarOpen && <aside className="absolute bottom-20 left-3 top-3 z-20 flex w-56 flex-col overflow-hidden rounded-2xl border border-[#393633] bg-[#211f1d]/95 shadow-2xl backdrop-blur-xl"><div className="flex items-center justify-between border-b border-[#393633] px-4 py-3"><span className="text-sm font-semibold text-[#e8e2dc]">节点库</span><button type="button" title="收起节点库" onClick={() => setSidebarOpen(false)} className="p-1 text-[#938b84] hover:text-white"><ChevronLeft className="h-4 w-4" /></button></div><div className="border-b border-[#393633] p-3"><label className="flex items-center gap-2 rounded-lg bg-[#2a2725] px-2 py-2 text-[#938b84]"><Search className="h-3.5 w-3.5" /><input value={catalogQuery} onChange={(event) => setCatalogQuery(event.target.value)} placeholder="搜索节点" className="min-w-0 flex-1 bg-transparent text-xs text-white outline-none placeholder:text-[#817a74]" /></label></div><div className="min-h-0 flex-1 overflow-y-auto p-2">{Object.entries(catalogGroups).map(([category, items]) => <div key={category} className="mb-3"><p className="px-2 py-1 text-[10px] text-[#817a74]">{category}</p>{items.map((item) => <button key={item.type} type="button" draggable onDragStart={(event) => event.dataTransfer.setData('application/x-storycanvas-node', item.type)} onClick={() => { captureHistory(); addCatalogNode(item); }} className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-xs text-[#d9d2cb] hover:bg-[#34312e]"><Plus className="h-3.5 w-3.5 text-[#958d86]" />{item.label}</button>)}</div>)}</div></aside>}
      {!sidebarOpen && <button type="button" title="打开节点库" onClick={() => setSidebarOpen(true)} className="absolute left-3 top-3 z-20 rounded-xl border border-[#393633] bg-[#211f1d]/95 p-3 text-[#a49b94] shadow-xl hover:text-white"><PanelLeft className="h-4 w-4" /></button>}
      <div className="pointer-events-none absolute right-4 top-4 z-20 flex items-center gap-2"><div className="pointer-events-auto flex items-center gap-2 rounded-xl border border-[#393633] bg-[#211f1d]/95 px-3 py-2 shadow-xl"><span className={`h-2 w-2 rounded-full ${dirty ? 'bg-amber-400' : 'bg-emerald-400'}`} /><select value={canvas.id} onChange={(event) => void selectCanvas(Number(event.target.value))} className="max-w-[150px] bg-transparent text-xs text-[#ded7d0] outline-none"><option className="bg-[#211f1d]" value={canvas.id}>{canvas.name}</option>{canvasList.filter((item) => item.id !== canvas.id).map((item) => <option className="bg-[#211f1d]" key={item.id} value={item.id}>{item.name}</option>)}</select><button type="button" title="新建空白画布" onClick={() => void createBlankCanvas()} className="text-[#a49b94] hover:text-white"><Plus className="h-4 w-4" /></button><button type="button" title="同步分镜到画布" disabled={!workflow} onClick={() => void previewWorkflowSync()} className="inline-flex items-center gap-1 rounded-lg bg-white/10 px-2 py-1 text-xs text-[#ded7d0] hover:bg-white/15 hover:text-white disabled:opacity-30"><Upload className="h-3.5 w-3.5" />同步分镜</button><button type="button" title="保存画布" disabled={saving} onClick={() => void saveCanvas()} className="text-[#a49b94] hover:text-white disabled:opacity-30"><Save className="h-4 w-4" /></button><button type="button" title="画布 AI 助手" onClick={() => setAgentOpen((open) => !open)} className="text-[#a49b94] hover:text-white"><Bot className="h-4 w-4" /></button><button type="button" disabled={running} onClick={() => void runCanvas()} className="rounded-lg bg-[#eee9e4] px-3 py-1.5 text-xs font-semibold text-[#24211f] disabled:opacity-40">{running ? '提交中' : '运行全部'}</button></div></div>
      {syncPreview && <div className="absolute inset-0 z-40 flex items-center justify-center bg-black/55 p-4" onClick={() => setSyncPreview(null)}><section role="dialog" aria-modal="true" aria-label="同步分镜预览" onClick={(event) => event.stopPropagation()} className="w-full max-w-md rounded-xl border border-[#49433f] bg-[#242220] p-5 text-[#e4dfda] shadow-2xl"><h3 className="text-base font-semibold">同步分镜到画布</h3><p className="mt-2 text-sm leading-6 text-[#aaa19a]">将剧本与分镜详情同步为文本节点，角色、场景、道具和故事版同步为图片节点，视频结果同步为视频节点。手动创建的节点不会被覆盖。</p><div className="mt-4 flex gap-3"><div className="flex-1 rounded-lg bg-black/20 p-3"><p className="text-lg font-semibold">{syncPreview.nodeCount}</p><p className="text-xs text-[#938b84]">待同步节点</p></div><div className="flex-1 rounded-lg bg-black/20 p-3"><p className="text-lg font-semibold">{syncPreview.edgeCount}</p><p className="text-xs text-[#938b84]">关系连线</p></div></div><div className="mt-5 flex justify-end gap-2"><button type="button" onClick={() => setSyncPreview(null)} className="rounded-lg px-3 py-2 text-sm text-[#aaa19a] hover:bg-white/10">取消</button><button type="button" onClick={() => void importWorkflow()} className="rounded-lg bg-white px-3 py-2 text-sm font-semibold text-[#24211f]">确认同步</button></div></section></div>}
      {agentOpen && <aside className="absolute bottom-20 right-4 top-20 z-30 flex w-[380px] flex-col overflow-hidden rounded-2xl border border-[#393633] bg-[#211f1d]/[.98] shadow-2xl"><div className="flex items-center justify-between border-b border-[#393633] px-4 py-3"><span className="text-sm font-semibold">画布 AI 助手</span><button type="button" title="关闭助手" onClick={() => setAgentOpen(false)} className="text-[#958d86] hover:text-white"><X className="h-4 w-4" /></button></div><div className="min-h-0 flex-1 overflow-hidden"><Suspense fallback={<div className="p-4 text-sm text-[#948b84]">正在加载 AI 助手...</div>}><AgentPanel storyId={storyId} chapterId={chapterId} workflowType="video_canvas" workflowId={canvas.id} onContentUpdated={() => void refreshCanvas()} /></Suspense></div></aside>}
      <div className="absolute bottom-20 right-4 z-20 rounded-xl border border-[#393633] bg-[#211f1d]/95 px-3 py-2 text-[11px] text-[#a79f98]">{nodes.length} 节点 · {edges.length} 连线{connectionStart && ' · 选择兼容输入端口完成连接'}{latestRun && ` · ${latestRun.status}`}{latestRun?.status === 'awaiting_approval' && <button type="button" onClick={() => void confirmRun()} className="ml-2 rounded bg-[#eee9e4] px-2 py-1 text-[#25221f]">确认生成</button>}{latestRun && ['queued', 'running', 'cancel_requested'].includes(latestRun.status) && <button type="button" onClick={() => void cancelRun()} className="ml-2 rounded border border-[#5a534d] px-2 py-1 text-[#d7d0c9]">取消</button>}</div>
      <CanvasBottomToolbar scale={viewport.k} supportsAudio={false} onScaleChange={(k) => updateViewport({ ...viewport, k })} onReset={() => { const rect = surfaceRef.current?.getBoundingClientRect(); updateViewport({ x: rect ? rect.width / 2 : 260, y: rect ? rect.height / 2 : 120, k: 1 }); }} onFit={fitAll} onUndo={undo} onRedo={redo} onDelete={() => removeNodes(selectedNodeIds)} onTool={(tool) => { if (tool === 'text') addNodeFromTool('text'); else if (tool === 'image') addNodeFromTool('image'); else if (tool === 'video') addNodeFromTool('video'); else if (tool === 'settings') setAgentOpen(true); else if (tool === 'upload' || tool === 'more') setSidebarOpen(true); else if (tool === 'select') { setConnectionStart(null); toast.info('已切换到选择工具'); } else if (tool === 'help') toast.info('空格或中键平移，滚轮缩放，框选多个节点'); }} />
    </main>
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
