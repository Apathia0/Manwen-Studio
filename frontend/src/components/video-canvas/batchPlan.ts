/** 批量生成规划：把选中的图片/视频节点按依赖分成若干"波次"，同一波次内互不依赖、可并行提交。 */

export interface BatchNode {
  id: string;
  type: string;
  /** result_style_key：这张图/这条视频生成时使用的画风指纹（由运行输出合并时写入） */
  data: { label?: string; config?: Record<string, unknown>; result?: unknown; result_style_key?: string };
}

export interface BatchEdge {
  source: string;
  target: string;
  data?: { disabled?: boolean } | null;
}

export type ProductionKind = 'storyboard' | 'video';

export interface ProductionEntry {
  nodeId: string;
  kind: ProductionKind;
  title: string;
  sequence: number;
  duration: number | null;
  mediaUrl: string;
  generated: boolean;
}

const cfg = (node: BatchNode): Record<string, unknown> => node.data.config || {};

/** 可批量生成的节点：图片与视频（合片不在批量范围内，由用户单独提交）。 */
export const isGenerationNode = (node: BatchNode): boolean => node.type === 'image' || node.type === 'video';

/** 已有结果：固定了素材，或运行输出里有地址。 */
export const isGenerated = (node: BatchNode): boolean => Boolean(cfg(node).asset_id) || Boolean((node.data.result as { url?: string } | undefined)?.url);

/** 分镜图与视频节点，按镜头序号排列，用于资产面板的「分镜 / 视频」标签。 */
export function collectProduction(nodes: BatchNode[]): ProductionEntry[] {
  return nodes
    .filter((node) => !cfg(node).stale && ((node.type === 'image' && cfg(node).node_role === 'storyboard') || (node.type === 'video' && Boolean(cfg(node).source_scene_node))))
    .map((node): ProductionEntry => {
      const config = cfg(node);
      const duration = Number(config.duration_seconds);
      return {
        nodeId: node.id,
        kind: node.type === 'video' ? 'video' : 'storyboard',
        title: String(node.data.label || config.title || node.id),
        sequence: Number(config.sequence) || 0,
        duration: Number.isFinite(duration) && duration > 0 ? duration : null,
        mediaUrl: String((node.data.result as { url?: string } | undefined)?.url || ''),
        generated: isGenerated(node),
      };
    })
    .sort((a, b) => a.sequence - b.sequence || a.title.localeCompare(b.title, 'zh-Hans-CN'));
}

/** 某节点上游（沿有效连线向上，穿过文本/场景等中间节点）的全部生成节点 id。 */
export function generationAncestors(nodeId: string, nodes: BatchNode[], edges: BatchEdge[]): Set<string> {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const parents = new Map<string, string[]>();
  for (const edge of edges) {
    if (edge.data?.disabled) continue;
    parents.set(edge.target, [...(parents.get(edge.target) || []), edge.source]);
  }
  const found = new Set<string>();
  const seen = new Set<string>([nodeId]);
  const queue = [nodeId];
  while (queue.length) {
    for (const parent of parents.get(queue.shift()!) || []) {
      if (seen.has(parent)) continue;
      seen.add(parent);
      const node = byId.get(parent);
      if (node && isGenerationNode(node)) found.add(parent);
      queue.push(parent);
    }
  }
  return found;
}

export interface BatchPlan {
  /** 依次执行的波次；波次内互不依赖，可同时提交 */
  waves: string[][];
  /** 选中节点之外、因依赖而自动加入的上游节点（尚未生成） */
  added: string[];
  /** 选中但已有结果而跳过的节点 */
  skipped: string[];
}

export interface BatchPlanOptions {
  /** 重新生成：选中节点即使已有结果也重新生成（已锁定的除外，且不会自动带上上游） */
  regenerate?: boolean;
}

export function planBatchWaves(nodes: BatchNode[], edges: BatchEdge[], selectedIds: string[], options: BatchPlanOptions = {}): BatchPlan {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const selected = selectedIds.filter((id) => {
    const node = byId.get(id);
    return node && isGenerationNode(node);
  });
  const skipped = selected.filter((id) => (options.regenerate ? Boolean(byId.get(id)!.data.config?.locked) : isGenerated(byId.get(id)!)));
  const pending = new Set(selected.filter((id) => !skipped.includes(id)));
  const added: string[] = [];
  // 依赖的上游若还没生成，必须先生成，否则每个下游运行都会各自重复生成它们。
  for (const id of options.regenerate ? [] : [...pending]) {
    for (const ancestor of generationAncestors(id, nodes, edges)) {
      const node = byId.get(ancestor);
      if (node && !isGenerated(node) && !pending.has(ancestor)) {
        pending.add(ancestor);
        added.push(ancestor);
      }
    }
  }
  const upstream = new Map([...pending].map((id) => [id, [...generationAncestors(id, nodes, edges)].filter((a) => pending.has(a))]));
  const waves: string[][] = [];
  const placed = new Set<string>();
  while (placed.size < pending.size) {
    const wave = [...pending].filter((id) => !placed.has(id) && (upstream.get(id) || []).every((a) => placed.has(a)));
    if (!wave.length) break; // 存在环时保护性退出
    wave.forEach((id) => placed.add(id));
    waves.push(wave);
  }
  return { waves, added, skipped };
}
