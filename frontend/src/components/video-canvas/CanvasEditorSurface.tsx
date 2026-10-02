import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type RefObject } from 'react';
import { Info, Loader2, Trash2, Upload } from 'lucide-react';
import { toPublicVideoAssetUrl, type VideoCanvasNodeCatalogItem } from '../../api';

export interface CanvasViewport { x: number; y: number; scale: number }
export interface CanvasSceneNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: { label?: string; config?: Record<string, unknown>; ui?: { width?: number; height?: number }; [key: string]: unknown };
}
export interface CanvasSceneEdge { id: string; source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null }

type CanvasPortHit = { nodeId: string; side: 'input' | 'output'; key: string; dataType: string };
type ConnectionDragState = { source: CanvasPortHit; pointer: { x: number; y: number }; target: CanvasPortHit | null; hasMoved: boolean };

interface Props {
  containerRef: RefObject<HTMLDivElement | null>;
  nodes: CanvasSceneNode[];
  edges: CanvasSceneEdge[];
  catalog: VideoCanvasNodeCatalogItem[];
  viewport: CanvasViewport;
  selectedNodeIds: string[];
  onViewportChange: (next: CanvasViewport) => void;
  onSelectionChange: (ids: string[]) => void;
  onNodeMove: (ids: string[], delta: { x: number; y: number }) => void;
  onNodeResize: (id: string, size: { width: number; height: number }, position?: { x: number; y: number }) => void;
  onStartConnection?: (nodeId: string, handle: string) => void;
  onFinishConnection?: (nodeId: string, handle: string) => void;
  onCreateConnection?: (sourceNodeId: string, sourceHandle: string, targetNodeId: string, targetHandle: string) => void;
  onCancelConnection?: () => void;
  connectionStart?: { nodeId: string; handle: string } | null;
  onOpenInfo?: (nodeId: string) => void;
  onDeleteNode?: (nodeId: string) => void;
  onUploadNode?: (nodeId: string) => void;
  uploadingNodeId?: string | null;
  onGestureStart?: (ids: string[]) => void;
}

export const MIN_SCALE = 0.1;
export const MAX_SCALE = 5;
const GRID_SIZE = 32;
const DEFAULT_NODE_SIZE = { width: 420, height: 236 };
const SMALL_NODE_SIZE = { width: 300, height: 174 };
const MEDIA_TYPES = new Set(['image', 'video', 'image_generation', 'storyboard', 'video_generation', 'video_asset', 'asset']);

export function nodeSize(node: CanvasSceneNode): { width: number; height: number } {
  const width = Number(node.data.ui?.width);
  const height = Number(node.data.ui?.height);
  if (width >= 180 && height >= 120) return { width, height };
  return MEDIA_TYPES.has(node.type) ? DEFAULT_NODE_SIZE : SMALL_NODE_SIZE;
}
export function worldPoint(event: PointerEvent | WheelEvent, rect: DOMRect, viewport: CanvasViewport) { return { x: (event.clientX - rect.left - viewport.x) / viewport.scale, y: (event.clientY - rect.top - viewport.y) / viewport.scale } }
export function screenPoint(point: { x: number; y: number }, viewport: CanvasViewport) { return { x: point.x * viewport.scale + viewport.x, y: point.y * viewport.scale + viewport.y } }
export function isInside(point: { x: number; y: number }, node: CanvasSceneNode) { const size = nodeSize(node); return point.x >= node.position.x && point.x <= node.position.x + size.width && point.y >= node.position.y && point.y <= node.position.y + size.height }

function roundedRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, radius: number) {
  const r = Math.min(radius, w / 2, h / 2); ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}
