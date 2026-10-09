import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Check, Download, FolderOpen, Link2, Loader2, Lock, LocateFixed, Sparkles, Unlock, Upload, X } from 'lucide-react';
import MediaImage from '../shared/MediaImage';
import { downloadImagesAsZip, sanitizeFilename } from '../../lib/zipDownload';
import { toast } from '../../lib/toast';
import { normalizeErrorMessage } from '../../lib/errors';
import { estimateVideoCanvasCost, type AssetCandidate, type CanvasCostEstimate, type VideoCanvasGraph } from '../../api';
import { ASSET_KIND_LABEL, summarizeAssets, type AssetEntry, type AssetKind } from './assetLibrary';
import type { ProductionEntry } from './batchPlan';
import { formatCostLine } from './canvasPipeline';
import MediaLightbox from './MediaLightbox';
import StyleControl from './StyleControl';
import type { CanvasStyle } from './canvasStyle';

type Tab = 'all' | AssetKind | 'storyboard' | 'video';

export interface BatchProgress {
  total: number;
  done: number;
  failed: number;
}

interface Props {
  canvasId: number;
  entries: AssetEntry[];
  /** 未入选的场景/道具候选（已排除画布上已存在的） */
  candidates: AssetCandidate[];
  onAddCandidate: (candidate: AssetCandidate) => void;
  /** 分镜图与视频节点 */
  production: ProductionEntry[];
  /** 节点当前的运行状态：queued / running / succeeded / failed */
  statuses: Map<string, string>;
  batch: BatchProgress | null;
  /** 当前画布风格，以及打开风格选择 */
  canvasStyle: CanvasStyle | null;
  onPickStyle: () => void;
  onToggleStyle: (enabled: boolean) => void;
  /** 与当前画风不一致的已生成节点数，以及一键统一 */
  inconsistentCount: number;
  onUnifyStyle: () => void;
  busy: boolean;
  uploadingNodeId: string | null;
  /** 当前浏览器画布图（含未保存修改），用于预估所选项的花费 */
  getGraph: () => VideoCanvasGraph;
  onClose: () => void;
  onToggleLock: (nodeId: string) => void;
  onEditSetting: (nodeId: string, kind: AssetKind, text: string) => void;
  onLinkShots: (nodeId: string, shotIds: string[]) => void;
  onFocus: (nodeId: string) => void;
  onGenerate: (nodeId: string) => void;
  onUpload: (nodeId: string) => void;
  /** 批量生成所选节点：同一批次内互不依赖的节点并行提交 */
  onBatchGenerate: (nodeIds: string[]) => void;
  onCancelBatch: () => void;
  /** 打开完整素材库（上传、删除、批量管理）；章节模式等没有入口时不显示 */
  onOpenLibrary?: () => void;
}

const SETTING_HINT: Record<AssetKind, string> = {
  character: '角色设定：年龄、身份、性格、体型与标志性服装',
  scene: '场景设定：空间布局、材质、光线与氛围',
  prop: '道具设定：外形、材质、颜色与识别特征',
};

const STATUS_BADGE: Record<string, { label: string; className: string }> = {
  queued: { label: '排队中', className: 'text-[#9fc2ff]' },
  awaiting_approval: { label: '排队中', className: 'text-[#9fc2ff]' },
  running: { label: '生成中', className: 'text-[#9fc2ff]' },
  cancel_requested: { label: '取消中', className: 'text-amber-300' },
  failed: { label: '失败', className: 'text-rose-300' },
  cancelled: { label: '已取消', className: 'text-[#8f8984]' },
};

function StatusBadge({ status, generated }: { status?: string; generated: boolean }) {
  const active = status && STATUS_BADGE[status];
  if (active) {
    const running = ['queued', 'awaiting_approval', 'running', 'cancel_requested'].includes(status!);
    return <span className={`inline-flex items-center gap-1 text-[10px] ${active.className}`}>{running && <Loader2 className="h-3 w-3 animate-spin" />}{active.label}</span>;
  }
  return <span className={`text-[10px] ${generated ? 'text-emerald-300' : 'text-[#7d756e]'}`}>{generated ? '已生成' : '未生成'}</span>;
}

