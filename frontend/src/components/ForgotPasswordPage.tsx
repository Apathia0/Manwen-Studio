import { useEffect, useState } from 'react';
import { AuthLayout } from './AuthLayout';

const DEFAULT_SITE_NAME = 'StoryCanvas';
const DEFAULT_SITE_SLOGAN = 'AI 小说与漫画创作平台';

/** 找回密码页面 */
export function ForgotPasswordPage({
  title,
  subtitle,
  onBack,
  onSendCode,
  onResetPassword,
  error,
}: {
  title: string;
  subtitle: string;
  onBack: () => void;
  onSendCode: (email: string) => Promise<{ ok: boolean; expires_in_seconds: number }>;
  onResetPassword: (email: string, verificationCode: string) => Promise<void>;
  error: string | null;
}) {
  const [email, setEmail] = useState('');
  const [verificationCode, setVerificationCode] = useState('');
  const [sendingCode, setSendingCode] = useState(false);
  const [codeCooldown, setCodeCooldown] = useState(0);
  const [resetting, setResetting] = useState(false);
  const brandName = title || DEFAULT_SITE_NAME;
  const brandSlogan = subtitle || DEFAULT_SITE_SLOGAN;

  useEffect(() => {
    if (codeCooldown <= 0) return;
    const timer = window.setTimeout(() => setCodeCooldown((prev) => Math.max(0, prev - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [codeCooldown]);

  return (
    <AuthLayout
      brandName={brandName}
      brandSlogan={brandSlogan}
      title="找回密码"
      subtitle={`验证邮箱后，新密码将发送到您的邮箱。`}
      onBack={onBack}
    >
      <div className="space-y-3">
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:bg-white focus:ring-4 focus:ring-[#dbeafe]"
          placeholder="邮箱"
        />
        <div className="flex gap-2">
          <input
            value={verificationCode}
            onChange={(e) => setVerificationCode(e.target.value)}
            className="min-w-0 flex-1 rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:bg-white focus:ring-4 focus:ring-[#dbeafe]"
            placeholder="邮箱验证码"
          />
          <button
            onClick={() =>
              void (async () => {
                setSendingCode(true);
                try {
                  await onSendCode(email);
                  setCodeCooldown(60);
                } finally {
                  setSendingCode(false);
                }
              })()
            }
            className="shrink-0 rounded-2xl border border-[#bfdbfe] bg-white px-4 py-3 text-sm font-medium text-[#2563eb] transition hover:bg-[#eff6ff] disabled:cursor-not-allowed disabled:opacity-60"
            disabled={sendingCode || codeCooldown > 0 || !email}
          >
            {sendingCode ? '发送中...' : codeCooldown > 0 ? `${codeCooldown}s 后重发` : '发送验证码'}
          </button>
        </div>
        <button
          onClick={() =>
            void (async () => {
              setResetting(true);
              try {
                await onResetPassword(email, verificationCode);
              } finally {
                setResetting(false);
              }
            })()
          }
          disabled={resetting || !email || !verificationCode}
          className="w-full rounded-2xl bg-[#2563eb] py-3 text-sm font-medium text-white shadow-[0_16px_34px_rgba(59,130,246,0.24)] transition hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {resetting ? '处理中...' : '重置密码'}
        </button>
        {error && <div className="text-xs text-rose-600">{error}</div>}
      </div>
    </AuthLayout>
  );
}
