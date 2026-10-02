import type { CanvasSceneNode } from './CanvasEditorSurface';
import { nodeSize } from './useCanvasInteractions';

/**
 * 节点组（container 类型）纯函数层：
 * - 组框是包住成员的 Frame，位置/尺寸一律由成员推导（refit），不可独立编辑。
 * - 成员关系来源优先级：config.member_ids（新）→ config.tabs（旧文件夹式）→ 成员边。
 * - 成员边（成员→组框，targetHandle='items'）是后端运行时的事实源，仅供渲染隐藏与展开解析。
 * 全部函数保持纯函数、幂等，便于测试。
 */

export interface GroupEdge {
  id?: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
  data?: Record<string, unknown>;
}

/** 组框左右内边距 */
export const GROUP_PADDING_X = 32;
/** 组框顶部内边距（容纳标题栏） */
export const GROUP_PADDING_TOP = 48;
/** 组框底部内边距 */
export const GROUP_PADDING_BOTTOM = 32;

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === 'string' && item.length > 0);
}

function nodeConfig(node: CanvasSceneNode): Record<string, unknown> {
  return (node.data?.config || {}) as Record<string, unknown>;
}

/** 旧文件夹式 config.tabs[].nodes 拍平 */
function legacyTabIds(config: Record<string, unknown>): string[] {
  const tabs = config.tabs;
  if (!Array.isArray(tabs)) return [];
  const ids: string[] = [];
  for (const tab of tabs) {
    if (tab && typeof tab === 'object') ids.push(...asStringList((tab as Record<string, unknown>).nodes));
  }
  return ids;
}

/**
 * 解析组框成员（有序、去重、剔除不存在的节点与自身）。
 * 优先 member_ids，其次旧 tabs，最后回退到成员边。
 */
export function getContainerMemberIds(
  nodes: CanvasSceneNode[],
  edges: GroupEdge[],
  containerId: string,
): string[] {
  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const container = nodeMap.get(containerId);
  if (!container || container.type !== 'container') return [];

  const config = nodeConfig(container);
  let candidates = asStringList(config.member_ids);
  if (!candidates.length) candidates = legacyTabIds(config);
  if (!candidates.length) {
    candidates = edges
      .filter((edge) => edge.target === containerId && edge.targetHandle === 'items')
      .map((edge) => edge.source);
  }

  const seen = new Set<string>();
  const result: string[] = [];
  for (const id of candidates) {
    if (id === containerId || seen.has(id)) continue;
    if (!nodeMap.has(id)) continue;
    seen.add(id);
    result.push(id);
  }
  return result;
}

/** 子节点 → 所属组框（首个命中），用于深度计算与渲染排序 */
export function getContainerParentMap(nodes: CanvasSceneNode[], edges: GroupEdge[]): Map<string, string> {
  const parentOf = new Map<string, string>();
  for (const node of nodes) {
    if (node.type !== 'container') continue;
    for (const memberId of getContainerMemberIds(nodes, edges, node.id)) {
      if (!parentOf.has(memberId)) parentOf.set(memberId, node.id);
    }
  }
  return parentOf;
}

/** 组框嵌套深度（最外层 0）；成环时按 0 处理 */
export function getContainerDepth(nodeId: string, parentOf: Map<string, string>): number {
  let depth = 0;
  const visited = new Set<string>([nodeId]);
  let current = parentOf.get(nodeId);
  while (current && !visited.has(current) && depth < 32) {
    visited.add(current);
    depth += 1;
    current = parentOf.get(current);
  }
  return depth;
}

export interface GroupBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** 成员并集 bbox + 内边距 = 组框几何；无成员返回 null */
export function computeGroupBounds(memberNodes: CanvasSceneNode[]): GroupBounds | null {
  if (!memberNodes.length) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const node of memberNodes) {
    const size = nodeSize(node);
    minX = Math.min(minX, node.position.x);
    minY = Math.min(minY, node.position.y);
    maxX = Math.max(maxX, node.position.x + size.width);
    maxY = Math.max(maxY, node.position.y + size.height);
  }
  return {
    x: minX - GROUP_PADDING_X,
    y: minY - GROUP_PADDING_TOP,
    width: maxX - minX + GROUP_PADDING_X * 2,
    height: maxY - minY + GROUP_PADDING_TOP + GROUP_PADDING_BOTTOM,
  };
}

function boundsMatch(node: CanvasSceneNode, bounds: GroupBounds): boolean {
  const size = nodeSize(node);
  return (
    node.position.x === bounds.x
    && node.position.y === bounds.y
    && size.width === bounds.width
    && size.height === bounds.height
  );
}

/**
 * 按嵌套深度由内到外重算所有组框几何（内层先算，外层才能包住已更新的内层框）。
 * 幂等：几何一致时不产生新数组。同时剔除 member_ids 里已删除的节点。
 */