function Checkbox({ checked, indeterminate, onChange, label }: { checked: boolean; indeterminate?: boolean; onChange: () => void; label: string }) {
  return (
    <button type="button" role="checkbox" aria-checked={indeterminate ? 'mixed' : checked} aria-label={label} onClick={(event) => { event.stopPropagation(); onChange(); }}
      className={`grid h-4 w-4 shrink-0 place-items-center rounded border ${checked || indeterminate ? 'border-[#73a7ff] bg-[#73a7ff] text-[#111827]' : 'border-[#6b625b] bg-transparent text-transparent hover:border-[#9a9088]'}`}>
      {indeterminate ? <span className="h-0.5 w-2 rounded bg-[#111827]" /> : <Check className="h-3 w-3" />}
    </button>
  );
}


/** 设定输入框：默认紧凑，点击聚焦时放大到能完整查看和编辑，失焦后收回。 */
function SettingTextarea({ value, placeholder, onCommit }: { value: string; placeholder: string; onCommit: (text: string) => void }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [height, setHeight] = useState<number | undefined>(undefined);

  const measure = () => {
    const element = ref.current;
    if (!element) return;
    element.style.height = 'auto';
    setHeight(Math.min(Math.max(element.scrollHeight + 2, 132), 300));
    element.style.height = '';
  };

  return (
    <textarea
      ref={ref}
      defaultValue={value}
      key={value}
      placeholder={placeholder}
      rows={3}
      onFocus={() => { setExpanded(true); requestAnimationFrame(measure); }}
      onInput={measure}
      onBlur={(event) => { setExpanded(false); event.currentTarget.scrollTop = 0; if (event.target.value !== value) onCommit(event.target.value); }}
      onKeyDown={(event) => { if (event.key === 'Escape') event.currentTarget.blur(); }}
      style={expanded && height ? { height } : undefined}
      className={`mt-2 w-full resize-none rounded-md border bg-[#211f1d] px-2 py-1.5 text-[11px] leading-[1.15rem] text-[#d8d1ca] outline-none transition-[height,border-color] duration-150 ${expanded ? 'overflow-y-auto border-[#73a7ff]' : 'h-14 overflow-hidden border-[#393633]'}`}
    />
  );
}

/**
 * 画布资产与镜头面板：角色 / 场景 / 道具资产，以及分镜图、视频。
 * 支持多选、全选，并把所选节点按依赖分波次并行生成；同时保留锁定、补齐引用、替换图片与下载。
 */
