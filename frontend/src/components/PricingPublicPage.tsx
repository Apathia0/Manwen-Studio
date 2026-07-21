import { UserPricingPage } from './UserPricingPage';

export function PricingPublicPage({
  onBack,
  onRegister,
}: {
  onBack: () => void;
  plans?: unknown[];
  onRegister: () => void;
}) {
  return (
    <div className="min-h-screen bg-[#f7f8f5] px-4 py-10">
      <div className="mx-auto max-w-6xl">
        <button onClick={onBack} className="mb-6 text-sm text-slate-600 hover:text-slate-900">
          返回首页
        </button>
        <UserPricingPage onPrimary={onRegister} />
      </div>
    </div>
  );
}
