import { useCallback, useEffect, useRef, useState, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent, type RefObject } from 'react';
import type { VideoCanvasNodeCatalogItem } from '../../api';

/**
 * 画布交互状态机 hook。
 *
 * 移植自 MIT 参考项目 infinite-canvas（basketikun/infinite-canvas）的交互模型：
 * - 滚轮围绕鼠标位置缩放（0.05x - 5x）
 * - 空格 / Ctrl / 中键临时平移（rAF 节流）
 * - 背景按下启动框选（Shift 追加选择）
 * - 节点按下启动拖拽（全局 mousemove + rAF 节流，多选整体移动）
 * - 端口按下启动连线（3 级吸附：端口命中 > 节点内部 > 节点扩展）
 * - 双击背景触发创建菜单、右键背景/连线触发上下文菜单
 * - 快捷键：Ctrl/Cmd+Z 撤销、Ctrl/Cmd+Shift+Z 或 Ctrl/Cmd+Y 重做、Ctrl/Cmd+A 全选、Delete/Backspace 删除、Escape 清空
 *
 * 适配 StoryCanvas 数据协议：多端口节点（sourceHandle / targetHandle）、
 * 节点尺寸由 nodeSize() 计算、端口纵向位置由 portY() 计算。
 */

// ===== 共享类型 =====

export interface CanvasViewport {
  x: number;
  y: number;
  scale: number;
}

export interface CanvasSceneNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: {
    label?: string;
    config?: Record<string, unknown>;
    ui?: { width?: number; height?: number };
    [key: string]: unknown;
  };
}

export interface CanvasSceneEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
}

export type Position = { x: number; y: number };

/** 连线进行中的端口句柄（handleKey 对应 catalog 端口 key） */
export type ConnectionHandle = { nodeId: string; handleType: 'source' | 'target'; handleKey: string };

/** 框选矩形（世界坐标），additive 表示 Shift 追加选择 */
export type SelectionBox = {
  startWorldX: number;
  startWorldY: number;
  currentWorldX: number;
  currentWorldY: number;
  additive: boolean;
  initialSelectedNodeIds: string[];
};

/** 右键菜单状态：节点菜单 / 连线菜单 */
export type ContextMenuState =
  | { type: 'node'; x: number; y: number; nodeId: string }
  | { type: 'connection'; x: number; y: number; connectionId: string }
  | null;

export type CanvasTool = 'select' | 'pan';

/** 工具栏动作：复制 / 删除节点 / 删除连线 / 查看信息 / 上传图片 */
export type CanvasToolbarAction = 'duplicate' | 'delete' | 'delete-connection' | 'info' | 'upload';

// ===== 常量 =====

export const MIN_SCALE = 0.05;
export const MAX_SCALE = 5;
/** 连线拖拽时端口命中半径（世界坐标，除以 scale 后使用） */
export const CONNECTION_HANDLE_HIT_RADIUS = 40;
/** 连线拖拽时节点扩展命中内边距（世界坐标，除以 scale 后使用） */
export const CONNECTION_NODE_HIT_PADDING = 32;
/** 背景网格间距（世界坐标） */
export const GRID_SIZE = 48;

const DEFAULT_NODE_SIZE = { width: 420, height: 236 };
const SMALL_NODE_SIZE = { width: 300, height: 174 };
const MEDIA_TYPES = new Set(['image', 'video', 'image_generation', 'storyboard', 'video_generation', 'video_asset', 'asset']);

// ===== 辅助函数 =====

/** 计算节点渲染尺寸：优先取 ui.width/ui.height，否则按类型回退默认值 */
export function nodeSize(node: CanvasSceneNode): { width: number; height: number } {
  const width = Number(node.data.ui?.width);
  const height = Number(node.data.ui?.height);
  if (width >= 180 && height >= 120) return { width, height };
  return MEDIA_TYPES.has(node.type) ? DEFAULT_NODE_SIZE : SMALL_NODE_SIZE;
}

/** 屏幕坐标（相对容器）转画布世界坐标 */
export function screenToCanvas(clientX: number, clientY: number, rect: DOMRect | null, viewport: CanvasViewport): Position {
  const localX = clientX - (rect?.left || 0);
  const localY = clientY - (rect?.top || 0);
  return { x: (localX - viewport.x) / viewport.scale, y: (localY - viewport.y) / viewport.scale };
}

/** 画布世界坐标转屏幕坐标（相对容器） */
export function screenPoint(point: Position, viewport: CanvasViewport): Position {
  return { x: point.x * viewport.scale + viewport.x, y: point.y * viewport.scale + viewport.y };
}

/** 端口纵向位置（相对节点顶部，世界坐标）：单端口居中，多端口均分 */
export function portY(index: number, total: number, height: number): number {
  return total <= 1 ? height / 2 : 26 + ((height - 52) * index) / (total - 1);
}

