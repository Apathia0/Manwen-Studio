import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Check, Database, KeyRound, Loader2, RefreshCw, Server, ShieldCheck } from 'lucide-react';
import {
  completeInstall,
  getInstallStatus,
  restartInstallBackend,
  testInstallDatabase,
  testInstallRedis,
  type InstallAdminConfig,
  type InstallCompleteResponse,
  type InstallDatabaseConfig,
  type InstallRedisConfig,
} from '../api';

type InstallWizardPageProps = {
  onInstalled: () => void;
};

const steps = [
  { key: 'database', label: '数据库', icon: Database },
  { key: 'redis', label: 'Redis', icon: Server },
  { key: 'admin', label: '管理员', icon: KeyRound },
  { key: 'confirm', label: '确认安装', icon: ShieldCheck },
] as const;

export function InstallWizardPage({ onInstalled }: InstallWizardPageProps) {
  const [step, setStep] = useState(0);
  const [database, setDatabase] = useState<InstallDatabaseConfig>({
    host: 'localhost',
    port: 5432,
    database: 'manga_novel',
    username: 'postgres',
    password: '',
    sslmode: 'prefer',
  });
  const [redis, setRedis] = useState<InstallRedisConfig>({
    host: 'localhost',
    port: 6379,
    db: 0,
    username: '',
    password: '',
    tls: false,
  });
  const [admin, setAdmin] = useState<InstallAdminConfig>({
    name: '系统管理员',
    email: '',
    password: '',
    confirmPassword: '',
  });
  const [databaseResult, setDatabaseResult] = useState<string>('');
  const [redisResult, setRedisResult] = useState<string>('');
  const [testing, setTesting] = useState<'database' | 'redis' | null>(null);
  const [installing, setInstalling] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [restartMessage, setRestartMessage] = useState('');
  const [error, setError] = useState<string>('');
  const [result, setResult] = useState<InstallCompleteResponse | null>(null);

  const adminEmailValid = useMemo(() => {
    return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(admin.email.trim());
  }, [admin.email]);

  const adminValid = useMemo(() => {
    return adminEmailValid && admin.password.length >= 8 && admin.password === admin.confirmPassword;
  }, [adminEmailValid, admin.password, admin.confirmPassword]);

  async function handleTestDatabase() {
    setTesting('database');
    setError('');
    try {
      const res = await testInstallDatabase(database);
      setDatabaseResult(res.database_url || '数据库连接成功');
    } catch (err: any) {
      setDatabaseResult('');
      setError(err.message || '数据库连接测试失败');
    } finally {
      setTesting(null);
    }
  }

  async function handleTestRedis() {
    setTesting('redis');
    setError('');
    try {
      const res = await testInstallRedis(redis);
      setRedisResult(res.redis_url || 'Redis 连接成功');
    } catch (err: any) {
      setRedisResult('');
      setError(err.message || 'Redis 连接测试失败');
    } finally {
      setTesting(null);
    }
  }

  async function handleCompleteInstall() {
    setInstalling(true);
    setError('');
    try {
      const res = await completeInstall({ database, redis, admin });
      setResult(res);
    } catch (err: any) {
      setError(err.message || '系统安装失败');
    } finally {
      setInstalling(false);
    }
  }

  async function handleRestartBackend() {
    setRestarting(true);
    setError('');
    setRestartMessage('正在提交重启请求...');
    try {
      const restartResult = await restartInstallBackend();
      setRestartMessage(restartResult.message || '已提交重启请求，正在等待后端恢复...');
      await waitForBackendReady();
      onInstalled();
    } catch (err: any) {
      setRestartMessage('');
      setError(err.message || '自动重启失败，请手动重启后端或 PM2 后刷新页面');
      setRestarting(false);
    }
  }

  async function waitForBackendReady() {
    const deadline = Date.now() + 60_000;
    while (Date.now() < deadline) {
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
      try {
        const status = await getInstallStatus();
        if (status.installed && !status.requires_restart) {
          setRestartMessage('后端已重启，正在刷新系统状态...');
          return;
        }
      } catch {
        setRestartMessage('后端正在重启，等待服务恢复...');
      }
    }
    throw new Error('自动重启已提交，但 60 秒内未检测到后端恢复。请手动重启后刷新页面。');
  }

  function canContinue(): boolean {
    if (step === 0) return Boolean(databaseResult);
    if (step === 1) return Boolean(redisResult);
    if (step === 2) return Boolean(adminValid);
    return true;
  }

  if (result) {
    return (
      <InstallShell>
        <div className="mx-auto max-w-2xl rounded-[32px] border border-emerald-200 bg-white/95 p-8 shadow-[0_30px_90px_rgba(15,23,42,0.14)]">
          <div className="flex h-14 w-14 items-center justify-center rounded-3xl bg-emerald-100 text-emerald-700">
            <Check size={28} />
          </div>
          <h1 className="mt-6 text-3xl font-semibold tracking-tight text-slate-950">安装已完成</h1>
          <p className="mt-3 text-sm leading-6 text-slate-600">
            配置已写入后端环境文件。当前进程不会热切换数据库连接，请重启 FastAPI 后端或执行 PM2 reload 后刷新页面。
          </p>
          <div className="mt-6 space-y-3 rounded-3xl border border-slate-200 bg-slate-50 p-5 text-sm text-slate-700">
            <InfoRow label="数据库" value={result.database_url} />
            <InfoRow label="Redis" value={result.redis_url} />
            <InfoRow label="管理员" value={`${result.admin.name} (${result.admin.email})`} />
            <InfoRow label="环境文件" value={result.env_path} />
            {result.backup_path ? <InfoRow label="备份文件" value={result.backup_path} /> : null}
          </div>
          {restartMessage ? (
            <div className="mt-6 rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-700">{restartMessage}</div>
          ) : null}
          {error ? <div className="mt-6 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div> : null}
          <div className="mt-7 flex flex-col gap-3 sm:flex-row">
            <button
              type="button"
              disabled={restarting}
              onClick={() => void handleRestartBackend()}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-2xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {restarting ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
              自动重启后端
            </button>
            <button
              type="button"
              disabled={restarting}
              onClick={onInstalled}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white px-5 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <RefreshCw size={16} />
              我已手动重启，重新检查
            </button>
          </div>
        </div>
      </InstallShell>
    );
  }

  return (
    <InstallShell>
      <div className="mx-auto grid max-w-6xl gap-8 lg:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="rounded-[34px] border border-white/70 bg-white/82 p-6 shadow-[0_24px_70px_rgba(15,23,42,0.10)] backdrop-blur-xl">
          <div className="flex items-center gap-3">
            <img src="/brand-mark.svg" alt="LoreVista logo" className="h-11 w-11 rounded-2xl shadow-[0_10px_24px_rgba(15,23,42,0.12)]" />
            <div>
              <div className="text-sm font-semibold tracking-wide text-slate-950">LoreVista</div>
              <div className="text-xs text-slate-500">系统安装向导</div>
            </div>
          </div>
          <div className="mt-8 space-y-2">
            {steps.map((item, index) => {
              const Icon = item.icon;
              const active = step === index;
              const done = step > index;
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => index < step && setStep(index)}
                  className={`flex min-h-12 w-full items-center gap-3 rounded-2xl px-3 text-left text-sm transition ${
                    active
                      ? 'bg-slate-950 text-white shadow-[0_14px_30px_rgba(15,23,42,0.20)]'
                      : done
                        ? 'bg-emerald-50 text-emerald-800'
                        : 'bg-white/70 text-slate-600'
                  }`}
                >
                  <span className={`flex h-8 w-8 items-center justify-center rounded-xl ${active ? 'bg-white/15' : 'bg-slate-100'}`}>
                    {done ? <Check size={16} /> : <Icon size={16} />}
                  </span>
                  {item.label}
                </button>
              );
            })}
          </div>
          <p className="mt-8 text-xs leading-5 text-slate-500">
            安装程序只初始化已存在的 PostgreSQL 数据库，不会自动创建数据库。Redis 当前仅做配置和连通性校验。
          </p>
        </aside>

        <main className="rounded-[34px] border border-white/70 bg-white/90 p-6 shadow-[0_24px_70px_rgba(15,23,42,0.10)] backdrop-blur-xl sm:p-8">
          <div className="mb-6">
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">Step {step + 1} / 4</p>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">{steps[step].label}</h1>
          </div>

          {step === 0 && (
            <section className="space-y-5">
              <div className="grid gap-4 sm:grid-cols-2">
                <TextField label="数据库主机" value={database.host} onChange={(value) => setDatabase({ ...database, host: value })} />
                <NumberField label="端口" value={database.port} onChange={(value) => setDatabase({ ...database, port: value })} />
                <TextField label="数据库名" value={database.database} onChange={(value) => setDatabase({ ...database, database: value })} />
                <TextField label="用户名" value={database.username} onChange={(value) => setDatabase({ ...database, username: value })} />
                <TextField label="密码" value={database.password} type="password" onChange={(value) => setDatabase({ ...database, password: value })} />
                <SelectField label="SSL Mode" value={database.sslmode} options={['disable', 'allow', 'prefer', 'require', 'verify-ca', 'verify-full']} onChange={(value) => setDatabase({ ...database, sslmode: value })} />
              </div>
              <TestPanel
                value={databaseResult}
                buttonLabel="测试数据库连接"
                loading={testing === 'database'}
                onClick={handleTestDatabase}
              />
            </section>
          )}

          {step === 1 && (
            <section className="space-y-5">
              <div className="grid gap-4 sm:grid-cols-2">
                <TextField label="Redis 主机" value={redis.host} onChange={(value) => setRedis({ ...redis, host: value })} />
                <NumberField label="端口" value={redis.port} onChange={(value) => setRedis({ ...redis, port: value })} />
                <NumberField label="DB" value={redis.db} onChange={(value) => setRedis({ ...redis, db: value })} />
                <TextField label="用户名" value={redis.username} onChange={(value) => setRedis({ ...redis, username: value })} />
                <TextField label="密码" value={redis.password} type="password" onChange={(value) => setRedis({ ...redis, password: value })} />
                <label className="flex min-h-14 items-center justify-between rounded-2xl border border-slate-200 bg-slate-50 px-4 text-sm text-slate-700">
                  启用 TLS
                  <input
                    type="checkbox"
                    checked={redis.tls}
                    onChange={(event) => setRedis({ ...redis, tls: event.target.checked })}
                    className="h-5 w-5 rounded border-slate-300"
                  />
                </label>
              </div>
              <TestPanel value={redisResult} buttonLabel="测试 Redis 连接" loading={testing === 'redis'} onClick={handleTestRedis} />
            </section>
          )}

          {step === 2 && (
            <section className="space-y-5">
              <div className="grid gap-4 sm:grid-cols-2">
                <TextField label="管理员名称" value={admin.name} onChange={(value) => setAdmin({ ...admin, name: value })} />
                <TextField label="管理员邮箱" value={admin.email} type="email" onChange={(value) => setAdmin({ ...admin, email: value })} />
                <TextField label="密码" value={admin.password} type="password" onChange={(value) => setAdmin({ ...admin, password: value })} />
                <TextField label="确认密码" value={admin.confirmPassword} type="password" onChange={(value) => setAdmin({ ...admin, confirmPassword: value })} />
              </div>
              {admin.email.trim() && !adminEmailValid ? (
                <p className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs leading-5 text-rose-700">
                  管理员邮箱格式不正确，请填写类似 admin@example.com 的邮箱地址。
                </p>
              ) : null}
              {admin.password && admin.password.length < 8 ? (
                <p className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-700">
                  密码至少 8 位。
                </p>
              ) : null}
              {admin.confirmPassword && admin.password !== admin.confirmPassword ? (
                <p className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs leading-5 text-rose-700">
                  两次输入的密码不一致。
                </p>
              ) : null}
              <p className="rounded-2xl bg-slate-50 px-4 py-3 text-xs leading-5 text-slate-500">
                密码至少 8 位。安装程序会创建该账号为管理员，并绑定默认 Free 套餐。
              </p>
            </section>
          )}

          {step === 3 && (
            <section className="space-y-5">
              <div className="grid gap-3 text-sm">
                <InfoRow label="数据库" value={`${database.username}@${database.host}:${database.port}/${database.database}`} />
                <InfoRow label="Redis" value={`${redis.tls ? 'rediss' : 'redis'}://${redis.host}:${redis.port}/${redis.db}`} />
                <InfoRow label="管理员" value={`${admin.name} (${admin.email})`} />
              </div>
              <button
                type="button"
                disabled={installing || !adminValid}
                onClick={() => void handleCompleteInstall()}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-2xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {installing ? <Loader2 size={16} className="animate-spin" /> : <ShieldCheck size={16} />}
                开始安装
              </button>
            </section>
          )}

          {error ? <div className="mt-6 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div> : null}

          <div className="mt-8 flex items-center justify-between border-t border-slate-200 pt-5">
            <button
              type="button"
              onClick={() => setStep((prev) => Math.max(0, prev - 1))}
              disabled={step === 0 || installing}
              className="min-h-11 rounded-2xl border border-slate-200 bg-white px-5 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              上一步
            </button>
            {step < 3 ? (
              <button
                type="button"
                onClick={() => setStep((prev) => Math.min(3, prev + 1))}
                disabled={!canContinue() || installing}
                className="min-h-11 rounded-2xl bg-slate-950 px-5 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                下一步
              </button>
            ) : null}
          </div>
        </main>
      </div>
    </InstallShell>
  );
}

function InstallShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_12%_12%,_rgba(14,165,233,0.22),_transparent_28%),radial-gradient(circle_at_84%_16%,_rgba(34,197,94,0.18),_transparent_26%),linear-gradient(135deg,_#eef6ff_0%,_#f8fafc_46%,_#f1f5f9_100%)] px-4 py-8 text-slate-900 sm:px-6 lg:px-8">
      <div className="mb-8 mx-auto max-w-6xl">
        <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-500">First run setup</p>
        <h1 className="mt-2 text-4xl font-semibold tracking-tight text-slate-950">初始化系统安装</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">
          填写数据库、Redis 和管理员信息。完成后需要重启后端进程，让新环境变量正式生效。
        </p>
      </div>
      {children}
    </div>
  );
}

