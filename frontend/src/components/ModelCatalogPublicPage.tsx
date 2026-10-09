import { ArrowRight } from 'lucide-react';
import { ModelCatalogPage } from './ModelCatalogPage';

/** 未登录访客可访问的模型广场：沿用公开定价页的外壳样式 */
export function ModelCatalogPublicPage({
  onBack,
  onLogin,
  onRegister,
}: {
  onBack: () => void;
  onLogin: () => void;
  onRegister: () => void;
}) {
  return (
    <div className="min-h-screen bg-[#f7f8f5] px-4 py-10">
      <div className="mx-auto max-w-7xl">
        <div className="mb-6 flex items-center justify-between gap-3">
          <button onClick={onBack} className="text-sm text-slate-600 hover:text-slate-900">
            返回首页
          </button>
          <div className="flex items-center gap-2">
            <button onClick={onLogin} className="rounded-full border border-[#d9dfd7] bg-white px-4 py-2 text-sm text-slate-700">
              登录
            </button>
            <button onClick={onRegister} className="inline-flex items-center gap-2 rounded-full bg-[#2563eb] px-4 py-2 text-sm font-medium text-white transition hover:bg-[#1d4ed8]">
              免费注册
              <ArrowRight size={15} />
            </button>
          </div>
        </div>
        <ModelCatalogPage publicMode />
      </div>
    </div>
  );
}
