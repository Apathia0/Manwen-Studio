import { useState } from 'react';
import { AlertTriangle, Check, ChevronDown, ChevronUp, Loader2 } from 'lucide-react';
import type { CanvasCostEstimate, CanvasPipelineTask } from '../../api';
import { continuePrompt, formatCostLine, type PipelineSummary } from './canvasPipeline';

interface Props {
  summary: PipelineSummary;
  agentBusy: boolean;
  /** 待生成部分的成本预估；为空表示尚未取得 */
  cost?: CanvasCostEstimate | null;
  /** 让助手继续推进；由外部决定如何发送 */
  onContinue: (prompt: string) => void;
  /** 一键批量生成指定节点；正在批量或运行时 busy 为 true */
  onBatch?: (ids: string[]) => void;
  batchBusy?: boolean;
  /** 批量生成进度；有值时显示进度 */
  batch?: { total: number; done: number; failed: number } | null;
  /** 与当前画风不一致的已生成节点数，以及一键统一 */
  inconsistentCount?: number;
  onUnifyStyle?: () => void;
  /** 服务端自动编排任务（最近一次），以及启动 / 取消 */
  pipelineRun?: CanvasPipelineTask | null;
  onRunPipeline?: () => void;
  onCancelPipeline?: () => void;
  /** 三个审核点的质检面板（由外部提供，放在阶段进度下方） */
  reviewSlot?: React.ReactNode;
  /** 非空时自动收起成小胶囊（例如节点输入框打开时），值变化视为新的一次；用户点胶囊可临时展开 */
  autoCollapseKey?: string | null;
}

// v2：旧版本里任何一次手动折叠都会一直保留，新用户一进来就是收起的、不知道怎么往下走；换新键让所有人重新从“展开”开始
const COLLAPSE_STORAGE_KEY = 'canvas-pipeline-bar-collapsed-v2';
const readCollapsed = () => { try { return window.localStorage.getItem(COLLAPSE_STORAGE_KEY) === '1'; } catch { return false; } };
const writeCollapsed = (value: boolean) => { try { window.localStorage.setItem(COLLAPSE_STORAGE_KEY, value ? '1' : '0'); } catch { /* 存储不可用时只在本次有效 */ } };

const ACTIVE_RUN = new Set(['pending', 'running', 'retrying', 'cancel_requested']);

const dot: Record<string, string> = {
  done: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
  active: 'bg-[#73a7ff]/20 text-[#9fc2ff] border-[#73a7ff]/50',
  next: 'bg-amber-400/15 text-amber-200 border-amber-400/40',
  pending: 'bg-transparent text-[#7d756e] border-[#393633]',
  failed: 'bg-rose-500/20 text-rose-300 border-rose-500/50',
};

const secondaryButton = 'rounded-md border border-[#4a4540] px-2.5 py-1 text-[11px] font-medium text-[#e1ddd9] hover:border-[#73a7ff] disabled:cursor-not-allowed disabled:opacity-40';
const primaryButton = 'rounded-md bg-[#73a7ff] px-3 py-1 text-[11px] font-semibold text-[#111827] hover:bg-[#8db6ff]';
const warnButton = 'rounded-md border border-amber-400/50 bg-amber-400/10 px-2.5 py-1 text-[11px] font-medium text-amber-200 hover:bg-amber-400/20 disabled:cursor-not-allowed disabled:opacity-40';

/**
 * 画布底部流水线，三行：
 * ① 阶段进度  ② 当前状态说明（下一步、花费、失败原因、批量进度）  ③ 可执行的操作按钮
 */
