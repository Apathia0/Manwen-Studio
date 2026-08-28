import { useState } from 'react';
import { CheckCircle2, ChevronDown, ChevronRight, Clapperboard, ThumbsUp } from 'lucide-react';
import SceneNodeView, { type SceneNodeConfig } from './SceneNodeView';

export interface SceneListConfig {
  scenes?: SceneNodeConfig[];
  approved?: boolean;
  title?: string;
  [key: string]: unknown;
}

interface SceneListNodeViewProps {
  config: SceneListConfig;
  /** partial 合并进节点 config */
  onChange: (partial: Record<string, unknown>) => void;
  /** 统一审批 / 撤销（作用整个节点内所有场景） */
  onToggleApproved?: () => void;
}

/**
 * 场景审核聚合节点：一场拆分产出的全部场次放在同一个大节点里垂直排列，
 * 便于整体浏览与逐场编辑；审批在聚合层统一操作。
 */
export default function SceneListNodeView({ config, onChange, onToggleApproved }: SceneListNodeViewProps) {
  const scenes = Array.isArray(config.scenes) ? config.scenes : [];
  const [collapsed, setCollapsed] = useState(false);
  const approved = Boolean(config.approved);

  const updateScene = (index: number, partial: Record<string, unknown>) => {
    const next = scenes.map((scene, i) => (i === index ? { ...scene, ...partial } : scene));
    onChange({ scenes: next });
  };

  return (
    <div className="flex h-full w-full flex-col overflow-hidden" onPointerDown={(event) => event.stopPropagation()}>
      {/* 头部：统计 + 展开/收起 */}
      <div className="flex shrink-0 items-center justify-between border-b border-[#3a3f45] px-3 py-2">
        <div className="flex items-center gap-2">
          <Clapperboard size={14} className="text-[#73a7ff]" />
          <span className="text-xs font-medium text-white">场景审核</span>
          <span className="rounded-full bg-[#2a2e33] px-2 py-0.5 text-[10px] text-[#aeb6c5]">{scenes.length} 个场景</span>
          {approved && (
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
              <CheckCircle2 size={11} /> 已批准
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => setCollapsed((value) => !value)}
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[10px] text-[#aeb6c5] hover:bg-white/10"
        >
          {collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
          {collapsed ? '展开列表' : '收起列表'}
        </button>
      </div>

      {/* 场景卡片垂直列表 */}
      {!collapsed && (
        <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-2">
          {scenes.length === 0 ? (
            <p className="py-6 text-center text-xs text-slate-500">暂无场景</p>
          ) : (
            scenes.map((scene, index) => (
              <div key={scene.scene_id ?? index} className="rounded-xl border border-[#3a3f45] bg-[#202226]">
                <SceneNodeView
                  config={scene}
                  hideApproval
                  onChange={(partial) => updateScene(index, partial)}
                />
              </div>
            ))
          )}
        </div>
      )}

      {/* 统一审批 */}
      <div className="shrink-0 border-t border-[#3a3f45] p-2">
        {approved ? (
          <button
            type="button"
            onClick={() => onToggleApproved?.()}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2 py-1.5 text-[11px] text-emerald-400 transition-colors hover:bg-emerald-500/20"
            title="撤销审批"
          >
            <CheckCircle2 size={12} />
            已通过审批（点击撤销）
          </button>
        ) : (
          <button
            type="button"
            onClick={() => onToggleApproved?.()}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-emerald-600 px-2 py-1.5 text-[11px] font-medium text-white transition-colors hover:bg-emerald-500"
          >
            <ThumbsUp size={12} />
            通过审批，进入下一步（{scenes.length} 个场景）
          </button>
        )}
      </div>
    </div>
  );
}
