/**
 * 画布「自动整理」的排版算法（纯函数）。
 *
 * 流程节点（剧本 → 场景审核 → 分镜图 → 视频 → 合片）按连线分层，自左向右一层一列；
 * 资产节点不参与分层，按类型分成三栏，插在场景审核和分镜之间：【角色】一列、【道具】一列、【场景】一列。
 * 之前资产没有上游连线，全被分到第 0 层，和剧本节点叠成一列，角色 / 道具 / 场景还混在一起。
 */

export const ASSET_KIND_ORDER = ['character', 'prop', 'scene'] as const;
export type AssetColumnKind = (typeof ASSET_KIND_ORDER)[number];

export interface LayoutNode {
  id: string;
  type: string;
  width: number;
  height: number;
  /** 当前位置，用来保持同层 / 同栏内的相对上下顺序 */
  x: number;
  y: number;
  /** 图片节点的资产类型（character / prop / scene），其他节点为空 */
  assetRole?: string;
}

export interface LayoutEdge { source: string; target: string }

const FLOW_COLUMN_GAP = 120;
const ASSET_COLUMN_GAP = 100;
const ROW_GAP = 60;
const ORIGIN = 120;

export function isAssetLayoutNode(node: LayoutNode): boolean {
  return node.type === 'image' && (ASSET_KIND_ORDER as readonly string[]).includes(String(node.assetRole || ''));
}

export function computeAutoLayout(nodes: LayoutNode[], edges: LayoutEdge[]): Map<string, { x: number; y: number }> {
  const assets = nodes.filter(isAssetLayoutNode);
  const flow = nodes.filter((node) => !isAssetLayoutNode(node));
  const ids = new Set(flow.map((node) => node.id));
  const incoming = new Map(flow.map((node) => [node.id, 0]));
  const children = new Map(flow.map((node) => [node.id, [] as string[]]));
  for (const edge of edges) {
    if (!ids.has(edge.source) || !ids.has(edge.target)) continue;
    children.get(edge.source)?.push(edge.target);
    incoming.set(edge.target, (incoming.get(edge.target) || 0) + 1);
  }
  const layers = new Map<string, number>();
  const queue = flow.filter((node) => (incoming.get(node.id) || 0) === 0).map((node) => node.id);
  for (const id of queue) layers.set(id, 0);
  for (let cursor = 0; cursor < queue.length; cursor += 1) {
    const id = queue[cursor];
    const layer = layers.get(id) || 0;
    for (const childId of children.get(id) || []) {
      layers.set(childId, Math.max(layers.get(childId) || 0, layer + 1));
      const remaining = (incoming.get(childId) || 1) - 1;
      incoming.set(childId, remaining);
      if (remaining === 0) queue.push(childId);
    }
  }
  for (const node of flow) if (!layers.has(node.id)) layers.set(node.id, 0);

  const byLayer = new Map<number, LayoutNode[]>();
  for (const node of flow) {
    const layer = layers.get(node.id) || 0;
    byLayer.set(layer, [...(byLayer.get(layer) || []), node]);
  }
  // 资产三栏插在场景审核那一层之后；没有场景节点就插在第一层之后
  const sceneLayers = flow.filter((node) => node.type === 'scene').map((node) => layers.get(node.id) || 0);
  const assetsAfter = sceneLayers.length ? Math.max(...sceneLayers) : 0;

  const positions = new Map<string, { x: number; y: number }>();
  let x = ORIGIN;
  let assetsPlaced = assets.length === 0;
  const placeAssets = () => {
    for (const kind of ASSET_KIND_ORDER) {
      const group = assets.filter((node) => node.assetRole === kind).sort((a, b) => a.y - b.y || a.x - b.x);
      if (!group.length) continue;
      let y = ORIGIN;
      for (const node of group) { positions.set(node.id, { x, y }); y += node.height + ROW_GAP; }
      x += Math.max(...group.map((node) => node.width)) + ASSET_COLUMN_GAP;
    }
    x += FLOW_COLUMN_GAP - ASSET_COLUMN_GAP;
    assetsPlaced = true;
  };
  for (const [layer, column] of [...byLayer.entries()].sort(([a], [b]) => a - b)) {
    let y = ORIGIN;
    for (const node of [...column].sort((a, b) => a.y - b.y)) { positions.set(node.id, { x, y }); y += node.height + ROW_GAP; }
    x += Math.max(...column.map((node) => node.width)) + FLOW_COLUMN_GAP;
    if (!assetsPlaced && layer >= assetsAfter) placeAssets();
  }
  if (!assetsPlaced) placeAssets();
  return positions;
}