function portY(index: number, total: number, height: number) { return total <= 1 ? height / 2 : 26 + ((height - 52) * index) / (total - 1) }
function canConnectPorts(source: CanvasPortHit, target: CanvasPortHit | null): target is CanvasPortHit { return Boolean(target && source.side === 'output' && target.side === 'input' && source.nodeId !== target.nodeId && (source.dataType === target.dataType || source.dataType === 'any' || target.dataType === 'any')) }
function curveControls(from: { x: number; y: number }, to: { x: number; y: number }) { const curve = Math.max(48, Math.abs(to.x - from.x) * .45); return { control1: { x: from.x + curve, y: from.y }, control2: { x: to.x - curve, y: to.y } } }
function cubicPoint(t: number, from: { x: number; y: number }, control1: { x: number; y: number }, control2: { x: number; y: number }, to: { x: number; y: number }) { const inverse = 1 - t; return { x: inverse ** 3 * from.x + 3 * inverse ** 2 * t * control1.x + 3 * inverse * t ** 2 * control2.x + t ** 3 * to.x, y: inverse ** 3 * from.y + 3 * inverse ** 2 * t * control1.y + 3 * inverse * t ** 2 * control2.y + t ** 3 * to.y } }
function nodeIcon(type: string) { return type === 'video' || type === 'video_generation' || type === 'video_asset' ? '▣' : type === 'image' || type === 'image_generation' || type === 'storyboard' || type === 'asset' ? '▧' : type === 'text' || type === 'screenplay' || type === 'shot' ? 'T' : '◇' }
function nodeSummary(node: CanvasSceneNode) {
  const config = node.data.config || {};
  const content = config.video_prompt || config.storyboard_prompt || config.prompt || config.content || config.story_summary || '';
  return String(content).trim();
}

