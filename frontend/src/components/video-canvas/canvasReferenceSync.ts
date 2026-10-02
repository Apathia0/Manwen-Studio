export interface CanvasReferenceAsset {
  id: number;
  revision?: number;
  file_path?: string | null;
  asset_type?: string | null;
}

export interface CanvasReferenceNode {
  id: string;
  type: string;
  data?: {
    config?: Record<string, unknown>;
    result?: Record<string, unknown>;
    [key: string]: unknown;
  };
}

export interface CanvasReferenceEdge {
  id?: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
  data?: Record<string, unknown>;
}

const TARGET_MEDIA_TYPES = new Set(['image', 'image_generation', 'storyboard', 'video', 'video_generation']);
const EDGE_REFERENCE_PROVENANCE = 'edge';
const MANUAL_REFERENCE_PROVENANCE = 'manual';

type ReferenceProvenance = {
  asset_id: number;
  source: typeof EDGE_REFERENCE_PROVENANCE | typeof MANUAL_REFERENCE_PROVENANCE;
  source_node_id?: string;
  source_edge_id?: string;
};

type SourceMedia = { assetId: number; url: string; revision?: number; sourceNodeId: string; sourceEdgeId?: string };

function publicAssetUrl(filePath: unknown): string {
  const raw = String(filePath || '').trim();
  if (!raw) return '';
  if (/^(https?:|\/static\/|data:|blob:)/i.test(raw)) return raw;
  if (raw.startsWith('manga_outputs/')) return `/static/manga/${raw.slice('manga_outputs/'.length)}`;
  if (raw.startsWith('video_outputs/')) return `/static/video/${raw.slice('video_outputs/'.length)}`;
  return raw;
}

function numericAssetId(value: unknown): number | null {
  const id = typeof value === 'number' ? value : Number(value);
  return Number.isInteger(id) && id > 0 ? id : null;
}

function sourceMedia(node: CanvasReferenceNode, assets: CanvasReferenceAsset[], sourceNodeId = node.id, sourceEdgeId?: string): SourceMedia | null {
  const config = node.data?.config || {};
  const result = node.data?.result || {};
  const assetId = numericAssetId(result.asset_id ?? config.asset_id);
  if (assetId == null) return null;
  const asset = assets.find((item) => item.id === assetId);
  const url = publicAssetUrl(result.url ?? result.file_path ?? config.existing_url ?? asset?.file_path);
  if (!url) return null;
  return { assetId, url, sourceNodeId, ...(typeof asset?.revision === 'number' ? { revision: asset.revision } : {}), ...(sourceEdgeId ? { sourceEdgeId } : {}) };
}

function groupMemberIds(container: CanvasReferenceNode, edges: CanvasReferenceEdge[]): string[] {
  const config = container.data?.config || {};
  const configured = Array.isArray(config.member_ids) ? config.member_ids.filter((id): id is string => typeof id === 'string') : [];
  if (configured.length) return configured;
  const tabs = Array.isArray(config.tabs) ? config.tabs : [];
  const fromTabs: string[] = [];
  for (const tab of tabs) {
    if (tab && typeof tab === 'object') {
      const list = (tab as Record<string, unknown>).nodes;
      if (Array.isArray(list)) fromTabs.push(...list.filter((id): id is string => typeof id === 'string'));
    }
  }
  if (fromTabs.length) return fromTabs;
  return edges.filter((edge) => edge.target === container.id && edge.targetHandle === 'items' && !edge.data?.disabled).map((edge) => edge.source);
}

function sourceMediaForEdge(
  source: CanvasReferenceNode,
  assets: CanvasReferenceAsset[],
  edges: CanvasReferenceEdge[],
  nodeMap: Map<string, CanvasReferenceNode>,
  sourceEdgeId?: string,
  visited = new Set<string>(),
): SourceMedia[] {
  if (source.type !== 'container') {
    const media = sourceMedia(source, assets, source.id, sourceEdgeId);
    return media ? [media] : [];
  }
  if (visited.has(source.id)) return [];
  const nextVisited = new Set(visited).add(source.id);
  return groupMemberIds(source, edges).flatMap((memberId) => {
    const member = nodeMap.get(memberId);
    return member ? sourceMediaForEdge(member, assets, edges, nodeMap, sourceEdgeId, nextVisited) : [];
  });
}

export interface CanvasConnectedPreview {
  key: string;
  nodeId: string;
  label: string;
  url: string;
}

