/**
 * 画布图的三方合并：基准版本（上次与服务端同步的图）、本地图（含未保存的修改）、服务端最新图（后台编排 / 助手 / 其他窗口写入的）。
 *
 * 为什么需要：后台编排期间本地如果有未保存的修改，前端不会用服务端结果覆盖本地；编排结束后保存撞上版本冲突时，
 * 如果直接拿本地图去覆盖服务端，后台刚生成的资产、镜头等新内容会被本地的旧内容整个冲掉（曾经因此丢过一整批资产）。
 * 三方合并的原则：谁改了就留谁的，两边都改了同一处，以服务端为准并明确告诉用户。
 */

import type { VideoCanvasGraph } from '../../api';

type AnyRecord = Record<string, unknown>;

/** 键顺序无关的稳定序列化，用来判断两个值是否相等。 */
export function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`;
  if (value && typeof value === 'object') {
    const record = value as AnyRecord;
    return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`).join(',')}}`;
  }
  return JSON.stringify(value) ?? 'null';
}

const same = (a: unknown, b: unknown) => stableStringify(a) === stableStringify(b);

/** 字典按键三方合并：本地改了服务端没改取本地；服务端改了本地没改取服务端；都改且不同取服务端并记冲突。 */
function mergeRecord(base: AnyRecord, local: AnyRecord, server: AnyRecord, label: string, conflicts: string[]): AnyRecord {
  const result: AnyRecord = {};
  for (const key of new Set([...Object.keys(base), ...Object.keys(local), ...Object.keys(server)])) {
    const b = base[key];
    const l = local[key];
    const s = server[key];
    let chosen: unknown;
    if (same(l, s)) chosen = l;
    else if (same(l, b)) chosen = s;
    else if (same(s, b)) chosen = l;
    else { chosen = s; conflicts.push(`${label}·${key}`); }
    if (chosen !== undefined) result[key] = chosen;
  }
  return result;
}

type GraphNode = VideoCanvasGraph['nodes'][number];

function mergeNode(base: GraphNode | undefined, local: GraphNode | undefined, server: GraphNode | undefined, conflicts: string[]): GraphNode | undefined {
  if (!base) {
    // 只有一边新增就留下；两边都新增同一个 ID（极少）以服务端为准
    return server ?? local;
  }
  if (!local) {
    // 本地删了：服务端没动就删；服务端改过则保留服务端的（宁可多留，不丢后台的新内容）
    if (!server || same(base, server)) return undefined;
    conflicts.push(`节点已被你删除但后台更新过：${base.id}`);
    return server;
  }
  if (!server) {
    if (same(base, local)) return undefined;
    conflicts.push(`节点已被后台移除但你修改过：${base.id}`);
    return local;
  }
  if (same(local, server)) return server;
  if (same(local, base)) return server;
  if (same(server, base)) return local;
  const label = String((local.data?.config as AnyRecord | undefined)?.asset_name || local.data?.label || local.id);
  const config = mergeRecord((base.data?.config || {}) as AnyRecord, (local.data?.config || {}) as AnyRecord, (server.data?.config || {}) as AnyRecord, label, conflicts);
  // 位置是用户在本地拖的：本地挪过就用本地的
  const position = same(local.position, base.position) ? server.position : local.position;
  return { ...server, position, data: { ...server.data, label: same(local.data?.label, base.data?.label) ? server.data?.label : local.data?.label, config } } as GraphNode;
}

function mergeById<T extends { id: string }>(base: T[], local: T[], server: T[], merge: (b: T | undefined, l: T | undefined, s: T | undefined) => T | undefined): T[] {
  const index = (list: T[]) => new Map(list.map((item) => [item.id, item]));
  const b = index(base);
  const l = index(local);
  const s = index(server);
  const order = [...server.map((item) => item.id), ...local.map((item) => item.id), ...base.map((item) => item.id)];
  const result: T[] = [];
  for (const id of new Set(order)) {
    const merged = merge(b.get(id), l.get(id), s.get(id));
    if (merged) result.push(merged);
  }
  return result;
}

/** 用户在画布顶部 / 开场卡片里直接设置的元数据：始终以本地为准（它们只由界面设置，不由后台改写）。 */
const LOCAL_OWNED_METADATA = ['canvas_style'] as const;
const LOCAL_OWNED_PRODUCTION_KEYS = ['aspect_ratio', 'shot_duration_mode'] as const;

export interface MergeResult {
  graph: VideoCanvasGraph;
  /** 两边都改了同一处、已按服务端为准处理的位置，用来告诉用户 */
  conflicts: string[];
}

export function mergeCanvasGraphs(base: VideoCanvasGraph, local: VideoCanvasGraph, server: VideoCanvasGraph): MergeResult {
  const conflicts: string[] = [];
  const nodes = mergeById(base.nodes || [], local.nodes || [], server.nodes || [], (b, l, s) => mergeNode(b, l, s, conflicts));
  const nodeIds = new Set(nodes.map((node) => node.id));
  const localNodeIds = new Set((local.nodes || []).map((node) => node.id));
  const edges = mergeById(base.edges || [], local.edges || [], server.edges || [], (b, l, s) => {
    if (!b) return s ?? l;
    if (!l) {
      if (!s) return undefined;
      if (!same(b, s)) return s;
      // 本地没有这条线：如果是因为删了它的端点节点而连带消失，而那个节点因为后台改过被保留下来了，线也要保留
      return !localNodeIds.has(s.source) || !localNodeIds.has(s.target) ? s : undefined;
    }
    if (!s) return same(b, l) ? undefined : l;
    return same(l, b) ? s : l;
  }).filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target));

  const metadata = mergeRecord((base.metadata || {}) as AnyRecord, (local.metadata || {}) as AnyRecord, (server.metadata || {}) as AnyRecord, '画布设置', conflicts);
  const localMetadata = (local.metadata || {}) as AnyRecord;
  for (const key of LOCAL_OWNED_METADATA) if (localMetadata[key] !== undefined) metadata[key] = localMetadata[key];
  const localProduction = (localMetadata.production_settings || {}) as AnyRecord;
  const production = { ...((metadata.production_settings || {}) as AnyRecord) };
  for (const key of LOCAL_OWNED_PRODUCTION_KEYS) if (localProduction[key] !== undefined) production[key] = localProduction[key];
  if (Object.keys(production).length) metadata.production_settings = production;
  // 冲突里去掉已经按“本地为准”处理的设置项，免得误报
  const filtered = conflicts.filter((item) => !item.startsWith('画布设置·canvas_style') && !item.startsWith('画布设置·production_settings'));

  return {
    graph: { ...server, nodes, edges, groups: same(local.groups, base.groups) ? server.groups : local.groups, metadata } as VideoCanvasGraph,
    conflicts: filtered,
  };
}
