import type { StoryKnowledgeItem, StoryKnowledgeKind } from '../api';

export type TimelineDomain = {
  start: number;
  end: number;
  ticks: number[];
};

export type EntityGraphNode = {
  id: string;
  itemId: number;
  key: string;
  name: string;
  type: string;
  kind: 'entity' | 'plot_thread';
  x: number;
  y: number;
  item: StoryKnowledgeItem;
};

export type EntityGraphEdge = {
  id: string;
  from: EntityGraphNode;
  to: EntityGraphNode;
  label: string;
  kind: 'fact' | 'plot_thread';
  directed: boolean;
  item: StoryKnowledgeItem;
};

export type EntityGraph = {
  nodes: EntityGraphNode[];
  edges: EntityGraphEdge[];
  width: number;
  height: number;
  hiddenCount: number;
  hiddenThreadCount: number;
};

export type GraphPoint = {
  x: number;
  y: number;
};

export type EntityGraphLayoutCache = {
  version: 1;
  nodes: Record<string, GraphPoint>;
};

export type RelationshipFactDraft = {
  subjectKey: string;
  predicate: string;
  objectKey: string;
  description?: string;
};

const ENTITY_TYPE_ORDER = ['character', 'faction', 'location', 'item', 'concept', 'other'];
const PLOT_THREAD_LIMIT = 20;
export const ENTITY_CARD_WIDTH = 176;
export const ENTITY_CARD_HEIGHT = 56;
const LAYOUT_CACHE_VERSION = 1;

export function timelineChapterValues(item: StoryKnowledgeItem, kind: StoryKnowledgeKind): number[] {
  const values = kind === 'plot_thread'
    ? [item.setup_chapter, item.expected_payoff_from, item.expected_payoff_to, item.actual_payoff_chapter]
    : [item.valid_from_chapter, item.valid_to_chapter];
  return values.filter((value): value is number => typeof value === 'number' && Number.isFinite(value) && value > 0);
}

export function buildTimelineDomain(items: StoryKnowledgeItem[], kind: StoryKnowledgeKind): TimelineDomain {
  const chapters = items.flatMap((item) => timelineChapterValues(item, kind));
  const highest = chapters.length > 0 ? Math.max(...chapters) : 12;
  const end = Math.max(12, Math.ceil(highest / 5) * 5);
  const desiredTicks = 8;
  const rawStep = Math.max(1, Math.ceil(end / desiredTicks));
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalized = rawStep / magnitude;
  const step = (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10) * magnitude;
  const ticks: number[] = [1];
  for (let chapter = step; chapter < end; chapter += step) ticks.push(chapter);
  if (ticks[ticks.length - 1] !== end) ticks.push(end);
  return { start: 1, end, ticks };
}

export function chapterPosition(chapter: number | null | undefined, domain: TimelineDomain): number {
  if (chapter == null || !Number.isFinite(chapter)) return 0;
  const clamped = Math.min(domain.end, Math.max(domain.start, chapter));
  if (domain.end === domain.start) return 0;
  return ((clamped - domain.start) / (domain.end - domain.start)) * 100;
}

export function entityGraphLayoutStorageKey(storyId: number, kind: 'entity' | 'fact' | 'plot_thread'): string {
  return `storycanvas:knowledge-graph-layout:v1:${storyId}:${kind}`;
}

export function clampGraphPoint(point: GraphPoint, width: number, height: number): GraphPoint {
  const halfWidth = ENTITY_CARD_WIDTH / 2;
  const halfHeight = ENTITY_CARD_HEIGHT / 2;
  return {
    x: Math.min(Math.max(halfWidth, point.x), Math.max(halfWidth, width - halfWidth)),
    y: Math.min(Math.max(halfHeight, point.y), Math.max(halfHeight, height - halfHeight)),
  };
}