const VIDEO_URL_RE = /\.(mp4|mov|webm|mkv|avi|m4v|flv)(\?|#|$)/i;
const IMAGE_URL_RE = /\.(png|jpe?g|webp|gif|avif|bmp|svg)(\?|#|$)/i;
const IMAGE_PREVIEW_TYPES = new Set(['image', 'image_generation', 'storyboard', 'asset']);

export function imagePreviewUrl(node: CanvasReferenceNode): string {
  const result = node.data?.result || {};
  const config = node.data?.config || {};
  const url = publicAssetUrl(result.url ?? result.file_path ?? config.existing_url);
  if (!url || VIDEO_URL_RE.test(url)) return '';
  if (IMAGE_PREVIEW_TYPES.has(node.type)) return url;
  return IMAGE_URL_RE.test(url) ? url : '';
}

export interface CanvasReferenceCandidate {
  nodeId: string;
  label: string;
  url: string;
  group: string;
}

const CANDIDATE_GROUP_ORDER = ['角色', '场景', '道具', '分镜图', '其他图片'];

/**
 * 可以被连成参考图的画布节点：已经有图片结果的节点，按 角色 / 场景 / 道具 / 分镜图 / 其他 分组。
 * 排除自己、已失效节点、已经直接连到目标的节点，以及目标的下游节点（连回去会成环）。
 */
export function collectReferenceCandidates(nodes: CanvasReferenceNode[], edges: CanvasReferenceEdge[], targetId: string): CanvasReferenceCandidate[] {
  const downstream = new Set<string>([targetId]);
  for (let changed = true; changed;) {
    changed = false;
    for (const edge of edges) {
      if (downstream.has(edge.source) && !downstream.has(edge.target)) { downstream.add(edge.target); changed = true; }
    }
  }
  const linked = new Set(edges.filter((edge) => edge.target === targetId).map((edge) => edge.source));
  const result: CanvasReferenceCandidate[] = [];
  for (const node of nodes) {
    if (downstream.has(node.id) || linked.has(node.id) || node.type === 'container') continue;
    const config = node.data?.config || {};
    if (config.stale) continue;
    const url = imagePreviewUrl(node);
    if (!url) continue;
    const role = String(config.asset_role || '');
    const group = role === 'character' ? '角色' : role === 'scene' ? '场景' : role === 'prop' ? '道具' : config.node_role === 'storyboard' ? '分镜图' : '其他图片';
    result.push({ nodeId: node.id, label: String(config.asset_name || node.data?.label || node.type), url, group });
  }
  return result.sort((a, b) => CANDIDATE_GROUP_ORDER.indexOf(a.group) - CANDIDATE_GROUP_ORDER.indexOf(b.group));
}

export function collectConnectedReferencePreviews(nodes: CanvasReferenceNode[], edges: CanvasReferenceEdge[], targetId: string): CanvasConnectedPreview[] {
  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const seen = new Set<string>();
  const previews: CanvasConnectedPreview[] = [];
  const pushLeaf = (node: CanvasReferenceNode) => {
    if (seen.has(node.id)) return;
    const url = imagePreviewUrl(node);
    if (!url) return;
    seen.add(node.id);
    previews.push({ key: `connected:${node.id}`, nodeId: node.id, label: String(node.data?.label || node.type), url });
  };
  const visit = (node: CanvasReferenceNode, visitedContainers: Set<string>) => {
    if (node.type === 'container') {
      if (visitedContainers.has(node.id)) return;
      const nextVisited = new Set(visitedContainers).add(node.id);
      groupMemberIds(node, edges).forEach((memberId) => {
        const member = nodeMap.get(memberId);
        if (member) visit(member, nextVisited);
      });
      return;
    }
    pushLeaf(node);
  };
  for (const edge of edges) {
    if (edge.target !== targetId || edge.data?.disabled) continue;
    const source = nodeMap.get(edge.source);
    if (!source) continue;
    if (source.type === 'container') {
      visit(source, new Set());
      continue;
    }
    if (edge.sourceHandle != null && !['image', 'asset'].includes(edge.sourceHandle)) continue;
    visit(source, new Set());
  }
  return previews;
}

function readProvenance(config: Record<string, unknown>, existingIds: number[]): ReferenceProvenance[] {
  const raw = Array.isArray(config.reference_provenance) ? config.reference_provenance : [];
  const parsed = raw.flatMap((item): ReferenceProvenance[] => {
    if (!item || typeof item !== 'object') return [];
    const record = item as Record<string, unknown>;
    const assetId = numericAssetId(record.asset_id);
    if (assetId == null || !existingIds.includes(assetId)) return [];
    const source = record.source === EDGE_REFERENCE_PROVENANCE ? EDGE_REFERENCE_PROVENANCE : MANUAL_REFERENCE_PROVENANCE;
    return [{ asset_id: assetId, source, ...(typeof record.source_node_id === 'string' ? { source_node_id: record.source_node_id } : {}), ...(typeof record.source_edge_id === 'string' ? { source_edge_id: record.source_edge_id } : {}) }];
  });
  const knownIds = new Set(parsed.map((item) => item.asset_id));
  return [...parsed, ...existingIds.filter((assetId) => !knownIds.has(assetId)).map((asset_id): ReferenceProvenance => ({ asset_id, source: MANUAL_REFERENCE_PROVENANCE }))];
}

function sameJson(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

/** Recompute edge-derived media references while retaining explicitly selected assets. */
export function syncCanvasMediaReferences(nodes: CanvasReferenceNode[], edges: CanvasReferenceEdge[], assets: CanvasReferenceAsset[] = []): CanvasReferenceNode[] {
  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const additions = new Map<string, SourceMedia[]>();
  for (const edge of edges) {
    if (edge.data?.disabled || !TARGET_MEDIA_TYPES.has(nodeMap.get(edge.target)?.type || '') || !['image', 'references'].includes(edge.targetHandle || '')) continue;
    const source = nodeMap.get(edge.source);
    if (!source || (source.type !== 'container' && edge.sourceHandle != null && !['image', 'asset'].includes(edge.sourceHandle))) continue;
    const media = sourceMediaForEdge(source, assets, edges, nodeMap, edge.id);
    const list = additions.get(edge.target) || [];
    media.forEach((item) => { if (!list.some((existing) => existing.assetId === item.assetId && existing.sourceNodeId === item.sourceNodeId)) list.push(item); });
    additions.set(edge.target, list);
  }

  return nodes.map((node) => {
    const config = { ...(node.data?.config || {}) };
    const existingIds = Array.isArray(config.reference_asset_ids) ? config.reference_asset_ids.map(numericAssetId).filter((id): id is number => id != null) : [];
    const validAssetIds = assets.length ? new Set(assets.map((asset) => asset.id)) : null;
    const provenance = readProvenance(config, existingIds).filter((item) => !validAssetIds || validAssetIds.has(item.asset_id));
    const manualIds = provenance.filter((item) => item.source === MANUAL_REFERENCE_PROVENANCE).map((item) => item.asset_id);
    const incoming = additions.get(node.id) || [];
    const nextIds = [...manualIds];
    const nextProvenance: ReferenceProvenance[] = manualIds.map((asset_id) => ({ asset_id, source: MANUAL_REFERENCE_PROVENANCE }));
    const existingPreviews = Array.isArray(config.reference_previews) ? config.reference_previews.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')) : [];
    const manualPreviews = existingPreviews.filter((preview) => preview.source !== EDGE_REFERENCE_PROVENANCE);
    const nextPreviews = [...manualPreviews];
    const existingRevisions = Array.isArray(config.reference_asset_revisions) ? config.reference_asset_revisions.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')) : [];
    const manualRevisions = existingRevisions.filter((revision) => revision.source !== EDGE_REFERENCE_PROVENANCE);
    const nextRevisions = [...manualRevisions];
    incoming.forEach((item) => {
      if (!nextIds.includes(item.assetId)) nextIds.push(item.assetId);
      if (!nextProvenance.some((entry) => entry.asset_id === item.assetId && entry.source === EDGE_REFERENCE_PROVENANCE && entry.source_node_id === item.sourceNodeId)) {
        nextProvenance.push({ asset_id: item.assetId, source: EDGE_REFERENCE_PROVENANCE, source_node_id: item.sourceNodeId, ...(item.sourceEdgeId ? { source_edge_id: item.sourceEdgeId } : {}) });
      }
      if (!nextPreviews.some((preview) => numericAssetId(preview.asset_id) === item.assetId && preview.source !== EDGE_REFERENCE_PROVENANCE)) {
        nextPreviews.push({ asset_id: item.assetId, url: item.url, kind: 'image', source: EDGE_REFERENCE_PROVENANCE, source_node_id: item.sourceNodeId, ...(item.sourceEdgeId ? { source_edge_id: item.sourceEdgeId } : {}) });
      }
      if (item.revision != null && !nextRevisions.some((revision) => numericAssetId(revision.asset_id) === item.assetId && revision.source !== EDGE_REFERENCE_PROVENANCE)) {
        nextRevisions.push({ asset_id: item.assetId, revision: item.revision, source: EDGE_REFERENCE_PROVENANCE, source_node_id: item.sourceNodeId, ...(item.sourceEdgeId ? { source_edge_id: item.sourceEdgeId } : {}) });
      }
    });
    const nextConfig = { ...config };
    if (existingIds.length || nextIds.length || Array.isArray(config.reference_asset_ids)) nextConfig.reference_asset_ids = nextIds;
    if (existingPreviews.length || nextPreviews.length) nextConfig.reference_previews = nextPreviews;
    if (existingRevisions.length || nextRevisions.length) nextConfig.reference_asset_revisions = nextRevisions;
    if (nextProvenance.length || Array.isArray(config.reference_provenance)) nextConfig.reference_provenance = nextProvenance;
    if (sameJson(config, nextConfig)) return node;
    return { ...node, data: { ...(node.data || {}), config: nextConfig } };
  });
}
