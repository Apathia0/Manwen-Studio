import { useMemo, useState, type ReactNode } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  FileText,
  Link2,
  Loader2,
  MapPin,
  RotateCw,
  Sparkles,
  Target,
  ThumbsUp,
  UserRound,
} from 'lucide-react';
import SceneNodeView, { type SceneNodeConfig } from './SceneNodeView';

export interface SceneListConfig {
  scenes?: SceneNodeConfig[];
  approved?: boolean;
  source_content?: string;
  [key: string]: unknown;
}

/**
 * 导演编排的演示类型留在画布组件内，避免把画布 UI 与后端 schema 耦合。
 * 后端新增字段时仍可通过索引签名透传，组件只依赖当前可视化字段。
 */
export interface DirectorPlanContinuity {
  anchor?: string | null;
  [key: string]: unknown;
}

export interface DirectorPlanUnit {
  sequence?: number | string;
  unit_index?: number | string;
  title?: string | null;
  duration_seconds?: number | null;
  duration_reason?: string | null;
  beat_ids?: Array<string | number> | null;
  narrative_purpose?: string | null;
  transition_out?: string | null;
  continuity?: DirectorPlanContinuity | string | null;
  warnings?: string[] | null;
  [key: string]: unknown;
}

export interface DirectorPlan {
  units?: DirectorPlanUnit[];
  /** 兼容早期字段名 */
  sequence?: DirectorPlanUnit[];
  warnings?: string[] | null;
  [key: string]: unknown;
}

function planUnits(plan?: DirectorPlan | null): DirectorPlanUnit[] {
  if (Array.isArray(plan?.units)) return plan.units;
  if (Array.isArray(plan?.sequence)) return plan.sequence;
  return [];
}

export interface SceneListNodeViewProps {
  config: SceneListConfig;
  /** partial 合并进节点 config */
  onChange: (partial: Record<string, unknown>) => void;
  /** 统一审批 / 撤销（作用整个节点内所有场景） */
  onToggleApproved?: () => void;
  /** 聚合场景审批后的 AI 导演编排状态与操作 */
  directorPlan?: DirectorPlan | null;
  directorPlanLoading?: boolean;
  directorPlanError?: string | null;
  onGenerateDirectorPlan?: () => void;
  onApplyDirectorPlan?: () => void;
  directorPlanStale?: boolean;
  /** AI 资产分析（角色/场景/道具）：批准后可用 */
  onAnalyzeAssets?: () => void;
  assetAnalysisLoading?: boolean;
}

function displayText(value: unknown): string {
  return String(value ?? '').trim();
}

function displayList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => displayText(item)).filter(Boolean);
}

function continuityAnchor(unit: DirectorPlanUnit): string {
  if (typeof unit.continuity === 'string') return unit.continuity.trim();
  if (unit.continuity && typeof unit.continuity === 'object') return displayText(unit.continuity.anchor);
  return '';
}

function InfoLine({ label, value, icon }: { label: string; value: string; icon?: ReactNode }) {
  if (!value) return null;
  return (
    <div className="flex min-w-0 items-start gap-1.5 text-[10px] leading-4">
      <span className="flex shrink-0 items-center gap-1 text-[#827d77]">{icon}{label}</span>
      <span className="min-w-0 text-[#c4beb8]">{value}</span>
    </div>
  );
}