/** 点是否落在节点矩形内 */
export function isInside(point: Position, node: CanvasSceneNode): boolean {
  const size = nodeSize(node);
  return point.x >= node.position.x && point.x <= node.position.x + size.width && point.y >= node.position.y && point.y <= node.position.y + size.height;
}

/** 端口是否可连接：输出 → 输入，类型一致或任一端口接收任意类型 */
export function canConnectPorts(source: { side: 'input' | 'output'; dataType: string }, target: { side: 'input' | 'output'; dataType: string } | null): boolean {
  return Boolean(target && source.side === 'output' && target.side === 'input' && (source.dataType === target.dataType || source.dataType === 'any' || target.dataType === 'any'));
}

/**
 * 按 output→input 方向校验一条待创建连线的端口类型，与后端 _validate_graph 规则对齐。
 * 同节点、未知节点/目录/端口一律拒绝；端口类型经 catalog 解析后交给 canConnectPorts。
 */
export function canCreateConnection(
  nodes: CanvasSceneNode[],
  catalog: VideoCanvasNodeCatalogItem[],
  sourceNodeId: string,
  sourceHandleKey: string,
  targetNodeId: string,
  targetHandleKey: string,
): boolean {
  if (sourceNodeId === targetNodeId) return false;
  const sourceNode = nodes.find((node) => node.id === sourceNodeId);
  const targetNode = nodes.find((node) => node.id === targetNodeId);
  if (!sourceNode || !targetNode) return false;
  const sourceSpec = catalog.find((item) => item.type === sourceNode.type);
  const targetSpec = catalog.find((item) => item.type === targetNode.type);
  if (!sourceSpec || !targetSpec) return false;
  const sourcePort = sourceSpec.outputs.find((port) => port.key === sourceHandleKey);
  const targetPort = targetSpec.inputs.find((port) => port.key === targetHandleKey);
  if (!sourcePort || !targetPort) return false;
  return canConnectPorts({ side: 'output', dataType: sourcePort.type }, { side: 'input', dataType: targetPort.type });
}

/** 规范化连线方向：返回 { fromNodeId, toNodeId }，同节点返回 null */
export function normalizeConnection(firstNodeId: string, secondNodeId: string): { fromNodeId: string; toNodeId: string } | null {
  if (!firstNodeId || !secondNodeId || firstNodeId === secondNodeId) return null;
  return { fromNodeId: firstNodeId, toNodeId: secondNodeId };
}

// ===== 交互状态 / 处理器接口 =====

export interface CanvasInteractionState {
  /** 正在进行的连线（端口句柄） */
  connecting: ConnectionHandle | null;
  /** 连线拖拽时吸附到的目标节点 id */
  connectionTargetNodeId: string | null;
  /** 连线拖拽时鼠标的世界坐标 */
  mouseWorld: Position;
  /** 框选矩形（世界坐标） */
  selectionBox: SelectionBox | null;
  /** 当前悬停节点 id */
  hoveredNodeId: string | null;
  /** 当前选中的连线 id */
  selectedConnectionId: string | null;
  /** 右键菜单状态 */
  contextMenu: ContextMenuState;
  /** 双击背景后的创建菜单位置（世界坐标） */
  nodeCreatePosition: Position | null;
  /** 是否可以撤销 */
  canUndo: boolean;
  /** 是否可以重做 */
  canRedo: boolean;
  /** 当前生效工具（空格/Ctrl 临时切换后） */
  activeTool: CanvasTool;
  /** 是否正在平移 */
  isPanning: boolean;
  /** 空格键是否按下 */
  isSpacePressed: boolean;
}

export interface CanvasInteractionHandlers {
  /** 画布背景按下（框选 / 平移 / 清空选择） */
  onCanvasMouseDown: (event: ReactPointerEvent<HTMLDivElement>) => void;
  /** 画布背景双击（创建菜单） */
  onCanvasDoubleClick: (event: ReactMouseEvent<HTMLDivElement>) => void;
  /** 画布右键（背景阻止默认并关闭菜单） */
  onContextMenu: (event: ReactMouseEvent) => void;
  /** 节点按下（选择 + 开始拖拽） */
  onNodePointerDown: (event: ReactPointerEvent, nodeId: string) => void;
  /** 端口按下（开始连线 / 完成连线） */
  onNodeConnectStart: (event: ReactMouseEvent, nodeId: string, handleType: 'source' | 'target', handleKey: string) => void;
  /** 端口按下（连线进行中时完成连线） */
  onNodeConnectFinish: (event: ReactMouseEvent, nodeId: string, handleType: 'source' | 'target', handleKey: string) => void;
  /** 连线点击（选中连线） */
  onConnectionClick: (connectionId: string) => void;
  /** 连线右键（连线菜单） */
  onConnectionContextMenu: (event: ReactMouseEvent, connectionId: string) => void;
  /** 节点开始缩放（通知集成方） */
  onNodeResizeStart: (nodeId: string) => void;
  /** 工具栏动作（复制 / 删除等） */
  onToolbarAction: (action: CanvasToolbarAction, nodeId?: string) => void;
}