export default function CanvasAssetPanel({
  canvasId, entries, candidates, onAddCandidate, production, statuses, batch, canvasStyle, onPickStyle, onToggleStyle, inconsistentCount, onUnifyStyle, busy, uploadingNodeId, getGraph,
  onClose, onToggleLock, onEditSetting, onLinkShots, onFocus, onGenerate, onUpload, onBatchGenerate, onCancelBatch, onOpenLibrary,
}: Props) {
  const [tab, setTab] = useState<Tab>('all');
  const [downloading, setDownloading] = useState(false);
  const [candidatesOpen, setCandidatesOpen] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [cost, setCost] = useState<CanvasCostEstimate | null>(null);
  const [preview, setPreview] = useState<{ url: string; title: string; isVideo: boolean } | null>(null);

  const summary = useMemo(() => summarizeAssets(entries), [entries]);
  const isAssetTab = tab !== 'storyboard' && tab !== 'video';
  const visibleAssets = tab === 'all' ? entries : isAssetTab ? entries.filter((entry) => entry.kind === tab) : [];
  const visibleProduction = tab === 'storyboard' || tab === 'video' ? production.filter((entry) => entry.kind === tab) : [];
  const visibleCandidates = tab === 'all' ? candidates : isAssetTab ? candidates.filter((item) => item.role === tab) : [];

  // 当前标签下的可选项（节点 id → 是否已生成）
  const rows = useMemo(() => [
    ...visibleAssets.map((entry) => ({ id: entry.nodeId, generated: entry.hasImage })),
    ...visibleProduction.map((entry) => ({ id: entry.nodeId, generated: entry.generated })),
  ], [visibleAssets, visibleProduction]);
  const allNodes = useMemo(() => new Map([
    ...entries.map((entry) => [entry.nodeId, entry.hasImage] as const),
    ...production.map((entry) => [entry.nodeId, entry.generated] as const),
  ]), [entries, production]);

  // 节点被删除后清掉失效的选中项
  useEffect(() => {
    setSelected((current) => {
      const next = new Set([...current].filter((id) => allNodes.has(id)));
      return next.size === current.size ? current : next;
    });
  }, [allNodes]);

  const selectedIds = useMemo(() => [...selected].filter((id) => allNodes.has(id)), [selected, allNodes]);
  const pendingIds = useMemo(() => selectedIds.filter((id) => !allNodes.get(id)), [selectedIds, allNodes]);
  const visibleSelected = rows.filter((row) => selected.has(row.id)).length;
  const allVisibleSelected = rows.length > 0 && visibleSelected === rows.length;

  const toggle = (id: string) => setSelected((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const toggleAllVisible = () => setSelected((current) => {
    const next = new Set(current);
    if (allVisibleSelected) rows.forEach((row) => next.delete(row.id)); else rows.forEach((row) => next.add(row.id));
    return next;
  });
  const selectUngenerated = () => setSelected((current) => new Set([...current, ...rows.filter((row) => !row.generated).map((row) => row.id)]));

  // 所选未生成项的花费预估（含需要先生成的上游节点，与后端同口径）
  useEffect(() => {
    if (!pendingIds.length) { setCost(null); return undefined; }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      estimateVideoCanvasCost(canvasId, { target_node_ids: pendingIds, graph: getGraph() }, controller.signal)
        .then(setCost)
        .catch(() => { if (!controller.signal.aborted) setCost(null); });
    }, 500);
    return () => { window.clearTimeout(timer); controller.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canvasId, pendingIds.join('|')]);

  const tabs: Array<{ key: Tab; label: string; count: number }> = [
    { key: 'all', label: '资产', count: summary.total },
    { key: 'character', label: ASSET_KIND_LABEL.character, count: summary.byKind.character },
    { key: 'scene', label: ASSET_KIND_LABEL.scene, count: summary.byKind.scene },
    { key: 'prop', label: ASSET_KIND_LABEL.prop, count: summary.byKind.prop },
    { key: 'storyboard', label: '分镜', count: production.filter((e) => e.kind === 'storyboard').length },
    { key: 'video', label: '视频', count: production.filter((e) => e.kind === 'video').length },
  ];

  const downloadVisible = async () => {
    const items = [
      ...visibleAssets.filter((entry) => entry.imageUrl).map((entry) => ({ filename: `${ASSET_KIND_LABEL[entry.kind]}_${sanitizeFilename(entry.name)}.png`, url: entry.imageUrl })),
      ...(tab === 'storyboard' ? visibleProduction.filter((entry) => entry.mediaUrl).map((entry) => ({ filename: `分镜_${sanitizeFilename(entry.title)}.png`, url: entry.mediaUrl })) : []),
    ];
    if (items.length === 0) { toast.error('当前没有可下载的图片'); return; }
    setDownloading(true);
    try {
      await downloadImagesAsZip(items, { zipName: `画布${tab === 'storyboard' ? '分镜' : '资产'}_${new Date().toISOString().slice(0, 10)}.zip` });
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '导出失败'));
    } finally {
      setDownloading(false);
    }
  };

  const running = Boolean(batch);
  return (
    <div className="compact-controls absolute right-4 top-20 z-30 flex max-h-[calc(100%-9rem)] w-[360px] flex-col rounded-xl border border-[#393633] bg-[#211f1d]/98 shadow-2xl">
      <div className="flex shrink-0 items-center justify-between border-b border-[#393633] px-3 py-2.5">
        <div className="text-sm font-semibold text-[#f0ebde]">资产与镜头 <span className="ml-1 text-[11px] font-normal text-[#8f8984]">可多选批量生成</span></div>
        <div className="flex items-center gap-0.5">
          <button type="button" title="下载当前分类的图片" disabled={downloading || tab === 'video'} onClick={() => void downloadVisible()} className="rounded-md p-1.5 text-[#958d86] hover:bg-white/10 hover:text-white disabled:opacity-40"><Download className="h-4 w-4" /></button>
          {onOpenLibrary && <button type="button" title="打开完整素材库：上传、删除、批量管理" onClick={onOpenLibrary} className="rounded-md p-1.5 text-[#958d86] hover:bg-white/10 hover:text-white"><FolderOpen className="h-4 w-4" /></button>}
          <button type="button" aria-label="关闭资产面板" onClick={onClose} className="rounded-md p-1.5 text-[#958d86] hover:bg-white/10 hover:text-white"><X className="h-4 w-4" /></button>
        </div>
      </div>
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-[#393633] px-3 py-1.5">
        <span className="text-[11px] text-[#8f8984]">统一画风</span>
        <StyleControl style={canvasStyle} onPick={onPickStyle} onToggle={onToggleStyle} />
      </div>
      {inconsistentCount > 0 && (
        <div className="flex shrink-0 items-center justify-between gap-2 border-b border-[#393633] bg-amber-400/10 px-3 py-2 text-[11px] text-amber-200">
          <span className="flex min-w-0 items-start gap-1.5"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /><span>{inconsistentCount} 个已生成的图片/视频画风与当前设置不一致（已锁定的不算）</span></span>
          <button type="button" disabled={busy || running} onClick={onUnifyStyle} className="shrink-0 rounded-md bg-amber-300 px-2 py-1 text-[11px] font-semibold text-[#3b2a00] hover:bg-amber-200 disabled:opacity-40">一键统一</button>
        </div>
      )}
      <div className="flex shrink-0 flex-wrap gap-0.5 border-b border-[#393633] px-2 py-1.5">
        {tabs.map((item) => (
          <button key={item.key} type="button" onClick={() => setTab(item.key)} className={`shrink-0 rounded-md px-2 py-1 text-xs ${tab === item.key ? 'bg-white/10 text-white' : 'text-[#958d86] hover:text-white'}`}>
            {item.label}<span className="ml-1 text-[10px] text-[#7d756e]">{item.count}</span>
          </button>
        ))}
      </div>
      {rows.length > 0 && (
        <div className="flex shrink-0 items-center gap-2 border-b border-[#393633] px-3 py-1.5 text-[11px] leading-4 text-[#a79f98]">
          <Checkbox checked={allVisibleSelected} indeterminate={!allVisibleSelected && visibleSelected > 0} onChange={toggleAllVisible} label="全选当前分类" />
          <span>{visibleSelected > 0 ? `已选 ${visibleSelected}/${rows.length}` : '全选'}</span>
          <span className="flex-1" />
          <button type="button" onClick={selectUngenerated} className="text-[11px] hover:text-white">选中未生成</button>
          {selected.size > 0 && <button type="button" onClick={() => setSelected(new Set())} className="text-[11px] hover:text-white">清除</button>}
        </div>
      )}
      {isAssetTab && (summary.withoutImage > 0 || summary.missingRefs > 0) && (
        <div className="flex shrink-0 items-start gap-1.5 border-b border-[#393633] bg-amber-400/10 px-3 py-2 text-[11px] text-amber-200">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{summary.withoutImage > 0 && `${summary.withoutImage} 个资产还没有图片；`}{summary.missingRefs > 0 && `${summary.missingRefs} 处镜头没有引用对应资产，画面可能不一致。`}</span>
        </div>
      )}
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {rows.length === 0 && visibleCandidates.length === 0 && (
          <p className="py-6 text-center text-xs text-[#8f8984]">
            {isAssetTab ? (entries.length === 0 ? '还没有资产。完成「资产」阶段后，角色、场景和道具会出现在这里。' : `还没有${tab === 'all' ? '' : ASSET_KIND_LABEL[tab as AssetKind]}资产。`) : `还没有${tab === 'video' ? '视频' : '分镜'}节点。完成「分镜」阶段后会出现在这里。`}
          </p>
        )}
        {visibleAssets.map((entry) => (
          <div key={entry.nodeId} className={`rounded-lg border bg-[#171513] p-2.5 ${selected.has(entry.nodeId) ? 'border-[#73a7ff]/60' : 'border-[#393633]'}`}>
            <div className="flex gap-2.5">
              <Checkbox checked={selected.has(entry.nodeId)} onChange={() => toggle(entry.nodeId)} label={`选择 ${entry.name}`} />
              <div className={`grid shrink-0 place-items-center overflow-hidden rounded-md border border-[#393633] bg-[#211f1d] text-[10px] text-[#6f6862] ${entry.kind === 'character' ? 'h-20 w-16' : 'h-16 w-24'}`}>
                {entry.imageUrl ? <button type="button" title="点击放大查看" onClick={() => setPreview({ url: entry.imageUrl, title: entry.name, isVideo: false })} className="h-full w-full cursor-zoom-in"><MediaImage src={entry.imageUrl} alt={entry.name} width={480} className="h-full w-full object-cover" /></button> : '暂无图片'}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-1">
                  <span className="truncate text-sm font-medium text-[#f0ebde]" title={entry.name}>{entry.name}</span>
                  <div className="flex shrink-0 items-center">
                    <button type="button" title="在画布中定位" onClick={() => onFocus(entry.nodeId)} className="rounded p-1 text-[#958d86] hover:bg-white/10 hover:text-white"><LocateFixed className="h-3.5 w-3.5" /></button>
                    <button type="button" title={entry.locked ? '更换图片前请先解锁' : '上传图片替换当前资产'} disabled={entry.locked || uploadingNodeId === entry.nodeId} onClick={() => onUpload(entry.nodeId)} className="rounded p-1 text-[#958d86] hover:bg-white/10 hover:text-white disabled:opacity-30"><Upload className="h-3.5 w-3.5" /></button>
                    <button
                      type="button"
                      disabled={!entry.hasImage}
                      title={entry.locked ? '已锁定：重新分析和一键返工都不会改动这个资产，点击解锁' : entry.hasImage ? '锁定当前图片，保证全片一致' : '生成图片后才能锁定'}
                      onClick={() => onToggleLock(entry.nodeId)}
                      className={`rounded p-1 hover:bg-white/10 disabled:opacity-30 ${entry.locked ? 'text-[#73a7ff]' : 'text-[#958d86] hover:text-white'}`}
                    >
                      {entry.locked ? <Lock className="h-3.5 w-3.5" /> : <Unlock className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                </div>
                <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-[#8f8984]">
                  <span className="rounded bg-white/5 px-1.5 py-0.5">{ASSET_KIND_LABEL[entry.kind]}</span>
                  <span>用于 {entry.appearances.length} 个镜头</span>
                  <StatusBadge status={statuses.get(entry.nodeId)} generated={entry.hasImage} />
                  {entry.locked && <span>· 已锁定</span>}
                </div>
                {!entry.hasImage && !statuses.get(entry.nodeId) && (
                  <button type="button" disabled={busy || running} onClick={() => onGenerate(entry.nodeId)} className="mt-1.5 inline-flex items-center gap-1 rounded-md bg-[#73a7ff] px-2 py-0.5 text-[11px] font-medium text-[#111827] hover:bg-[#8db6ff] disabled:opacity-40"><Sparkles className="h-3 w-3" />生成图片</button>
                )}
              </div>
            </div>
            <SettingTextarea value={entry.setting} placeholder={SETTING_HINT[entry.kind]} onCommit={(text) => onEditSetting(entry.nodeId, entry.kind, text)} />
            {entry.missingRefs.length > 0 && (
              <button type="button" onClick={() => onLinkShots(entry.nodeId, entry.missingRefs)} className="mt-1.5 inline-flex items-center gap-1 rounded-md border border-amber-400/40 px-2 py-0.5 text-[11px] text-amber-200 hover:bg-amber-400/10">
                <Link2 className="h-3 w-3" />补齐 {entry.missingRefs.length} 个镜头的引用
              </button>
            )}
          </div>
        ))}
        {visibleProduction.map((entry) => (
          <div key={entry.nodeId} className={`flex items-center gap-2.5 rounded-lg border bg-[#171513] p-2 ${selected.has(entry.nodeId) ? 'border-[#73a7ff]/60' : 'border-[#393633]'}`}>
            <Checkbox checked={selected.has(entry.nodeId)} onChange={() => toggle(entry.nodeId)} label={`选择 ${entry.title}`} />
            <div className="grid h-12 w-20 shrink-0 place-items-center overflow-hidden rounded-md border border-[#393633] bg-[#211f1d] text-[10px] text-[#6f6862]">
              {entry.mediaUrl
                ? <button type="button" title="点击放大查看" onClick={() => setPreview({ url: entry.mediaUrl, title: entry.title, isVideo: entry.kind === 'video' })} className="h-full w-full cursor-zoom-in">{entry.kind === 'video' ? <video src={entry.mediaUrl} muted preload="metadata" disablePictureInPicture disableRemotePlayback tabIndex={-1} className="pointer-events-none h-full w-full object-cover" /> : <MediaImage src={entry.mediaUrl} alt={entry.title} width={480} className="h-full w-full object-cover" />}</button>
                : '暂无'}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs font-medium text-[#f0ebde]" title={entry.title}>{entry.title}</div>
              <div className="mt-0.5 flex items-center gap-2 text-[11px] text-[#8f8984]">
                {entry.duration !== null && <span>{entry.duration} 秒</span>}
                <StatusBadge status={statuses.get(entry.nodeId)} generated={entry.generated} />
              </div>
            </div>
            <button type="button" title="在画布中定位" onClick={() => onFocus(entry.nodeId)} className="rounded p-1 text-[#958d86] hover:bg-white/10 hover:text-white"><LocateFixed className="h-3.5 w-3.5" /></button>
          </div>
        ))}
        {visibleCandidates.length > 0 && (
          <div className="rounded-lg border border-dashed border-[#4a4540] p-2.5">
            <button type="button" onClick={() => setCandidatesOpen((open) => !open)} className="flex w-full items-center justify-between text-left text-xs text-[#c9c1ba]">
              <span>可选资产 <span className="text-[#8f8984]">{visibleCandidates.length}</span></span>
              <span className="text-[10px] text-[#7d756e]">{candidatesOpen ? '收起' : '展开'}</span>
            </button>
            <p className="mt-1 text-[10px] leading-4 text-[#7d756e]">这些角色、场景和道具出现次数少，已在分镜提示词里一句带过。后续还会再出现、需要保证前后一致时，点「添加」再单独生成。</p>
            {candidatesOpen && (
              <ul className="mt-2 space-y-1.5">
                {visibleCandidates.map((item) => (
                  <li key={`${item.role}:${item.name}`} className="flex items-start justify-between gap-2 rounded-md bg-[#171513] px-2 py-1.5">
                    <div className="min-w-0">
                      <div className="truncate text-xs text-[#e1ddd9]"><span className="mr-1 rounded bg-white/5 px-1 py-0.5 text-[10px] text-[#8f8984]">{ASSET_KIND_LABEL[item.role]}</span>{item.name}</div>
                      <div className="mt-0.5 line-clamp-2 text-[10px] text-[#7d756e]">{item.desc}</div>
                    </div>
                    <button type="button" onClick={() => onAddCandidate(item)} className="shrink-0 rounded-md border border-[#4a4540] px-2 py-0.5 text-[11px] text-[#e1ddd9] hover:border-[#73a7ff]">添加</button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
      {preview && <MediaLightbox url={preview.url} title={preview.title} isVideo={preview.isVideo} onClose={() => setPreview(null)} />}
      {(selected.size > 0 || batch) && (
        <div className="shrink-0 border-t border-[#393633] bg-[#1b1917] px-3 py-2.5">
          {batch ? (
            <div>
              <div className="flex items-center justify-between text-xs text-[#e1ddd9]">
                <span className="inline-flex items-center gap-1.5"><Loader2 className="h-3.5 w-3.5 animate-spin text-[#73a7ff]" />批量生成中 {batch.done}/{batch.total}{batch.failed > 0 && <span className="text-rose-300">，失败 {batch.failed}</span>}</span>
                <button type="button" onClick={onCancelBatch} className="rounded-md border border-[#4a4540] px-2 py-0.5 text-[11px] hover:border-rose-400 hover:text-rose-300">取消</button>
              </div>
              <div className="mt-1.5 h-1 overflow-hidden rounded bg-white/10"><div className="h-full bg-[#73a7ff] transition-all" style={{ width: `${batch.total ? Math.round((batch.done / batch.total) * 100) : 0}%` }} /></div>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <div className="min-w-0 flex-1 text-[11px] leading-4 text-[#a79f98]">
                <div className="text-[#e1ddd9]">已选 {selectedIds.length} 项{selectedIds.length - pendingIds.length > 0 && `，${selectedIds.length - pendingIds.length} 项已生成将跳过`}</div>
                {pendingIds.length > 0 && <div className={`truncate ${cost?.sufficient === false ? 'text-rose-300' : ''}`} title={cost?.warnings.join('\n')}>{cost ? formatCostLine(cost).replace(/^待生成：/, '') : '正在预估花费…'}</div>}
              </div>
              <button type="button" disabled={busy || pendingIds.length === 0 || cost?.sufficient === false} onClick={() => onBatchGenerate(pendingIds)} className="shrink-0 rounded-lg bg-[#73a7ff] px-3 py-1.5 text-xs font-semibold text-[#111827] hover:bg-[#8db6ff] disabled:cursor-not-allowed disabled:opacity-40">生成所选 ({pendingIds.length})</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
