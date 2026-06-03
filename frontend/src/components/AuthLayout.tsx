import type { ReactNode } from 'react';

/** 认证页面通用布局容器 */
export function AuthLayout({
  brandName,
  brandSlogan,
  title,
  subtitle,
  children,
  onBack,
}: {
  brandName: string;
  brandSlogan: string;
  title: string;
  subtitle: string;
  children: ReactNode;
  onBack: () => void;
}) {
  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(59,130,246,0.18),_transparent_24%),linear-gradient(180deg,_#eef4ff_0%,_#f5f9ff_45%,_#f8fbff_100%)]">
      <div className="mx-auto max-w-md px-4 py-16">
        <button
          onClick={onBack}
          className="mb-6 inline-flex items-center rounded-full border border-[#d7e3f4] bg-white/88 px-4 py-2 text-sm text-slate-600 shadow-[0_10px_24px_rgba(59,130,246,0.08)] transition hover:bg-white hover:text-[#2563eb]"
        >
          返回首页
        </button>
        <div className="rounded-[28px] border border-[#d7e3f4] bg-white/96 p-7 shadow-[0_24px_60px_rgba(59,130,246,0.12)] backdrop-blur">
          <img src="/brand-mark.svg" alt={`${brandName} logo`} className="mb-5 h-11 w-11 rounded-2xl shadow-[0_12px_28px_rgba(59,130,246,0.14)]" />
          <div className="mb-3">
            <div className="text-[17px] font-semibold tracking-tight text-slate-950">{brandName}</div>
            <div className="mt-1 text-xs text-slate-500">{brandSlogan}</div>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-950">{title}</h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">{subtitle}</p>
          <div className="mt-6">{children}</div>
        </div>
      </div>
    </div>
  );
}