export interface UseCanvasInteractionsOptions {
  /** 画布容器 ref（用于坐标换算） */
  containerRef: RefObject<HTMLDivElement | null>;
  /** 画布节点列表 */
  nodes: CanvasSceneNode[];
  /** 节点目录（端口定义） */
  catalog: VideoCanvasNodeCatalogItem[];
  /** 当前视口变换 */
  viewport: CanvasViewport;
  /** 当前选中的节点 id 列表 */
  selectedNodeIds: string[];
  /** 当前工具（默认 select） */
  tool?: CanvasTool;
  /** 是否可以撤销（由集成方历史栈提供） */
  canUndo?: boolean;
  /** 是否可以重做（由集成方历史栈提供） */
  canRedo?: boolean;
  /** 视口变化回调（缩放 / 平移） */
  onViewportChange: (next: CanvasViewport) => void;
  /** 读取最新视口（含手势中尚未提交到 React 状态的中间值）；不传则用 viewport 属性 */
  getViewport?: () => CanvasViewport;
  /** 选择变化回调 */
  onSelectionChange: (ids: string[]) => void;
  /** 节点移动回调（initialNodes 为拖拽起点数组，delta 为相对起点的总位移，世界坐标） */
  onNodeMove: (initialNodes: { id: string; x: number; y: number }[], delta: { x: number; y: number }) => void;
  /** 创建连线回调 */
  onCreateConnection: (sourceNodeId: string, sourceHandle: string, targetNodeId: string, targetHandle: string) => void;
  /** 删除连线回调 */
  onDeleteConnection?: (connectionId: string) => void;
  /** 复制节点回调 */
  onDuplicateNode?: (nodeId: string) => void;
  /** 批量删除节点回调 */
  onDeleteNodes?: (ids: string[]) => void;
  /** 撤销回调 */
  onUndo?: () => void;
  /** 重做回调 */
  onRedo?: () => void;
  /** 双击背景创建节点回调（世界坐标） */
  onNodeCreate?: (position: Position) => void;
  /** 复制选中节点回调 */
  onCopyNodes?: (ids: string[]) => void;
  /** 粘贴已复制节点回调 */
  onPasteNodes?: () => void;
  onResizeStart?: () => void;
}

/** 按端口、节点内部、扩展区域的顺序确定连线落点。 */
export function connectionDropTarget(world: Position, scale: number, nodes: CanvasSceneNode[], catalog: VideoCanvasNodeCatalogItem[], current: ConnectionHandle): { nodeId: string | null; handleKey: string | null; isNearNode: boolean } {
    const padding = CONNECTION_NODE_HIT_PADDING / scale;
    const handleRadius = CONNECTION_HANDLE_HIT_RADIUS / scale;
    let isNearNode = false;
    let bestNodeId: string | null = null;
    let bestHandleKey: string | null = null;
    let bestPriority = Number.POSITIVE_INFINITY;

    [...nodes].reverse().forEach((node) => {
      const item = catalog.find((entry) => entry.type === node.type);
      if (!item) return;
      const size = nodeSize(node);
      // 连线从输出端口出发 → 目标是输入端口；从输入端口出发 → 目标是输出端口
      const ports = current.handleType === 'source' ? item.inputs : item.outputs;
      ports.forEach((port, index) => {
        const anchor = current.handleType === 'source'
          ? { x: node.position.x, y: node.position.y + portY(index, ports.length, size.height) }
          : { x: node.position.x + size.width, y: node.position.y + portY(index, ports.length, size.height) };
        const dx = world.x - anchor.x;
        const dy = world.y - anchor.y;
        if (dx * dx + dy * dy <= handleRadius * handleRadius) {
          isNearNode = true;
          if (node.id === current.nodeId) return;
          if (0 < bestPriority) {
            bestNodeId = node.id;
            bestHandleKey = port.key;
            bestPriority = 0;
          }
        }
      });
      // 节点内部 / 扩展区域命中
      // 组框（container）不吃内部/扩展落点：让位给框内子节点与画布空白，
      // 组框只能通过其端口（上面的优先级 0）成为连线目标。
      if (node.type === 'container') return;
      const hitsInside = world.x >= node.position.x && world.x <= node.position.x + size.width && world.y >= node.position.y && world.y <= node.position.y + size.height;
      const hitsExpanded = world.x >= node.position.x - padding && world.x <= node.position.x + size.width + padding && world.y >= node.position.y - padding && world.y <= node.position.y + size.height + padding;
      if (!hitsInside && !hitsExpanded) return;
      isNearNode = true;
      if (node.id === current.nodeId) return;
      const priority = hitsInside ? 1 : 2;
      if (priority < bestPriority) {
        bestNodeId = node.id;
        bestHandleKey = ports[0]?.key || null;
        bestPriority = priority;
      }
    });

    return { nodeId: bestNodeId, handleKey: bestHandleKey, isNearNode };
}

