import { useMemo, useState } from 'react';
import { BookOpen, CheckCircle2, ChevronDown, ChevronRight, Clock, FileText, MapPin, ThumbsUp } from 'lucide-react';
import SceneNodeView, { type SceneNodeConfig } from './SceneNodeView';

export interface SceneListConfig {
  scenes?: SceneNodeConfig[];
  approved?: boolean;
  source_content?: string;
  [key: string]: unknown;
}

interface SceneListNodeViewProps {
  config: SceneListConfig;
  /** partial 合并进节点 config */
  onChange: (partial: Record<string, unknown>) => void;
  /** 统一审批 / 撤销（作用整个节点内所有场景） */
  onToggleApproved?: () => void;
}

const importanceMeta: Record<string, { label: string; className: string }> = {
  high: { label: 'high', className: 'bg-rose-500/15 text-rose-300' },
  medium: { label: '一般', className: 'bg-[#2a2e33] text-[#8b93a1]' },
  low: { label: '低', className: 'bg-[#2a2e33] text-[#78818f]' },
};

/**
 * 场景审核聚合节点——复刻生产环境"左正文 + 右剧本审核"布局，深色画布主题：
 * 左栏来源正文（只读），右栏场景行列表（点击行展开该场景编辑卡），
 * 审批在聚合层统一操作。
 */
export default function SceneListNodeView({ config, onChange, onToggleApproved }: SceneListNodeViewProps) {
  const scenes = useMemo(() => (Array.isArray(config.scenes) ? config.scenes : []), [config.scenes]);
  const [collapsed, setCollapsed] = useState(false);
  const [expandedSceneId, setExpandedSceneId] = useState<string | number | null>(null);
  const approved = Boolean(config.approved);

  const updateScene = (index: number, partial: Record<string, unknown>) => {
    const next = scenes.map((scene, i) => (i === index ? { ...scene, ...partial } : scene));
    onChange({ scenes: next });
  };

  const toggleRow = (sceneId: string | number | undefined) => {
    const key = sceneId ?? '';
    setExpandedSceneId((current) => (current === key ? null : key));
  };

  return (
    <div className="flex h-full w-full flex-col overflow-hidden" onPointerDown={(event) => event.stopPropagation()}>
      {/* 头部：剧本审核 + 状态 + 列表展开/收起 */}
      <div className="flex shrink-0 items-center justify-between border-b border-[#3a3f45] bg-[#1b1d21] px-3 py-2">
        <div className="flex items-center gap-2">
          <FileText size={14} className="text-[#8b93a1]" />
          <span className="text-xs font-medium text-[#e8ebf0]">剧本审核</span>
          <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${approved ? 'bg-emerald-500/15 text-emerald-400' : 'bg-amber-500/15 text-amber-400'}`}>
            {approved ? '已批准' : '待批准'}
          </span>
          <span className="rounded-full bg-[#2a2e33] px-2 py-0.5 text-[10px] text-[#8b93a1]">{scenes.length} 场</span>
        </div>
        <button
          type="button"
          onClick={() => setCollapsed((value) => !value)}
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[10px] text-[#8b93a1] hover:bg-white/10"
        >
          {collapsed ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          {collapsed ? '展开场景' : '收起场景'}
        </button>
      </div>

      {/* 主体：左来源正文 / 右场景列表 */}
      {!collapsed && (
        <div className="flex min-h-0 flex-1">
          {/* 左：来源正文（只读） */}
          <div className="flex w-[38%] min-w-0 flex-col border-r border-[#3a3f45]">
            <div className="flex shrink-0 items-center gap-1.5 border-b border-[#3a3f45] bg-[#1b1d21] px-2.5 py-1.5">
              <BookOpen size={11} className="text-[#78818f]" />
              <span className="text-[10px] font-medium text-[#8b93a1]">来源正文</span>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-2.5">
              <div className="whitespace-pre-wrap text-[11px] leading-relaxed text-[#b3bac6]">
                {String(config.source_content || '').trim() || '（来源正文未随附，可在剧本节点查看）'}
              </div>
            </div>
          </div>

          {/* 右：场景行列表 + 展开编辑 */}
          <div className="min-w-0 flex-1 overflow-y-auto p-2">
            {scenes.length === 0 ? (
              <p className="py-6 text-center text-xs text-[#78818f]">暂无场景</p>
            ) : (
              <div className="space-y-1.5">
                {scenes.map((scene, index) => {
                  const sceneKey = scene.scene_id ?? index;
                  const isExpanded = expandedSceneId === sceneKey;
                  const importance = String(scene.importance || 'medium');
                  const meta = importanceMeta[importance] || importanceMeta.medium;
                  return (
                    <div key={sceneKey} className={`overflow-hidden rounded-lg border ${isExpanded ? 'border-[#73a7ff]/40' : 'border-[#35393f]'} bg-[#202226]`}>
                      {/* 场景行（收起态） */}
                      <button
                        type="button"
                        onClick={() => toggleRow(scene.scene_id)}
                        className="flex w-full items-center gap-2 px-2.5 py-2 text-left transition-colors hover:bg-white/5"
                      >
                        <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-[#73a7ff]/15 text-[10px] font-semibold text-[#73a7ff]">
                          {scene.scene_id ?? index + 1}
                        </span>
                        <span className="min-w-0 flex-1 truncate text-[11px] font-medium text-[#e8ebf0]">
                          {String(scene.title || `场景 ${index + 1}`)}
                        </span>
                        {scene.location && (
                          <span className="hidden shrink-0 items-center gap-0.5 text-[10px] text-[#78818f] sm:inline-flex">
                            <MapPin size={9} />{String(scene.location).slice(0, 12)}
                          </span>
                        )}
                        {scene.time_of_day && (
                          <span className="hidden shrink-0 items-center gap-0.5 text-[10px] text-[#78818f] sm:inline-flex">
                            <Clock size={9} />{String(scene.time_of_day).slice(0, 8)}
                          </span>
                        )}
                        {importance === 'high' && (
                          <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-medium ${meta.className}`}>{meta.label}</span>
                        )}
                        {isExpanded ? <ChevronDown size={13} className="shrink-0 text-[#78818f]" /> : <ChevronRight size={13} className="shrink-0 text-[#78818f]" />}
                      </button>

                      {/* 展开的场景编辑卡 */}
                      {isExpanded && (
                        <div className="border-t border-[#35393f] p-1.5">
                          <SceneNodeView
                            config={scene}
                            hideApproval
                            onChange={(partial) => updateScene(index, partial)}
                          />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
            {/* 生产模式同款提示 */}
            {!approved && (
              <p className="mt-2 text-center text-[10px] text-amber-400/90">请审核并批准剧本后，才能编译视频节点组</p>
            )}
          </div>
        </div>
      )}

      {/* 统一审批 */}
      <div className="shrink-0 border-t border-[#3a3f45] bg-[#1b1d21] p-2">
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
            批准剧本，进入下一步（{scenes.length} 场）
          </button>
        )}
      </div>
    </div>
  );
}
