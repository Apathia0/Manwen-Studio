import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Check, ChevronUp, Loader2, RotateCcw, Waypoints } from 'lucide-react';
import {
  approveCanvasCheckpoint,
  bindCanvasReferences,
  getCanvasReview,
  previewCanvasRedo,
  smartConnectCanvas,
  type SmartConnectResult,
  redoCanvasScene,
  type CanvasRedoPreview,
  type CanvasReview,
  type CanvasReviewCheckpoint,
  type CanvasReviewIssue,
  type CanvasPipelineTask,
  type RedoStage,
  type ReviewCheckpointKey,
} from '../../api';
import { normalizeErrorMessage } from '../../lib/errors';
import type { GhostEdge } from './CanvasConnectionLayer';
import { toast } from '../../lib/toast';

interface Props {
  canvasId: number;
  /** 画布已保存版本号：变化时重新质检 */
  revision: number;
  /** 手动刷新画布时递增，强制重新质检（版本号没变也要重新拉） */
  refreshKey?: number;
  /** 后台编排进行中不允许确认 / 重做，也不重复拉取 */
  busy: boolean;
  /** 质检可能依赖未保存内容：确认或重做前先保存 */
  onBeforeAction: () => Promise<boolean>;
  /** 确认 / 重做会产生新版本，通知外部刷新画布 */
  onChanged: () => void;
  onRedoStarted: (task: CanvasPipelineTask | null) => void;
  onFocusNode: (nodeId: string) => void;
  /** 智能连线预览：把将新增 / 将移除的连线叠加画在画布上；传空数组清除 */
  onPreviewEdges?: (edges: GhostEdge[]) => void;
}

const STAGE_LABEL: Record<RedoStage, string> = { director: '导演编排', assets: '资产分析', compile: '分镜编排' };
const STATUS_STYLE: Record<CanvasReviewCheckpoint['status'], string> = {
  pending: 'border-[#393633] text-[#7d756e]',
  blocked: 'border-rose-500/50 bg-rose-500/15 text-rose-300',
  ready: 'border-amber-400/40 bg-amber-400/10 text-amber-200',
  approved: 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300',
};
const STATUS_TEXT: Record<CanvasReviewCheckpoint['status'], string> = { pending: '未开始', blocked: '需处理', ready: '待确认', approved: '已确认' };

/**
 * 三个审核点（剧本 / 资产 / 分镜）：自动质检后只把"需要你看的地方"摆出来。
 * 有问题的审核点可以一键从某阶段重做单个场景，重做前先预览会影响多少节点。
 */
