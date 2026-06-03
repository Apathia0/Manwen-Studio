import { useEffect, useState } from 'react';
import { AuthLayout } from './AuthLayout';

const DEFAULT_SITE_NAME = 'StoryCanvas';
const DEFAULT_SITE_SLOGAN = 'AI 小说与漫画创作平台';

/** 注册页面 */
export function RegisterPage({
  title,
  subtitle,
  onBack,
  onRegister,
  onSendCode,
  requireEmailCode,
  codeExpireMinutes,
  toLogin,
  error,
}: {
  title: string;
  subtitle: string;
  onBack: () => void;
  onRegister: (name: string, email: string, password: string, verificationCode?: string) => Promise<void>;
  onSendCode: (email: string, purpose: 'register' | 'login') => Promise<void>;
  requireEmailCode: boolean;
  codeExpireMinutes: number;
  toLogin: () => void;
  error: string | null;
}) {
  const [name, setName] = useState('');
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
      title="注册"
      subtitle={`创建账号后即可开始 ${brandName} 的小说与漫画创作。`}
      onBack={onBack}
    >
      <div className="space-y-3">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:bg-white focus:ring-4 focus:ring-[#dbeafe]"
          placeholder="昵称"
        />
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
          placeholder="设置密码"
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
                    await onSendCode(email, 'register');
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
          onClick={() => void onRegister(name, email, password, verificationCode)}
          className="w-full rounded-2xl bg-[#2563eb] py-3 text-sm font-medium text-white shadow-[0_16px_34px_rgba(59,130,246,0.24)] transition hover:bg-[#1d4ed8]"
        >
          注册并进入
        </button>
        {error && <div className="text-xs text-rose-600">{error}</div>}
      </div>
      <button onClick={toLogin} className="mt-5 text-xs font-medium text-slate-600 transition hover:text-[#2563eb]">已有账号？去登录</button>
    </AuthLayout>
  );
}
