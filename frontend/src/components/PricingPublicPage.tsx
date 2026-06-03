import type { PublicPlan } from '../api';
import { UserPricingPage } from './UserPricingPage';

/** 未登录状态下展示的公开定价页面 */
export function PricingPublicPage({
  onBack,
  plans,
  onRegister,
}: {
  onBack: () => void;
  plans: PublicPlan[];
  onRegister: () => void;
}) {
  return (
    <div className="min-h-screen bg-[#f7f8f5] px-4 py-10">
      <div className="mx-auto max-w-6xl">
        <button onClick={onBack} className="mb-6 text-sm text-slate-600 hover:text-slate-900">返回首页</button>
        <UserPricingPage plans={plans} onPrimary={onRegister} />
      </div>
    </div>
  );
}