function TextField({ label, value, onChange, type = 'text' }: { label: string; value: string; onChange: (value: string) => void; type?: string }) {
  return (
    <label className="block text-sm font-medium text-slate-700">
      {label}
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-2 min-h-12 w-full rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-950 outline-none transition focus:border-sky-300 focus:ring-4 focus:ring-sky-100"
      />
    </label>
  );
}

function NumberField({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return (
    <TextField
      label={label}
      value={String(value)}
      type="number"
      onChange={(next) => onChange(Number(next))}
    />
  );
}

function SelectField({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return (
    <label className="block text-sm font-medium text-slate-700">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-2 min-h-12 w-full rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-950 outline-none transition focus:border-sky-300 focus:ring-4 focus:ring-sky-100"
      >
        {options.map((option) => (
          <option key={option} value={option}>{option}</option>
        ))}
      </select>
    </label>
  );
}

function TestPanel({ value, buttonLabel, loading, onClick }: { value: string; buttonLabel: string; loading: boolean; onClick: () => void }) {
  return (
    <div className="flex flex-col gap-3 rounded-3xl border border-slate-200 bg-slate-50 p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0 text-sm">
        <div className="font-medium text-slate-800">{value ? '连接已通过' : '需要先通过连通性测试'}</div>
        {value ? <div className="mt-1 truncate text-xs text-slate-500">{value}</div> : null}
      </div>
      <button
        type="button"
        disabled={loading}
        onClick={() => void onClick()}
        className="inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {loading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
        {buttonLabel}
      </button>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-2xl border border-slate-200 bg-white px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">{label}</span>
      <span className="break-all text-sm font-medium text-slate-800">{value}</span>
    </div>
  );
}