export function refitContainerBounds(
  nodes: CanvasSceneNode[],
  edges: GroupEdge[],
): { nodes: CanvasSceneNode[]; changed: boolean; pruned: boolean } {
  const containers = nodes.filter((node) => node.type === 'container');
  if (!containers.length) return { nodes, changed: false, pruned: false };

  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const parentOf = getContainerParentMap(nodes, edges);
  const ordered = [...containers].sort(
    (a, b) => getContainerDepth(b.id, parentOf) - getContainerDepth(a.id, parentOf),
  );

  let working = nodes;
  let changed = false;
  let pruned = false;

  for (const container of ordered) {
    const current = working.find((node) => node.id === container.id);
    if (!current) continue;
    const config = nodeConfig(current);

    let nextConfig = config;
    if (Array.isArray(config.member_ids)) {
      const validIds = asStringList(config.member_ids).filter((id) => nodeMap.has(id) && id !== current.id);
      const original = asStringList(config.member_ids);
      if (validIds.length !== original.length) {
        nextConfig = { ...nextConfig, member_ids: validIds };
        pruned = true;
      }
    }

    const memberIds = getContainerMemberIds(
      working.map((node) => (node.id === current.id ? { ...node, data: { ...node.data, config: nextConfig } } : node)),
      edges,
      current.id,
    );
    const memberNodes = memberIds
      .map((id) => working.find((node) => node.id === id))
      .filter((node): node is CanvasSceneNode => Boolean(node));
    const bounds = computeGroupBounds(memberNodes);
    if (!bounds) {
      if (nextConfig !== config) {
        working = working.map((node) => (node.id === current.id
          ? { ...node, data: { ...node.data, config: nextConfig } }
          : node));
        changed = true;
      }
      continue;
    }

    const geometryOk = boundsMatch({ ...current, data: { ...current.data, config: nextConfig } }, bounds);
    if (geometryOk && nextConfig === config) continue;

    working = working.map((node) => {
      if (node.id !== current.id) return node;
      return {
        ...node,
        position: { x: bounds.x, y: bounds.y },
        data: {
          ...node.data,
          config: nextConfig,
          ui: { ...(node.data?.ui || {}), width: bounds.width, height: bounds.height },
        },
      };
    });
    changed = true;
  }

  return { nodes: working, changed, pruned };
}

/**
 * 拖拽闭包：被拖节点是组框时，把其成员（含嵌套）并入移动集合，按 id 去重，
 * 保证同一个节点的 delta 只应用一次。
 */
export function expandGroupMove(
  nodeIds: string[],
  nodes: CanvasSceneNode[],
  edges: GroupEdge[],
): string[] {
  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const result: string[] = [];
  const seen = new Set<string>();
  const queue = [...nodeIds];
  while (queue.length) {
    const id = queue.shift() as string;
    if (seen.has(id)) continue;
    seen.add(id);
    result.push(id);
    const node = nodeMap.get(id);
    if (node?.type === 'container') {
      for (const memberId of getContainerMemberIds(nodes, edges, id)) {
        if (!seen.has(memberId)) queue.push(memberId);
      }
    }
  }
  return result;
}

/** 渲染排序：组框按深度外→内排最前，普通节点保持原相对顺序 */
export function orderNodesForRender(nodes: CanvasSceneNode[], edges: GroupEdge[]): CanvasSceneNode[] {
  if (!nodes.some((node) => node.type === 'container')) return nodes;
  const parentOf = getContainerParentMap(nodes, edges);
  return [...nodes]
    .map((node, index) => ({ node, index }))
    .sort((a, b) => {
      const rankA = a.node.type === 'container' ? getContainerDepth(a.node.id, parentOf) : Number.MAX_SAFE_INTEGER;
      const rankB = b.node.type === 'container' ? getContainerDepth(b.node.id, parentOf) : Number.MAX_SAFE_INTEGER;
      return rankA !== rankB ? rankA - rankB : a.index - b.index;
    })
    .map((entry) => entry.node);
}

/** 是否为“框内成员边”（不绘制）：打了 member 标记，或 source 在组框成员名单内 */
export function isMembershipEdge(edge: GroupEdge, nodes: CanvasSceneNode[]): boolean {
  if (edge.targetHandle !== 'items') return false;
  const target = nodes.find((node) => node.id === edge.target);
  if (!target || target.type !== 'container') return false;
  if (edge.data?.member) return true;
  const config = nodeConfig(target);
  const listed = new Set([...asStringList(config.member_ids), ...legacyTabIds(config)]);
  return listed.has(edge.source);
}

/**
 * 复制/粘贴副本剥离成员关系（成员仍指向原节点会导致双倍移动）。
 * 在调用方完成 id 重映射后再决定保留或清空。
 */
export function stripContainerMembership(node: CanvasSceneNode): CanvasSceneNode {
  if (node.type !== 'container') return node;
  const config = nodeConfig(node);
  return {
    ...node,
    data: {
      ...node.data,
      config: { ...config, member_ids: [], tabs: [] },
    },
  };
}

/** 把副本的 member_ids 经 idMap 重映射；映射不到的成员直接丢弃 */
export function remapContainerMembership(
  node: CanvasSceneNode,
  idMap: Map<string, string>,
): CanvasSceneNode {
  if (node.type !== 'container') return node;
  const config = nodeConfig(node);
  const sourceIds = asStringList(config.member_ids).length
    ? asStringList(config.member_ids)
    : legacyTabIds(config);
  const remapped = sourceIds
    .map((id) => idMap.get(id))
    .filter((id): id is string => Boolean(id));
  return {
    ...node,
    data: {
      ...node.data,
      config: { ...config, member_ids: remapped, tabs: [] },
    },
  };
}