export default function CanvasReviewPanel({ canvasId, revision, refreshKey = 0, busy, onBeforeAction, onChanged, onRedoStarted, onFocusNode, onPreviewEdges }: Props) {
  const [review, setReview] = useState<CanvasReview | null>(null);
  const [open, setOpen] = useState<ReviewCheckpointKey | null>(null);
  const [working, setWorking] = useState(false);
  const [connectPlan, setConnectPlan] = useState<SmartConnectResult | null>(null);
  // 预览里用户取消勾选的变更（key 集合）；默认全部应用
  const [skipped, setSkipped] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (!onPreviewEdges) return;
    if (!connectPlan) { onPreviewEdges([]); return; }
    onPreviewEdges([
      ...connectPlan.added.filter((item) => !skipped.has(`add:${item.key}`)).map((item) => ({ key: item.key, source: item.source, target: item.target, sourceHandle: item.source_handle, targetHandle: item.target_handle, kind: 'add' as const })),
      ...connectPlan.removed.filter((item) => !skipped.has(`remove:${item.key}`)).map((item) => ({ key: item.key, source: item.source, target: item.target, sourceHandle: item.source_handle, targetHandle: item.target_handle, kind: 'remove' as const })),
    ]);
  }, [connectPlan, skipped, onPreviewEdges]);
  // 面板卸载时清掉画布上的预览线
  useEffect(() => () => onPreviewEdges?.([]), [onPreviewEdges]);
  const [redo, setRedo] = useState<{ issue: CanvasReviewIssue; preview: CanvasRedoPreview } | null>(null);
  const canvasRef = useRef(canvasId);
  useEffect(() => { canvasRef.current = canvasId; }, [canvasId]);

  const load = useCallback(async () => {
    try {
      const { review: next } = await getCanvasReview(canvasId);
      if (canvasRef.current === canvasId) setReview(next);
    } catch { /* 质检是辅助信息，拉取失败不打扰创作 */ }
  }, [canvasId]);

  useEffect(() => {
    if (busy) return undefined;
    const timer = window.setTimeout(() => void load(), 300);
    return () => window.clearTimeout(timer);
  }, [load, revision, busy, refreshKey]);

  if (!review) return null;
  const checkpoints = Object.values(review.checkpoints);
  if (checkpoints.every((item) => item.status === 'pending')) return null;
  const current = open ? review.checkpoints[open] : null;

  const approve = async (key: ReviewCheckpointKey) => {
    if (working || !(await onBeforeAction())) return;
    setWorking(true);
    try {
      const result = await approveCanvasCheckpoint(canvasId, key);
      setReview(result.review);
      toast.success(`已确认「${result.review.checkpoints[key].label}」`);
      onChanged();
    } catch (error) { toast.error(normalizeErrorMessage(error, '确认失败')); }
    finally { setWorking(false); }
  };

  const bindReferences = async () => {
    if (working || !(await onBeforeAction())) return;
    setWorking(true);
    try {
      const result = await bindCanvasReferences(canvasId);
      setReview(result.review);
      toast.success(result.added > 0 ? `已给视频节点补连 ${result.added} 条角色 / 场景参考图` : '没有需要补连的参考图');
      onChanged();
    } catch (error) { toast.error(normalizeErrorMessage(error, '补连参考图失败')); }
    finally { setWorking(false); }
  };

  // 智能连线：先预览（不改画布），确认后再应用。
  const previewConnect = async () => {
    if (working) return;
    if (connectPlan) { setConnectPlan(null); return; }
    if (!(await onBeforeAction())) return;
    setWorking(true);
    setOpen(null);
    try { setSkipped(new Set()); setConnectPlan(await smartConnectCanvas(canvasId, false)); }
    catch (error) { toast.error(normalizeErrorMessage(error, '智能连线失败')); }
    finally { setWorking(false); }
  };
  const applyConnect = async () => {
    if (working || !connectPlan) return;
    setWorking(true);
    try {
      const result = await smartConnectCanvas(canvasId, true, {
        added: connectPlan.added.filter((item) => skipped.has(`add:${item.key}`)).map((item) => item.key),
        removed: connectPlan.removed.filter((item) => skipped.has(`remove:${item.key}`)).map((item) => item.key),
      });
      toast.success(`智能连线完成：新增 ${result.added.length} 条，移除 ${result.removed.length} 条`);
      setConnectPlan(null);
      void load();
      onChanged();
    } catch (error) { toast.error(normalizeErrorMessage(error, '智能连线失败')); }
    finally { setWorking(false); }
  };

  const askRedo = async (issue: CanvasReviewIssue) => {
    if (!issue.scene_node_id || !issue.redo_stage || working) return;
    setWorking(true);
    try { setRedo({ issue, preview: await previewCanvasRedo(canvasId, issue.scene_node_id, issue.redo_stage) }); }
    catch (error) { toast.error(normalizeErrorMessage(error, '获取重做影响失败')); }
    finally { setWorking(false); }
  };

  const confirmRedo = async () => {
    if (!redo || working || !redo.issue.scene_node_id || !redo.issue.redo_stage) return;
    if (!(await onBeforeAction())) return;
    setWorking(true);
    try {
      const result = await redoCanvasScene(canvasId, redo.issue.scene_node_id, redo.issue.redo_stage, undefined);
      setRedo(null);
      setOpen(null);
      onRedoStarted(result.task);
      onChanged();
    } catch (error) { toast.error(normalizeErrorMessage(error, '局部重做失败')); }
    finally { setWorking(false); }
  };

  return (
    <div className="relative flex flex-wrap items-center justify-center gap-1.5">
      <span className="text-[11px] text-[#7d756e]">质检</span>
      {checkpoints.map((item) => (
        <button
          key={item.key}
          type="button"
          disabled={item.status === 'pending'}
          onClick={() => { setOpen(open === item.key ? null : item.key); setRedo(null); }}
          className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] ${STATUS_STYLE[item.status]} ${open === item.key ? 'ring-1 ring-[#73a7ff]' : ''}`}
          title={item.status === 'pending' ? '还没有可检查的内容' : '点击查看质检结果'}
        >
          {item.status === 'approved' ? <Check className="h-3 w-3" /> : item.status === 'blocked' ? <AlertTriangle className="h-3 w-3" /> : null}
          {item.label} · {STATUS_TEXT[item.status]}
          {item.status !== 'approved' && item.issues.length > 0 && <span className="opacity-80">({item.issues.length})</span>}
        </button>
      ))}

      <button type="button" disabled={busy || working} onClick={() => void previewConnect()} title="按规则补齐 / 重排分镜图、视频与角色参考图的连线，并检查连线问题（先预览，不会生成或扣费）"
        className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] disabled:opacity-40 ${connectPlan ? 'border-[#73a7ff] text-[#9fc2ff]' : 'border-[#4a4540] text-[#e1ddd9] hover:border-[#73a7ff]'}`}>
        {working && !current ? <Loader2 className="h-3 w-3 animate-spin" /> : <Waypoints className="h-3 w-3" />}智能连线
      </button>

      {connectPlan && (() => {
        const rows = [
          ...connectPlan.added.map((item) => ({ id: `add:${item.key}`, kind: 'add' as const, item })),
          ...connectPlan.removed.map((item) => ({ id: `remove:${item.key}`, kind: 'remove' as const, item })),
        ];
        // 按"目标节点"分组，报告读起来是"镜头 2：+ 萧炎、+ 宴会厅、− 路人"
        const groups = rows.reduce<Record<string, { targetId: string; rows: typeof rows }>>((acc, row) => {
          const key = row.item.target_label || row.item.target;
          (acc[key] ||= { targetId: row.item.target, rows: [] }).rows.push(row);
          return acc;
        }, {});
        const selectedCount = rows.filter((row) => !skipped.has(row.id)).length;
        const toggle = (id: string) => setSkipped((current) => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; });
        return (
          <div className="pointer-events-auto absolute bottom-full left-1/2 z-50 mb-2 w-[min(32rem,calc(100vw-2rem))] -translate-x-1/2 rounded-xl border border-[#393633] bg-[#211f1d] p-3 text-left shadow-2xl">
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="text-xs font-semibold text-[#e1ddd9]">智能连线报告</span>
              <button type="button" onClick={() => setConnectPlan(null)} className="text-[#7d756e] hover:text-[#e1ddd9]" aria-label="收起"><ChevronUp className="h-4 w-4" /></button>
            </div>
            <p className="mb-2 text-[11px] leading-4 text-[#a79f98]">
              将新增 <b className="text-emerald-300">{connectPlan.added.length}</b> 条 · 将移除 <b className="text-rose-300">{connectPlan.removed.length}</b> 条 · 提示 {connectPlan.issues.length} 条。
              画布上<span className="text-emerald-300">绿色虚线</span>是将新增的连线，<span className="text-rose-300">红色虚线</span>是将移除的连线；取消勾选的变更不会应用。
            </p>
            <div className="max-h-64 space-y-2 overflow-y-auto pr-1 text-[11px] leading-4">
              {!connectPlan.changed && <p className="text-emerald-300">连线已经是最新的，不需要调整。</p>}
              {Object.entries(groups).map(([label, group]) => (
                <div key={label} className="rounded-md border border-[#393633] bg-[#1a1816] p-2">
                  <button type="button" onClick={() => onFocusNode(group.targetId)} className="mb-1 text-left font-medium text-[#e1ddd9] hover:text-[#9fc2ff]" title="在画布上定位">{label}</button>
                  <ul className="space-y-0.5">
                    {group.rows.map((row) => (
                      <li key={row.id}>
                        <label className="flex cursor-pointer items-center gap-1.5">
                          <input type="checkbox" checked={!skipped.has(row.id)} onChange={() => toggle(row.id)} className="h-3 w-3 accent-[#73a7ff]" />
                          <span className={row.kind === 'add' ? 'text-emerald-300' : 'text-rose-300'}>{row.kind === 'add' ? '＋ 连入' : '－ 移除'}</span>
                          <span className="min-w-0 flex-1 truncate text-[#cfc9c3]">{row.item.source_label}</span>
                        </label>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
              {connectPlan.issues.length > 0 && (
                <div><p className="mb-1 text-[#a79f98]">连线检查（需要你留意）</p>
                  <ul className="space-y-1">{connectPlan.issues.map((issue, index) => (
                    <li key={`${issue.code}-${index}`} className="flex items-start gap-1.5 rounded-md border border-[#393633] bg-[#1a1816] p-1.5">
                      <AlertTriangle className={`mt-0.5 h-3 w-3 shrink-0 ${issue.severity === 'error' ? 'text-rose-300' : issue.severity === 'warning' ? 'text-amber-300' : 'text-[#7d756e]'}`} />
                      <span className="min-w-0 flex-1 text-[#cfc9c3]">{issue.message}</span>
                      {issue.node_ids[0] && <button type="button" onClick={() => onFocusNode(issue.node_ids[0])} className="shrink-0 text-[#9fc2ff] hover:underline">定位</button>}
                    </li>))}</ul></div>
              )}
            </div>
            <div className="mt-2 flex items-center justify-between gap-2 border-t border-[#393633] pt-2">
              <span className="text-[11px] text-[#7d756e]">只调整连线，不会生成或扣费；手动拉的线不会被动。已选 {selectedCount}/{rows.length} 项</span>
              <div className="flex shrink-0 gap-1.5">
                <button type="button" onClick={() => setConnectPlan(null)} className="rounded-md border border-[#4a4540] px-2.5 py-1 text-[11px] text-[#e1ddd9] hover:border-[#73a7ff]">取消</button>
                <button type="button" disabled={busy || working || selectedCount === 0} onClick={() => void applyConnect()} className="inline-flex items-center gap-1 rounded-md bg-[#73a7ff] px-3 py-1 text-[11px] font-semibold text-[#111827] hover:bg-[#8db6ff] disabled:cursor-not-allowed disabled:opacity-40">
                  {working && <Loader2 className="h-3 w-3 animate-spin" />}应用所选
                </button>
              </div>
            </div>
          </div>
        );
      })()}

      {current && (
        <div className="pointer-events-auto absolute bottom-full left-1/2 z-50 mb-2 w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 rounded-xl border border-[#393633] bg-[#211f1d] p-3 text-left shadow-2xl">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="text-xs font-semibold text-[#e1ddd9]">{current.label}</span>
            <button type="button" onClick={() => { setOpen(null); setRedo(null); }} className="text-[#7d756e] hover:text-[#e1ddd9]" aria-label="收起"><ChevronUp className="h-4 w-4" /></button>
          </div>

          {current.issues.length === 0 ? (
            <p className="text-[11px] text-emerald-300">自动质检没有发现问题。</p>
          ) : (
            <ul className="max-h-56 space-y-1.5 overflow-y-auto pr-1">
              {current.issues.map((issue) => (
                <li key={issue.id} className="rounded-md border border-[#393633] bg-[#1a1816] p-2">
                  <div className="flex items-start gap-1.5">
                    <AlertTriangle className={`mt-0.5 h-3 w-3 shrink-0 ${issue.severity === 'error' ? 'text-rose-300' : 'text-amber-300'}`} />
                    <p className="min-w-0 flex-1 text-[11px] leading-4 text-[#cfc9c3]">{issue.message}</p>
                  </div>
                  <div className="mt-1.5 flex flex-wrap justify-end gap-1.5">
                    {issue.node_ids.length > 0 && (
                      <button type="button" onClick={() => onFocusNode(issue.node_ids[0])} className="rounded border border-[#4a4540] px-2 py-0.5 text-[11px] text-[#e1ddd9] hover:border-[#73a7ff]">定位节点</button>
                    )}
                    {issue.action === 'bind_references' && (
                      <button type="button" disabled={busy || working} onClick={() => void bindReferences()} className="rounded border border-[#73a7ff]/60 px-2 py-0.5 text-[11px] text-[#9fc2ff] hover:bg-[#73a7ff]/10 disabled:opacity-40">一键补连参考图</button>
                    )}
                    {issue.redo_stage && issue.scene_node_id && (
                      <button type="button" disabled={busy || working} onClick={() => void askRedo(issue)} className="inline-flex items-center gap-1 rounded border border-amber-400/50 px-2 py-0.5 text-[11px] text-amber-200 hover:bg-amber-400/10 disabled:opacity-40">
                        <RotateCcw className="h-3 w-3" />重做{STAGE_LABEL[issue.redo_stage]}
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}

          {redo && (
            <div className="mt-2 rounded-md border border-amber-400/40 bg-amber-400/10 p-2 text-[11px] leading-4 text-amber-100">
              <p>
                将从「{STAGE_LABEL[redo.preview.from_stage]}」起重做场景「{redo.preview.scene_label}」：作废 {redo.preview.asset_count} 个资产、{redo.preview.shot_count} 个镜头节点，其他场景不受影响。
                {redo.preview.generated_count > 0 && <> 其中 <b>{redo.preview.generated_count}</b> 个已生成过，重做后需要重新生成（会重新计费）。</>}
                {redo.preview.kept_locked_count > 0 && <> 已锁定的 {redo.preview.kept_locked_count} 个资产会保留。</>}
                只重新编排，不会自动提交出图和视频。
              </p>
              <div className="mt-1.5 flex justify-end gap-1.5">
                <button type="button" onClick={() => setRedo(null)} className="rounded border border-[#4a4540] px-2 py-0.5 text-[#e1ddd9]">取消</button>
                <button type="button" disabled={working} onClick={() => void confirmRedo()} className="inline-flex items-center gap-1 rounded bg-amber-300 px-2 py-0.5 font-semibold text-[#2b2110] disabled:opacity-50">
                  {working && <Loader2 className="h-3 w-3 animate-spin" />}确认重做
                </button>
              </div>
            </div>
          )}

          <div className="mt-2 flex items-center justify-between gap-2 border-t border-[#393633] pt-2">
            <span className="text-[11px] text-[#7d756e]">
              {busy && current.status !== 'blocked' && current.status !== 'approved' ? '任务运行中，完成后即可确认' : current.status === 'blocked' ? `还有 ${current.error_count} 个必须处理的问题` : current.status === 'approved' ? '内容再变动后需要重新确认' : '没有必须处理的问题，可以确认'}
            </span>
            <button
              type="button"
              disabled={busy || working || current.status === 'blocked' || current.status === 'approved'}
              onClick={() => void approve(current.key)}
              className="rounded-md bg-[#73a7ff] px-3 py-1 text-[11px] font-semibold text-[#111827] hover:bg-[#8db6ff] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {current.status === 'approved' ? '已确认' : '确认通过'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
