/** 画布资产：角色、场景、道具三类资产的形象、设定与"镜头引用缺失"，全部由节点图推导。 */

export type AssetKind = 'character' | 'scene' | 'prop';

export interface LibNode {
  id: string;
  type: string;
  data: { label?: string; config?: Record<string, unknown>; result?: unknown };
}

export interface LibEdge {
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
}

export interface AssetEntry {
  nodeId: string;
  kind: AssetKind;
  name: string;
  /** 角色为人物档案，场景/道具为生成提示词 */
  setting: string;
  locked: boolean;
  /** 已生成的图片；为空表示尚未生成 */
  imageUrl: string;
  hasImage: boolean;
  sceneIds: string[];
  /** 会用到该资产的分镜节点 */
  appearances: string[];
  /** 会用到但没有引用该资产的分镜节点：形象可能不一致 */
  missingRefs: string[];
}

export const ASSET_KIND_LABEL: Record<AssetKind, string> = { character: '角色', scene: '场景', prop: '道具' };
const KIND_ORDER: Record<AssetKind, number> = { character: 0, scene: 1, prop: 2 };

const cfg = (node: LibNode): Record<string, unknown> => node.data.config || {};
const strings = (value: unknown): string[] => (Array.isArray(value) ? value.map((v) => String(v)) : []);
const isKind = (value: unknown): value is AssetKind => value === 'character' || value === 'scene' || value === 'prop';

/** 与后端 _bind_assets 同口径：场景重叠即相关；角色另按角色名匹配。 */
function relatedShots(kind: AssetKind, name: string, sceneIds: string[], shots: LibNode[]): string[] {
  return shots.filter((shot) => {
    const shotConfig = cfg(shot);
    if (strings(shotConfig.source_scene_ids).some((id) => sceneIds.includes(id))) return true;
    return kind === 'character' && strings(shotConfig.characters).includes(name);
  }).map((shot) => shot.id);
}

export function collectAssets(nodes: LibNode[], edges: LibEdge[]): AssetEntry[] {
  const live = nodes.filter((n) => !cfg(n).stale);
  const shots = live.filter((n) => n.type === 'image' && cfg(n).node_role === 'storyboard');
  return live
    .filter((n) => n.type === 'image' && isKind(cfg(n).asset_role))
    .map((node): AssetEntry => {
      const config = cfg(node);
      const kind = config.asset_role as AssetKind;
      const name = String(config.asset_name || node.data.label || ASSET_KIND_LABEL[kind]);
      const sceneIds = strings(config.scene_ids);
      const appearances = relatedShots(kind, name, sceneIds, shots);
      const linked = new Set(edges.filter((e) => e.source === node.id && e.targetHandle === 'references').map((e) => e.target));
      const url = String((node.data.result as { url?: string } | undefined)?.url || '');
      return {
        nodeId: node.id,
        kind,
        name,
        setting: String(kind === 'character' ? config.profile || '' : config.prompt || ''),
        locked: Boolean(config.locked),
        imageUrl: url,
        hasImage: Boolean(config.asset_id) || Boolean(url),
        sceneIds,
        appearances,
        missingRefs: appearances.filter((id) => !linked.has(id)),
      };
    })
    .sort((a, b) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind] || a.name.localeCompare(b.name, 'zh-Hans-CN'));
}

/** 给用到但缺引用的分镜补连线；已存在的不重复创建。 */
export function buildReferenceEdges(assetNodeId: string, shotIds: string[], existing: LibEdge[]): Array<LibEdge & { id: string }> {
  const have = new Set(existing.filter((e) => e.source === assetNodeId && e.targetHandle === 'references').map((e) => e.target));
  return shotIds
    .filter((id) => !have.has(id))
    .map((id) => ({ id: `edge-asset-${assetNodeId}-${id}`, source: assetNodeId, target: id, sourceHandle: 'image', targetHandle: 'references' }));
}

export interface AssetSummary {
  total: number;
  byKind: Record<AssetKind, number>;
  withoutImage: number;
  missingRefs: number;
}

export function summarizeAssets(entries: AssetEntry[]): AssetSummary {
  const byKind: Record<AssetKind, number> = { character: 0, scene: 0, prop: 0 };
  for (const entry of entries) byKind[entry.kind] += 1;
  return {
    total: entries.length,
    byKind,
    withoutImage: entries.filter((e) => !e.hasImage).length,
    missingRefs: entries.reduce((sum, e) => sum + e.missingRefs.length, 0),
  };
}