function DirectorPlanPanel({
  plan,
  loading,
  error,
  stale,
  onGenerate,
  onApply,
  open = false,
  onToggleOpen,
  grow = 1,
}: {
  open?: boolean;
  onToggleOpen?: () => void;
  grow?: number;
  plan?: DirectorPlan | null;
  loading?: boolean;
  error?: string | null;
  stale?: boolean;
  onGenerate?: () => void;
  onApply?: () => void;
}) {
  const sequence = planUnits(plan);
  const planWarnings = displayList(plan?.warnings);
  const totalDuration = sequence.reduce((sum, unit) => {
    const duration = Number(unit.duration_seconds);
    return Number.isFinite(duration) ? sum + duration : sum;
  }, 0);
  const hasPlan = Boolean(plan);

  return (
    <section style={open ? { flexGrow: grow } : undefined} className={`flex min-w-0 flex-col overflow-hidden rounded-xl ${open ? 'min-h-[160px] basis-0' : 'shrink-0'} border ${stale ? 'border-amber-400/35' : 'border-[#4c4641]'} bg-[#211f1d] shadow-[0_10px_28px_rgba(0,0,0,.2)]`} aria-label="AI导演编排">
      <div className={`flex shrink-0 items-center gap-2 px-2.5 py-2 ${open ? 'border-b border-[#3a3633]' : ''}`}>
        <button type="button" onPointerDown={(event) => event.stopPropagation()} onClick={onToggleOpen} aria-expanded={open} title={open ? '收起导演编排' : '展开导演编排'} className="flex min-w-0 flex-1 items-center gap-2 text-left">
        <span className="grid size-6 shrink-0 place-items-center rounded-lg bg-[#f3cf84]/12 text-[#f3cf84]"><Sparkles size={13} /></span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <h3 className="truncate text-[11px] font-semibold text-[#eee8e1]">AI导演编排</h3>
            {hasPlan && <span className="rounded-full bg-[#f3cf84]/12 px-1.5 py-0.5 text-[9px] text-[#f3cf84]">已生成</span>}
          </div>
          <p className="mt-0.5 truncate text-[9px] text-[#817a74]">
            {hasPlan ? `${sequence.length} 个视频单元${totalDuration ? ` · ${totalDuration}s` : ''}` : '审批通过后，为场景安排节奏与镜头顺序'}
          </p>
        </div>
        {open ? <ChevronDown size={13} className="shrink-0 text-[#817a74]" /> : <ChevronRight size={13} className="shrink-0 text-[#817a74]" />}
        </button>
        <button
          type="button"
          disabled={Boolean(loading)}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={() => onGenerate?.()}
          className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-[#625442] px-2 py-1.5 text-[10px] font-medium text-[#f3cf84] transition hover:border-[#f3cf84]/70 hover:bg-[#f3cf84]/10 disabled:cursor-wait disabled:opacity-50"
          title={loading ? '正在生成导演编排' : hasPlan ? '根据已批准场景重新生成编排' : '生成AI导演编排'}
        >
          {loading ? <Loader2 size={11} className="animate-spin" /> : <RotateCw size={11} />}
          {loading ? '编排中…' : hasPlan ? '重新编排' : 'AI导演编排'}
        </button>
      </div>

      {open && <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {error && (
          <div className="mb-2 flex items-start gap-1.5 rounded-lg border border-rose-400/20 bg-rose-400/8 px-2 py-1.5 text-[10px] leading-4 text-rose-300">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}
        {stale && (
          <div className="mb-2 flex items-start gap-1.5 rounded-lg border border-amber-400/25 bg-amber-400/8 px-2 py-1.5 text-[10px] leading-4 text-amber-200">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
            <span>方案已过期，请重新编排。场景内容发生变化后，旧方案不能直接应用。</span>
          </div>
        )}
        {loading && !hasPlan ? (
          <div className="flex items-center justify-center gap-2 py-5 text-[10px] text-[#a39a92]"><Loader2 size={14} className="animate-spin text-[#f3cf84]" />导演正在整理节奏与转场…</div>
        ) : hasPlan ? (
          <div className="space-y-2">
            {sequence.length ? sequence.map((unit, index) => {
              const sequenceNumber = displayText(unit.sequence ?? unit.unit_index ?? index + 1);
              const beatIds = displayList(unit.beat_ids);
              const warnings = displayList(unit.warnings);
              const anchor = continuityAnchor(unit);
              return (
                <article key={`${sequenceNumber}-${index}`} className="relative overflow-hidden rounded-lg border border-[#3b3734] bg-[#292623] p-2.5">
                  <div className="absolute inset-y-0 left-0 w-0.5 bg-[#f3cf84]/65" />
                  <div className="flex items-start gap-2">
                    <span className="grid size-6 shrink-0 place-items-center rounded-md bg-[#f3cf84]/12 font-mono text-[10px] font-semibold text-[#f3cf84]">{sequenceNumber}</span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <h4 className="min-w-0 flex-1 text-[11px] font-semibold text-[#eee8e1]">{displayText(unit.title) || `视频单元 ${sequenceNumber}`}</h4>
                        {unit.duration_seconds != null && <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-[#73a7ff]/12 px-1.5 py-0.5 text-[10px] font-medium text-[#9fc2ff]"><Clock size={9} />{unit.duration_seconds}s</span>}
                      </div>
                      <div className="mt-1.5 space-y-0.5">
                        <InfoLine label="时长依据" value={displayText(unit.duration_reason)} />
                        <InfoLine label="节拍" value={beatIds.length ? beatIds.join(' · ') : ''} icon={<Target size={9} />} />
                        <InfoLine label="叙事目的" value={displayText(unit.narrative_purpose)} />
                        <InfoLine label="连续性锚点" value={anchor} icon={<Link2 size={9} />} />
                        <InfoLine label="转场" value={displayText(unit.transition_out)} icon={<ArrowRight size={9} />} />
                      </div>
                      {warnings.length > 0 && <div className="mt-2 rounded-md border border-amber-400/15 bg-amber-400/6 px-2 py-1.5 text-[10px] leading-4 text-amber-200"><span className="mr-1 text-amber-300">注意</span>{warnings.join('；')}</div>}
                    </div>
                  </div>
                </article>
              );
            }) : <p className="py-3 text-center text-[10px] text-[#817a74]">编排方案没有可展示的视频单元</p>}
            {planWarnings.length > 0 && <div className="rounded-lg border border-amber-400/15 bg-amber-400/6 px-2 py-1.5 text-[10px] leading-4 text-amber-200"><span className="mr-1 text-amber-300">方案提示</span>{planWarnings.join('；')}</div>}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-[#4b4540] bg-[#282522] px-3 py-3 text-center">
            <p className="text-[10px] leading-4 text-[#a39a92]">让 AI 导演把场景串成可执行的视频节奏，生成后可逐单元检查时长、节拍与连续性。</p>
            <button type="button" disabled={Boolean(loading)} onPointerDown={(event) => event.stopPropagation()} onClick={() => onGenerate?.()} className="mt-2 inline-flex items-center gap-1.5 rounded-lg bg-[#f3cf84] px-3 py-1.5 text-[10px] font-semibold text-[#30281d] transition hover:bg-[#ffe0a1] disabled:cursor-wait disabled:opacity-50"><Sparkles size={11} />生成导演编排</button>
          </div>
        )}
      </div>}

      {open && hasPlan && (
        <div className="shrink-0 border-t border-[#3a3633] p-2">
          <button
            type="button"
            disabled={Boolean(stale || loading || !sequence.length)}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={() => onApply?.()}
            title={stale ? '方案已过期，请重新编排' : '应用编排并生成视频节点组'}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-[#f3cf84] px-2.5 py-2 text-[10px] font-semibold text-[#30281d] transition hover:bg-[#ffe0a1] disabled:cursor-not-allowed disabled:bg-[#4a433b] disabled:text-[#8d8379]"
          >
            <CheckCircle2 size={12} />
            {stale ? '请重新编排后再应用' : '应用编排，生成视频节点组'}
          </button>
        </div>
      )}
    </section>
  );
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
export default function SceneListNodeView({
  config,
  onChange,
  onToggleApproved,
  directorPlan,
  directorPlanLoading = false,
  directorPlanError = null,
  onGenerateDirectorPlan,
  onApplyDirectorPlan,
  directorPlanStale = false,
  onAnalyzeAssets,
  assetAnalysisLoading = false,
}: SceneListNodeViewProps) {
  const scenes = useMemo(() => (Array.isArray(config.scenes) ? config.scenes : []), [config.scenes]);
  const [collapsed, setCollapsed] = useState(false);
  const [scenesOpen, setScenesOpen] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);
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
    <div className="flex h-full w-full flex-col overflow-hidden">
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

          {/* 右：两张可折叠卡片（默认收起），同时展开时按 4:6 分配高度 */}
          <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2 p-2">
            <section style={scenesOpen ? { flexGrow: approved && planOpen ? 4 : 1 } : undefined} className={`flex min-w-0 flex-col overflow-hidden rounded-xl border border-[#35393f] bg-[#1c1e22] ${scenesOpen ? 'min-h-[140px] basis-0' : 'shrink-0'}`}>
              <button type="button" onClick={() => setScenesOpen((value) => !value)} aria-expanded={scenesOpen} title={scenesOpen ? '收起场景审核' : '展开场景审核'} className={`flex w-full shrink-0 items-center gap-2 px-2.5 py-2 text-left hover:bg-white/5 ${scenesOpen ? 'border-b border-[#35393f]' : ''}`}>
                <FileText size={13} className="text-[#8b93a1]" />
                <span className="min-w-0 flex-1 truncate text-[11px] font-semibold text-[#e8ebf0]">场景审核 <span className="font-normal text-[#78818f]">· {scenes.length} 场</span></span>
                {scenesOpen ? <ChevronDown size={13} className="shrink-0 text-[#78818f]" /> : <ChevronRight size={13} className="shrink-0 text-[#78818f]" />}
              </button>
              {scenesOpen && <div className="min-h-0 flex-1 overflow-y-auto p-2">
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
              </div>}
            </section>
            {/* 生产模式同款提示 */}
            {!approved && (
              <p className="text-center text-[10px] text-amber-400/90">请审核并批准剧本后，才能编排或编译视频节点组</p>
            )}
            {approved && (
              <DirectorPlanPanel
                plan={directorPlan}
                loading={directorPlanLoading}
                error={directorPlanError}
                stale={directorPlanStale}
                onGenerate={() => { setPlanOpen(true); onGenerateDirectorPlan?.(); }}
                onApply={onApplyDirectorPlan}
                open={planOpen}
                onToggleOpen={() => setPlanOpen((value) => !value)}
                grow={scenesOpen ? 6 : 1}
              />
            )}
          </div>
        </div>
      )}

      {/* 统一审批 + 资产分析 */}
      <div className="shrink-0 border-t border-[#3a3f45] bg-[#1b1d21] p-2">
        {approved && onAnalyzeAssets && (
          <button
            type="button"
            disabled={assetAnalysisLoading}
            onClick={() => onAnalyzeAssets()}
            className="mb-1.5 inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-[#625442] bg-[#f3cf84]/10 px-2 py-1.5 text-[11px] text-[#f3cf84] transition-colors hover:bg-[#f3cf84]/20 disabled:cursor-wait disabled:opacity-50"
            title="从剧本自动解析角色/场景/道具资产与绘图提示词，生成参考图后绑定到分镜和视频节点保证一致性"
          >
            {assetAnalysisLoading ? <Loader2 size={12} className="animate-spin" /> : <UserRound size={12} />}
            {assetAnalysisLoading ? '资产分析中…' : 'AI 资产分析（角色 / 场景 / 道具）'}
          </button>
        )}
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
