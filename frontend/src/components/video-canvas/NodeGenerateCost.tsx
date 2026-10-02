import { useEffect, useState } from 'react';
import { estimateVideoCanvasCost, type CanvasCostEstimate, type VideoCanvasGraph } from '../../api';
import { formatRegenerateCost } from './canvasPipeline';

interface Props {
  canvasId: number;
  nodeId: string;
  /** 当前浏览器画布图（含未保存修改），预估按它计算 */
  getGraph: () => VideoCanvasGraph;
  /** 节点已有结果：预估按“重新生成”（去掉固定的素材、强制重跑）计算 */
  regenerates: boolean;
  /** 运行状态 / 结果变化时重新预估 */
  refreshKey: string;
}

/** 生成键旁边的积分预估。已复用、不会产生费用的节点显示“0 积分”；预估失败时不显示，不影响生成。 */
export default function NodeGenerateCost({ canvasId, nodeId, getGraph, regenerates, refreshKey }: Props) {
  const [cost, setCost] = useState<CanvasCostEstimate | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const graph = structuredClone(getGraph());
    if (regenerates) {
      for (const node of graph.nodes) {
        if (node.id === nodeId && node.data?.config) { delete node.data.config.asset_id; delete node.data.config._reused_definition_hash; }
      }
    }
    estimateVideoCanvasCost(canvasId, { target_node_ids: [nodeId], rerun_node_ids: regenerates ? [nodeId] : [], graph }, controller.signal)
      .then(setCost).catch(() => { if (!controller.signal.aborted) setCost(null); });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canvasId, nodeId, regenerates, refreshKey]);

  if (!cost) return null;
  const detail = [formatRegenerateCost(cost), ...cost.warnings].join('\n');
  return (
    <span title={detail} className={`shrink-0 whitespace-nowrap rounded-full border px-2.5 py-1 text-[11px] ${cost.sufficient === false ? 'border-rose-400/60 text-rose-300' : 'border-[#4a4541] text-[#b6afa9]'}`}>
      {cost.credential_mode === 'platform' && cost.total_points !== null ? `约 ${Number(cost.total_points.toFixed(2))} 积分` : '自有 API Key'}
    </span>
  );
}
