import { useEffect, useState } from 'react';
import { AuthLayout } from './AuthLayout';

const DEFAULT_SITE_NAME = 'StoryCanvas';
const DEFAULT_SITE_SLOGAN = 'AI 小说与漫画创作平台';

/** 登录页面 */
export function LoginPage({
  title,
  subtitle,
  onBack,
  onLogin,
  onSendCode,
  requireEmailCode,
  codeExpireMinutes,
  toRegister,
  toForgotPassword,
  error,
}: {
  title: string;
  subtitle: string;
  onBack: () => void;
  onLogin: (email: string, password: string, verificationCode?: string) => Promise<void>;
  onSendCode: (email: string, purpose: 'register' | 'login') => Promise<void>;
  requireEmailCode: boolean;
  codeExpireMinutes: number;
  toRegister: () => void;
  toForgotPassword: () => void;
  error: string | null;
}) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [verificationCode, setVerificationCode] = useState('');
  const [sendingCode, setSendingCode] = useState(false);
  const [codeCooldown, setCodeCooldown] = useState(0);
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
      title="登录"
      subtitle={`登录后进入 ${brandName}，按角色展示可用菜单。`}
      onBack={onBack}
    >
      <div className="space-y-3">
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:bg-white focus:ring-4 focus:ring-[#dbeafe]"
          placeholder="邮箱"
        />
        <input
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:bg-white focus:ring-4 focus:ring-[#dbeafe]"
          placeholder="密码"
          type="password"
        />
        {requireEmailCode ? (
          <div className="flex gap-2">
            <input
              value={verificationCode}
              onChange={(e) => setVerificationCode(e.target.value)}
              className="min-w-0 flex-1 rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:bg-white focus:ring-4 focus:ring-[#dbeafe]"
              placeholder={`邮箱验证码（${codeExpireMinutes}分钟内有效）`}
            />
            <button
              onClick={() =>
                void (async () => {
                  setSendingCode(true);
                  try {
                    await onSendCode(email, 'login');
                    setCodeCooldown(60);
                  } finally {
                    setSendingCode(false);
                  }
                })()
              }
              className="shrink-0 rounded-2xl border border-[#bfdbfe] bg-white px-4 py-3 text-sm font-medium text-[#2563eb] transition hover:bg-[#eff6ff] disabled:cursor-not-allowed disabled:opacity-60"
              disabled={sendingCode || codeCooldown > 0}
            >
              {sendingCode ? '发送中...' : codeCooldown > 0 ? `${codeCooldown}s 后重发` : '发送验证码'}
            </button>
          </div>
        ) : null}
        <button
          onClick={() => void onLogin(email, password, verificationCode)}
          className="w-full rounded-2xl bg-[#2563eb] py-3 text-sm font-medium text-white shadow-[0_16px_34px_rgba(59,130,246,0.24)] transition hover:bg-[#1d4ed8]"
        >
          登录
        </button>
        {error && <div className="text-xs text-rose-600">{error}</div>}
      </div>
      <div className="mt-5 flex items-center justify-between">
        <button onClick={toForgotPassword} className="text-xs font-medium text-slate-500 transition hover:text-[#2563eb]">忘记密码？</button>
        <button onClick={toRegister} className="text-xs font-medium text-slate-600 transition hover:text-[#2563eb]">没有账号？去注册</button>
      </div>
    </AuthLayout>
  );
}
