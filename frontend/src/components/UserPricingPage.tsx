import type { PublicPlan, MySubscriptionResponse } from '../api';
import { formatMoney, featureLabel, formatFeatureValue } from '../lib/format';

/** 已登录用户套餐订阅页面 */
export function UserPricingPage({
  plans,
  onPrimary,
  subscription,
  onSubscribe,
  subscribingPlanId,
}: {
  plans: PublicPlan[];
  onPrimary?: () => void;
  subscription?: MySubscriptionResponse | null;
  onSubscribe?: (planId: number, billingCycle: 'monthly' | 'yearly') => void;
  subscribingPlanId?: number | null;
}) {
  const fallback = [
    { id: 0, name: 'Free', monthly_price: 0, description: '适合体验和轻量创作', features: { 'framework.generate.monthly_limit': 5, 'chapter.expand.monthly_limit': 20, 'scene.generate.monthly_limit': 15, 'manga.image.generate.monthly_limit': 100, 'ai.text.advanced_calls.monthly_limit': 20, 'deconstruction.run.monthly_limit': 1, 'manga.max_image_count_per_chapter': 6, 'manga.allow_color_mode': false, 'video.shot.split.monthly_limit': 0, 'video.generate.count.monthly_limit': 0 } },
    { id: 1, name: 'Pro', monthly_price: 59, description: '适合稳定更新的个人创作者', features: { 'framework.generate.monthly_limit': 50, 'chapter.expand.monthly_limit': 200, 'scene.generate.monthly_limit': 120, 'manga.image.generate.monthly_limit': 1100, 'ai.text.advanced_calls.monthly_limit': 180, 'deconstruction.run.monthly_limit': 20, 'manga.max_image_count_per_chapter': 12, 'manga.allow_color_mode': true, 'video.shot.split.monthly_limit': 5, 'video.generate.count.monthly_limit': 5 } },
    { id: 2, name: 'Premium', monthly_price: 199, description: '适合高频产出的团队和工作室', features: { 'framework.generate.monthly_limit': 200, 'chapter.expand.monthly_limit': 1000, 'scene.generate.monthly_limit': 500, 'manga.image.generate.monthly_limit': 5500, 'ai.text.advanced_calls.monthly_limit': 600, 'deconstruction.run.monthly_limit': 80, 'manga.max_image_count_per_chapter': 20, 'manga.allow_color_mode': true, 'video.shot.split.monthly_limit': 10, 'video.generate.count.monthly_limit': 15 } },
  ];
  const data = plans.length > 0 ? plans : (fallback as any[]);

  return (
    <div>
      <h2 className="text-xl font-semibold">套餐订阅</h2>
      <p className="mt-1 text-sm text-slate-600">所有小说创作、分镜生成和漫画出图能力都由平台套餐统一控制。你可以在这里直观看到不同套餐的额度差异和适用场景。</p>
      <div className="mt-4 grid gap-4 md:grid-cols-3">
        {data.map((plan: any) => {
          const isCurrent = subscription?.subscription.plan.id === plan.id;
          const highlights = [
            ['framework.generate.monthly_limit', plan.features?.['framework.generate.monthly_limit'] ?? 0],
            ['chapter.expand.monthly_limit', plan.features?.['chapter.expand.monthly_limit'] ?? 0],
            ['scene.generate.monthly_limit', plan.features?.['scene.generate.monthly_limit'] ?? 0],
            ['manga.image.generate.monthly_limit', plan.features?.['manga.image.generate.monthly_limit'] ?? 0],
            ['ai.text.advanced_calls.monthly_limit', plan.features?.['ai.text.advanced_calls.monthly_limit'] ?? 0],
            ['deconstruction.run.monthly_limit', plan.features?.['deconstruction.run.monthly_limit'] ?? 0],
            ['video.shot.split.monthly_limit', plan.features?.['video.shot.split.monthly_limit'] ?? 0],
            ['video.generate.count.monthly_limit', plan.features?.['video.generate.count.monthly_limit'] ?? 0],
          ] as const;

          return (
            <div key={plan.id ?? plan.name} className="rounded-3xl border border-[#d7e3f4] bg-white/95 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
              <div className="flex items-center justify-between">
                <div className="text-base font-semibold text-slate-900">{plan.name}</div>
                {isCurrent ? <span className="rounded-full bg-[#eff6ff] px-3 py-1 text-xs text-[#1d4ed8]">当前套餐</span> : null}
              </div>
              <div className="mt-3 text-3xl font-semibold text-slate-900">
                ¥{formatMoney(plan.monthly_price)}
                <span className="ml-1 text-sm font-normal text-slate-500">/月</span>
              </div>
              <div className="mt-2 text-sm leading-6 text-slate-500">{plan.description || '暂无套餐说明'}</div>
              <div className="mt-4 space-y-2 rounded-2xl bg-[#f8fbff] p-3">
                {highlights.map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between text-sm">
                    <span className="text-slate-600">{featureLabel(key)}</span>
                    <span className="font-medium text-slate-900">{formatFeatureValue(key, value)}</span>
                  </div>
                ))}
              </div>
              <div className="mt-4 rounded-2xl border border-dashed border-[#d7e3f4] px-3 py-3 text-xs leading-6 text-slate-500">
                {plan.features?.['manga.allow_color_mode'] ? '支持彩漫模式' : '支持黑白漫画模式'}
                ，单章节最多生成 {plan.features?.['manga.max_image_count_per_chapter'] ?? 0} 张图片。
              </div>
              {onSubscribe ? (
                <button
                  onClick={() => onSubscribe(plan.id, 'monthly')}
                  disabled={isCurrent || subscribingPlanId === plan.id}
                  className="mt-5 w-full rounded-2xl bg-[#1d4ed8] py-2.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isCurrent ? '已生效' : subscribingPlanId === plan.id ? '处理中...' : '立即订阅'}
                </button>
              ) : null}
              {!onSubscribe && onPrimary ? (
                <button onClick={onPrimary} className="mt-5 w-full rounded-2xl bg-[#1d4ed8] py-2.5 text-sm font-medium text-white">开始使用</button>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
