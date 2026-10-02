import { useEffect, useState } from 'react';
import { ClipboardList, Loader2, Minimize2 } from 'lucide-react';
import type { VideoCanvasPlan } from '../../api';

interface Props {
  plans: VideoCanvasPlan[];
  loading: boolean;
  applyingPlanId: number | null;
  onRefresh: () => void;
  onConfirm: (plan: VideoCanvasPlan) => void;
  onSync: (plan: VideoCanvasPlan) => void;
  onApply: (plan: VideoCanvasPlan) => void;
}

const STATUS_TEXT: Record<string, { label: string; className: string }> = {
  applied: { label: '已应用', className: 'text-emerald-300' },
  approved: { label: '已确认', className: 'text-sky-300' },
  ready: { label: '待确认', className: 'text-amber-300' },
};

/**
 * 创作计划悬浮胶囊：没有计划时不显示；有计划时默认收成胶囊，点击展开为卡片。
 * 展开层级高于画布上其他浮层（工具栏、角色库、节点），避免被覆盖。
 */
export default function CanvasPlanCapsule({ plans, loading, applyingPlanId, onRefresh, onConfirm, onSync, onApply }: Props) {
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!expanded) return undefined;
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setExpanded(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [expanded]);

  if (plans.length === 0) return null;
  const pending = plans.filter((plan) => plan.status === 'ready').length;

  if (!expanded) {
    return (
      <button
        type="button"
        title="展开创作计划"
        onClick={() => setExpanded(true)}
        className="compact-controls absolute left-4 top-4 z-[60] inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-[#25231f]/95 px-3 py-1.5 text-xs text-[#ded7d0] shadow-xl hover:bg-[#2f2c27]"
      >
        <ClipboardList className="h-3.5 w-3.5" />
        创作计划
        <span className="text-[#8f8984]">{plans.length}</span>
        {pending > 0 && <span className="h-2 w-2 rounded-full bg-amber-400" title={`${pending} 个计划待确认`} />}
      </button>
    );
  }

  return (
    <aside className="compact-controls absolute left-4 top-4 z-[60] w-80 max-w-[calc(100%-2rem)] overflow-hidden rounded-2xl border border-white/10 bg-[#25231f]/[.98] shadow-2xl">
      <div className="flex items-center justify-between gap-2 border-b border-white/[.08] px-3 py-2.5">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-[#f0ebde]">创作计划</p>
          <p className="mt-0.5 text-[10px] text-white/35">确认后可分别同步工作流或应用画布</p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button type="button" title="刷新创作计划" onClick={onRefresh} className="rounded-md p-1.5 text-white/45 hover:bg-white/10 hover:text-white">
            <Loader2 className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button type="button" onClick={() => setExpanded(false)} className="inline-flex items-center gap-1 rounded-full border border-white/10 px-2.5 py-1 text-[11px] text-[#ded7d0] hover:bg-white/10">
            <Minimize2 className="h-3 w-3" />收起为胶囊
          </button>
        </div>
      </div>
      <div className="max-h-[min(20rem,calc(100vh-10rem))] overflow-y-auto p-2">
        {loading && plans.length === 0 ? <p className="p-2 text-xs text-white/40">读取计划中</p> : plans.map((plan) => {
          const status = STATUS_TEXT[plan.status] || { label: '草案', className: 'text-white/35' };
          const shots = Array.isArray(plan.shots.shots) ? plan.shots.shots.length : 0;
          const assets = Array.isArray(plan.assets.assets) ? plan.assets.assets.length : 0;
          return (
            <div key={plan.id} className="border-b border-white/[.08] px-1 py-2 last:border-0">
              <div className="flex items-center justify-between">
                <span className="text-xs text-white/80">计划 #{plan.id}</span>
                <span className={`text-[10px] ${status.className}`}>{status.label}</span>
              </div>
              <p className="mt-1 text-[10px] text-white/35">镜头 {shots} · 资产 {assets}</p>
              {plan.status === 'ready' && (
                <button type="button" disabled={applyingPlanId === plan.id} onClick={() => onConfirm(plan)} className="mt-1.5 rounded bg-white px-2 py-1 text-[10px] font-medium text-[#17191c] disabled:opacity-40">确认计划</button>
              )}
              {['approved', 'applied'].includes(plan.status) && (
                <div className="mt-1.5 flex gap-1.5">
                  {!plan.workflow_id && <button type="button" disabled={applyingPlanId === plan.id} onClick={() => onSync(plan)} className="rounded bg-white/10 px-2 py-1 text-[10px] text-white/85 disabled:opacity-40">同步分镜</button>}
                  {plan.status === 'approved' && <button type="button" disabled={applyingPlanId === plan.id} onClick={() => onApply(plan)} className="rounded bg-[#73a7ff] px-2 py-1 text-[10px] font-medium text-[#111827] disabled:opacity-40">应用画布</button>}
                </div>
              )}
              {plan.workflow_id && <p className="mt-1 text-[10px] text-emerald-300/80">已同步工作流 #{plan.workflow_id}</p>}
            </div>
          );
        })}
      </div>
    </aside>
  );
}