export default function CanvasPipelineBar({ summary, agentBusy, cost, onContinue, onBatch, batchBusy = false, batch = null, inconsistentCount = 0, onUnifyStyle, pipelineRun = null, onRunPipeline, onCancelPipeline, reviewSlot, autoCollapseKey = null }: Props) {
  const [manualCollapsed, setManualCollapsed] = useState(readCollapsed);
  const [peekedKey, setPeekedKey] = useState<string | null>(null);
  const [announcedBusy, setAnnouncedBusy] = useState(false);
  // 输入框关闭后清掉临时展开记录，下次再打开同一个节点仍会自动收起
  if (autoCollapseKey === null && peekedKey !== null) setPeekedKey(null);
  const { stages, next, failure, pendingImages, pendingVideos, awaitingSceneApproval, pendingAssetIds, pendingShotIds, pendingVideoIds, shotsCompiled } = summary;
  // 还没开始创作时不显示，避免空画布上出现一排灰色阶段。
  const runActive = Boolean(pipelineRun && ACTIVE_RUN.has(pipelineRun.status));
  const runFailed = pipelineRun?.status === 'failed';
  // 一开始创作（助手 / 后台编排开始工作）就展开流程栏，让用户看到进度和下一步，即使之前手动收起过
  if ((runActive || agentBusy) && !announcedBusy) { setAnnouncedBusy(true); if (manualCollapsed) setManualCollapsed(false); }
  const runDone = pipelineRun?.status === 'succeeded';
  if (stages[0].state === 'next' && !agentBusy && !failure && !runFailed) return null;
  // 剧本之后的阶段交给服务端运行器（场景会被自动批准）；写剧本需要创作对话，仍交给助手。
  const useRunner = Boolean(onRunPipeline && next && next.byAgent && next.key !== 'screenplay');
  const canContinue = Boolean(next && next.byAgent && !agentBusy && (useRunner || !awaitingSceneApproval));
  const idle = !batch && !agentBusy;
  const showBatchButtons = Boolean(onBatch) && idle && !awaitingSceneApproval;

  // 第二行：只放文字说明，不放按钮
  const notes: Array<{ key: string; className?: string; title?: string; content: React.ReactNode }> = [];
  if (runActive) notes.push({ key: 'run', className: 'text-[#9fc2ff]', content: <span className="inline-flex items-center gap-1"><Loader2 className="h-3 w-3 animate-spin" />{pipelineRun?.message || '后台自动编排中'}，节点会实时出现在画布上，可以离开页面</span> });
  else if (agentBusy) notes.push({ key: 'busy', className: 'text-[#9fc2ff]', content: '助手正在编排，节点会实时出现在画布上' });
  if (!agentBusy && runFailed) notes.push({ key: 'run-failed', className: 'text-rose-300', content: `自动编排已停止：${pipelineRun?.error || pipelineRun?.message || '未知原因'}` });
  if (!agentBusy && runDone && (pipelineRun?.auto_fixes.length || 0) > 0) notes.push({ key: 'run-fixes', className: 'text-emerald-300', title: pipelineRun?.auto_fixes.join('\n'), content: `系统自动处理了 ${pipelineRun?.auto_fixes.length} 个问题（悬停查看）` });
  if (!agentBusy && awaitingSceneApproval && !useRunner) notes.push({ key: 'approve', className: 'text-amber-200', content: '场景已拆分：请在场景节点点击「批准」后继续（全自动模式会自动批准）' });
  if (!agentBusy && !awaitingSceneApproval && next && !next.byAgent) notes.push({ key: 'next', content: `下一步：在画布上提交「${next.label}」生成任务` });
  if (batch) notes.push({ key: 'batch', className: 'text-[#9fc2ff]', content: <span className="inline-flex items-center gap-1"><Loader2 className="h-3 w-3 animate-spin" />批量生成 {batch.done}/{batch.total}{batch.failed > 0 && <span className="text-rose-300">，失败 {batch.failed}</span>}</span> });
  if (pendingImages > 0 || pendingVideos > 0) {
    notes.push(cost
      ? { key: 'cost', className: cost.sufficient === false ? 'text-rose-300' : undefined, title: cost.warnings.join('\n'), content: formatCostLine(cost) }
      : { key: 'cost', content: `待生成：图片 ${pendingImages} · 视频 ${pendingVideos}` });
  }
  if (failure) notes.push({ key: 'failure', className: 'text-rose-300', content: `失败原因：${failure}` });

  // 第三行：操作按钮，主操作放最右
  const collapsed = manualCollapsed || (autoCollapseKey !== null && peekedKey !== autoCollapseKey);
  const currentStage = stages.find((stage) => stage.state === 'active' || stage.state === 'failed') || stages.find((stage) => stage.state === 'next');
  const hasActions = runActive || canContinue || (showBatchButtons && (pendingAssetIds.length > 0 || (shotsCompiled && (pendingShotIds.length > 0 || pendingVideoIds.length > 0)))) || Boolean(onUnifyStyle && inconsistentCount > 0 && idle);

  if (collapsed) {
    const pending = pendingImages + pendingVideos;
    const expand = () => { if (manualCollapsed) { setManualCollapsed(false); writeCollapsed(false); } else setPeekedKey(autoCollapseKey); };
    return (
      <div className="compact-controls pointer-events-none absolute bottom-[calc(.75rem+var(--safe-area-bottom))] left-[17.5rem] z-40">
        <button type="button" onClick={expand} title="展开创作流程" className="pointer-events-auto inline-flex h-10 items-center gap-2 rounded-full border border-[#393633] bg-[#211f1d]/95 px-3 text-[11px] text-[#e1ddd9] shadow-xl hover:border-[#73a7ff]">
          {runActive || agentBusy || batch ? <Loader2 className="h-3.5 w-3.5 animate-spin text-[#9fc2ff]" /> : failure || runFailed ? <AlertTriangle className="h-3.5 w-3.5 text-rose-300" /> : <Check className="h-3.5 w-3.5 text-emerald-300" />}
          <span>流程{currentStage ? ` · ${currentStage.label}` : ''}</span>
          {pending > 0 && <span className="text-[#a79f98]">待生成 {pending}</span>}
          <ChevronUp className="h-3.5 w-3.5 text-[#a79f98]" />
        </button>
      </div>
    );
  }

  return (
    <div className="compact-controls pointer-events-none absolute bottom-[calc(.75rem+var(--safe-area-bottom))] left-1/2 z-40 w-max max-w-[calc(100%-24rem)] -translate-x-1/2">
      <div className="pointer-events-auto relative flex flex-col items-center gap-2 rounded-xl border border-[#393633] bg-[#211f1d]/95 px-3 py-2.5 shadow-xl">
        <button type="button" onClick={() => { setManualCollapsed(true); writeCollapsed(true); }} title="收起流程栏" className="absolute -right-2 -top-2 flex h-5 w-5 items-center justify-center rounded-full border border-[#393633] bg-[#211f1d] text-[#a79f98] shadow hover:border-[#73a7ff] hover:text-[#e1ddd9]"><ChevronDown className="h-3 w-3" /></button>
        <div className="flex flex-wrap items-center justify-center gap-1">
          {stages.map((stage, index) => (
            <span key={stage.key} className="flex items-center gap-1">
              <span title={stage.byAgent ? 'AI 助手自动推进' : '需要你在画布上提交生成'} className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] ${dot[stage.state]}`}>
                {stage.state === 'done' && <Check className="h-3 w-3" />}
                {stage.state === 'active' && <Loader2 className="h-3 w-3 animate-spin" />}
                {stage.state === 'failed' && <AlertTriangle className="h-3 w-3" />}
                {stage.label}
              </span>
              {index < stages.length - 1 && <span className="text-[#544d47]">›</span>}
            </span>
          ))}
        </div>

        {reviewSlot}

        {notes.length > 0 && (
          <div className="flex max-w-full flex-col items-center gap-0.5 text-center text-[11px] leading-4 text-[#a79f98]">
            {notes.map((note) => <span key={note.key} title={note.title} className={note.className}>{note.content}</span>)}
          </div>
        )}

        {hasActions && (
          <div className="flex flex-wrap items-center justify-center gap-1.5 border-t border-[#393633] pt-2">
            {onUnifyStyle && inconsistentCount > 0 && idle && (
              <button type="button" disabled={batchBusy} onClick={onUnifyStyle} className={warnButton} title="这些图片/视频生成时的画风与当前设置不同，一键按当前画风重新生成（已锁定的不动）">统一画风 ({inconsistentCount})</button>
            )}
            {showBatchButtons && onBatch && pendingAssetIds.length > 0 && (
              <button type="button" disabled={batchBusy} onClick={() => onBatch(pendingAssetIds)} className={secondaryButton} title="并行生成尚未生成的角色、场景、道具图片">生成资产图 ({pendingAssetIds.length})</button>
            )}
            {showBatchButtons && onBatch && shotsCompiled && pendingShotIds.length > 0 && (
              <button type="button" disabled={batchBusy} onClick={() => onBatch(pendingShotIds)} className={secondaryButton} title="并行生成全部分镜图；依赖的资产图若未生成会先生成">生成全部分镜图 ({pendingShotIds.length})</button>
            )}
            {showBatchButtons && onBatch && shotsCompiled && pendingVideoIds.length > 0 && (
              <button type="button" disabled={batchBusy} onClick={() => onBatch(pendingVideoIds)} className={secondaryButton} title="并行生成全部视频；依赖的分镜图若未生成会先生成">生成全部视频 ({pendingVideoIds.length})</button>
            )}
            {runActive && onCancelPipeline && (
              <button type="button" onClick={onCancelPipeline} className={secondaryButton} title="当前这一步做完后停下，已完成的节点保留">取消自动编排</button>
            )}
            {canContinue && next && (useRunner
              ? <button type="button" onClick={onRunPipeline} className={primaryButton} title="在后台自动完成拆分、导演编排、资产分析、分镜编排，失败会自动重试；不会提交出图和视频">{runFailed ? '重试自动编排' : '一键自动编排'}</button>
              : <button type="button" onClick={() => onContinue(continuePrompt(next.key))} className={primaryButton}>{failure ? '让助手重试' : `继续：${next.label}`}</button>)}
          </div>
        )}
      </div>
    </div>
  );
}
