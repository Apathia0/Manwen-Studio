import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent, type WheelEvent as ReactWheelEvent } from 'react';
import { Link2, Loader2, Move, Pencil, Plus, RotateCcw, Route, Sparkles, UsersRound, X, ZoomIn, ZoomOut } from 'lucide-react';

import type { StoryKnowledgeCategory, StoryKnowledgeItem, StoryKnowledgeMutation } from '../api';
import {
  buildEntityGraph,
  buildRelationshipFactPayload,
  canCreateRelationship,
  buildTimelineDomain,
  chapterPosition,
  clampGraphPoint,
  entityGraphLayoutStorageKey,
  mergeEntityGraphLayoutCache,
  parseEntityGraphLayoutCache,
  stringifyEntityGraphLayoutCache,
  type EntityGraphNode,
  type GraphPoint,
  timelineChapterValues,
  type TimelineDomain,
} from './knowledgeVisualizationUtils';

type Props = {
  storyId: number;
  kind: 'entity' | 'fact' | 'plot_thread';
  items: StoryKnowledgeItem[];
  facts: StoryKnowledgeItem[];
  plotThreads: StoryKnowledgeItem[];
  categories: StoryKnowledgeCategory[];
  onEdit: (item: StoryKnowledgeItem) => void;
  onCreateRelation: () => void;
  onCreateEntity: (payload: StoryKnowledgeMutation) => Promise<void>;
  onCreateFact: (payload: StoryKnowledgeMutation) => Promise<void>;
  onSync: () => void;
  syncing: boolean;
  syncMessage: string;
};

const ENTITY_COLORS: Record<string, { fill: string; stroke: string; text: string; label: string }> = {
  character: { fill: '#eff6ff', stroke: '#3b82f6', text: '#1d4ed8', label: '人物' },
  faction: { fill: '#fdf4ff', stroke: '#c026d3', text: '#86198f', label: '势力' },
  location: { fill: '#ecfdf5', stroke: '#10b981', text: '#047857', label: '地点' },
  item: { fill: '#fffbeb', stroke: '#f59e0b', text: '#b45309', label: '物品' },
  concept: { fill: '#f5f3ff', stroke: '#8b5cf6', text: '#6d28d9', label: '概念' },
  plot_thread: { fill: '#f5f3ff', stroke: '#8b5cf6', text: '#6d28d9', label: '剧情线' },
  other: { fill: '#f8fafc', stroke: '#94a3b8', text: '#475569', label: '其他' },
};

const TIMELINE_LIMIT = 300;
const CLICK_DRAG_THRESHOLD = 5;
const RELATION_PRESETS = ['关联', '属于', '敌对', '信任', '位于', '持有'];

export default function KnowledgeVisualizations(props: Props) {
  if (props.kind === 'entity') return <EntityRelationshipGraph {...props} />;
  return <ChapterTimeline {...props} kind={props.kind} />;
}