export function parseEntityGraphLayoutCache(raw: string | null | undefined, width: number, height: number): EntityGraphLayoutCache {
  if (!raw) return { version: LAYOUT_CACHE_VERSION, nodes: {} };
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== 'object') return { version: LAYOUT_CACHE_VERSION, nodes: {} };
    const version = (parsed as { v?: unknown; version?: unknown }).v ?? (parsed as { version?: unknown }).version;
    const rawNodes = (parsed as { n?: unknown; nodes?: unknown }).n ?? (parsed as { nodes?: unknown }).nodes;
    if (version !== LAYOUT_CACHE_VERSION || !rawNodes || typeof rawNodes !== 'object') {
      return { version: LAYOUT_CACHE_VERSION, nodes: {} };
    }
    const nodes: Record<string, GraphPoint> = {};
    for (const [key, value] of Object.entries(rawNodes as Record<string, unknown>)) {
      const point = Array.isArray(value)
        ? { x: Number(value[0]), y: Number(value[1]) }
        : value && typeof value === 'object'
          ? { x: Number((value as { x?: unknown }).x), y: Number((value as { y?: unknown }).y) }
          : null;
      if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)) continue;
      nodes[key] = clampGraphPoint(point, width, height);
    }
    return { version: LAYOUT_CACHE_VERSION, nodes };
  } catch {
    return { version: LAYOUT_CACHE_VERSION, nodes: {} };
  }
}

export function stringifyEntityGraphLayoutCache(cache: EntityGraphLayoutCache): string {
  const compactNodes: Record<string, [number, number]> = {};
  for (const [key, point] of Object.entries(cache.nodes)) {
    compactNodes[key] = [Math.round(point.x), Math.round(point.y)];
  }
  return JSON.stringify({ v: LAYOUT_CACHE_VERSION, n: compactNodes });
}

export function mergeEntityGraphLayoutCache(cache: EntityGraphLayoutCache, updates: Record<string, GraphPoint>): EntityGraphLayoutCache {
  return { version: LAYOUT_CACHE_VERSION, nodes: { ...cache.nodes, ...updates } };
}

export function canCreateRelationship(source: EntityGraphNode | null | undefined, target: EntityGraphNode | null | undefined): boolean {
  return Boolean(source && target && source.kind === 'entity' && target.kind === 'entity' && source.id !== target.id);
}

export function buildRelationshipFactPayload(draft: RelationshipFactDraft) {
  const predicate = draft.predicate.trim();
  const description = (draft.description || '').trim();
  const valueText = description || `${draft.subjectKey} ${predicate} ${draft.objectKey}`;
  return {
    subject_key: draft.subjectKey,
    predicate,
    object_key: draft.objectKey,
    value_text: valueText,
    status: 'active',
  };
}