// ===== hook =====

export function useCanvasInteractions(options: UseCanvasInteractionsOptions): { handlers: CanvasInteractionHandlers; state: CanvasInteractionState; closeCreateMenu: () => void; closeContextMenu: () => void } {
  const {
    containerRef,
    nodes,
    catalog,
    viewport,
    getViewport,
    selectedNodeIds,
    tool = 'select',
    canUndo = false,
    canRedo = false,
    onViewportChange,
    onSelectionChange,
    onNodeMove,
    onCreateConnection,
    onDeleteConnection,
    onDuplicateNode,
    onDeleteNodes,
    onUndo,
    onRedo,
    onNodeCreate,
    onCopyNodes,
    onPasteNodes,
    onResizeStart,
  } = options;

  // refs 保存最新值，避免全局监听闭包过期
  const nodesRef = useRef(nodes);
  const catalogRef = useRef(catalog);
  const viewportRef = useRef(viewport);
  const selectedNodeIdsRef = useRef(selectedNodeIds);
  useEffect(() => { nodesRef.current = nodes; }, [nodes]);
  useEffect(() => { catalogRef.current = catalog; }, [catalog]);
  useEffect(() => { viewportRef.current = viewport; }, [viewport]);
  // 手势中视口只写 DOM、停手才提交：读取视口一律先取实时值，避免缩放后立刻框选 / 连线 / 平移时坐标换算过期
  const getViewportRef = useRef(getViewport);
  useEffect(() => { getViewportRef.current = getViewport; });
  const liveViewport = useCallback((): CanvasViewport => getViewportRef.current?.() ?? viewportRef.current, []);
  useEffect(() => { selectedNodeIdsRef.current = selectedNodeIds; }, [selectedNodeIds]);

  // 交互状态
  const [connecting, setConnecting] = useState<ConnectionHandle | null>(null);
  const [connectionTargetNodeId, setConnectionTargetNodeId] = useState<string | null>(null);
  const [mouseWorld, setMouseWorld] = useState<Position>({ x: 0, y: 0 });
  const [selectionBox, setSelectionBox] = useState<SelectionBox | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [selectedConnectionId, setSelectedConnectionId] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState>(null);
  const [nodeCreatePosition, setNodeCreatePosition] = useState<Position | null>(null);
  const [isPanning, setIsPanning] = useState(false);
  const [isSpacePressed, setIsSpacePressed] = useState(false);
  const [isControlPressed, setIsControlPressed] = useState(false);

  // 内部交互 refs
  const dragRef = useRef({ isDraggingNode: false, hasMoved: false, startX: 0, startY: 0, initialSelectedNodes: [] as { id: string; x: number; y: number }[] });
  const selectionBoxRef = useRef<SelectionBox | null>(null);
  const connectingRef = useRef<ConnectionHandle | null>(null);
  const connectionTargetNodeIdRef = useRef<string | null>(null);
  const rafRef = useRef<number | null>(null);
  const panStateRef = useRef({ isPanning: false, startX: 0, startY: 0, initialX: 0, initialY: 0, hasMoved: false, startedOnBackground: false });

  // 空格 / Ctrl 键监听（临时切换平移工具）
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Control') setIsControlPressed(true);
      if (event.code !== 'Space') return;
      const target = event.target instanceof Element ? event.target : null;
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement || target?.closest('[contenteditable="true"]')) return;
      event.preventDefault();
      setIsSpacePressed(true);
    };
    const handleKeyUp = (event: KeyboardEvent) => {
      if (event.code === 'Space') {
        const target = event.target instanceof Element ? event.target : null;
        if (!(event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement || target?.closest('[contenteditable="true"]'))) event.preventDefault();
        setIsSpacePressed(false);
      }
      if (event.key === 'Control') setIsControlPressed(false);
    };
    const handleBlur = () => {
      setIsSpacePressed(false);
      setIsControlPressed(false);
      panStateRef.current.isPanning = false;
      setIsPanning(false);
      document.body.style.cursor = '';
    };
    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);
    window.addEventListener('blur', handleBlur);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
      window.removeEventListener('blur', handleBlur);
    };
  }, []);

  // 平移：window pointermove / pointerup（rAF 节流）
  useEffect(() => {
    const handlePointerMove = (event: PointerEvent) => {
      if (!panStateRef.current.isPanning) return;
      const dx = event.clientX - panStateRef.current.startX;
      const dy = event.clientY - panStateRef.current.startY;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) panStateRef.current.hasMoved = true;
      const next = { x: panStateRef.current.initialX + dx, y: panStateRef.current.initialY + dy, scale: liveViewport().scale };
      if (rafRef.current) return;
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = null;
        onViewportChange(next);
      });
    };
    const handlePointerUp = () => {
      if (!panStateRef.current.isPanning) return;
      // 未移动且从背景开始 → 视为背景点击，清空选择
      if (!panStateRef.current.hasMoved && panStateRef.current.startedOnBackground) {
        onSelectionChange([]);
      }
      panStateRef.current.isPanning = false;
      setIsPanning(false);
      document.body.style.cursor = '';
    };
    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp);
    window.addEventListener('pointercancel', handlePointerUp);
    return () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
      window.removeEventListener('pointercancel', handlePointerUp);
      document.body.style.cursor = '';
    };
  }, [liveViewport, onSelectionChange, onViewportChange]);

  // 连线拖拽时的 3 级吸附目标计算
  const getConnectionDropTarget = useCallback((clientX: number, clientY: number, current: ConnectionHandle): { nodeId: string | null; handleKey: string | null; isNearNode: boolean } => {
    const rect = containerRef.current?.getBoundingClientRect() || null;
    const currentViewport = liveViewport();
    const world = screenToCanvas(clientX, clientY, rect, currentViewport);
    const scale = Math.max(currentViewport.scale, 0.05);
    const target = connectionDropTarget(world, scale, nodesRef.current, catalogRef.current, current);
    // 类型不兼容的落点视为未命中：不高亮、不吸附、抬起时不创建连线（保留 isNearNode 以走取消分支）
    if (target.nodeId && target.handleKey) {
      const [sourceNodeId, sourceHandleKey, targetNodeId, targetHandleKey] = current.handleType === 'source'
        ? [current.nodeId, current.handleKey, target.nodeId, target.handleKey]
        : [target.nodeId, target.handleKey, current.nodeId, current.handleKey];
      if (!canCreateConnection(nodesRef.current, catalogRef.current, sourceNodeId, sourceHandleKey, targetNodeId, targetHandleKey)) {
        return { nodeId: null, handleKey: null, isNearNode: target.isNearNode };
      }
    }
    return target;
  }, [containerRef, liveViewport]);

  // 完成节点拖拽：应用最终位移
  const finishNodeDrag = useCallback((clientX?: number, clientY?: number) => {
    if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null; }
    if (!dragRef.current.isDraggingNode) return;
    const currentViewport = liveViewport();
    const dx = clientX == null ? 0 : (clientX - dragRef.current.startX) / currentViewport.scale;
    const dy = clientY == null ? 0 : (clientY - dragRef.current.startY) / currentViewport.scale;
    const initialPositions = dragRef.current.initialSelectedNodes;
    if (dragRef.current.hasMoved && clientX != null && clientY != null) {
      onNodeMove(initialPositions, { x: dx, y: dy });
    }
    dragRef.current.isDraggingNode = false;
    dragRef.current.hasMoved = false;
    dragRef.current.initialSelectedNodes = [];
  }, [liveViewport, onNodeMove]);

  // 全局鼠标移动：节点拖拽 + 连线吸附
  const handleGlobalMouseMove = useCallback((event: MouseEvent) => {
    const currentViewport = liveViewport();
    if (dragRef.current.isDraggingNode) {
      const dx = (event.clientX - dragRef.current.startX) / currentViewport.scale;
      const dy = (event.clientY - dragRef.current.startY) / currentViewport.scale;
      if (Math.abs(event.clientX - dragRef.current.startX) > 3 || Math.abs(event.clientY - dragRef.current.startY) > 3) {
        dragRef.current.hasMoved = true;
      }
      const initialPositions = dragRef.current.initialSelectedNodes;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => {
        onNodeMove(initialPositions, { x: dx, y: dy });
        rafRef.current = null;
      });
      return;
    }
    if (connectingRef.current) {
      const dropTarget = getConnectionDropTarget(event.clientX, event.clientY, connectingRef.current);
      connectionTargetNodeIdRef.current = dropTarget.nodeId;
      setConnectionTargetNodeId(dropTarget.nodeId);
      setMouseWorld(screenToCanvas(event.clientX, event.clientY, containerRef.current?.getBoundingClientRect() || null, currentViewport));
    }
  }, [containerRef, getConnectionDropTarget, liveViewport, onNodeMove]);

  // 全局指针移动：框选
  const handleGlobalPointerMove = useCallback((event: PointerEvent) => {
    const currentSelection = selectionBoxRef.current;
    if (!currentSelection) return;
    if (event.buttons === 0) {
      selectionBoxRef.current = null;
      setSelectionBox(null);
      return;
    }
    const world = screenToCanvas(event.clientX, event.clientY, containerRef.current?.getBoundingClientRect() || null, liveViewport());
    const rectX = Math.min(currentSelection.startWorldX, world.x);
    const rectY = Math.min(currentSelection.startWorldY, world.y);
    const rectW = Math.abs(world.x - currentSelection.startWorldX);
    const rectH = Math.abs(world.y - currentSelection.startWorldY);
    const nextSelected = new Set<string>(currentSelection.additive ? currentSelection.initialSelectedNodeIds : []);
    nodesRef.current.forEach((node) => {
      const size = nodeSize(node);
      const intersects = rectX < node.position.x + size.width && rectX + rectW > node.position.x && rectY < node.position.y + size.height && rectY + rectH > node.position.y;
      if (intersects) nextSelected.add(node.id);
    });
    const nextSelectionBox = { ...currentSelection, currentWorldX: world.x, currentWorldY: world.y };
    selectionBoxRef.current = nextSelectionBox;
    setSelectionBox(nextSelectionBox);
    onSelectionChange([...nextSelected]);
  }, [containerRef, liveViewport, onSelectionChange]);

  // 全局鼠标抬起：完成拖拽 / 框选 / 连线
  const handleGlobalMouseUp = useCallback((event: MouseEvent) => {
    finishNodeDrag(event.clientX, event.clientY);
    selectionBoxRef.current = null;
    setSelectionBox(null);
    const currentConnection = connectingRef.current;
    if (currentConnection) {
      const dropTarget = getConnectionDropTarget(event.clientX, event.clientY, currentConnection);
      if (dropTarget.nodeId && dropTarget.handleKey) {
        if (currentConnection.handleType === 'source') {
          onCreateConnection(currentConnection.nodeId, currentConnection.handleKey, dropTarget.nodeId, dropTarget.handleKey);
        } else {
          onCreateConnection(dropTarget.nodeId, dropTarget.handleKey, currentConnection.nodeId, currentConnection.handleKey);
        }
        setConnecting(null);
        connectingRef.current = null;
      } else if (dropTarget.isNearNode) {
        // 靠近节点但未命中 → 取消连线
        setConnecting(null);
        connectingRef.current = null;
      } else {
        // 空白处释放 → 触发创建菜单
        const world = screenToCanvas(event.clientX, event.clientY, containerRef.current?.getBoundingClientRect() || null, liveViewport());
        setMouseWorld(world);
        setNodeCreatePosition(world);
        setConnecting(null);
        connectingRef.current = null;
      }
      connectionTargetNodeIdRef.current = null;
      setConnectionTargetNodeId(null);
    }
  }, [containerRef, finishNodeDrag, getConnectionDropTarget, liveViewport, onCreateConnection]);

  // 注册全局监听
  useEffect(() => {
    const handlePointerUp = (event: PointerEvent) => finishNodeDrag(event.clientX, event.clientY);
    const cancelNodeDrag = () => finishNodeDrag();
    window.addEventListener('mousemove', handleGlobalMouseMove);
    window.addEventListener('mouseup', handleGlobalMouseUp);
    window.addEventListener('pointerup', handlePointerUp);
    window.addEventListener('pointercancel', cancelNodeDrag);
    window.addEventListener('blur', cancelNodeDrag);
    window.addEventListener('pointermove', handleGlobalPointerMove);
    return () => {
      window.removeEventListener('mousemove', handleGlobalMouseMove);
      window.removeEventListener('mouseup', handleGlobalMouseUp);
      window.removeEventListener('pointerup', handlePointerUp);
      window.removeEventListener('pointercancel', cancelNodeDrag);
      window.removeEventListener('blur', cancelNodeDrag);
      window.removeEventListener('pointermove', handleGlobalPointerMove);
    };
  }, [finishNodeDrag, handleGlobalMouseMove, handleGlobalMouseUp, handleGlobalPointerMove]);

  // 快捷键：撤销 / 重做 / 全选 / 删除 / 清空
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement || target?.closest('[contenteditable="true"],[data-canvas-no-zoom],[data-canvas-shortcuts-ignore]')) return;
      const key = event.key.toLowerCase();
      const isModifier = event.metaKey || event.ctrlKey;
      if (isModifier && !event.altKey && key === 'z') {
        event.preventDefault();
        if (event.shiftKey) onRedo?.(); else onUndo?.();
        return;
      }
      if (isModifier && !event.altKey && key === 'y') {
        event.preventDefault();
        onRedo?.();
        return;
      }
      if (isModifier && !event.altKey && key === 'a') {
        event.preventDefault();
        onSelectionChange(nodesRef.current.map((node) => node.id));
        setSelectedConnectionId(null);
        setContextMenu(null);
        setSelectionBox(null);
        return;
      }
      if (isModifier && !event.altKey && key === 'c' && selectedNodeIdsRef.current.length) {
        event.preventDefault();
        onCopyNodes?.(selectedNodeIdsRef.current);
        return;
      }
      if (isModifier && !event.altKey && key === 'v') {
        event.preventDefault();
        onPasteNodes?.();
        return;
      }
      if (event.key === 'Delete' || event.key === 'Backspace') {
        if (selectedNodeIdsRef.current.length) {
          onDeleteNodes?.(selectedNodeIdsRef.current);
        } else if (selectedConnectionId) {
          onDeleteConnection?.(selectedConnectionId);
        }
      }
      if (event.key === 'Escape') {
        setSelectedConnectionId(null);
        setContextMenu(null);
        setNodeCreatePosition(null);
        setSelectionBox(null);
        setConnecting(null);
        connectingRef.current = null;
        setHoveredNodeId(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onCopyNodes, onDeleteConnection, onDeleteNodes, onPasteNodes, onRedo, onSelectionChange, onUndo, selectedConnectionId]);

  // ===== handlers =====

  const onCanvasMouseDown = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement | null;
    const isBackgroundClick = !target?.closest('[data-node-id],[data-connection-id]');
    const temporaryTool = event.ctrlKey || isSpacePressed;
    const activeTool = temporaryTool ? (tool === 'select' ? 'pan' : 'select') : tool;
    const shouldPan = event.button === 1 || (event.button === 0 && activeTool === 'pan');
    // Node content normally stops canvas gestures so its own controls can scroll/edit.
    // The explicit pan tool is the exception: it must also work when pressed on a node.
    if (!shouldPan && target?.closest('[data-canvas-no-zoom],[data-connection-create-menu]')) return;
    if (shouldPan && target?.closest('input, textarea, select, [contenteditable="true"]')) return;
    if (shouldPan) {
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      panStateRef.current = { isPanning: true, startX: event.clientX, startY: event.clientY, initialX: liveViewport().x, initialY: liveViewport().y, hasMoved: false, startedOnBackground: isBackgroundClick };
      setIsPanning(true);
      document.body.style.cursor = 'grabbing';
      return;
    }
    if (event.button === 0 && isBackgroundClick) {
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      setContextMenu(null);
      setNodeCreatePosition(null);
      setHoveredNodeId(null);
      const world = screenToCanvas(event.clientX, event.clientY, containerRef.current?.getBoundingClientRect() || null, liveViewport());
      const nextSelectionBox = { startWorldX: world.x, startWorldY: world.y, currentWorldX: world.x, currentWorldY: world.y, additive: event.shiftKey, initialSelectedNodeIds: event.shiftKey ? [...selectedNodeIdsRef.current] : [] };
      selectionBoxRef.current = nextSelectionBox;
      setSelectionBox(nextSelectionBox);
      if (!event.shiftKey) onSelectionChange([]);
      setSelectedConnectionId(null);
    }
  }, [containerRef, isSpacePressed, liveViewport, onSelectionChange, tool]);

  const onCanvasDoubleClick = useCallback((event: ReactMouseEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement | null;
    if (target?.closest('[data-canvas-no-zoom],[data-node-id],[data-connection-id]')) return;
    setContextMenu(null);
    const world = screenToCanvas(event.clientX, event.clientY, containerRef.current?.getBoundingClientRect() || null, liveViewport());
    setNodeCreatePosition(world);
    onNodeCreate?.(world);
  }, [containerRef, liveViewport, onNodeCreate]);

  const onContextMenu = useCallback((event: ReactMouseEvent) => {
    if ((event.target as HTMLElement).closest('[data-node-id]')) return;
    event.preventDefault();
    setContextMenu(null);
  }, []);

  const onNodePointerDown = useCallback((event: ReactPointerEvent, nodeId: string) => {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement | null;
    // 参考项目交互模型：拖拽从节点卡片体启动；交互控件（输入框/按钮/链接等）
    // 自己处理按下事件，不触发节点拖拽（useFieldEditing 等已在控件上阻断冒泡）
    if (target?.closest('input, textarea, select, button, a, [contenteditable="true"], [data-no-drag]')) return;
    const temporaryTool = event.ctrlKey || isSpacePressed;
    const effectiveTool = temporaryTool ? (tool === 'select' ? 'pan' : 'select') : tool;
    if (event.button === 0 && effectiveTool === 'pan') {
      // Let the bubbling canvas handler start the pan gesture.
      return;
    }
    event.stopPropagation();
    // 选择逻辑：Shift/Ctrl/Meta 切换，否则单选
    const nextSelected = new Set(selectedNodeIdsRef.current);
    if (event.shiftKey || event.metaKey || event.ctrlKey) {
      if (nextSelected.has(nodeId)) nextSelected.delete(nodeId);
      else nextSelected.add(nodeId);
    } else if (!nextSelected.has(nodeId)) {
      nextSelected.clear();
      nextSelected.add(nodeId);
    }
    onSelectionChange([...nextSelected]);
    // 开始拖拽：记录所有选中节点的初始位置
    const currentNodes = nodesRef.current;
    const dragIds = new Set(nextSelected);
    dragRef.current = {
      isDraggingNode: true,
      hasMoved: false,
      startX: event.clientX,
      startY: event.clientY,
      initialSelectedNodes: currentNodes.filter((node) => dragIds.has(node.id)).map((node) => ({ id: node.id, x: node.position.x, y: node.position.y })),
    };
  }, [isSpacePressed, onSelectionChange, tool]);

  const onNodeConnectStart = useCallback((event: ReactMouseEvent, nodeId: string, handleType: 'source' | 'target', handleKey: string) => {
    event.stopPropagation();
    const current = connectingRef.current;
    // 连线进行中点击目标输入端口 → 直接完成连线（类型不兼容时仅结束连线，不创建）
    if (handleType === 'target' && current && current.handleType === 'source') {
      if (current.nodeId !== nodeId && canCreateConnection(nodesRef.current, catalogRef.current, current.nodeId, current.handleKey, nodeId, handleKey)) {
        onCreateConnection(current.nodeId, current.handleKey, nodeId, handleKey);
      }
      setConnecting(null);
      connectingRef.current = null;
      connectionTargetNodeIdRef.current = null;
      setConnectionTargetNodeId(null);
      return;
    }
    setMouseWorld(screenToCanvas(event.clientX, event.clientY, containerRef.current?.getBoundingClientRect() || null, liveViewport()));
    setConnecting({ nodeId, handleType, handleKey });
    connectingRef.current = { nodeId, handleType, handleKey };
    connectionTargetNodeIdRef.current = null;
    setConnectionTargetNodeId(null);
    setSelectedConnectionId(null);
  }, [containerRef, liveViewport, onCreateConnection]);

  const onNodeConnectFinish = useCallback((event: ReactMouseEvent, nodeId: string, handleType: 'source' | 'target', handleKey: string) => {
    event.stopPropagation();
    const current = connectingRef.current;
    if (!current) return;
    if (current.nodeId === nodeId) {
      setConnecting(null);
      connectingRef.current = null;
      return;
    }
    if (current.handleType === 'source' && handleType === 'target') {
      if (canCreateConnection(nodesRef.current, catalogRef.current, current.nodeId, current.handleKey, nodeId, handleKey)) {
        onCreateConnection(current.nodeId, current.handleKey, nodeId, handleKey);
      }
    } else if (current.handleType === 'target' && handleType === 'source') {
      if (canCreateConnection(nodesRef.current, catalogRef.current, nodeId, handleKey, current.nodeId, current.handleKey)) {
        onCreateConnection(nodeId, handleKey, current.nodeId, current.handleKey);
      }
    }
    setConnecting(null);
    connectingRef.current = null;
    connectionTargetNodeIdRef.current = null;
    setConnectionTargetNodeId(null);
  }, [onCreateConnection]);

  const onConnectionClick = useCallback((connectionId: string) => {
    setSelectedConnectionId(connectionId);
    onSelectionChange([]);
    setContextMenu(null);
  }, [onSelectionChange]);

  const onConnectionContextMenu = useCallback((event: ReactMouseEvent, connectionId: string) => {
    event.preventDefault();
    event.stopPropagation();
    setSelectedConnectionId(connectionId);
    onSelectionChange([]);
    setContextMenu({ type: 'connection', x: event.clientX, y: event.clientY, connectionId });
  }, [onSelectionChange]);

  const onNodeResizeStart = useCallback((nodeId: string) => {
    void nodeId;
    onResizeStart?.();
    setHoveredNodeId(null);
  }, [onResizeStart]);

  const onToolbarAction = useCallback((action: CanvasToolbarAction, nodeId?: string) => {
    if (action === 'duplicate' && nodeId) onDuplicateNode?.(nodeId);
    if (action === 'delete' && nodeId) onDeleteNodes?.([nodeId]);
    if (action === 'delete-connection' && selectedConnectionId) onDeleteConnection?.(selectedConnectionId);
  }, [onDeleteConnection, onDeleteNodes, onDuplicateNode, selectedConnectionId]);

  // 空格 / Ctrl 临时切换工具
  const temporaryTool = isControlPressed || isSpacePressed;
  const activeTool = temporaryTool ? (tool === 'select' ? 'pan' : 'select') : tool;

  return {
    handlers: {
      onCanvasMouseDown,
      onCanvasDoubleClick,
      onContextMenu,
      onNodePointerDown,
      onNodeConnectStart,
      onNodeConnectFinish,
      onConnectionClick,
      onConnectionContextMenu,
      onNodeResizeStart,
      onToolbarAction,
    },
    state: {
      connecting,
      connectionTargetNodeId,
      mouseWorld,
      selectionBox,
      hoveredNodeId,
      selectedConnectionId,
      contextMenu,
      nodeCreatePosition,
      canUndo,
      canRedo,
      activeTool,
      isPanning,
      isSpacePressed,
    },
    closeCreateMenu: () => setNodeCreatePosition(null),
    closeContextMenu: () => setContextMenu(null),
  };
}