function EntityRelationshipGraph({ storyId, items, facts, onEdit, onCreateRelation, onCreateEntity, onCreateFact, onSync, syncing, syncMessage }: Props) {
  const graph = useMemo(() => buildEntityGraph(items, facts, []), [items, facts]);
  const storageKey = useMemo(() => entityGraphLayoutStorageKey(storyId, 'entity'), [storyId]);
  const svgRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<{ nodeId: string; pointerId: number; startClientX: number; startClientY: number; offsetX: number; offsetY: number; moved: boolean } | null>(null);
  const relationDragRef = useRef<{ sourceId: string; pointerId: number; moved: boolean } | null>(null);
  const relationClickSuppressRef = useRef(false);
  const suppressClickRef = useRef<string | null>(null);
  const relationDialogRef = useRef<HTMLDivElement>(null);
  const relationTypeInputRef = useRef<HTMLInputElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const [positions, setPositions] = useState<Record<string, GraphPoint>>(() => {
    try {
      const cache = parseEntityGraphLayoutCache(window.localStorage.getItem(storageKey), graph.width, graph.height);
      const allowed = new Set(graph.nodes.filter((node) => node.kind === 'entity').map((node) => node.id));
      return Object.fromEntries(Object.entries(cache.nodes).filter(([nodeId]) => allowed.has(nodeId)));
    } catch {
      return {};
    }
  });
  const [relationSourceId, setRelationSourceId] = useState<string | null>(null);
  const [relationPreview, setRelationPreview] = useState<{ sourceId: string; to: GraphPoint } | null>(null);
  const [pendingRelation, setPendingRelation] = useState<{ source: EntityGraphNode; target: EntityGraphNode } | null>(null);
  const [relationType, setRelationType] = useState('关联');
  const [relationDescription, setRelationDescription] = useState('');
  const [relationSaving, setRelationSaving] = useState(false);
  const [quickEntityOpen, setQuickEntityOpen] = useState(false);
  const [quickEntityName, setQuickEntityName] = useState('');
  const [quickEntityType, setQuickEntityType] = useState('character');
  const [quickEntitySaving, setQuickEntitySaving] = useState(false);
  const cancelRelation = useCallback(() => {
    setRelationSourceId(null);
    setRelationPreview(null);
    setPendingRelation(null);
    relationDragRef.current = null;
  }, []);
  const positionedGraph = useMemo(() => {
    const nodeMap = new Map<string, EntityGraphNode>();
    const nodes = graph.nodes.map((node) => {
      const point = positions[node.id];
      const nextNode = point ? { ...node, ...clampGraphPoint(point, graph.width, graph.height) } : node;
      nodeMap.set(node.id, nextNode);
      return nextNode;
    });
    const edges = graph.edges.map((edge) => ({ ...edge, from: nodeMap.get(edge.from.id) || edge.from, to: nodeMap.get(edge.to.id) || edge.to }));
    return { ...graph, nodes, edges };
  }, [graph, positions]);

  const nodesById = useMemo(() => new Map(positionedGraph.nodes.map((node) => [node.id, node])), [positionedGraph.nodes]);

  const persistPositions = useCallback((nextPositions: Record<string, GraphPoint>) => {
    try {
      const cached = parseEntityGraphLayoutCache(window.localStorage.getItem(storageKey), graph.width, graph.height);
      const visibleNodes = Object.fromEntries(Object.entries(nextPositions).filter(([nodeId]) => nodesById.get(nodeId)?.kind === 'entity'));
      window.localStorage.setItem(storageKey, stringifyEntityGraphLayoutCache(mergeEntityGraphLayoutCache(cached, visibleNodes)));
    } catch {
      // localStorage 不可用时忽略，图谱仍按默认布局工作。
    }
  }, [graph.height, graph.width, nodesById, storageKey]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || (!relationSourceId && !relationPreview && !pendingRelation)) return;
      event.preventDefault();
      event.stopPropagation();
      (event as KeyboardEvent & { stopImmediatePropagation?: () => void }).stopImmediatePropagation?.();
      cancelRelation();
    };
    document.addEventListener('keydown', handleKeyDown, true);
    return () => document.removeEventListener('keydown', handleKeyDown, true);
  }, [cancelRelation, pendingRelation, relationPreview, relationSourceId]);

  useEffect(() => {
    if (!pendingRelation) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    relationTypeInputRef.current?.focus();
    const handleDialogKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Tab' || !relationDialogRef.current) return;
      const focusable = Array.from(relationDialogRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), textarea:not([disabled])'));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', handleDialogKeyDown);
    return () => {
      document.removeEventListener('keydown', handleDialogKeyDown);
      previousFocusRef.current?.focus();
      previousFocusRef.current = null;
    };
  }, [pendingRelation]);

  function svgPoint(event: Pick<PointerEvent | ReactPointerEvent, 'clientX' | 'clientY'>): GraphPoint {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    return {
      x: ((event.clientX - rect.left) / Math.max(1, rect.width)) * graph.width,
      y: ((event.clientY - rect.top) / Math.max(1, rect.height)) * graph.height,
    };
  }

  function beginNodeDrag(event: ReactPointerEvent<HTMLButtonElement>, node: EntityGraphNode) {
    if (node.kind !== 'entity' || event.button !== 0 || relationSourceId) return;
    const point = svgPoint(event);
    dragRef.current = { nodeId: node.id, pointerId: event.pointerId, startClientX: event.clientX, startClientY: event.clientY, offsetX: point.x - node.x, offsetY: point.y - node.y, moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveNode(event: ReactPointerEvent<HTMLButtonElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const moved = Math.hypot(event.clientX - drag.startClientX, event.clientY - drag.startClientY) > CLICK_DRAG_THRESHOLD;
    drag.moved = drag.moved || moved;
    if (!drag.moved) return;
    const point = svgPoint(event);
    setPositions((current) => ({
      ...current,
      [drag.nodeId]: clampGraphPoint({ x: point.x - drag.offsetX, y: point.y - drag.offsetY }, graph.width, graph.height),
    }));
  }

  function endNodeDrag(event: ReactPointerEvent<HTMLButtonElement>, node: EntityGraphNode) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (drag.moved) {
      suppressClickRef.current = node.id;
      setPositions((current) => {
        persistPositions(current);
        return current;
      });
    }
    dragRef.current = null;
  }

  function beginRelationDrag(event: ReactPointerEvent<HTMLButtonElement>, node: EntityGraphNode) {
    event.stopPropagation();
    if (node.kind !== 'entity') return;
    const point = svgPoint(event);
    relationDragRef.current = { sourceId: node.id, pointerId: event.pointerId, moved: false };
    setRelationSourceId(node.id);
    setRelationPreview({ sourceId: node.id, to: point });
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveRelation(event: ReactPointerEvent<HTMLButtonElement>) {
    const drag = relationDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    drag.moved = true;
    setRelationPreview({ sourceId: drag.sourceId, to: svgPoint(event) });
  }

  function endRelationDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    const drag = relationDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const targetId = document.elementFromPoint(event.clientX, event.clientY)?.closest('[data-graph-node-id]')?.getAttribute('data-graph-node-id') || null;
    const source = nodesById.get(drag.sourceId);
    const target = targetId ? nodesById.get(targetId) : undefined;
    if (drag.moved) {
      relationClickSuppressRef.current = true;
      if (canCreateRelationship(source, target)) openRelationConfirm(source!, target!);
    }
    setRelationPreview(null);
    relationDragRef.current = null;
  }

  function handleNodeClick(event: ReactMouseEvent<HTMLButtonElement>, node: EntityGraphNode) {
    if (suppressClickRef.current === node.id) {
      suppressClickRef.current = null;
      event.preventDefault();
      return;
    }
    if (relationSourceId) {
      const source = nodesById.get(relationSourceId);
      if (canCreateRelationship(source, node)) {
        event.preventDefault();
        openRelationConfirm(source!, node);
        return;
      }
      if (node.kind === 'entity' && source?.id === node.id) {
        event.preventDefault();
        cancelRelation();
        return;
      }
    }
    onEdit(node.item);
  }

  function openRelationConfirm(source: EntityGraphNode, target: EntityGraphNode) {
    setPendingRelation({ source, target });
    setRelationType('关联');
    setRelationDescription('');
    setRelationSourceId(null);
  }

  async function saveRelation() {
    if (!pendingRelation || !relationType.trim()) return;
    setRelationSaving(true);
    try {
      await onCreateFact(buildRelationshipFactPayload({
        subjectKey: pendingRelation.source.key,
        predicate: relationType,
        objectKey: pendingRelation.target.key,
        description: relationDescription,
      }));
      cancelRelation();
    } catch {
      // 工作台回调已展示具体错误，保留表单方便用户修正后重试。
    } finally {
      setRelationSaving(false);
    }
  }

  async function saveQuickEntity() {
    const name = quickEntityName.trim();
    if (!name) return;
    setQuickEntitySaving(true);
    try {
      await onCreateEntity({ canonical_name: name, entity_type: quickEntityType, status: 'active', importance: 60 });
      setQuickEntityName('');
      setQuickEntityType('character');
      setQuickEntityOpen(false);
    } catch {
      // 工作台回调已展示具体错误，保留输入内容方便用户重试。
    } finally {
      setQuickEntitySaving(false);
    }
  }

  return (
    <div className="min-h-0 flex-1 overflow-auto bg-slate-50/60 p-4">
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-slate-500">
        <span className="font-medium text-slate-700">当前关系图谱 · {items.length} 个对象 · {positionedGraph.edges.length} 条关联</span>
        {Object.entries(ENTITY_COLORS).slice(0, 5).map(([key, value]) => (
          <span key={key} className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ backgroundColor: value.stroke }} />{value.label}</span>
        ))}
        {positionedGraph.hiddenCount > 0 ? <span className="text-amber-700">优先展示重要度最高的 30 个，另有 {positionedGraph.hiddenCount} 个可在列表查看</span> : null}
        <span className="ml-auto flex items-center gap-2">
          <button type="button" onClick={() => setQuickEntityOpen((open) => !open)} className="inline-flex h-8 items-center gap-1.5 rounded border border-slate-200 bg-white px-2.5 font-medium text-slate-700 hover:border-blue-300 hover:text-blue-700"><Plus size={13} />新增对象</button>
          <button type="button" onClick={onCreateRelation} className="inline-flex h-8 items-center gap-1.5 rounded border border-slate-200 bg-white px-2.5 font-medium text-slate-700 hover:border-blue-300 hover:text-blue-700"><Link2 size={13} />新增关系</button>
          <button type="button" onClick={onSync} disabled={syncing} className="inline-flex h-8 items-center gap-1.5 rounded bg-blue-600 px-2.5 font-medium text-white hover:bg-blue-700 disabled:opacity-60">{syncing ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}{syncing ? syncMessage || '同步中' : 'AI 同步'}</button>
        </span>
      </div>
      {quickEntityOpen ? (
        <div className="mb-3 flex flex-wrap items-end gap-2 rounded-md border border-slate-200 bg-white p-3 text-xs">
          <label className="min-w-[180px] flex-1">
            <span className="mb-1 block font-medium text-slate-600">名称</span>
            <input value={quickEntityName} onChange={(event) => setQuickEntityName(event.target.value)} className="h-8 w-full rounded border border-slate-200 px-2 outline-none focus:border-blue-400" placeholder="输入对象名称" />
          </label>
          <label>
            <span className="mb-1 block font-medium text-slate-600">类型</span>
            <select value={quickEntityType} onChange={(event) => setQuickEntityType(event.target.value)} className="h-8 rounded border border-slate-200 px-2 outline-none focus:border-blue-400">
              <option value="character">人物</option>
              <option value="location">地点</option>
              <option value="faction">势力</option>
              <option value="item">物品</option>
              <option value="concept">概念</option>
            </select>
          </label>
          <button type="button" onClick={() => void saveQuickEntity()} disabled={quickEntitySaving || !quickEntityName.trim()} className="inline-flex h-8 items-center gap-1.5 rounded bg-blue-600 px-3 font-medium text-white hover:bg-blue-700 disabled:opacity-60">{quickEntitySaving ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}保存</button>
          <button type="button" onClick={() => setQuickEntityOpen(false)} className="flex h-8 w-8 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700" title="关闭快速新增"><X size={14} /></button>
        </div>
      ) : null}
      <div className="relative min-w-[900px] overflow-hidden rounded-md border border-slate-200 bg-white">
        {relationSourceId ? <div className="absolute left-3 top-3 z-10 rounded bg-slate-900/80 px-2 py-1 text-[11px] text-white">选择目标对象，或按 Esc 取消</div> : null}
        <svg ref={svgRef} viewBox={`0 0 ${positionedGraph.width} ${positionedGraph.height}`} className="block w-full touch-none" style={{ minHeight: 430 }} role="group" aria-label="人物与地点关系图谱">
          <defs>
            <marker id="knowledge-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />
            </marker>
          </defs>
          {positionedGraph.edges.map((edge) => {
            const middleX = (edge.from.x + edge.to.x) / 2;
            const middleY = (edge.from.y + edge.to.y) / 2;
            return (
              <g key={edge.id}>
                <title>{edge.kind === 'plot_thread' ? `剧情线关联：${edge.label}` : `事实关系：${edge.label}`}</title>
                <line x1={edge.from.x} y1={edge.from.y} x2={edge.to.x} y2={edge.to.y} stroke={edge.kind === 'plot_thread' ? '#a78bfa' : '#94a3b8'} strokeWidth="1.5" strokeOpacity={edge.kind === 'plot_thread' ? 0.55 : 0.8} strokeDasharray={edge.kind === 'plot_thread' ? '5 4' : undefined} markerEnd={edge.directed ? 'url(#knowledge-arrow)' : undefined} />
                <line x1={edge.from.x} y1={edge.from.y} x2={edge.to.x} y2={edge.to.y} stroke="transparent" strokeWidth="14" className="cursor-pointer" aria-hidden="true" onClick={() => onEdit(edge.item)} />
                <g pointerEvents="none">
                  <rect x={middleX - Math.max(34, Math.min(84, truncate(edge.label, 14).length * 5 + 10))} y={middleY - 10} width={Math.max(68, Math.min(168, truncate(edge.label, 14).length * 10 + 20))} height="20" rx="5" fill="white" fillOpacity="0.94" stroke={edge.kind === 'plot_thread' ? '#c4b5fd' : '#e2e8f0'} />
                  <text x={middleX} y={middleY + 3.5} textAnchor="middle" fontSize="10" fill={edge.kind === 'plot_thread' ? '#6d28d9' : '#475569'}>{truncate(edge.label, 14)}</text>
                </g>
              </g>
            );
          })}
          {relationPreview ? (() => {
            const source = nodesById.get(relationPreview.sourceId);
            return source ? <line x1={source.x} y1={source.y} x2={relationPreview.to.x} y2={relationPreview.to.y} stroke="#2563eb" strokeWidth="1.5" strokeDasharray="6 4" pointerEvents="none" /> : null;
          })() : null}
          {positionedGraph.nodes.map((node) => {
            const colors = ENTITY_COLORS[node.type] || ENTITY_COLORS.other;
            const selected = relationSourceId === node.id;
            return (
              <foreignObject key={node.id} x={node.x - 88} y={node.y - 28} width="176" height="62">
                <div className="relative h-[62px] w-[176px]" data-graph-node-id={node.id}>
                  <button
                    type="button"
                    data-graph-node-id={node.id}
                    onPointerDown={(event) => beginNodeDrag(event, node)}
                    onPointerMove={moveNode}
                    onPointerUp={(event) => endNodeDrag(event, node)}
                    onPointerCancel={() => { dragRef.current = null; }}
                    onClick={(event) => handleNodeClick(event, node)}
                    title={`编辑${colors.label}：${node.name}`}
                    aria-label={`${node.name}，${colors.label}，拖拽移动或点击编辑`}
                    className={`ml-3 flex h-[56px] w-[152px] cursor-grab items-center gap-2 rounded-md border bg-white px-3 text-left shadow-sm transition hover:shadow-md active:cursor-grabbing ${selected ? 'ring-2 ring-blue-300' : ''}`}
                    style={{ borderColor: selected ? '#2563eb' : colors.stroke }}
                  >
                    <span className="h-3 w-3 shrink-0 rounded-full" style={{ backgroundColor: colors.stroke }} />
                    <span className="min-w-0">
                      <span className="block truncate text-xs font-semibold" style={{ color: colors.text }}>{node.name}</span>
                      <span className="mt-0.5 block text-[10px] text-slate-400">{colors.label} · 拖拽移动</span>
                    </span>
                  </button>
                  {node.kind === 'entity' ? (
                    <button
                      type="button"
                      title={`从${node.name}创建关系`}
                      aria-label={`从${node.name}创建关系`}
                      onPointerDown={(event) => beginRelationDrag(event, node)}
                      onPointerMove={moveRelation}
                      onPointerUp={endRelationDrag}
                      onPointerCancel={() => { relationDragRef.current = null; setRelationPreview(null); }}
                      onClick={(event) => {
                        event.stopPropagation();
                        if (relationClickSuppressRef.current) {
                          relationClickSuppressRef.current = false;
                          return;
                        }
                        setRelationSourceId((current) => current === node.id ? null : node.id);
                      }}
                      className="absolute right-1 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-full border border-blue-200 bg-white text-blue-600 shadow-sm hover:border-blue-400 hover:bg-blue-50"
                    >
                      <Link2 size={13} />
                    </button>
                  ) : null}
                </div>
              </foreignObject>
            );
          })}
          {positionedGraph.edges.filter((edge) => edge.kind === 'fact').map((edge) => {
            const middleX = (edge.from.x + edge.to.x) / 2;
            const middleY = (edge.from.y + edge.to.y) / 2;
            const labelHalfWidth = Math.max(34, Math.min(84, truncate(edge.label, 14).length * 5 + 10));
            return <foreignObject key={`edit-${edge.id}`} x={middleX + labelHalfWidth + 4} y={middleY - 12} width="24" height="24"><button type="button" title={`编辑关系：${edge.label}`} aria-label={`编辑关系：${edge.label}`} onClick={() => onEdit(edge.item)} className="flex h-6 w-6 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-400 shadow-sm hover:border-blue-300 hover:text-blue-700"><Pencil size={11} /></button></foreignObject>;
          })}
        </svg>
        {positionedGraph.nodes.length === 0 ? (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <UsersRound size={30} className="mx-auto text-slate-300" />
              <p className="mt-3 text-sm font-medium text-slate-600">暂无可展示对象</p>
              <p className="mt-1 text-xs text-slate-400">可以快速新增对象，也可以让 AI 同步作品信息。</p>
            </div>
          </div>
        ) : null}
        {pendingRelation ? (
          <div ref={relationDialogRef} role="dialog" aria-modal="true" aria-labelledby="knowledge-relation-dialog-title" className="absolute right-3 top-3 z-20 w-72 rounded-md border border-slate-200 bg-white p-3 text-xs shadow-xl">
            <div className="mb-2 flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <p id="knowledge-relation-dialog-title" className="font-semibold text-slate-800">确认关系</p>
                <p className="mt-0.5 truncate text-slate-500">{pendingRelation.source.name} → {pendingRelation.target.name}</p>
              </div>
              <button type="button" onClick={cancelRelation} className="flex h-7 w-7 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700" title="取消关系"><X size={14} /></button>
            </div>
            <label className="block">
              <span className="mb-1 block font-medium text-slate-600">关系类型</span>
              <input ref={relationTypeInputRef} list="knowledge-relation-presets" value={relationType} onChange={(event) => setRelationType(event.target.value)} className="h-8 w-full rounded border border-slate-200 px-2 outline-none focus:border-blue-400" />
              <datalist id="knowledge-relation-presets">
                {RELATION_PRESETS.map((preset) => <option key={preset} value={preset} />)}
              </datalist>
            </label>
            <label className="mt-2 block">
              <span className="mb-1 block font-medium text-slate-600">描述</span>
              <textarea value={relationDescription} onChange={(event) => setRelationDescription(event.target.value)} rows={2} className="w-full resize-none rounded border border-slate-200 px-2 py-1.5 outline-none focus:border-blue-400" placeholder="可选" />
            </label>
            <div className="mt-3 flex justify-end gap-2">
              <button type="button" onClick={cancelRelation} className="h-8 rounded border border-slate-200 px-3 font-medium text-slate-600 hover:bg-slate-50">取消</button>
              <button type="button" onClick={() => void saveRelation()} disabled={relationSaving || !relationType.trim()} className="inline-flex h-8 items-center gap-1.5 rounded bg-blue-600 px-3 font-medium text-white hover:bg-blue-700 disabled:opacity-60">{relationSaving ? <Loader2 size={13} className="animate-spin" /> : <Link2 size={13} />}保存</button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ChapterTimeline({ kind, items, categories, onEdit, onSync, syncing, syncMessage }: Props & { kind: 'fact' | 'plot_thread' }) {
  const categoryColors = useMemo(() => new Map(categories.map((category) => [category.id, category.color || '#2563eb'])), [categories]);
  const sortedItems = useMemo(() => items.slice().sort((a, b) => earliestChapter(a, kind) - earliestChapter(b, kind) || a.id - b.id), [items, kind]);
  const visibleItems = useMemo(() => sortedItems.slice(0, TIMELINE_LIMIT), [sortedItems]);
  const domain = useMemo(() => buildTimelineDomain(visibleItems, kind), [visibleItems, kind]);
  const [zoom, setZoom] = useState(1);
  const [viewStart, setViewStart] = useState(domain.start);
  const dragRef = useRef<{ x: number; start: number } | null>(null);
  const hiddenCount = Math.max(0, sortedItems.length - TIMELINE_LIMIT);
  const totalSpan = Math.max(1, domain.end - domain.start);
  const visibleSpan = Math.max(4, totalSpan / zoom);
  const maxStart = Math.max(domain.start, domain.end - visibleSpan);
  const normalizedStart = Math.min(maxStart, Math.max(domain.start, viewStart));
  const rowHeight = 46;
  const axisHeight = 44;
  const canvasHeight = Math.max(240, axisHeight + visibleItems.length * rowHeight);
  const viewDomain: TimelineDomain = { start: normalizedStart, end: normalizedStart + visibleSpan, ticks: domain.ticks };
  const ticks = buildVisibleTicks(viewDomain);

  function updateZoom(nextZoom: number, anchor = 0.5) {
    const clampedZoom = Math.min(8, Math.max(1, nextZoom));
    const anchorChapter = normalizedStart + visibleSpan * anchor;
    const nextSpan = Math.max(4, totalSpan / clampedZoom);
    setZoom(clampedZoom);
    setViewStart(Math.min(domain.end - nextSpan, Math.max(domain.start, anchorChapter - nextSpan * anchor)));
  }

  function handlePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    dragRef.current = { x: event.clientX, start: normalizedStart };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!dragRef.current) return;
    const width = event.currentTarget.getBoundingClientRect().width || 1;
    const delta = ((event.clientX - dragRef.current.x) / width) * visibleSpan;
    setViewStart(Math.min(maxStart, Math.max(domain.start, dragRef.current.start - delta)));
  }

  function handleWheel(event: ReactWheelEvent<HTMLDivElement>) {
    if (event.ctrlKey || Math.abs(event.deltaY) > Math.abs(event.deltaX)) {
      event.preventDefault();
      const rect = event.currentTarget.getBoundingClientRect();
      updateZoom(zoom * (event.deltaY > 0 ? 0.85 : 1.18), (event.clientX - rect.left) / Math.max(1, rect.width));
      return;
    }
    setViewStart(Math.min(maxStart, Math.max(domain.start, normalizedStart + (event.deltaX / 600) * visibleSpan)));
  }

  if (items.length === 0) {
    return <TimelineEmpty kind={kind} onSync={onSync} syncing={syncing} syncMessage={syncMessage} />;
  }
  return (
    <div className="min-h-0 flex-1 overflow-auto bg-slate-50/60 p-4">
      <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-slate-500">
        <span className="font-medium text-slate-700">共享章节时间轴 · {items.length} 条记录</span>
        {kind === 'fact' ? <><Legend color="#2563eb" label="事实有效期" /><Legend color="#94a3b8" label="未设置有效期" /></> : <><Legend color="#2563eb" label="埋设" /><Legend color="#f59e0b" label="计划回收" /><Legend color="#10b981" label="实际回收" /></>}
        {hiddenCount > 0 ? <span className="text-amber-700">仅展示前 {TIMELINE_LIMIT} 条，另有 {hiddenCount} 条可通过筛选查看</span> : null}
        <div className="ml-auto flex items-center gap-1">
          <button type="button" title="缩小" onClick={() => updateZoom(zoom / 1.4)} className="flex h-8 w-8 items-center justify-center rounded border border-slate-200 bg-white text-slate-500 hover:text-blue-700"><ZoomOut size={14} /></button>
          <span className="w-11 text-center text-[11px] text-slate-500">{Math.round(zoom * 100)}%</span>
          <button type="button" title="放大" onClick={() => updateZoom(zoom * 1.4)} className="flex h-8 w-8 items-center justify-center rounded border border-slate-200 bg-white text-slate-500 hover:text-blue-700"><ZoomIn size={14} /></button>
          <button type="button" title="重置视图" onClick={() => { setZoom(1); setViewStart(domain.start); }} className="flex h-8 w-8 items-center justify-center rounded border border-slate-200 bg-white text-slate-500 hover:text-blue-700"><RotateCcw size={14} /></button>
          <span className="ml-2 inline-flex items-center gap-1 text-[11px] text-slate-400"><Move size={13} />拖拽查看</span>
          <button type="button" onClick={onSync} disabled={syncing} className="ml-2 inline-flex h-8 items-center gap-1.5 rounded bg-blue-600 px-2.5 font-medium text-white hover:bg-blue-700 disabled:opacity-60">{syncing ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}{syncing ? syncMessage || '同步中' : 'AI 同步'}</button>
        </div>
      </div>
      <div className="min-w-[940px] overflow-hidden rounded-md border border-slate-200 bg-white">
        <div className="grid grid-cols-[260px_minmax(680px,1fr)]">
          <div className="border-r border-slate-200" style={{ height: canvasHeight }}>
            <div className="flex h-11 items-center border-b border-slate-200 bg-slate-50 px-4 text-xs font-semibold text-slate-600">事件与伏笔</div>
            {visibleItems.map((item) => {
              const title = item.title || item.value_text || item.subject_key || '未命名记录';
              const color = categoryColors.get(item.category_id || -1) || '#2563eb';
              return <button key={item.id} type="button" onClick={() => onEdit(item)} className="flex w-full items-center gap-2 border-b border-slate-100 px-3 text-left hover:bg-blue-50/50" style={{ height: rowHeight }}><span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: color }} /><span className="min-w-0 flex-1"><span className="block truncate text-xs font-medium text-slate-700">{title}</span><span className="block truncate text-[10px] text-slate-400">{chapterLabel(item, kind)}</span></span><Pencil size={12} className="shrink-0 text-slate-300" /></button>;
            })}
          </div>
          <div role="application" aria-label="可缩放拖拽的共享章节时间轴" className="relative cursor-grab select-none overflow-hidden active:cursor-grabbing" style={{ height: canvasHeight }} onPointerDown={handlePointerDown} onPointerMove={handlePointerMove} onPointerUp={() => { dragRef.current = null; }} onPointerCancel={() => { dragRef.current = null; }} onWheel={handleWheel}>
            <div className="absolute inset-x-0 top-0 h-11 border-b border-slate-200 bg-slate-50" />
            {ticks.map((chapter) => <div key={chapter} className="absolute top-0 border-l border-slate-200" style={{ left: `${chapterPosition(chapter, viewDomain)}%`, height: canvasHeight }}><span className="absolute left-1 top-3 whitespace-nowrap text-[10px] text-slate-400">第 {chapter} 章</span></div>)}
            {visibleItems.map((item, index) => <SharedTimelineItem key={item.id} kind={kind} item={item} color={categoryColors.get(item.category_id || -1) || '#2563eb'} domain={viewDomain} top={axisHeight + index * rowHeight} height={rowHeight} onEdit={onEdit} />)}
          </div>
        </div>
      </div>
    </div>
  );
}

