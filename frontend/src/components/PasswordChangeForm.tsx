import { useState } from 'react';
import { toast } from '../lib/toast';

/** 密码修改表单 */
export function PasswordChangeForm({
  onChangePassword,
}: {
  onChangePassword: (oldPassword: string, newPassword: string) => Promise<void>;
}) {
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [localSuccess, setLocalSuccess] = useState<string | null>(null);

  async function handleSubmit() {
    setLocalError(null);
    setLocalSuccess(null);
    if (!oldPassword || !newPassword || !confirmPassword) {
      setLocalError('请填写所有密码字段');
      toast.error('请填写所有密码字段');
      return;
    }
    if (newPassword.length < 6) {
      setLocalError('新密码长度不能少于 6 位');
      toast.error('新密码长度不能少于 6 位');
      return;
    }
    if (newPassword !== confirmPassword) {
      setLocalError('两次输入的新密码不一致');
      toast.error('两次输入的新密码不一致');
      return;
    }
    if (newPassword === oldPassword) {
      setLocalError('新密码不能与旧密码相同');
      toast.error('新密码不能与旧密码相同');
      return;
    }
    setSaving(true);
    try {
      await onChangePassword(oldPassword, newPassword);
      setLocalSuccess('密码修改成功');
      toast.success('密码修改成功');
      setOldPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (err: any) {
      setLocalError(err.message || '密码修改失败');
      toast.error(err.message || '密码修改失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-3 space-y-3">
      <input
        value={oldPassword}
        onChange={(e) => setOldPassword(e.target.value)}
        type="password"
        placeholder="当前密码"
        className="w-full rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe]"
      />
      <input
        value={newPassword}
        onChange={(e) => setNewPassword(e.target.value)}
        type="password"
        placeholder="新密码（不少于 6 位）"
        className="w-full rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe]"
      />
      <input
        value={confirmPassword}
        onChange={(e) => setConfirmPassword(e.target.value)}
        type="password"
        placeholder="确认新密码"
        className="w-full rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe]"
      />
      <button
        onClick={() => void handleSubmit()}
        disabled={saving}
        className="rounded-2xl bg-[#1d4ed8] px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
      >
        {saving ? '修改中...' : '修改密码'}
      </button>
      {localError && <div className="text-xs text-rose-600">{localError}</div>}
      {localSuccess && <div className="text-xs text-emerald-600">{localSuccess}</div>}
    </div>
  );
}