export function buildEntityGraph(
  entities: StoryKnowledgeItem[],
  facts: StoryKnowledgeItem[],
  plotThreads: StoryKnowledgeItem[],
  limit = 30,
): EntityGraph {
  const ordered = entities
    .slice()
    .sort((a, b) => (b.importance || 0) - (a.importance || 0) || String(a.canonical_name || '').localeCompare(String(b.canonical_name || ''), 'zh-CN'));
  const visible = ordered.slice(0, limit);
  const grouped = new Map<string, StoryKnowledgeItem[]>();
  for (const item of visible) {
    const rawType = item.entity_type || 'other';
    const type = ENTITY_TYPE_ORDER.includes(rawType) ? rawType : 'other';
    grouped.set(type, [...(grouped.get(type) || []), item]);
  }
  const groupKeys = ENTITY_TYPE_ORDER.filter((type) => grouped.has(type));
  const width = Math.max(900, groupKeys.length * 190 + 100);
  const maxRows = Math.max(1, ...groupKeys.map((type) => grouped.get(type)?.length || 0));
  const visiblePlotThreads = plotThreads
    .slice()
    .sort((a, b) => (b.priority || 0) - (a.priority || 0) || a.id - b.id)
    .slice(0, PLOT_THREAD_LIMIT);
  const plotRows = Math.ceil(visiblePlotThreads.length / 3);
  const height = Math.max(430, maxRows * 76 + 110, 430 + plotRows * 58);
  const nodes: EntityGraphNode[] = [];
  groupKeys.forEach((type, groupIndex) => {
    const groupItems = grouped.get(type) || [];
    const x = groupKeys.length === 1 ? width / 2 : 90 + groupIndex * ((width - 180) / (groupKeys.length - 1));
    groupItems.forEach((item, itemIndex) => {
      const y = 78 + itemIndex * 76;
      nodes.push({
        id: `entity:${item.id}`,
        itemId: item.id,
        key: item.entity_key || `entity:${item.id}`,
        name: item.canonical_name || item.title || '未命名对象',
        type,
        kind: 'entity',
        x,
        y,
        item,
      });
    });
  });

  const entityNodes = nodes.filter((node) => node.kind === 'entity');
  const lookup = buildEntityLookup(entityNodes);
  const edges: EntityGraphEdge[] = [];
  const edgeKeys = new Set<string>();
  for (const fact of facts) {
    const from = findEntityNode(lookup, fact.subject_key);
    const to = findEntityNode(lookup, fact.object_key || (typeof fact.value_json === 'string' ? fact.value_json : null));
    pushEdge(edges, edgeKeys, from, to, fact.predicate || fact.category_name || '关联', 'fact', `fact:${fact.id}`, fact);
  }
  const threadBaseY = height - 48;
  visiblePlotThreads.forEach((thread, threadIndex) => {
    const related = (thread.related_entity_keys || [])
      .map((key) => findEntityNode(lookup, key))
      .filter((node): node is EntityGraphNode => Boolean(node));
    const averageX = related.length > 0 ? related.reduce((total, node) => total + node.x, 0) / related.length : width / 2;
    const threadNode: EntityGraphNode = {
      id: `thread:${thread.id}`,
      itemId: thread.id,
      key: thread.thread_key || `thread:${thread.id}`,
      name: thread.title || '未命名剧情线',
      type: 'plot_thread',
      kind: 'plot_thread',
      x: Math.min(width - 90, Math.max(90, averageX + ((threadIndex % 3) - 1) * 28)),
      y: threadBaseY - Math.floor(threadIndex / 3) * 58,
      item: thread,
    };
    nodes.push(threadNode);
    for (const node of related) {
      pushEdge(edges, edgeKeys, threadNode, node, threadNode.name, 'plot_thread', `thread:${thread.id}:${node.id}`, thread);
    }
  });
  return {
    nodes,
    edges,
    width,
    height,
    hiddenCount: Math.max(0, entities.length - visible.length),
    hiddenThreadCount: Math.max(0, plotThreads.length - visiblePlotThreads.length),
  };
}

type EntityLookup = {
  keys: Map<string, EntityGraphNode>;
  names: Map<string, EntityGraphNode | null>;
};

function buildEntityLookup(nodes: EntityGraphNode[]): EntityLookup {
  const keys = new Map<string, EntityGraphNode>();
  const names = new Map<string, EntityGraphNode | null>();
  for (const node of nodes) {
    const stableKey = normalizeStableKey(node.key);
    if (stableKey) keys.set(stableKey, node);
    for (const alias of [node.name, ...(node.item.aliases_json || [])]) {
      const normalized = normalizeKey(alias);
      if (!normalized) continue;
      const existing = names.get(normalized);
      names.set(normalized, existing && existing.id !== node.id ? null : node);
    }
  }
  return { keys, names };
}

function findEntityNode(lookup: EntityLookup, value?: string | null): EntityGraphNode | undefined {
  const stableKey = normalizeStableKey(value);
  if (!stableKey) return undefined;
  return lookup.keys.get(stableKey) || lookup.names.get(normalizeKey(value)) || undefined;
}

function pushEdge(
  edges: EntityGraphEdge[],
  edgeKeys: Set<string>,
  from: EntityGraphNode | undefined,
  to: EntityGraphNode | undefined,
  label: string,
  kind: EntityGraphEdge['kind'],
  id: string,
  item: StoryKnowledgeItem,
) {
  if (!from || !to || from.id === to.id) return;
  const key = [from.id, to.id, kind, label].join(':');
  if (edgeKeys.has(key)) return;
  edgeKeys.add(key);
  edges.push({ id, from, to, label, kind, directed: kind === 'fact', item });
}

function normalizeStableKey(value?: string | null): string {
  return String(value || '').trim().toLocaleLowerCase();
}

function normalizeKey(value?: string | null): string {
  return String(value || '').trim().toLocaleLowerCase().replace(/[\s:_-]+/g, '');
}