function SharedTimelineItem({ kind, item, color, domain, top, height, onEdit }: { kind: 'fact' | 'plot_thread'; item: StoryKnowledgeItem; color: string; domain: TimelineDomain; top: number; height: number; onEdit: (item: StoryKnowledgeItem) => void }) {
  const position = (chapter: number | null | undefined) => chapterPosition(chapter, domain);
  const setup = item.setup_chapter;
  const payoffFrom = item.expected_payoff_from;
  const payoffTo = item.expected_payoff_to;
  const actual = item.actual_payoff_chapter;
  const rowClass = "absolute inset-x-0 border-b border-slate-100";
  const inView = (chapter: number | null | undefined) => chapter != null && chapter >= domain.start && chapter <= domain.end;
  if (kind === 'fact') {
    const start = item.valid_from_chapter;
    const end = item.valid_to_chapter;
    const overlapsView = (start == null || start <= domain.end) && (end == null || end >= domain.start);
    return <div className={rowClass} style={{ top, height }}>{start == null && end == null ? <button type="button" onClick={() => onEdit(item)} className="absolute left-2 top-1/2 -translate-y-1/2 text-[10px] text-slate-400">未设置有效期</button> : overlapsView ? <button type="button" onClick={() => onEdit(item)} className="absolute top-1/2 h-5 -translate-y-1/2 rounded opacity-85 hover:opacity-100" style={{ left: `${Math.max(0, position(start ?? domain.start))}%`, width: `${Math.max(1, Math.min(100, position(end ?? domain.end)) - Math.max(0, position(start ?? domain.start)))}%`, backgroundColor: color }} title={chapterLabel(item, kind)} /> : null}</div>;
  }
  const target = actual ?? payoffTo ?? payoffFrom;
  const invalid = setup != null && target != null && setup > target;
  const progressionVisible = setup != null && target != null && Math.max(setup, target) >= domain.start && Math.min(setup, target) <= domain.end;
  const payoffStart = payoffFrom ?? payoffTo;
  const payoffEnd = payoffTo ?? payoffFrom;
  const payoffVisible = payoffStart != null && payoffEnd != null && Math.max(payoffStart, payoffEnd) >= domain.start && Math.min(payoffStart, payoffEnd) <= domain.end;
  return <div className={rowClass} style={{ top, height }}>
    {progressionVisible ? <span className="absolute top-1/2 h-0.5 -translate-y-1/2" style={{ left: `${Math.max(0, Math.min(position(setup), position(target)))}%`, width: `${Math.max(1, Math.min(100, Math.max(position(setup), position(target))) - Math.max(0, Math.min(position(setup), position(target))))}%`, backgroundColor: invalid ? '#ef4444' : color, opacity: 0.45 }} /> : null}
    {payoffVisible ? <button type="button" onClick={() => onEdit(item)} className="absolute top-1/2 h-6 -translate-y-1/2 rounded border border-dashed border-amber-400 bg-amber-50/80" style={{ left: `${Math.max(0, Math.min(position(payoffStart), position(payoffEnd)))}%`, width: `${Math.max(1.5, Math.min(100, Math.max(position(payoffStart), position(payoffEnd))) - Math.max(0, Math.min(position(payoffStart), position(payoffEnd))))}%` }} title="编辑计划回收窗口" /> : null}
    {inView(setup) ? <button type="button" onClick={() => onEdit(item)} className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow" style={{ left: `${position(setup)}%`, backgroundColor: color }} title={`第 ${setup} 章埋设`} /> : null}
    {inView(actual) ? <button type="button" onClick={() => onEdit(item)} className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-emerald-500 shadow" style={{ left: `${position(actual)}%` }} title={`第 ${actual} 章回收`} /> : null}
  </div>;
}

function TimelineEmpty({ kind, onSync, syncing, syncMessage }: { kind: 'fact' | 'plot_thread'; onSync: () => void; syncing: boolean; syncMessage: string }) {
  return <div className="flex min-h-0 flex-1 flex-col items-center justify-center p-8 text-center"><Route size={30} className="text-slate-300" /><p className="mt-3 text-sm font-medium text-slate-600">暂无章节时间轴</p><p className="mt-1 max-w-md text-xs text-slate-400">{kind === 'fact' ? '可以手动新增事实，或让 AI 从作品圣经、大纲和已写章节中定向补充。' : '可以手动新增伏笔，或让 AI 识别已有线索、埋设章节和回收状态。'}</p><button type="button" onClick={onSync} disabled={syncing} className="mt-4 inline-flex h-9 items-center gap-2 rounded bg-blue-600 px-4 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-60">{syncing ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}{syncing ? syncMessage || '正在同步' : 'AI 同步作品信息'}</button></div>;
}

function buildVisibleTicks(domain: TimelineDomain): number[] {
  const span = Math.max(1, domain.end - domain.start);
  const rawStep = Math.max(1, Math.ceil(span / 8));
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalized = rawStep / magnitude;
  const step = (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10) * magnitude;
  const first = Math.max(1, Math.ceil(domain.start / step) * step);
  const ticks: number[] = [];
  for (let chapter = first; chapter <= domain.end; chapter += step) ticks.push(chapter);
  return ticks;
}

function Legend({ color, label }: { color: string; label: string }) {
  return <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />{label}</span>;
}

function chapterLabel(item: StoryKnowledgeItem, kind: 'fact' | 'plot_thread'): string {
  if (kind === 'fact') {
    if (item.valid_from_chapter && item.valid_to_chapter) return `第 ${item.valid_from_chapter}-${item.valid_to_chapter} 章有效`;
    if (item.valid_from_chapter) return `第 ${item.valid_from_chapter} 章起有效`;
    if (item.valid_to_chapter) return `截至第 ${item.valid_to_chapter} 章`;
    return '未设置有效期';
  }
  const parts = [
    item.setup_chapter ? `第 ${item.setup_chapter} 章埋设` : '未填写埋设章节',
    item.actual_payoff_chapter ? `第 ${item.actual_payoff_chapter} 章回收` : item.expected_payoff_from || item.expected_payoff_to ? `计划第 ${item.expected_payoff_from || '?'}-${item.expected_payoff_to || '?'} 章回收` : '',
  ].filter(Boolean);
  const payoffTarget = item.actual_payoff_chapter ?? item.expected_payoff_to ?? item.expected_payoff_from;
  if (item.setup_chapter != null && payoffTarget != null && item.setup_chapter > payoffTarget) parts.push('埋设晚于回收');
  return parts.join(' · ');
}

function truncate(value: string, length: number): string {
  return value.length > length ? `${value.slice(0, length)}...` : value;
}

function earliestChapter(item: StoryKnowledgeItem, kind: 'fact' | 'plot_thread'): number {
  const chapters = timelineChapterValues(item, kind);
  return chapters.length > 0 ? Math.min(...chapters) : Number.MAX_SAFE_INTEGER;
}