export default function CanvasEditorSurface(props: Props) {
  const { containerRef, nodes, edges, catalog, viewport, selectedNodeIds, onViewportChange, onSelectionChange, onNodeMove, onNodeResize, onStartConnection, onFinishConnection, onCreateConnection, onCancelConnection, connectionStart, onOpenInfo, onDeleteNode, onUploadNode, uploadingNodeId, onGestureStart } = props;
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const frameRef = useRef<number | null>(null);
  const sizeRef = useRef({ width: 0, height: 0 });
  const imageCacheRef = useRef(new Map<string, HTMLImageElement>());
  const interactionRef = useRef<{ kind: 'pan' | 'drag' | 'resize' | 'marquee' | 'connect'; startX: number; startY: number; endX?: number; endY?: number; originViewport?: CanvasViewport; nodeIds?: string[]; originPositions?: Record<string, { x: number; y: number }>; nodeId?: string; originSize?: { width: number; height: number }; originPosition?: { x: number; y: number }; resizeSide?: 'left' | 'right'; source?: CanvasPortHit; hasMoved?: boolean } | null>(null);
  const [spacePressed, setSpacePressed] = useState(false);
  const [marquee, setMarquee] = useState<{ startX: number; startY: number; endX: number; endY: number } | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [connectionDrag, setConnectionDrag] = useState<ConnectionDragState | null>(null);
  const [loadedImageUrls, setLoadedImageUrls] = useState<Set<string>>(() => new Set());
  const selectedSet = useMemo(() => new Set(selectedNodeIds), [selectedNodeIds]);
  const catalogMap = useMemo(() => new Map(catalog.map((item) => [item.type, item])), [catalog]);
  const drawRef = useRef<() => void>(() => undefined);
  const requestDraw = useCallback(() => { if (frameRef.current !== null) return; frameRef.current = requestAnimationFrame(() => { frameRef.current = null; drawRef.current() }) }, []);

  const draw = useCallback(() => {
    const canvas = canvasRef.current; const ctx = canvas?.getContext('2d'); if (!ctx) return;
    const { width, height } = sizeRef.current; const dpr = window.devicePixelRatio || 1; const flowTime = performance.now();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, width, height); ctx.fillStyle = '#181818'; ctx.fillRect(0, 0, width, height);
    const grid = Math.max(4, GRID_SIZE * viewport.scale); const ox = ((viewport.x % grid) + grid) % grid; const oy = ((viewport.y % grid) + grid) % grid;
    ctx.strokeStyle = '#333333'; ctx.lineWidth = 1; for (let x = ox; x < width; x += grid) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke() } for (let y = oy; y < height; y += grid) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke() }
    const visible = nodes.filter((node) => { const s = screenPoint(node.position, viewport); const size = nodeSize(node); return s.x + size.width * viewport.scale > -160 && s.y + size.height * viewport.scale > -160 && s.x < width + 160 && s.y < height + 160 });
    const byId = new Map(nodes.map((node) => [node.id, node]));
    edges.forEach((edge, edgeIndex) => {
      const source = byId.get(edge.source); const target = byId.get(edge.target); if (!source || !target) return;
      const sc = catalogMap.get(source.type); const tc = catalogMap.get(target.type); const ss = nodeSize(source); const ts = nodeSize(target);
      const si = Math.max(0, sc?.outputs.findIndex((p) => p.key === edge.sourceHandle) ?? 0); const ti = Math.max(0, tc?.inputs.findIndex((p) => p.key === edge.targetHandle) ?? 0);
      const from = screenPoint({ x: source.position.x + ss.width, y: source.position.y + portY(si, sc?.outputs.length || 1, ss.height) }, viewport); const to = screenPoint({ x: target.position.x, y: target.position.y + portY(ti, tc?.inputs.length || 1, ts.height) }, viewport);
      if (Math.max(from.x, to.x) < -80 || Math.min(from.x, to.x) > width + 80 || Math.max(from.y, to.y) < -80 || Math.min(from.y, to.y) > height + 80) return;
      const controls = curveControls(from, to);
      // 用可见的底线与流动高光表达节点之间的数据传递，深色画布中也能清晰分辨。
      ctx.save();
      ctx.strokeStyle = '#475569'; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(from.x, from.y); ctx.bezierCurveTo(controls.control1.x, controls.control1.y, controls.control2.x, controls.control2.y, to.x, to.y); ctx.stroke();
      ctx.strokeStyle = '#60a5fa'; ctx.lineWidth = 1.8; ctx.setLineDash([10, 12]); ctx.lineDashOffset = -((flowTime / 52) + edgeIndex * 7) % 22; ctx.beginPath(); ctx.moveTo(from.x, from.y); ctx.bezierCurveTo(controls.control1.x, controls.control1.y, controls.control2.x, controls.control2.y, to.x, to.y); ctx.stroke();
      ctx.setLineDash([]); ctx.restore();
      for (let particle = 0; particle < 2; particle += 1) { const progress = ((flowTime / 1800) + particle * .5 + edgeIndex * .13) % 1; const point = cubicPoint(progress, from, controls.control1, controls.control2, to); ctx.fillStyle = '#60a5fa'; ctx.shadowColor = '#60a5fa'; ctx.shadowBlur = 8; ctx.beginPath(); ctx.arc(point.x, point.y, 3.5, 0, Math.PI * 2); ctx.fill(); ctx.shadowBlur = 0; }
    });
    if (connectionDrag) {
      const sourceNode = byId.get(connectionDrag.source.nodeId);
      const sourceCatalog = sourceNode ? catalogMap.get(sourceNode.type) : undefined;
      const sourceSize = sourceNode ? nodeSize(sourceNode) : null;
      if (sourceNode && sourceCatalog && sourceSize) {
        const sourceIndex = Math.max(0, sourceCatalog.outputs.findIndex((port) => port.key === connectionDrag.source.key));
        const from = screenPoint({ x: sourceNode.position.x + sourceSize.width, y: sourceNode.position.y + portY(sourceIndex, sourceCatalog.outputs.length || 1, sourceSize.height) }, viewport);
        const targetNode = connectionDrag.target ? byId.get(connectionDrag.target.nodeId) : undefined;
        const targetCatalog = targetNode ? catalogMap.get(targetNode.type) : undefined;
        const targetSize = targetNode ? nodeSize(targetNode) : null;
        const targetIndex = targetNode && targetCatalog ? Math.max(0, targetCatalog.inputs.findIndex((port) => port.key === connectionDrag.target?.key)) : 0;
        const to = targetNode && targetCatalog && targetSize ? screenPoint({ x: targetNode.position.x, y: targetNode.position.y + portY(targetIndex, targetCatalog.inputs.length || 1, targetSize.height) }, viewport) : connectionDrag.pointer;
        const controls = curveControls(from, to);
        ctx.save(); ctx.strokeStyle = connectionDrag.target ? '#60a5fa' : '#9ca3af'; ctx.lineWidth = 2.5; ctx.setLineDash([8, 6]); ctx.lineDashOffset = -(flowTime / 80) % 14; ctx.beginPath(); ctx.moveTo(from.x, from.y); ctx.bezierCurveTo(controls.control1.x, controls.control1.y, controls.control2.x, controls.control2.y, to.x, to.y); ctx.stroke(); ctx.setLineDash([]); ctx.restore();
      }
    }
    visible.forEach((node) => {
      const size = nodeSize(node); const s = screenPoint(node.position, viewport); const w = size.width * viewport.scale; const h = size.height * viewport.scale; const selected = selectedSet.has(node.id); const connectionTarget = connectionDrag?.target?.nodeId === node.id;
      ctx.save(); roundedRect(ctx, s.x, s.y, w, h, Math.min(20, 20 * viewport.scale)); ctx.fillStyle = selected ? '#2a2726' : '#252321'; ctx.fill(); ctx.strokeStyle = selected ? '#3b82f6' : connectionTarget ? '#60a5fa' : '#45403d'; ctx.lineWidth = selected || connectionTarget ? 2.4 : 1.5; ctx.stroke();
      const imageUrl = toPublicVideoAssetUrl(String(node.data.config?.existing_url || node.data.config?.preview_url || '')) || '';
      if (/^(https?:|data:|blob:)/.test(imageUrl)) { let image = imageCacheRef.current.get(imageUrl); if (!image) { image = new Image(); image.onload = () => requestDraw(); image.src = imageUrl; imageCacheRef.current.set(imageUrl, image) } if (image.complete && image.naturalWidth) { ctx.globalAlpha = .88; ctx.drawImage(image, s.x, s.y, w, h); ctx.globalAlpha = 1 } }
      else { ctx.fillStyle = '#8b847e'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.font = `${Math.max(22, 34 * viewport.scale)}px system-ui`; ctx.fillText(nodeIcon(node.type), s.x + w / 2, s.y + h / 2 - 12 * viewport.scale); ctx.fillStyle = '#aaa19a'; ctx.font = `${Math.max(12, 15 * viewport.scale)}px system-ui`; ctx.fillText(String(node.data.label || catalogMap.get(node.type)?.label || '画布节点'), s.x + w / 2, s.y + h / 2 + 28 * viewport.scale) }
      if (selected || hoveredNodeId === node.id || connectionStart || connectionDrag) { const item = catalogMap.get(node.type); item?.inputs.forEach((port, i) => { const inputHit = { nodeId: node.id, side: 'input' as const, key: port.key, dataType: port.type }; ctx.fillStyle = connectionDrag?.source && canConnectPorts(connectionDrag.source, inputHit) ? '#60a5fa' : connectionDrag?.source ? '#6b7280' : connectionStart ? '#60a5fa' : '#bab5b1'; ctx.beginPath(); ctx.arc(s.x, s.y + portY(i, item.inputs.length, size.height) * viewport.scale, 5, 0, Math.PI * 2); ctx.fill() }); if (selected || hoveredNodeId === node.id || connectionStart?.nodeId === node.id || connectionDrag?.source.nodeId === node.id) item?.outputs.forEach((port, i) => { ctx.fillStyle = connectionStart?.nodeId === node.id && connectionStart.handle === port.key || connectionDrag?.source.nodeId === node.id && connectionDrag.source.key === port.key ? '#fff' : '#bab5b1'; ctx.beginPath(); ctx.arc(s.x + w, s.y + portY(i, item.outputs.length, size.height) * viewport.scale, 5, 0, Math.PI * 2); ctx.fill() }) }
      if (selected) { ctx.fillStyle = '#3b82f6'; ctx.fillRect(s.x - 5, s.y + h / 2 - 5, 10, 10); ctx.fillRect(s.x + w - 5, s.y + h / 2 - 5, 10, 10) }
      ctx.restore();
    });
    if (marquee) { const left = Math.min(marquee.startX, marquee.endX); const top = Math.min(marquee.startY, marquee.endY); const w = Math.abs(marquee.endX - marquee.startX); const h = Math.abs(marquee.endY - marquee.startY); ctx.fillStyle = 'rgba(59,130,246,.14)'; ctx.fillRect(left, top, w, h); ctx.strokeStyle = '#3b82f6'; ctx.setLineDash([5, 4]); ctx.strokeRect(left, top, w, h); ctx.setLineDash([]) }
  }, [catalogMap, connectionDrag, connectionStart, edges, hoveredNodeId, marquee, nodes, requestDraw, selectedSet, viewport]);
  useEffect(() => { drawRef.current = draw }, [draw]);
  useEffect(() => { requestDraw() }, [requestDraw]);
  useEffect(() => {
    if (!edges.length && !connectionDrag) return;
    let animationFrame = 0;
    const tick = () => { requestDraw(); animationFrame = window.requestAnimationFrame(tick); };
    animationFrame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(animationFrame);
  }, [connectionDrag, edges.length, requestDraw]);
  useEffect(() => { const container = containerRef.current; if (!container) return; let timer: number | undefined; const resize = () => { window.clearTimeout(timer); timer = window.setTimeout(() => { const rect = container.getBoundingClientRect(); sizeRef.current = { width: rect.width, height: rect.height }; const canvas = canvasRef.current; if (canvas) { const dpr = window.devicePixelRatio || 1; canvas.width = Math.max(1, Math.floor(rect.width * dpr)); canvas.height = Math.max(1, Math.floor(rect.height * dpr)); canvas.style.width = `${rect.width}px`; canvas.style.height = `${rect.height}px` } requestDraw() }, 80) }; resize(); const observer = new ResizeObserver(resize); observer.observe(container); return () => { window.clearTimeout(timer); observer.disconnect() } }, [containerRef, requestDraw]);
  useEffect(() => () => { if (frameRef.current !== null) cancelAnimationFrame(frameRef.current); imageCacheRef.current.clear() }, []);
  useEffect(() => { const down = (event: KeyboardEvent) => { const target = event.target as HTMLElement | null; if (event.code === 'Space' && !target?.matches('input, textarea, select, [contenteditable="true"]')) { event.preventDefault(); setSpacePressed(true) } }; const up = (event: KeyboardEvent) => { if (event.code === 'Space') setSpacePressed(false) }; window.addEventListener('keydown', down); window.addEventListener('keyup', up); return () => { window.removeEventListener('keydown', down); window.removeEventListener('keyup', up) } }, []);
  const rect = () => containerRef.current?.getBoundingClientRect() || null;
  const hitNode = (point: { x: number; y: number }) => [...nodes].reverse().find((node) => isInside(point, node));
  const hitPort = (screenX: number, screenY: number) => {
    const hitRadius = 18;
    for (const node of [...nodes].reverse()) {
      const item = catalogMap.get(node.type);
      if (!item) continue;
      const size = nodeSize(node);
      const screen = screenPoint(node.position, viewport);
      for (let index = 0; index < item.outputs.length; index += 1) {
        const portYPosition = screen.y + portY(index, item.outputs.length, size.height) * viewport.scale;
        if (Math.hypot(screenX - (screen.x + size.width * viewport.scale), screenY - portYPosition) <= hitRadius) return { nodeId: node.id, side: 'output' as const, key: item.outputs[index].key, dataType: item.outputs[index].type };
      }
      for (let index = 0; index < item.inputs.length; index += 1) {
        const portYPosition = screen.y + portY(index, item.inputs.length, size.height) * viewport.scale;
        if (Math.hypot(screenX - screen.x, screenY - portYPosition) <= hitRadius) return { nodeId: node.id, side: 'input' as const, key: item.inputs[index].key, dataType: item.inputs[index].type };
      }
    }
    return null;
  };
  const pointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    const bounds = rect();
    if (!bounds) return;
    const screenX = event.clientX - bounds.left;
    const screenY = event.clientY - bounds.top;
    if (event.button === 0) {
      const port = hitPort(screenX, screenY);
      if (port) {
        event.preventDefault();
        if (port.side === 'output') {
          onStartConnection?.(port.nodeId, port.key);
          interactionRef.current = { kind: 'connect', startX: event.clientX, startY: event.clientY, source: port, hasMoved: false };
          setConnectionDrag({ source: port, pointer: { x: screenX, y: screenY }, target: null, hasMoved: false });
          event.currentTarget.setPointerCapture(event.pointerId);
        } else onFinishConnection?.(port.nodeId, port.key);
        return;
      }
    }
    const point = worldPoint(event.nativeEvent, bounds, viewport);
    const node = hitNode(point);
    if (node) {
      const size = nodeSize(node);
      const screen = screenPoint(node.position, viewport);
      const resizeSide = selectedSet.has(node.id) && Math.abs(screenY - (screen.y + size.height * viewport.scale / 2)) < 18 && (Math.abs(screenX - screen.x) < 16 || Math.abs(screenX - (screen.x + size.width * viewport.scale)) < 16) ? (Math.abs(screenX - screen.x) < 16 ? 'left' : 'right') : undefined;
      const ids = event.ctrlKey || event.metaKey ? (selectedSet.has(node.id) ? selectedNodeIds.filter((id) => id !== node.id) : [...selectedNodeIds, node.id]) : [node.id];
      onSelectionChange(ids);
      onGestureStart?.(ids);
      if (resizeSide) interactionRef.current = { kind: 'resize', startX: event.clientX, startY: event.clientY, nodeId: node.id, originSize: size, originPosition: node.position, resizeSide };
      else interactionRef.current = { kind: 'drag', startX: event.clientX, startY: event.clientY, nodeIds: ids, originPositions: Object.fromEntries(ids.map((id) => { const current = nodes.find((entry) => entry.id === id)!; return [id, current.position] })) };
      event.currentTarget.setPointerCapture(event.pointerId);
      return;
    }
    if (event.button === 1 || spacePressed || event.ctrlKey || event.metaKey) {
      interactionRef.current = { kind: 'pan', startX: event.clientX, startY: event.clientY, originViewport: viewport };
      event.currentTarget.setPointerCapture(event.pointerId);
      return;
    }
    onSelectionChange([]);
    interactionRef.current = { kind: 'marquee', startX: screenX, startY: screenY, endX: screenX, endY: screenY };
    setMarquee({ startX: screenX, startY: screenY, endX: screenX, endY: screenY });
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const pointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const bounds = rect();
    if (!bounds) return;
    const screenX = event.clientX - bounds.left;
    const screenY = event.clientY - bounds.top;
    const interaction = interactionRef.current;
    if (!interaction) { setHoveredNodeId(hitNode(worldPoint(event.nativeEvent, bounds, viewport))?.id || null); return; }
    if (interaction.kind === 'connect' && interaction.source) {
      const moved = interaction.hasMoved || Math.hypot(event.clientX - interaction.startX, event.clientY - interaction.startY) > 3;
      interactionRef.current = { ...interaction, hasMoved: moved };
      const candidate = hitPort(screenX, screenY);
      const target = candidate && canConnectPorts(interaction.source, candidate) ? candidate : null;
      setConnectionDrag({ source: interaction.source, pointer: { x: screenX, y: screenY }, target, hasMoved: moved });
      return;
    }
    if (interaction.kind === 'pan' && interaction.originViewport) onViewportChange({ ...viewport, x: interaction.originViewport.x + event.clientX - interaction.startX, y: interaction.originViewport.y + event.clientY - interaction.startY });
    if (interaction.kind === 'drag' && interaction.nodeIds) onNodeMove(interaction.nodeIds, { x: (event.clientX - interaction.startX) / viewport.scale, y: (event.clientY - interaction.startY) / viewport.scale });
    if (interaction.kind === 'resize' && interaction.nodeId && interaction.originSize && interaction.originPosition) { const delta = (event.clientX - interaction.startX) / viewport.scale; const min = 220; const width = Math.max(min, interaction.originSize.width + (interaction.resizeSide === 'left' ? -delta : delta)); const x = interaction.resizeSide === 'left' ? interaction.originPosition.x + (interaction.originSize.width - width) : interaction.originPosition.x; onNodeResize(interaction.nodeId, { width, height: Math.max(140, width * .5625) }, { x, y: interaction.originPosition.y }); }
    if (interaction.kind === 'marquee') { const next = { ...interaction, endX: screenX, endY: screenY }; interactionRef.current = next; setMarquee({ startX: next.startX, startY: next.startY, endX: next.endX || next.startX, endY: next.endY || next.startY }); }
  };
  const pointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    const interaction = interactionRef.current;
    if (interaction?.kind === 'connect' && interaction.source) {
      const bounds = rect();
      const candidate = bounds ? hitPort(event.clientX - bounds.left, event.clientY - bounds.top) : null;
      const target = candidate && canConnectPorts(interaction.source, candidate) ? candidate : null;
      if (target) onCreateConnection?.(interaction.source.nodeId, interaction.source.key, target.nodeId, target.key);
      else if (interaction.hasMoved) onCancelConnection?.();
      setConnectionDrag(null);
      interactionRef.current = null;
      return;
    }
    if (interaction?.kind === 'marquee' && marquee) { const left = Math.min(marquee.startX, marquee.endX); const right = Math.max(marquee.startX, marquee.endX); const top = Math.min(marquee.startY, marquee.endY); const bottom = Math.max(marquee.startY, marquee.endY); onSelectionChange(nodes.filter((node) => { const s = screenPoint(node.position, viewport); const size = nodeSize(node); return s.x < right && s.x + size.width * viewport.scale > left && s.y < bottom && s.y + size.height * viewport.scale > top }).map((node) => node.id)); setMarquee(null); }
    interactionRef.current = null;
  };
  const doubleClick = (event: ReactPointerEvent<HTMLDivElement>) => { const bounds = rect(); if (bounds && !hitNode(worldPoint(event.nativeEvent, bounds, viewport))) onSelectionChange([]) };
  const selectedNode = selectedNodeIds.length === 1 ? nodes.find((node) => node.id === selectedNodeIds[0]) : undefined; const selectedScreen = selectedNode ? screenPoint(selectedNode.position, viewport) : null; const selectedSize = selectedNode ? nodeSize(selectedNode) : null;
  const zoom = (event: React.WheelEvent<HTMLDivElement>) => { const bounds = rect(); if (!bounds) return; event.preventDefault(); const factor = Math.pow(1.1, -event.deltaY / 100); const nextScale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, viewport.scale * factor)); const mouseX = event.clientX - bounds.left; const mouseY = event.clientY - bounds.top; const wx = (mouseX - viewport.x) / viewport.scale; const wy = (mouseY - viewport.y) / viewport.scale; onViewportChange({ x: mouseX - wx * nextScale, y: mouseY - wy * nextScale, scale: nextScale }) };
  return <div role="application" tabIndex={0} aria-label="无限画布" className={`relative h-full w-full overflow-hidden bg-[#181818] outline-none ${spacePressed ? 'cursor-grab' : 'cursor-default'}`} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={pointerUp} onDoubleClick={doubleClick} onWheel={zoom}>
    <canvas ref={canvasRef} className="absolute inset-0" aria-label="画布渲染层" />
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 z-[1] overflow-hidden">
      {nodes.map((node) => {
        const size = nodeSize(node);
        const position = screenPoint(node.position, viewport);
        const width = size.width * viewport.scale;
        const height = size.height * viewport.scale;
        const summary = nodeSummary(node);
        const imageUrl = toPublicVideoAssetUrl(String(node.data.config?.existing_url || node.data.config?.preview_url || '')) || '';
        const selected = selectedSet.has(node.id);
        const uploading = uploadingNodeId === node.id;
        const connectionTarget = connectionDrag?.target?.nodeId === node.id;
        const incomingCount = edges.filter((edge) => edge.target === node.id).length;
        const imageLoaded = Boolean(imageUrl && loadedImageUrls.has(imageUrl));
        return <article key={node.id} className={`absolute overflow-hidden rounded-[inherit] text-[#e4dfda] ${connectionTarget ? 'ring-2 ring-blue-400/90 shadow-[0_0_22px_rgba(96,165,250,.35)]' : ''}`} style={{ left: position.x + 1, top: position.y + 1, width: Math.max(1, width - 2), height: Math.max(1, height - 2) }}>
          <header className="flex items-center gap-2 border-b border-white/10 bg-[#292624] px-3 py-2" style={{ minHeight: Math.min(42, Math.max(26, height * .22)) }}>
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-white/10 text-xs text-[#ded8d2]">{nodeIcon(node.type)}</span>
            <div className="min-w-0 flex-1"><p className="truncate text-xs font-semibold">{String(node.data.label || catalogMap.get(node.type)?.label || '画布节点')}</p><p className="mt-0.5 truncate text-[10px] text-[#a69e96]">{catalogMap.get(node.type)?.category || node.type}</p></div>
            {connectionTarget ? <span className="rounded-full bg-blue-400/20 px-1.5 py-0.5 text-[9px] text-blue-200">接收信息</span> : selected ? <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[#60a5fa]" /> : null}
          </header>
          <div className="relative flex h-[calc(100%-44px)] flex-col justify-between bg-[#201e1c] px-3 py-2">
            {imageUrl && !imageLoaded && <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-[#252321] text-[11px] text-[#aaa19a]"><Loader2 className="h-5 w-5 animate-spin text-[#8d857d]" /><span>图片加载中</span></div>}
            {imageUrl ? <img src={imageUrl} alt="" className={`absolute inset-0 h-full w-full object-cover transition-opacity duration-200 ${imageLoaded ? 'opacity-90' : 'opacity-0'}`} onLoad={(event) => { const image = event.currentTarget; const finish = () => setLoadedImageUrls((current) => current.has(imageUrl) ? current : new Set(current).add(imageUrl)); if (typeof image.decode === 'function') void image.decode().catch(() => undefined).finally(finish); else finish(); }} onError={() => setLoadedImageUrls((current) => current.has(imageUrl) ? current : new Set(current).add(imageUrl))} /> : null}
            {uploading && <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 bg-[#201e1c]/90 text-xs text-white/80 backdrop-blur-[2px]"><Loader2 className="h-6 w-6 animate-spin text-blue-300" /><span>图片上传中</span></div>}
            {imageUrl || summary ? <p className={`relative line-clamp-3 text-[11px] leading-5 ${summary ? 'text-[#c8c0ba]' : 'text-[#8f8780]'}`}>{summary || ''}</p> : <div className="relative flex flex-1 flex-col items-center justify-center gap-2 text-[#8f8780]"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#3a3632] text-xl">{nodeIcon(node.type)}</span><span className="text-[11px]">{node.type === 'video' || node.type === 'video_generation' ? '空视频节点' : node.type === 'image' || node.type === 'image_generation' || node.type === 'storyboard' ? '空图片节点' : '待配置节点'}</span></div>}
            <div className="mt-2 flex items-center justify-between text-[10px] text-[#938b84]"><span>{incomingCount ? `已接收 ${incomingCount} 路信息` : `${catalogMap.get(node.type)?.inputs.length || 0} 输入`}</span><span>{catalogMap.get(node.type)?.outputs.length || 0} 输出</span></div>
          </div>
        </article>;
      })}
    </div>
    {selectedNode && selectedScreen && selectedSize && <div onPointerDown={(event) => event.stopPropagation()} className="pointer-events-auto absolute z-20 flex h-11 -translate-x-1/2 items-center gap-4 rounded-xl bg-white px-4 text-xs text-[#3f3a37] shadow-[0_12px_30px_rgba(0,0,0,.28)]" style={{ left: selectedScreen.x + selectedSize.width * viewport.scale / 2, top: Math.max(8, selectedScreen.y - 56) }}><button type="button" title="查看节点信息" onClick={() => onOpenInfo?.(selectedNode.id)} className="inline-flex items-center gap-1 hover:text-black"><Info className="h-4 w-4" />信息</button><button type="button" title="删除节点" onClick={() => onDeleteNode?.(selectedNode.id)} className="inline-flex items-center gap-1 hover:text-rose-600"><Trash2 className="h-4 w-4" />删除</button><button type="button" disabled={uploadingNodeId === selectedNode.id} title={uploadingNodeId === selectedNode.id ? '图片上传中' : '从本地文件上传图片'} onClick={() => onUploadNode?.(selectedNode.id)} className="inline-flex items-center gap-1 hover:text-black disabled:cursor-wait disabled:opacity-60">{uploadingNodeId === selectedNode.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}{uploadingNodeId === selectedNode.id ? '上传中' : '上传图片'}</button></div>}
    {marquee && <div className="pointer-events-none absolute z-10 border border-blue-400 bg-blue-500/10" style={{ left: Math.min(marquee.startX, marquee.endX), top: Math.min(marquee.startY, marquee.endY), width: Math.abs(marquee.endX - marquee.startX), height: Math.abs(marquee.endY - marquee.startY) }} />}
  </div>;
}
