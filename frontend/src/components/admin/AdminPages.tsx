import type * as React from 'react';
import { useEffect, useMemo, useState } from 'react';
import {
  adminGrantUserQuota,
  getAdminStoryChapters,
  adminUpdateUserSubscription,
  checkAdminSystemUpdate,
  createAdminPlan,
  createAdminUser,
  deleteAdminPlan,
  deleteAdminUser,
  getAdminAnnouncement,
  getAdminAuditLogs,
  getAdminFeatureCatalog,
  getAdminPlanFeatures,
  getAdminPlans,
  getAdminPlatformSettings,
  getAdminQuotaRules,
  getAdminSystemUpdateStatus,
  getAdminSystemPrompts,
  getAdminUserEntitlements,
  getAdminUserStories,
  getAdminUsers,
  saveAdminPlanFeatures,
  saveAdminQuotaRules,
  startAdminSystemUpdate,
  updateAdminAnnouncement,
  updateAdminPlan,
  updateAdminPlatformSettings,
  updateAdminSystemPrompts,
  updateAdminUser,
  type AdminAuditLogItem,
  type AdminFeatureCatalogItem,
  type AdminFeatureItem,
  type AdminPlan,
  type AdminQuotaRule,
  type AdminReviewChapter,
  type AdminReviewStory,
  type AdminSystemPrompt,
  type AdminSystemUpdateCheck,
  type AdminSystemUpdateStatus,
  type AdminUserItem,
  type PlatformAnnouncement,
  type PlatformSettings,
} from '../../api';
import { confirm } from '../../lib/confirm';
import { toast } from '../../lib/toast';

type AsyncAction = () => Promise<void>;

function cn(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(' ');
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN');
}

export function formatMoney(value: number | string | null | undefined): string {
  const amount = Number(value ?? 0);
  if (!Number.isFinite(amount)) return '-';
  return amount.toFixed(2).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1');
}

export function orderStatusLabel(status: string) {
  if (status === 'pending') return '待支付';
  if (status === 'paid') return '已支付';
  if (status === 'cancelled') return '已取消';
  if (status === 'expired') return '已过期';
  return status;
}

function SectionCard({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-3xl border border-[#d7e3f4] bg-white/90 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
        {description ? <p className="mt-1 text-sm text-slate-500">{description}</p> : null}
      </div>
      {children}
    </section>
  );
}

function PrimaryButton({
  onClick,
  children,
  className,
  disabled,
}: {
  onClick?: () => void;
  children: React.ReactNode;
  className?: string;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'rounded-2xl bg-[#1d4ed8] px-4 py-2 text-sm font-medium text-white transition hover:bg-[#1e40af] disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
    >
      {children}
    </button>
  );
}

function SecondaryButton({
  onClick,
  children,
  className,
  disabled,
}: {
  onClick?: () => void;
  children: React.ReactNode;
  className?: string;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'rounded-2xl border border-[#d7e3f4] bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-[#eff6ff] disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
    >
      {children}
    </button>
  );
}

function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cn(
        'w-full rounded-2xl border border-[#d7e3f4] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe]',
        props.className,
      )}
    />
  );
}

function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={cn(
        'w-full rounded-2xl border border-[#d7e3f4] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe]',
        props.className,
      )}
    />
  );
}

function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={cn(
        'w-full rounded-2xl border border-[#d7e3f4] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe]',
        props.className,
      )}
    />
  );
}

function useBusyAction(onError: (message: string) => void) {
  const [busy, setBusy] = useState(false);

  async function run(action: AsyncAction) {
    setBusy(true);
    try {
      await action();
    } catch (error: any) {
      onError(error?.message || '操作失败');
    } finally {
      setBusy(false);
    }
  }

  return { busy, run };
}

function featureName(catalogMap: Record<string, AdminFeatureCatalogItem>, key: string) {
  return catalogMap[key]?.name || key;
}

function featureDescription(catalogMap: Record<string, AdminFeatureCatalogItem>, key: string) {
  return catalogMap[key]?.description || '';
}

function featureCategory(catalogMap: Record<string, AdminFeatureCatalogItem>, key: string) {
  return catalogMap[key]?.category || '其他';
}

function usagePercent(used: number, limit: number) {
  if (limit <= 0) return 0;
  return Math.min(100, Math.max(0, Math.round((used / limit) * 100)));
}

export function AdminPlanManagementPage({ onError }: { onError: (message: string) => void }) {
  const [plans, setPlans] = useState<AdminPlan[]>([]);
  const [selectedPlanId, setSelectedPlanId] = useState<number | null>(null);
  const [features, setFeatures] = useState<AdminFeatureItem[]>([]);
  const [rules, setRules] = useState<AdminQuotaRule[]>([]);
  const [catalog, setCatalog] = useState<AdminFeatureCatalogItem[]>([]);
  const [draftPlan, setDraftPlan] = useState({
    code: '',
    name: '',
    description: '',
    monthly_price: '0',
    yearly_price: '0',
  });
  const [planMeta, setPlanMeta] = useState({
    name: '',
    description: '',
    monthly_price: '0',
    yearly_price: '0',
    is_visible: true,
    is_recommended: false,
  });
  const { busy, run } = useBusyAction(onError);

  const selectedPlan = useMemo(
    () => plans.find((item) => item.id === selectedPlanId) || null,
    [plans, selectedPlanId],
  );
  const catalogMap = useMemo(
    () => Object.fromEntries(catalog.map((item) => [item.key, item])),
    [catalog],
  );
  const groupedFeatures = useMemo(() => {
    const groups = new Map<string, AdminFeatureItem[]>();
    for (const item of features) {
      const category = featureCategory(catalogMap, item.feature_key);
      groups.set(category, [...(groups.get(category) || []), item]);
    }
    return [...groups.entries()];
  }, [catalogMap, features]);

  async function loadPlans(preferredPlanId?: number) {
    const [planList, featureCatalog] = await Promise.all([getAdminPlans(), getAdminFeatureCatalog()]);
    setPlans(planList);
    setCatalog(featureCatalog);
    const nextPlanId = preferredPlanId || selectedPlanId || planList[0]?.id || null;
    setSelectedPlanId(nextPlanId);
    if (!nextPlanId) return;
    const [nextFeatures, nextRules] = await Promise.all([
      getAdminPlanFeatures(nextPlanId),
      getAdminQuotaRules(nextPlanId),
    ]);
    setFeatures(nextFeatures);
    setRules(nextRules);
    const currentPlan = planList.find((item) => item.id === nextPlanId);
    if (currentPlan) {
      setPlanMeta({
        name: currentPlan.name,
        description: currentPlan.description || '',
        monthly_price: String(currentPlan.monthly_price ?? 0),
        yearly_price: String(currentPlan.yearly_price ?? 0),
        is_visible: currentPlan.is_visible,
        is_recommended: currentPlan.is_recommended,
      });
    }
  }

  useEffect(() => {
    void run(async () => {
      await loadPlans();
    });
  }, []);

  useEffect(() => {
    if (!selectedPlan) return;
    setPlanMeta({
      name: selectedPlan.name,
      description: selectedPlan.description || '',
      monthly_price: String(selectedPlan.monthly_price ?? 0),
      yearly_price: String(selectedPlan.yearly_price ?? 0),
      is_visible: selectedPlan.is_visible,
      is_recommended: selectedPlan.is_recommended,
    });
  }, [selectedPlan]);

  return (
    <div className="space-y-5">
      <SectionCard title="套餐管理" description="维护套餐基础信息、功能额度和扣减规则。">
        <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
          <div className="space-y-3 rounded-3xl border border-[#d7e3f4] bg-[#f8fbff] p-4">
            <div className="text-sm font-semibold text-slate-900">套餐列表</div>
            <div className="space-y-2">
              {plans.map((plan) => (
                <button
                  key={plan.id}
                  onClick={() =>
                    void run(async () => {
                      await loadPlans(plan.id);
                    })
                  }
                  className={cn(
                    'w-full rounded-2xl border px-3 py-3 text-left transition',
                    selectedPlanId === plan.id ? 'border-[#60a5fa] bg-white shadow-sm' : 'border-[#d7e3f4] bg-white/70 hover:bg-white',
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-medium text-slate-900">{plan.name}</div>
                    <span className="text-xs text-slate-500">¥{formatMoney(plan.monthly_price)}/月</span>
                  </div>
                  <div className="mt-1 text-xs text-slate-500">{plan.description || '暂无描述'}</div>
                </button>
              ))}
            </div>

            <div className="border-t border-[#d7e3f4] pt-3">
              <div className="mb-2 text-sm font-semibold text-slate-900">新建套餐</div>
              <div className="space-y-2">
                <TextInput placeholder="套餐编码，例如 enterprise" value={draftPlan.code} onChange={(e) => setDraftPlan((prev) => ({ ...prev, code: e.target.value }))} />
                <TextInput placeholder="套餐名称" value={draftPlan.name} onChange={(e) => setDraftPlan((prev) => ({ ...prev, name: e.target.value }))} />
                <TextArea placeholder="套餐描述" rows={3} value={draftPlan.description} onChange={(e) => setDraftPlan((prev) => ({ ...prev, description: e.target.value }))} />
                <div className="grid gap-2 sm:grid-cols-2">
                  <TextInput type="number" step="0.01" min="0" placeholder="月费" value={draftPlan.monthly_price} onChange={(e) => setDraftPlan((prev) => ({ ...prev, monthly_price: e.target.value }))} />
                  <TextInput type="number" step="0.01" min="0" placeholder="年费" value={draftPlan.yearly_price} onChange={(e) => setDraftPlan((prev) => ({ ...prev, yearly_price: e.target.value }))} />
                </div>
                <PrimaryButton
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      await createAdminPlan({
                        code: draftPlan.code.trim(),
                        name: draftPlan.name.trim(),
                        description: draftPlan.description.trim(),
                        monthly_price: Number(draftPlan.monthly_price || 0),
                        yearly_price: Number(draftPlan.yearly_price || 0),
                      });
                      setDraftPlan({ code: '', name: '', description: '', monthly_price: '0', yearly_price: '0' });
                      await loadPlans();
                      toast.success('套餐创建成功');
                    })
                  }
                >
                  创建套餐
                </PrimaryButton>
              </div>
            </div>
          </div>

          <div className="space-y-4">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <TextInput value={planMeta.name} onChange={(e) => setPlanMeta((prev) => ({ ...prev, name: e.target.value }))} placeholder="套餐名称" />
              <TextInput type="number" step="0.01" min="0" value={planMeta.monthly_price} onChange={(e) => setPlanMeta((prev) => ({ ...prev, monthly_price: e.target.value }))} placeholder="月费" />
              <TextInput type="number" step="0.01" min="0" value={planMeta.yearly_price} onChange={(e) => setPlanMeta((prev) => ({ ...prev, yearly_price: e.target.value }))} placeholder="年费" />
              <div className="flex items-center gap-3 rounded-2xl border border-[#d7e3f4] bg-white px-3 py-2 text-sm text-slate-700">
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={planMeta.is_visible} onChange={(e) => setPlanMeta((prev) => ({ ...prev, is_visible: e.target.checked }))} />
                  前台展示
                </label>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={planMeta.is_recommended} onChange={(e) => setPlanMeta((prev) => ({ ...prev, is_recommended: e.target.checked }))} />
                  推荐套餐
                </label>
              </div>
            </div>
            <TextArea rows={3} value={planMeta.description} onChange={(e) => setPlanMeta((prev) => ({ ...prev, description: e.target.value }))} placeholder="套餐描述" />
            <div className="flex flex-wrap gap-2">
              <PrimaryButton
                disabled={!selectedPlanId || busy}
                onClick={() =>
                  void run(async () => {
                    if (!selectedPlanId) return;
                    await updateAdminPlan(selectedPlanId, {
                      name: planMeta.name,
                      description: planMeta.description,
                      monthly_price: Number(planMeta.monthly_price || 0),
                      yearly_price: Number(planMeta.yearly_price || 0),
                      is_visible: planMeta.is_visible,
                      is_recommended: planMeta.is_recommended,
                    });
                    await loadPlans(selectedPlanId);
                    toast.success('套餐信息已保存');
                  })
                }
              >
                保存套餐信息
              </PrimaryButton>
              <SecondaryButton
                disabled={!selectedPlanId || busy}
                onClick={() =>
                  void run(async () => {
                    if (!selectedPlanId) return;
                    await deleteAdminPlan(selectedPlanId);
                    await loadPlans();
                    toast.success('套餐已删除');
                  })
                }
              >
                删除套餐
              </SecondaryButton>
            </div>

            {groupedFeatures.map(([groupName, items]) => (
              <SectionCard key={groupName} title={`${groupName}配置`} description="支持调整套餐功能值与扣减规则。">
                <div className="overflow-hidden rounded-2xl border border-[#e5edf8]">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-[#f8fbff] text-slate-500">
                      <tr>
                        <th className="px-3 py-3 font-medium">功能项</th>
                        <th className="px-3 py-3 font-medium">套餐值</th>
                        <th className="px-3 py-3 font-medium">重置周期</th>
                        <th className="px-3 py-3 font-medium">扣减时机</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((item) => {
                        const rule = rules.find((entry) => entry.feature_key === item.feature_key);
                        return (
                          <tr key={item.feature_key} className="border-t border-[#e5edf8] align-top">
                            <td className="px-3 py-3">
                              <div className="font-medium text-slate-900">{featureName(catalogMap, item.feature_key)}</div>
                              <div className="mt-1 text-xs text-slate-500">{featureDescription(catalogMap, item.feature_key)}</div>
                            </td>
                            <td className="px-3 py-3">
                              {catalogMap[item.feature_key]?.value_type === 'boolean' ? (
                                <Select
                                  value={String(Boolean(item.value))}
                                  onChange={(e) =>
                                    setFeatures((prev) => prev.map((entry) => (
                                      entry.feature_key === item.feature_key ? { ...entry, value: e.target.value === 'true' } : entry
                                    )))
                                  }
                                >
                                  <option value="true">开启</option>
                                  <option value="false">关闭</option>
                                </Select>
                              ) : (
                                <TextInput
                                  value={String(item.value ?? '')}
                                  onChange={(e) =>
                                    setFeatures((prev) => prev.map((entry) => (
                                      entry.feature_key === item.feature_key ? { ...entry, value: Number.isNaN(Number(e.target.value)) ? e.target.value : Number(e.target.value) } : entry
                                    )))
                                  }
                                />
                              )}
                            </td>
                            <td className="px-3 py-3">
                              <Select
                                value={rule?.reset_period || 'monthly'}
                                onChange={(e) =>
                                  setRules((prev) => prev.map((entry) => (
                                    entry.feature_key === item.feature_key ? { ...entry, reset_period: e.target.value } : entry
                                  )))
                                }
                              >
                                <option value="monthly">按月重置</option>
                                <option value="yearly">按年重置</option>
                                <option value="never">不重置</option>
                              </Select>
                            </td>
                            <td className="px-3 py-3">
                              <Select
                                value={rule?.deduct_mode || 'on_success'}
                                onChange={(e) =>
                                  setRules((prev) => prev.map((entry) => (
                                    entry.feature_key === item.feature_key ? { ...entry, deduct_mode: e.target.value } : entry
                                  )))
                                }
                              >
                                <option value="on_success">成功后扣减</option>
                                <option value="on_submit">提交即扣减</option>
                                <option value="manual">手动扣减</option>
                              </Select>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </SectionCard>
            ))}

            <div className="flex gap-2">
              <PrimaryButton
                disabled={!selectedPlanId || busy}
                onClick={() =>
                  void run(async () => {
                    if (!selectedPlanId) return;
                    await saveAdminPlanFeatures(selectedPlanId, features);
                    await saveAdminQuotaRules(selectedPlanId, rules);
                    await loadPlans(selectedPlanId);
                    toast.success('套餐能力已保存');
                  })
                }
              >
                保存套餐能力
              </PrimaryButton>
            </div>
          </div>
        </div>
      </SectionCard>
    </div>
  );
}

export function AdminUserManagementPage({ onError }: { onError: (message: string) => void }) {
  const [users, setUsers] = useState<AdminUserItem[]>([]);
  const [plans, setPlans] = useState<AdminPlan[]>([]);
  const [catalog, setCatalog] = useState<AdminFeatureCatalogItem[]>([]);
  const [query, setQuery] = useState('');
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [entitlementPreview, setEntitlementPreview] = useState<any>(null);
  const [grantFeatureKey, setGrantFeatureKey] = useState('manga.image.monthly_limit');
  const [grantAmount, setGrantAmount] = useState('10');
  const [selectedPlanId, setSelectedPlanId] = useState<number | null>(null);
  const [reviewStories, setReviewStories] = useState<AdminReviewStory[]>([]);
  const [selectedReviewStoryId, setSelectedReviewStoryId] = useState<number | null>(null);
  const [reviewChapters, setReviewChapters] = useState<AdminReviewChapter[]>([]);
  const [selectedReviewChapterId, setSelectedReviewChapterId] = useState<number | null>(null);
  const [grantFeedback, setGrantFeedback] = useState<null | {
    feature_key: string;
    granted_amount: number;
    before_granted: number;
    after_granted: number;
  }>(null);
  const [newUser, setNewUser] = useState({
    name: '',
    email: '',
    password: '',
    role: 'user' as 'user' | 'admin',
    allow_api_key_override: false,
    allow_api_url_override: false,
  });
  const { busy, run } = useBusyAction(onError);

  const catalogMap = useMemo(
    () => Object.fromEntries(catalog.map((item) => [item.key, item])),
    [catalog],
  );
  const filteredUsers = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return users;
    return users.filter((item) =>
      [item.name, item.email, item.plan_name, item.role, item.status].some((value) => value.toLowerCase().includes(keyword)),
    );
  }, [query, users]);
  const selectedUser = useMemo(
    () => users.find((item) => item.id === selectedUserId) || null,
    [selectedUserId, users],
  );
  const usageItems = useMemo(() => (entitlementPreview?.usage || []) as Array<any>, [entitlementPreview]);
  const selectedReviewStory = useMemo(
    () => reviewStories.find((item) => item.id === selectedReviewStoryId) || null,
    [reviewStories, selectedReviewStoryId],
  );
  const selectedReviewChapter = useMemo(
    () => reviewChapters.find((item) => item.id === selectedReviewChapterId) || null,
    [reviewChapters, selectedReviewChapterId],
  );

  async function loadData() {
    const [userList, planList, featureCatalog] = await Promise.all([
      getAdminUsers(),
      getAdminPlans(),
      getAdminFeatureCatalog(),
    ]);
    setUsers(userList);
    setPlans(planList);
    setCatalog(featureCatalog);
    if (!selectedPlanId && planList[0]) setSelectedPlanId(planList[0].id);
    if (!selectedUserId && userList[0]) setSelectedUserId(userList[0].id);
  }

  async function loadEntitlements(userId: number) {
    const data = await getAdminUserEntitlements(userId);
    setEntitlementPreview(data);
    setSelectedPlanId(data.plan?.id || null);
  }

  async function loadReviewStories(userId: number) {
    const stories = await getAdminUserStories(userId);
    setReviewStories(stories);
    const nextStoryId = stories.some((item) => item.id === selectedReviewStoryId) ? selectedReviewStoryId : stories[0]?.id ?? null;
    setSelectedReviewStoryId(nextStoryId);
    if (!nextStoryId) {
      setReviewChapters([]);
      setSelectedReviewChapterId(null);
      return;
    }
    const detail = await getAdminStoryChapters(nextStoryId);
    setReviewChapters(detail.chapters);
    setSelectedReviewChapterId((current) => (detail.chapters.some((item) => item.id === current) ? current : detail.chapters[0]?.id ?? null));
  }

  async function loadReviewChapters(storyId: number) {
    const detail = await getAdminStoryChapters(storyId);
    setReviewChapters(detail.chapters);
    setSelectedReviewChapterId((current) => (detail.chapters.some((item) => item.id === current) ? current : detail.chapters[0]?.id ?? null));
  }

  useEffect(() => {
    void run(async () => {
      await loadData();
    });
  }, []);

  useEffect(() => {
    if (!selectedUserId) return;
    void run(async () => {
      await loadEntitlements(selectedUserId);
      await loadReviewStories(selectedUserId);
    });
  }, [selectedUserId]);

  return (
    <div className="space-y-5">
      <SectionCard title="用户管理" description="支持用户增删改查、套餐切换、额度补发与账号状态控制。">
        <div className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
          <div className="space-y-3 rounded-3xl border border-[#d7e3f4] bg-[#f8fbff] p-4">
            <TextInput placeholder="搜索姓名、邮箱、套餐或状态" value={query} onChange={(e) => setQuery(e.target.value)} />
            <div className="max-h-[460px] space-y-2 overflow-y-auto pr-1">
              {filteredUsers.map((user) => (
                <button
                  key={user.id}
                  onClick={() => {
                    setSelectedUserId(user.id);
                    setGrantFeedback(null);
                  }}
                  className={cn(
                    'w-full rounded-2xl border px-3 py-3 text-left transition',
                    selectedUserId === user.id ? 'border-[#60a5fa] bg-white shadow-sm' : 'border-[#d7e3f4] bg-white/70 hover:bg-white',
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-medium text-slate-900">{user.name}</div>
                    <span className="text-xs text-slate-500">#{user.id}</span>
                  </div>
                  <div className="mt-1 text-xs text-slate-500">{user.email}</div>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs">
                    <span className="rounded-full bg-[#eff6ff] px-2 py-1 text-[#1d4ed8]">{user.plan_name}</span>
                    <span className="rounded-full bg-[#f8fafc] px-2 py-1 text-slate-600">{user.role === 'admin' ? '管理员' : '用户'}</span>
                    <span className={cn('rounded-full px-2 py-1', user.status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600')}>
                      {user.status === 'active' ? '启用中' : '已停用'}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-4">
            <SectionCard title="新增用户" description="由运营直接创建用户账号并指定角色。">
              <div className="grid gap-3 md:grid-cols-2">
                <TextInput placeholder="姓名" value={newUser.name} onChange={(e) => setNewUser((prev) => ({ ...prev, name: e.target.value }))} />
                <TextInput placeholder="邮箱" value={newUser.email} onChange={(e) => setNewUser((prev) => ({ ...prev, email: e.target.value }))} />
                <TextInput type="password" placeholder="初始密码" value={newUser.password} onChange={(e) => setNewUser((prev) => ({ ...prev, password: e.target.value }))} />
                <Select value={newUser.role} onChange={(e) => setNewUser((prev) => ({ ...prev, role: e.target.value as 'user' | 'admin' }))}>
                  <option value="user">普通用户</option>
                  <option value="admin">管理员</option>
                </Select>
              </div>
              <div className="mt-3 flex flex-wrap gap-3 rounded-2xl border border-[#d7e3f4] bg-[#f8fbff] px-4 py-3 text-sm text-slate-700">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={newUser.allow_api_key_override}
                    onChange={(e) => setNewUser((prev) => ({ ...prev, allow_api_key_override: e.target.checked }))}
                  />
                  允许自定义 API Key
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={newUser.allow_api_url_override}
                    onChange={(e) => setNewUser((prev) => ({ ...prev, allow_api_url_override: e.target.checked }))}
                  />
                  允许自定义 URL/模型
                </label>
              </div>
              <div className="mt-3">
                <PrimaryButton
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      await createAdminUser(newUser);
                      setNewUser({
                        name: '',
                        email: '',
                        password: '',
                        role: 'user',
                        allow_api_key_override: false,
                        allow_api_url_override: false,
                      });
                      await loadData();
                      toast.success('用户创建成功');
                    })
                  }
                >
                  创建用户
                </PrimaryButton>
              </div>
            </SectionCard>

            {selectedUser ? (
              <>
                <SectionCard title="账号操作" description={`当前选中：${selectedUser.name} / ${selectedUser.email}`}>
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                    <TextInput value={selectedUser.name} onChange={(e) => setUsers((prev) => prev.map((item) => item.id === selectedUser.id ? { ...item, name: e.target.value } : item))} />
                    <TextInput value={selectedUser.email} onChange={(e) => setUsers((prev) => prev.map((item) => item.id === selectedUser.id ? { ...item, email: e.target.value } : item))} />
                    <Select value={selectedUser.role} onChange={(e) => setUsers((prev) => prev.map((item) => item.id === selectedUser.id ? { ...item, role: e.target.value as 'user' | 'admin' } : item))}>
                      <option value="user">普通用户</option>
                      <option value="admin">管理员</option>
                    </Select>
                    <Select value={selectedUser.status} onChange={(e) => setUsers((prev) => prev.map((item) => item.id === selectedUser.id ? { ...item, status: e.target.value as 'active' | 'disabled' } : item))}>
                      <option value="active">启用</option>
                      <option value="disabled">停用</option>
                    </Select>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-3 rounded-2xl border border-[#d7e3f4] bg-[#f8fbff] px-4 py-3 text-sm text-slate-700">
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={Boolean(selectedUser.allow_api_key_override)}
                        onChange={(e) => setUsers((prev) => prev.map((item) => item.id === selectedUser.id ? { ...item, allow_api_key_override: e.target.checked } : item))}
                      />
                      允许自定义 API Key
                    </label>
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={Boolean(selectedUser.allow_api_url_override)}
                        onChange={(e) => setUsers((prev) => prev.map((item) => item.id === selectedUser.id ? { ...item, allow_api_url_override: e.target.checked } : item))}
                      />
                      允许自定义 URL/模型
                    </label>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <PrimaryButton
                      disabled={busy}
                      onClick={() =>
                        void run(async () => {
                          const current = users.find((item) => item.id === selectedUser.id);
                          if (!current) return;
                          await updateAdminUser(selectedUser.id, {
                            name: current.name,
                            email: current.email,
                            role: current.role,
                            status: current.status,
                            allow_api_key_override: Boolean(current.allow_api_key_override),
                            allow_api_url_override: Boolean(current.allow_api_url_override),
                          });
                          await loadData();
                          await loadEntitlements(selectedUser.id);
                          toast.success('账号信息已保存');
                        })
                      }
                    >
                      保存账号信息
                    </PrimaryButton>
                    <SecondaryButton
                      disabled={busy}
                      onClick={() =>
                        void run(async () => {
                          await deleteAdminUser(selectedUser.id);
                          setEntitlementPreview(null);
                          setSelectedUserId(null);
                          setGrantFeedback(null);
                          await loadData();
                          toast.success('账号已停用');
                        })
                      }
                    >
                      停用账号
                    </SecondaryButton>
                  </div>
                </SectionCard>

                <div className="grid gap-4 xl:grid-cols-2">
                  <SectionCard title="套餐调整" description="立即切换用户当前套餐，适合运营补单、人工升降级和测试场景。">
                    <div className="flex flex-wrap gap-2">
                      {plans.map((plan) => (
                        <button
                          key={plan.id}
                          onClick={() => setSelectedPlanId(plan.id)}
                          className={cn(
                            'rounded-2xl border px-3 py-2 text-sm',
                            selectedPlanId === plan.id ? 'border-[#60a5fa] bg-[#eff6ff] text-[#1d4ed8]' : 'border-[#d7e3f4] bg-white text-slate-700',
                          )}
                        >
                          {plan.name}
                        </button>
                      ))}
                    </div>
                    <div className="mt-3">
                      <PrimaryButton
                        disabled={!selectedPlanId || busy}
                        onClick={() =>
                          void run(async () => {
                            if (!selectedPlanId) return;
                            await adminUpdateUserSubscription(selectedUser.id, selectedPlanId);
                            await loadData();
                            await loadEntitlements(selectedUser.id);
                            toast.success('套餐已切换');
                          })
                        }
                      >
                        应用选中套餐
                      </PrimaryButton>
                    </div>
                  </SectionCard>

                  <SectionCard title="额度补发" description="按本月补发额度累计值管理，可直接看到补发前后变化。">
                    <div className="grid gap-3 md:grid-cols-[1fr_120px_auto]">
                      <Select value={grantFeatureKey} onChange={(e) => setGrantFeatureKey(e.target.value)}>
                        {catalog.map((item) => (
                          <option key={item.key} value={item.key}>
                            {item.name}
                          </option>
                        ))}
                      </Select>
                      <TextInput value={grantAmount} onChange={(e) => setGrantAmount(e.target.value)} placeholder="补发数量" />
                      <PrimaryButton
                        disabled={busy}
                        onClick={() =>
                          void run(async () => {
                            const result = await adminGrantUserQuota(selectedUser.id, grantFeatureKey, Number(grantAmount || 0));
                            setGrantFeedback(result);
                            setEntitlementPreview((prev: any) => prev ? { ...prev, usage: result.usage } : prev);
                            await loadEntitlements(selectedUser.id);
                            toast.success('额度已补发');
                          })
                        }
                      >
                        发放额度
                      </PrimaryButton>
                    </div>
                    <div className="mt-2 text-xs text-slate-500">{featureDescription(catalogMap, grantFeatureKey)}</div>
                    {grantFeedback ? (
                      <div className="mt-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                        已为当前用户补发 {grantFeedback.granted_amount}，累计补发从 {grantFeedback.before_granted} 提升到 {grantFeedback.after_granted}。
                      </div>
                    ) : null}
                  </SectionCard>
                </div>

                <SectionCard title="额度进度" description="展示当前套餐总量、已用量、补发量与剩余额度，便于客服快速定位。">
                  <div className="grid gap-4 xl:grid-cols-[1.35fr_1fr]">
                    <div className="space-y-3">
                      {usageItems.map((item) => {
                        const percent = usagePercent(Number(item.used || 0), Number(item.limit || 0));
                        return (
                          <div key={item.feature_key} className="rounded-2xl border border-[#e5edf8] bg-white p-4">
                            <div className="flex flex-wrap items-start justify-between gap-3">
                              <div>
                                <div className="font-medium text-slate-900">{featureName(catalogMap, item.feature_key)}</div>
                                <div className="mt-1 text-xs text-slate-500">{item.feature_key}</div>
                              </div>
                              <div className="text-right text-sm text-slate-600">
                                <div>剩余 {item.remaining}</div>
                                <div className="text-xs text-slate-500">已用 {item.used} / 总量 {item.limit}</div>
                              </div>
                            </div>
                            <div className="mt-3 h-2 overflow-hidden rounded-full bg-[#e8eef8]">
                              <div className="h-full rounded-full bg-[linear-gradient(90deg,_#2563eb_0%,_#60a5fa_100%)]" style={{ width: `${percent}%` }} />
                            </div>
                            <div className="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-4">
                              <div className="rounded-xl bg-[#f8fbff] px-3 py-2">套餐基础量：{item.base_limit ?? item.limit}</div>
                              <div className="rounded-xl bg-[#f8fbff] px-3 py-2">已补发：{item.granted ?? 0}</div>
                              <div className="rounded-xl bg-[#f8fbff] px-3 py-2">本月已用：{item.used}</div>
                              <div className="rounded-xl bg-[#f8fbff] px-3 py-2">剩余额度：{item.remaining}</div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                    <div className="rounded-2xl border border-[#e5edf8] bg-[#f8fbff] p-4">
                      <div className="text-sm font-semibold text-slate-900">用户权益快照</div>
                      <pre className="mt-3 max-h-[420px] overflow-auto rounded-2xl bg-white p-3 text-xs text-slate-700">
                        {JSON.stringify(entitlementPreview?.entitlements || {}, null, 2)}
                      </pre>
                    </div>
                  </div>
                </SectionCard>

                <SectionCard title="作品审查" description="管理员可在这里按用户查看其作品与章节内容，但普通作品页仍然只显示自己的作品。">
                  <div className="grid gap-4 xl:grid-cols-[300px_280px_minmax(0,1fr)]">
                    <div className="rounded-2xl border border-[#e5edf8] bg-[#f8fbff] p-3">
                      <div className="mb-3 text-sm font-semibold text-slate-900">该用户的作品</div>
                      <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
                        {reviewStories.length ? reviewStories.map((story) => (
                          <button
                            key={story.id}
                            onClick={() =>
                              void run(async () => {
                                setSelectedReviewStoryId(story.id);
                                await loadReviewChapters(story.id);
                              })
                            }
                            className={cn(
                              'w-full rounded-2xl border px-3 py-3 text-left transition',
                              selectedReviewStoryId === story.id ? 'border-[#60a5fa] bg-white shadow-sm' : 'border-[#d7e3f4] bg-white/80 hover:bg-white',
                            )}
                          >
                            <div className="font-medium text-slate-900">{story.title}</div>
                            <div className="mt-1 line-clamp-2 text-xs text-slate-500">{story.description || '暂无简介'}</div>
                            <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
                              <span>{formatDateTime(story.created_at)}</span>
                              <span>{story.chapter_count} 章</span>
                            </div>
                          </button>
                        )) : (
                          <div className="rounded-2xl bg-white px-3 py-6 text-center text-sm text-slate-500">该用户暂时还没有作品。</div>
                        )}
                      </div>
                    </div>

                    <div className="rounded-2xl border border-[#e5edf8] bg-[#f8fbff] p-3">
                      <div className="mb-3 text-sm font-semibold text-slate-900">章节列表</div>
                      <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
                        {reviewChapters.length ? reviewChapters.map((chapter) => (
                          <button
                            key={chapter.id}
                            onClick={() => setSelectedReviewChapterId(chapter.id)}
                            className={cn(
                              'w-full rounded-2xl border px-3 py-3 text-left transition',
                              selectedReviewChapterId === chapter.id ? 'border-[#60a5fa] bg-white shadow-sm' : 'border-[#d7e3f4] bg-white/80 hover:bg-white',
                            )}
                          >
                            <div className="font-medium text-slate-900">
                              第 {chapter.chapter_number} 章 · {chapter.title || '未命名章节'}
                            </div>
                            <div className="mt-1 text-xs text-slate-500">
                              {chapter.word_count || 0} 字 · {chapter.status || 'pending'}
                            </div>
                            <div className="mt-1 text-xs text-slate-400">{formatDateTime(chapter.created_at)}</div>
                          </button>
                        )) : (
                          <div className="rounded-2xl bg-white px-3 py-6 text-center text-sm text-slate-500">
                            {selectedReviewStory ? '这部作品还没有章节。' : '先从左侧选择一部作品。'}
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="rounded-2xl border border-[#e5edf8] bg-white p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold text-slate-900">
                            {selectedReviewStory ? selectedReviewStory.title : '章节内容预览'}
                          </div>
                          <div className="mt-1 text-xs text-slate-500">
                            {selectedReviewStory ? `${selectedReviewStory.chapter_count} 章 · 创建于 ${formatDateTime(selectedReviewStory.created_at)}` : '选择作品和章节后，可在这里只读审查内容。'}
                          </div>
                        </div>
                      </div>
                      {selectedReviewChapter ? (
                        <div className="mt-4 space-y-3">
                          <div className="rounded-2xl bg-[#f8fbff] px-4 py-3">
                            <div className="text-sm font-medium text-slate-900">
                              第 {selectedReviewChapter.chapter_number} 章 · {selectedReviewChapter.title || '未命名章节'}
                            </div>
                            <div className="mt-1 text-xs text-slate-500">
                              {selectedReviewChapter.word_count || 0} 字 · {selectedReviewChapter.status || 'pending'} · {formatDateTime(selectedReviewChapter.created_at)}
                            </div>
                          </div>
                          <div className="max-h-[420px] overflow-y-auto rounded-2xl border border-[#e5edf8] bg-[#f8fbff] p-4 text-sm leading-7 text-slate-700 whitespace-pre-wrap">
                            {selectedReviewChapter.novel_content?.trim() || '该章节暂时还没有正文内容。'}
                          </div>
                        </div>
                      ) : (
                        <div className="mt-4 rounded-2xl border border-dashed border-[#d7e3f4] bg-[#f8fbff] px-4 py-10 text-center text-sm text-slate-500">
                          先选择一部作品和章节，再查看只读内容。
                        </div>
                      )}
                    </div>
                  </div>
                </SectionCard>
              </>
            ) : (
              <SectionCard title="用户详情" description="选择左侧用户后可查看套餐、权益与额度情况。">
                <div className="text-sm text-slate-500">当前还没有选中的用户。</div>
              </SectionCard>
            )}
          </div>
        </div>
      </SectionCard>
    </div>
  );
}

export function AdminAnnouncementPage({ onError }: { onError: (message: string) => void }) {
  const [announcement, setAnnouncement] = useState<PlatformAnnouncement>({ enabled: false, title: '', content: '' });
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const { run } = useBusyAction(onError);

  useEffect(() => {
    void run(async () => {
      const data = await getAdminAnnouncement();
      setAnnouncement(data);
      setLoaded(true);
    });
  }, []);

  async function handleSave() {
    setSaving(true);
    try {
      const result = await updateAdminAnnouncement(announcement);
      setAnnouncement(result.announcement);
      toast.success('公告已保存');
    } catch (error: any) {
      onError(error?.message || '保存公告失败');
    } finally {
      setSaving(false);
    }
  }

  if (!loaded) {
    return (
      <SectionCard title="平台公告" description="加载中...">
        <div className="text-sm text-slate-500">请稍候…</div>
      </SectionCard>
    );
  }

  return (
    <div className="space-y-5">
      <SectionCard title="平台公告管理" description="配置登录后向所有用户弹出的平台公告，支持 HTML 格式。">
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 rounded-2xl border border-[#d7e3f4] bg-white px-4 py-3 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={announcement.enabled}
                onChange={(e) => setAnnouncement((prev) => ({ ...prev, enabled: e.target.checked }))}
              />
              启用公告弹窗
            </label>
          </div>
          <div>
            <label className="mb-2 block text-sm font-medium text-slate-700">公告标题</label>
            <TextInput
              value={announcement.title}
              onChange={(e) => setAnnouncement((prev) => ({ ...prev, title: e.target.value }))}
              placeholder="例如：系统维护通知"
            />
          </div>
          <div>
            <label className="mb-2 block text-sm font-medium text-slate-700">公告内容（支持 HTML）</label>
            <TextArea
              rows={10}
              value={announcement.content}
              onChange={(e) => setAnnouncement((prev) => ({ ...prev, content: e.target.value }))}
              placeholder="<h3>公告标题</h3><p>公告内容...</p>"
            />
            <div className="mt-3 rounded-2xl border border-[#e5edf8] bg-[#f8fbff] p-4">
              <div className="mb-2 text-xs font-medium text-slate-500">预览效果：</div>
              <div className="rounded-xl bg-white p-4 text-sm leading-relaxed" dangerouslySetInnerHTML={{ __html: announcement.content || '<span class="text-slate-400">暂无内容</span>' }} />
            </div>
          </div>
          <div>
            <PrimaryButton disabled={saving} onClick={() => void handleSave()}>
              {saving ? '保存中...' : '保存公告'}
            </PrimaryButton>
          </div>
        </div>
      </SectionCard>
    </div>
  );
}

const PLATFORM_SETTINGS_TABS = [
  { key: 'basic', label: '基础信息' },
  { key: 'api', label: 'AI API 配置' },
  { key: 'auth-email', label: '认证与邮箱' },
  { key: 'payment', label: '支付配置' },
] as const;

export function AdminPlatformSettingsPage({
  onError,
  onSaved,
}: {
  onError: (message: string) => void;
  onSaved?: (settings: PlatformSettings) => void;
}) {
  const [settings, setSettings] = useState<PlatformSettings | null>(null);
  const [iconBusy, setIconBusy] = useState(false);
  const [activeTab, setActiveTab] = useState<string>('basic');
  const { busy, run } = useBusyAction(onError);

  useEffect(() => {
    void run(async () => {
      const data = await getAdminPlatformSettings();
      setSettings(data);
    });
  }, []);

  if (!settings) {
    return (
      <SectionCard title="平台配置" description="加载平台配置中。">
        <div className="text-sm text-slate-500">请稍候…</div>
      </SectionCard>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex gap-1 rounded-2xl border border-[#e5edf8] bg-[#f8fbff] p-1">
        {PLATFORM_SETTINGS_TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`rounded-xl px-4 py-2 text-sm font-medium transition ${
              activeTab === tab.key
                ? 'bg-white text-slate-900 shadow-[0_1px_3px_rgba(0,0,0,0.08)]'
                : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'basic' && (
        <SectionCard title="平台基础信息" description="统一管理品牌展示、客服联系方式与运营公告。">
          <div className="grid gap-3 md:grid-cols-2">
            <TextInput value={settings.basic.site_name} onChange={(e) => setSettings((prev) => prev ? { ...prev, basic: { ...prev.basic, site_name: e.target.value } } : prev)} placeholder="平台名称" />
            <TextInput value={settings.basic.site_slogan} onChange={(e) => setSettings((prev) => prev ? { ...prev, basic: { ...prev.basic, site_slogan: e.target.value } } : prev)} placeholder="平台副标题" />
            <TextInput value={settings.basic.support_email} onChange={(e) => setSettings((prev) => prev ? { ...prev, basic: { ...prev.basic, support_email: e.target.value } } : prev)} placeholder="客服邮箱" />
            <TextInput value={settings.basic.icp} onChange={(e) => setSettings((prev) => prev ? { ...prev, basic: { ...prev.basic, icp: e.target.value } } : prev)} placeholder="ICP备案号" />
          </div>
          <div className="mt-3 rounded-2xl border border-[#d7e3f4] bg-[#f8fbff] p-4">
            <div className="text-sm font-semibold text-slate-900">站点 Icon</div>
            <div className="mt-1 text-xs text-slate-500">支持上传 png / jpg / svg，保存后会自动更新浏览器标签页图标。</div>
            <div className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-center">
              <div className="flex h-16 w-16 items-center justify-center overflow-hidden rounded-2xl border border-[#d7e3f4] bg-white shadow-[0_8px_20px_rgba(59,130,246,0.08)]">
                <img src={settings.basic.icon_url || '/brand-mark.svg'} alt="site icon" className="h-10 w-10 object-contain" />
              </div>
              <div className="flex flex-wrap gap-2">
                <label className="inline-flex cursor-pointer items-center rounded-2xl bg-[#2563eb] px-4 py-2 text-sm font-medium text-white transition hover:bg-[#1d4ed8]">
                  {iconBusy ? '处理中...' : '上传图标'}
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/jpg,image/svg+xml,image/webp,image/x-icon"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      setIconBusy(true);
                      const reader = new FileReader();
                      reader.onload = () => {
                        const result = String(reader.result || '');
                        const [, base64 = ''] = result.split(',');
                        setSettings((prev) => prev ? {
                          ...prev,
                          basic: {
                            ...prev.basic,
                            icon_url: result,
                            icon_data: base64,
                            icon_mime: file.type || 'image/png',
                            clear_icon: false,
                          },
                        } : prev);
                        setIconBusy(false);
                      };
                      reader.onerror = () => {
                        setIconBusy(false);
                        onError('读取图标文件失败');
                      };
                      reader.readAsDataURL(file);
                      e.target.value = '';
                    }}
                  />
                </label>
                <SecondaryButton
                  disabled={iconBusy}
                  onClick={() =>
                    setSettings((prev) => prev ? {
                      ...prev,
                      basic: {
                        ...prev.basic,
                        icon_url: '/brand-mark.svg',
                        icon_data: '',
                        icon_mime: '',
                        clear_icon: true,
                      },
                    } : prev)
                  }
                >
                  恢复默认
                </SecondaryButton>
              </div>
            </div>
          </div>
          <div className="mt-3 grid gap-3">
            <TextInput value={settings.basic.copyright} onChange={(e) => setSettings((prev) => prev ? { ...prev, basic: { ...prev.basic, copyright: e.target.value } } : prev)} placeholder="版权信息" />
            <TextArea rows={4} value={settings.basic.notice} onChange={(e) => setSettings((prev) => prev ? { ...prev, basic: { ...prev.basic, notice: e.target.value } } : prev)} placeholder="运营公告 / 首页提示" />
          </div>
        </SectionCard>
      )}

      {activeTab === 'api' && (
        <SectionCard title="AI API 配置" description="平台保存的配置会在用户实际生成内容时自动生效。">
          <div className="grid gap-4 xl:grid-cols-2">
            <div className="rounded-2xl border border-[#e5edf8] bg-[#f8fbff] p-4">
              <div className="mb-3 text-sm font-semibold text-slate-900">文本模型服务</div>
              <div className="space-y-3">
                <TextInput value={settings.api.deepseek_base_url} onChange={(e) => setSettings((prev) => prev ? { ...prev, api: { ...prev.api, deepseek_base_url: e.target.value } } : prev)} placeholder="DeepSeek Base URL" />
                <TextInput value={settings.api.deepseek_model} onChange={(e) => setSettings((prev) => prev ? { ...prev, api: { ...prev.api, deepseek_model: e.target.value } } : prev)} placeholder="DeepSeek 模型名称" />
                <TextInput type="password" value={settings.api.deepseek_api_key} onChange={(e) => setSettings((prev) => prev ? { ...prev, api: { ...prev.api, deepseek_api_key: e.target.value } } : prev)} placeholder="DeepSeek API Key" />
              </div>
            </div>
            <div className="rounded-2xl border border-[#e5edf8] bg-[#f8fbff] p-4">
              <div className="mb-3 text-sm font-semibold text-slate-900">图片模型服务</div>
              <div className="space-y-3">
                <TextInput value={settings.api.image_base_url} onChange={(e) => setSettings((prev) => prev ? { ...prev, api: { ...prev.api, image_base_url: e.target.value } } : prev)} placeholder="图片服务 Base URL" />
                <TextInput value={settings.api.image_model} onChange={(e) => setSettings((prev) => prev ? { ...prev, api: { ...prev.api, image_model: e.target.value } } : prev)} placeholder="图片模型名称" />
                <TextInput type="password" value={settings.api.image_api_key} onChange={(e) => setSettings((prev) => prev ? { ...prev, api: { ...prev.api, image_api_key: e.target.value } } : prev)} placeholder="图片 API Key" />
              </div>
            </div>
            <div className="rounded-2xl border border-[#e5edf8] bg-[#f8fbff] p-4">
              <div className="mb-3 text-sm font-semibold text-slate-900">视频模型服务</div>
              <div className="space-y-3">
                <TextInput value={settings.api.video_base_url} onChange={(e) => setSettings((prev) => prev ? { ...prev, api: { ...prev.api, video_base_url: e.target.value } } : prev)} placeholder="视频服务 Base URL" />
                <TextInput value={settings.api.video_model} onChange={(e) => setSettings((prev) => prev ? { ...prev, api: { ...prev.api, video_model: e.target.value } } : prev)} placeholder="视频模型名称" />
                <TextInput type="password" value={settings.api.video_api_key} onChange={(e) => setSettings((prev) => prev ? { ...prev, api: { ...prev.api, video_api_key: e.target.value } } : prev)} placeholder="视频 API Key" />
              </div>
            </div>
            <div className="rounded-2xl border border-[#e5edf8] bg-[#f8fbff] p-4">
              <div className="mb-3 text-sm font-semibold text-slate-900">云存储 OSS</div>
              <div className="space-y-3">
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={settings.api.oss_enabled ?? false}
                    onChange={(e) => setSettings((prev) => prev ? { ...prev, api: { ...prev.api, oss_enabled: e.target.checked } } : prev)}
                  />
                  启用 OSS 云存储
                </label>
                <TextInput value={settings.api.oss_access_key_id ?? ''} onChange={(e) => setSettings((prev) => prev ? { ...prev, api: { ...prev.api, oss_access_key_id: e.target.value } } : prev)} placeholder="Access Key ID" />
                <TextInput type="password" value={settings.api.oss_access_key_secret ?? ''} onChange={(e) => setSettings((prev) => prev ? { ...prev, api: { ...prev.api, oss_access_key_secret: e.target.value } } : prev)} placeholder="Access Key Secret" />
                <TextInput value={settings.api.oss_endpoint ?? ''} onChange={(e) => setSettings((prev) => prev ? { ...prev, api: { ...prev.api, oss_endpoint: e.target.value } } : prev)} placeholder="Endpoint (如 oss-cn-hangzhou.aliyuncs.com)" />
                <TextInput value={settings.api.oss_bucket ?? ''} onChange={(e) => setSettings((prev) => prev ? { ...prev, api: { ...prev.api, oss_bucket: e.target.value } } : prev)} placeholder="Bucket 名称" />
                <TextInput value={settings.api.oss_public_url_base ?? ''} onChange={(e) => setSettings((prev) => prev ? { ...prev, api: { ...prev.api, oss_public_url_base: e.target.value } } : prev)} placeholder="公网域名 (可选，如 https://cdn.yourdomain.com)" />
              </div>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3 rounded-2xl border border-[#d7e3f4] bg-white px-4 py-3 text-sm text-slate-700">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={settings.api.enable_user_override}
                onChange={(e) => setSettings((prev) => prev ? { ...prev, api: { ...prev.api, enable_user_override: e.target.checked } } : prev)}
              />
              允许用户临时覆盖自己的 API Key
            </label>
          </div>

          <div className="mt-3 rounded-2xl border border-[#d7e3f4] bg-white px-4 py-3 text-sm text-slate-700">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={settings.api.enable_user_url_override ?? false}
                onChange={(e) => setSettings((prev) => prev ? { ...prev, api: { ...prev.api, enable_user_url_override: e.target.checked } } : prev)}
              />
              允许用户覆盖自己的 URL/模型
            </label>
          </div>
        </SectionCard>
      )}

      {activeTab === 'auth-email' && (
        <SectionCard title="认证与邮箱配置" description="管理登录注册验证码和 SMTP 发信服务。">
          <div className="grid gap-4 xl:grid-cols-2">
            <div className="rounded-3xl border border-[#d7e3f4] bg-white p-4">
              <div className="text-sm font-semibold text-slate-900">登录注册验证</div>
              <div className="mt-1 text-xs text-slate-500">可分别控制注册和登录是否必须通过邮箱验证码校验。</div>
              <div className="mt-4 space-y-3">
                <label className="flex items-center gap-2 rounded-2xl border border-[#e5edf8] px-3 py-3 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={settings.auth.require_email_code_for_register}
                    onChange={(e) => setSettings((prev) => prev ? { ...prev, auth: { ...prev.auth, require_email_code_for_register: e.target.checked } } : prev)}
                  />
                  注册必须验证邮箱验证码
                </label>
                <label className="flex items-center gap-2 rounded-2xl border border-[#e5edf8] px-3 py-3 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={settings.auth.require_email_code_for_login}
                    onChange={(e) => setSettings((prev) => prev ? { ...prev, auth: { ...prev.auth, require_email_code_for_login: e.target.checked } } : prev)}
                  />
                  登录必须验证邮箱验证码
                </label>
                <div className="grid gap-3 md:grid-cols-2">
                  <TextInput
                    value={String(settings.auth.email_code_expire_minutes ?? 10)}
                    onChange={(e) => setSettings((prev) => prev ? { ...prev, auth: { ...prev.auth, email_code_expire_minutes: Number(e.target.value || 10) } } : prev)}
                    placeholder="验证码有效期（分钟）"
                  />
                  <TextInput
                    value={String(settings.auth.email_code_length ?? 6)}
                    onChange={(e) => setSettings((prev) => prev ? { ...prev, auth: { ...prev.auth, email_code_length: Number(e.target.value || 6) } } : prev)}
                    placeholder="验证码位数"
                  />
                </div>
              </div>
            </div>

            <div className="rounded-3xl border border-[#d7e3f4] bg-white p-4">
              <div className="text-sm font-semibold text-slate-900">邮箱发信配置</div>
              <div className="mt-1 text-xs text-slate-500">用于注册、登录验证码发送。建议先完成配置，再开启上面的验证码开关。</div>
              <div className="mt-4 space-y-3">
                <label className="flex items-center gap-2 rounded-2xl border border-[#e5edf8] px-3 py-3 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={settings.email.smtp_enabled}
                    onChange={(e) => setSettings((prev) => prev ? { ...prev, email: { ...prev.email, smtp_enabled: e.target.checked } } : prev)}
                  />
                  启用 SMTP 发信
                </label>
                <div className="grid gap-3 md:grid-cols-2">
                  <TextInput value={settings.email.smtp_host} onChange={(e) => setSettings((prev) => prev ? { ...prev, email: { ...prev.email, smtp_host: e.target.value } } : prev)} placeholder="SMTP Host" />
                  <TextInput value={String(settings.email.smtp_port ?? 587)} onChange={(e) => setSettings((prev) => prev ? { ...prev, email: { ...prev.email, smtp_port: Number(e.target.value || 587) } } : prev)} placeholder="SMTP Port" />
                  <TextInput value={settings.email.smtp_username} onChange={(e) => setSettings((prev) => prev ? { ...prev, email: { ...prev.email, smtp_username: e.target.value } } : prev)} placeholder="SMTP 用户名" />
                  <TextInput type="password" value={settings.email.smtp_password} onChange={(e) => setSettings((prev) => prev ? { ...prev, email: { ...prev.email, smtp_password: e.target.value } } : prev)} placeholder="SMTP 密码 / 授权码" />
                  <TextInput value={settings.email.smtp_from_email} onChange={(e) => setSettings((prev) => prev ? { ...prev, email: { ...prev.email, smtp_from_email: e.target.value } } : prev)} placeholder="发件邮箱" />
                  <TextInput value={settings.email.smtp_from_name} onChange={(e) => setSettings((prev) => prev ? { ...prev, email: { ...prev.email, smtp_from_name: e.target.value } } : prev)} placeholder="发件人名称" />
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <label className="flex items-center gap-2 rounded-2xl border border-[#e5edf8] px-3 py-3 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={settings.email.smtp_use_tls}
                      onChange={(e) => setSettings((prev) => prev ? { ...prev, email: { ...prev.email, smtp_use_tls: e.target.checked } } : prev)}
                    />
                    使用 STARTTLS
                  </label>
                  <label className="flex items-center gap-2 rounded-2xl border border-[#e5edf8] px-3 py-3 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={settings.email.smtp_use_ssl}
                      onChange={(e) => setSettings((prev) => prev ? { ...prev, email: { ...prev.email, smtp_use_ssl: e.target.checked } } : prev)}
                    />
                    使用 SSL 直连
                  </label>
                </div>
              </div>
            </div>
          </div>
        </SectionCard>
      )}

      {activeTab === 'payment' && (
        <SectionCard title="支付配置" description="管理支付开关、渠道参数与订单策略。">
          <div className="mt-1 grid gap-3 md:grid-cols-2">
            {(() => {
              const pm = settings.payment;
              let cur = 'closed';
              if (pm.enabled) {
                if (pm.wechat_enabled) cur = 'wechat';
                else if (pm.alipay_enabled) cur = 'alipay';
                else if (pm.epay_enabled) cur = 'epay';
              }
              return (
                <Select value={cur} onChange={(e) => {
                  const v = e.target.value;
                  setSettings((prev) => {
                    if (!prev) return prev;
                    const base = { ...prev.payment };
                    base.enabled = v !== 'closed';
                    base.wechat_enabled = v === 'wechat';
                    base.alipay_enabled = v === 'alipay';
                    base.epay_enabled = v === 'epay';
                    if (v === 'wechat') base.default_method = 'wechat_qr';
                    else if (v === 'alipay') base.default_method = 'alipay_qr';
                    else if (v === 'epay') base.default_method = 'epay_qr';
                    return { ...prev, payment: base };
                  });
                }}>
                  <option value="closed">关闭</option>
                  <option value="wechat">微信支付</option>
                  <option value="alipay">支付宝</option>
                  <option value="epay">易支付</option>
                </Select>
              );
            })()}
            <TextInput
              value={String(settings.payment.order_expire_minutes ?? 30)}
              onChange={(e) => setSettings((prev) => prev ? { ...prev, payment: { ...prev.payment, order_expire_minutes: Number(e.target.value || 30) } } : prev)}
              placeholder="订单超时分钟数"
            />
          </div>
          <div className="mt-3">
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={settings.payment.auto_activate_free_plan ?? true}
                onChange={(e) => setSettings((prev) => prev ? { ...prev, payment: { ...prev.payment, auto_activate_free_plan: e.target.checked } } : prev)}
              />
              金额为 0 的套餐自动生效
            </label>
          </div>
          <div className="mt-3">
            <TextArea
              rows={3}
              value={settings.payment.instructions}
              onChange={(e) => setSettings((prev) => prev ? { ...prev, payment: { ...prev.payment, instructions: e.target.value } } : prev)}
              placeholder="支付说明"
            />
          </div>
          {(() => {
            const pm = settings.payment;
            let activeMethod = 'closed';
            if (pm.enabled) {
              if (pm.wechat_enabled) activeMethod = 'wechat';
              else if (pm.alipay_enabled) activeMethod = 'alipay';
              else if (pm.epay_enabled) activeMethod = 'epay';
            }

            const wechatSection = (
              <div className="rounded-2xl border border-[#e5edf8] bg-[#f8fbff] p-4">
                <div className="mb-3 text-sm font-semibold text-slate-900">微信参数</div>
                <div className="space-y-3">
                  <TextInput value={pm.wechat_app_id || ''} onChange={(e) => setSettings((prev) => prev ? { ...prev, payment: { ...prev.payment, wechat_app_id: e.target.value } } : prev)} placeholder="App ID" />
                  <TextInput value={pm.wechat_mch_id || ''} onChange={(e) => setSettings((prev) => prev ? { ...prev, payment: { ...prev.payment, wechat_mch_id: e.target.value } } : prev)} placeholder="商户号" />
                  <TextInput value={pm.wechat_notify_url || ''} onChange={(e) => setSettings((prev) => prev ? { ...prev, payment: { ...prev.payment, wechat_notify_url: e.target.value } } : prev)} placeholder="回调地址" />
                </div>
              </div>
            );

            const alipaySection = (
              <div className="rounded-2xl border border-[#e5edf8] bg-[#f8fbff] p-4">
                <div className="mb-3 text-sm font-semibold text-slate-900">支付宝参数</div>
                <div className="space-y-3">
                  <TextInput value={pm.alipay_app_id || ''} onChange={(e) => setSettings((prev) => prev ? { ...prev, payment: { ...prev.payment, alipay_app_id: e.target.value } } : prev)} placeholder="App ID" />
                  <TextInput value={pm.alipay_pid || ''} onChange={(e) => setSettings((prev) => prev ? { ...prev, payment: { ...prev.payment, alipay_pid: e.target.value } } : prev)} placeholder="卖家 ID / PID（可选）" />
                  <TextInput value={pm.alipay_gateway || ''} onChange={(e) => setSettings((prev) => prev ? { ...prev, payment: { ...prev.payment, alipay_gateway: e.target.value } } : prev)} placeholder="网关地址" />
                  <TextInput value={pm.alipay_sign_type || 'RSA2'} onChange={(e) => setSettings((prev) => prev ? { ...prev, payment: { ...prev.payment, alipay_sign_type: e.target.value } } : prev)} placeholder="签名类型" />
                  <TextInput value={pm.alipay_notify_url || ''} onChange={(e) => setSettings((prev) => prev ? { ...prev, payment: { ...prev.payment, alipay_notify_url: e.target.value } } : prev)} placeholder="异步回调地址" />
                  <TextArea rows={5} value={pm.alipay_app_private_key || ''} onChange={(e) => setSettings((prev) => prev ? { ...prev, payment: { ...prev.payment, alipay_app_private_key: e.target.value } } : prev)} placeholder="应用私钥（PKCS8）" />
                  <TextArea rows={5} value={pm.alipay_public_key || ''} onChange={(e) => setSettings((prev) => prev ? { ...prev, payment: { ...prev.payment, alipay_public_key: e.target.value } } : prev)} placeholder="支付宝公钥" />
                </div>
              </div>
            );

            const epaySection = (
              <div className="rounded-2xl border border-[#e5edf8] bg-[#f8fbff] p-4">
                <div className="mb-3 text-sm font-semibold text-slate-900">易支付参数</div>
                <div className="space-y-3">
                  <TextInput value={pm.epay_gateway || ''} onChange={(e) => setSettings((prev) => prev ? { ...prev, payment: { ...prev.payment, epay_gateway: e.target.value } } : prev)} placeholder="网关地址 https://your-epay.com" />
                  <TextInput value={pm.epay_pid || ''} onChange={(e) => setSettings((prev) => prev ? { ...prev, payment: { ...prev.payment, epay_pid: e.target.value } } : prev)} placeholder="商户ID" />
                  <TextInput value={pm.epay_key || ''} onChange={(e) => setSettings((prev) => prev ? { ...prev, payment: { ...prev.payment, epay_key: e.target.value } } : prev)} placeholder="商户密钥" type="password" />
                  <div className="text-xs font-medium text-slate-600">开放通道（可多选）</div>
                  <div className="flex flex-wrap gap-2">
                    {[
                      { value: 'alipay', label: '支付宝' },
                      { value: 'wxpay', label: '微信支付' },
                      { value: 'qqpay', label: 'QQ钱包' },
                      { value: 'tenpay', label: '财付通' },
                    ].map((ch) => {
                      const active = (pm.epay_type || 'alipay').split(',').map((s) => s.trim());
                      const checked = active.includes(ch.value);
                      return (
                        <label key={ch.value} className="flex items-center gap-1.5 rounded-xl border border-[#d7e3f4] px-3 py-1.5 text-sm text-slate-700 has-[:checked]:border-[#1d4ed8] has-[:checked]:bg-[#eff6ff] has-[:checked]:text-[#1d4ed8]">
                          <input
                            type="checkbox"
                            className="accent-[#1d4ed8]"
                            checked={checked}
                            onChange={() => {
                              const next = checked ? active.filter((s) => s !== ch.value) : [...active, ch.value];
                              setSettings((prev) => prev ? { ...prev, payment: { ...prev.payment, epay_type: next.join(',') || 'alipay' } } : prev);
                            }}
                          />
                          {ch.label}
                        </label>
                      );
                    })}
                  </div>
                  <TextInput value={pm.epay_notify_url || ''} onChange={(e) => setSettings((prev) => prev ? { ...prev, payment: { ...prev.payment, epay_notify_url: e.target.value } } : prev)} placeholder="异步通知地址" />
                  <TextInput value={pm.epay_return_url || ''} onChange={(e) => setSettings((prev) => prev ? { ...prev, payment: { ...prev.payment, epay_return_url: e.target.value } } : prev)} placeholder="同步跳转地址" />
                </div>
              </div>
            );

            const section = activeMethod === 'wechat' ? wechatSection
              : activeMethod === 'alipay' ? alipaySection
              : activeMethod === 'epay' ? epaySection
              : null;
            return section ? <div className="mt-3">{section}</div> : null;
          })()}
        </SectionCard>
      )}

      <div className="flex justify-start">
        <PrimaryButton
          disabled={busy}
          onClick={() =>
            void run(async () => {
              const next = await updateAdminPlatformSettings(settings);
              setSettings(next);
              onSaved?.(next);
              toast.success('平台配置已保存');
            })
          }
        >
          保存平台配置
        </PrimaryButton>
      </div>
    </div>
  );
}

export function AdminAuditLogsPage({ onError }: { onError: (message: string) => void }) {
  const [logs, setLogs] = useState<AdminAuditLogItem[]>([]);
  const [keyword, setKeyword] = useState('');
  const [action, setAction] = useState('');
  const { busy, run } = useBusyAction(onError);

  async function loadLogs(nextAction = action) {
    const data = await getAdminAuditLogs({ action: nextAction || undefined, limit: 300 });
    setLogs(data);
  }

  useEffect(() => {
    void run(async () => {
      await loadLogs('');
    });
  }, []);

  const actionOptions = useMemo(() => {
    return Array.from(new Set(logs.map((item) => item.action))).sort();
  }, [logs]);

  const filteredLogs = useMemo(() => {
    const term = keyword.trim().toLowerCase();
    if (!term) return logs;
    return logs.filter((item) =>
      [
        item.actor_name || '',
        item.action,
        item.target_type,
        item.target_id || '',
        item.summary || '',
        JSON.stringify(item.detail || {}),
      ].some((value) => value.toLowerCase().includes(term)),
    );
  }, [keyword, logs]);

  return (
    <div className="space-y-5">
      <SectionCard title="操作审计日志" description="集中查看套餐调整、额度补发、用户管理等后台操作记录。">
        <div className="mb-4 grid gap-3 md:grid-cols-[1fr_220px_auto]">
          <TextInput placeholder="搜索操作人、动作、目标或详情" value={keyword} onChange={(e) => setKeyword(e.target.value)} />
          <Select value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="">全部动作</option>
            {actionOptions.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </Select>
          <div className="flex gap-2">
            <PrimaryButton
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  await loadLogs(action);
                })
              }
            >
              刷新日志
            </PrimaryButton>
          </div>
        </div>

        <div className="overflow-hidden rounded-2xl border border-[#e5edf8]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[#f8fbff] text-slate-500">
              <tr>
                <th className="px-3 py-3 font-medium">时间</th>
                <th className="px-3 py-3 font-medium">操作人</th>
                <th className="px-3 py-3 font-medium">动作</th>
                <th className="px-3 py-3 font-medium">目标</th>
                <th className="px-3 py-3 font-medium">摘要</th>
                <th className="px-3 py-3 font-medium">详情</th>
              </tr>
            </thead>
            <tbody>
              {filteredLogs.map((item) => (
                <tr key={item.id} className="border-t border-[#e5edf8] align-top">
                  <td className="px-3 py-3 text-slate-600">{new Date(item.created_at).toLocaleString('zh-CN')}</td>
                  <td className="px-3 py-3">
                    <div className="font-medium text-slate-900">{item.actor_name || '系统'}</div>
                    <div className="mt-1 text-xs text-slate-500">{item.actor_user_id ? `#${item.actor_user_id}` : '-'}</div>
                  </td>
                  <td className="px-3 py-3">
                    <span className="rounded-full bg-[#eff6ff] px-2 py-1 text-xs text-[#1d4ed8]">{item.action}</span>
                  </td>
                  <td className="px-3 py-3 text-slate-700">
                    <div>{item.target_type}</div>
                    <div className="mt-1 text-xs text-slate-500">{item.target_id || '-'}</div>
                  </td>
                  <td className="px-3 py-3 text-slate-700">{item.summary || '-'}</td>
                  <td className="px-3 py-3">
                    <pre className="max-w-[360px] overflow-auto rounded-xl bg-[#f8fbff] p-2 text-xs text-slate-600">
                      {JSON.stringify(item.detail || {}, null, 2)}
                    </pre>
                  </td>
                </tr>
              ))}
              {filteredLogs.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-3 py-8 text-center text-sm text-slate-500">
                    暂无匹配的审计记录
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </SectionCard>
    </div>
  );
}

function updateStatusLabel(status: string) {
  if (status === 'idle') return '空闲';
  if (status === 'queued') return '排队中';
  if (status === 'running') return '更新中';
  if (status === 'succeeded') return '已完成';
  if (status === 'failed') return '失败';
  return status || '未知';
}

function updateStatusClass(status: string) {
  if (status === 'running' || status === 'queued') return 'bg-amber-50 text-amber-700 ring-amber-200';
  if (status === 'succeeded') return 'bg-emerald-50 text-emerald-700 ring-emerald-200';
  if (status === 'failed') return 'bg-rose-50 text-rose-700 ring-rose-200';
  return 'bg-slate-50 text-slate-700 ring-slate-200';
}

export function AdminSystemUpdatePage({ onError }: { onError: (message: string) => void }) {
  const [status, setStatus] = useState<AdminSystemUpdateStatus | null>(null);
  const [updateCheck, setUpdateCheck] = useState<AdminSystemUpdateCheck | null>(null);
  const [targetVersion, setTargetVersion] = useState('');
  const { busy, run } = useBusyAction(onError);
  const running = status?.running || status?.status === 'queued' || status?.status === 'running';

  async function loadStatus() {
    const data = await getAdminSystemUpdateStatus();
    setStatus(data);
  }

  useEffect(() => {
    void run(loadStatus);
  }, []);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      void loadStatus().catch((error: any) => onError(error?.message || '刷新更新状态失败'));
    }, 3000);
    return () => window.clearInterval(timer);
  }, [running]);

  async function handleCheckUpdate() {
    void run(async () => {
      const data = await checkAdminSystemUpdate();
      setUpdateCheck(data);
      if (!data.configured) {
        toast.error(data.message || '服务器尚未配置更新检测地址');
      } else if (data.update_available) {
        toast.success(`检测到新版本 ${data.latest_version}`);
      } else {
        toast.success('当前已是最新版本');
      }
    });
  }

  async function handleStart(target?: string) {
    const version = (target ?? targetVersion).trim();
    const confirmed = await confirm({
      title: '确认执行系统更新',
      message: version
        ? `将更新到镜像版本 ${version}。更新过程中后端和前端容器会重启，确认继续？`
        : '将按服务器当前 APP_VERSION 配置拉取镜像并执行更新。更新过程中后端和前端容器会重启，确认继续？',
      confirmText: '开始更新',
      cancelText: '取消',
      danger: true,
    });
    if (!confirmed) return;
    void run(async () => {
      const next = await startAdminSystemUpdate(version || undefined);
      setStatus(next);
      toast.success('系统更新已启动');
    });
  }

  const logTail = status?.log_tail || [];
  const latestVersion = updateCheck?.latest_version?.trim() || '';

  return (
    <div className="space-y-5">
      <SectionCard title="系统更新" description="管理员可在系统内手动触发 Docker 镜像更新。实际拉取镜像、迁移和重启由 updater 容器执行，业务后端不接触 Docker socket。">
        <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
          <div className="rounded-2xl border border-[#e5edf8] bg-[#f8fbff] p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-sm text-slate-500">当前状态</div>
                <div className="mt-2 flex items-center gap-2">
                  <span className={cn('rounded-full px-3 py-1 text-xs font-semibold ring-1', updateStatusClass(status?.status || 'unknown'))}>
                    {updateStatusLabel(status?.status || 'unknown')}
                  </span>
                  <span className="text-sm text-slate-500">当前版本：{status?.current_version || '-'}</span>
                </div>
              </div>
              <SecondaryButton disabled={busy} onClick={() => void run(loadStatus)}>
                刷新状态
              </SecondaryButton>
            </div>
            <div className="mt-4 grid gap-3 text-sm md:grid-cols-2">
              <div className="rounded-xl bg-white px-3 py-2">
                <div className="text-xs text-slate-400">目标版本</div>
                <div className="mt-1 font-medium text-slate-800">{status?.target_version || '按服务器 APP_VERSION'}</div>
              </div>
              <div className="rounded-xl bg-white px-3 py-2">
                <div className="text-xs text-slate-400">退出码</div>
                <div className="mt-1 font-medium text-slate-800">{status?.exit_code ?? '-'}</div>
              </div>
              <div className="rounded-xl bg-white px-3 py-2">
                <div className="text-xs text-slate-400">开始时间</div>
                <div className="mt-1 font-medium text-slate-800">{formatDateTime(status?.started_at)}</div>
              </div>
              <div className="rounded-xl bg-white px-3 py-2">
                <div className="text-xs text-slate-400">结束时间</div>
                <div className="mt-1 font-medium text-slate-800">{formatDateTime(status?.finished_at)}</div>
              </div>
            </div>
            {status?.message ? <p className="mt-4 rounded-2xl bg-white p-3 text-sm text-slate-600">{status.message}</p> : null}
          </div>

          <div className="space-y-4">
            <div className="rounded-2xl border border-[#dbeafe] bg-white p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-slate-900">检测更新</h3>
                  <p className="mt-1 text-xs leading-relaxed text-slate-500">
                    默认从发布清单读取最新稳定版本，管理员无需手动输入版本号。
                  </p>
                </div>
                <SecondaryButton disabled={busy || running} onClick={handleCheckUpdate}>
                  检测更新
                </SecondaryButton>
              </div>

              {updateCheck ? (
                <div className="mt-4 rounded-2xl bg-[#f8fbff] p-3 text-sm text-slate-700">
                  <div className="grid gap-2">
                    <div className="flex justify-between gap-3">
                      <span className="text-slate-500">当前版本</span>
                      <span className="font-medium">{updateCheck.current_version || '-'}</span>
                    </div>
                    <div className="flex justify-between gap-3">
                      <span className="text-slate-500">最新版本</span>
                      <span className="font-medium">{latestVersion || '-'}</span>
                    </div>
                    <div className="flex justify-between gap-3">
                      <span className="text-slate-500">发布渠道</span>
                      <span className="font-medium">{updateCheck.channel || 'stable'}</span>
                    </div>
                    {updateCheck.published_at ? (
                      <div className="flex justify-between gap-3">
                        <span className="text-slate-500">发布时间</span>
                        <span className="font-medium">{formatDateTime(updateCheck.published_at)}</span>
                      </div>
                    ) : null}
                  </div>
                  {updateCheck.message ? <p className="mt-3 text-xs text-slate-500">{updateCheck.message}</p> : null}
                  {updateCheck.release_notes ? (
                    <p className="mt-3 rounded-xl bg-white p-3 text-xs leading-relaxed text-slate-600">{updateCheck.release_notes}</p>
                  ) : null}
                  {updateCheck.manifest_url ? <p className="mt-2 break-all text-[11px] text-slate-400">清单：{updateCheck.manifest_url}</p> : null}
                  {updateCheck.update_available && latestVersion ? (
                    <PrimaryButton className="mt-4 w-full" disabled={busy || running} onClick={() => void handleStart(latestVersion)}>
                      更新到最新版 {latestVersion}
                    </PrimaryButton>
                  ) : null}
                </div>
              ) : null}
            </div>

            <div className="rounded-2xl border border-[#e5edf8] bg-white p-4">
              <label className="text-sm font-semibold text-slate-900">高级：指定镜像版本</label>
              <TextInput
                className="mt-2"
                value={targetVersion}
                onChange={(event) => setTargetVersion(event.target.value)}
                placeholder="可选：v1.2.3 或 sha-abcdef123456"
                disabled={running}
              />
              <p className="mt-2 text-xs leading-relaxed text-slate-500">
                通常不需要填写版本号。仅在回滚、灰度或技术支持要求时使用。填写版本时，updater 会先更新服务器 .env 中的 APP_VERSION，再执行拉取、迁移、重启和健康检查。
              </p>
              <PrimaryButton className="mt-4 w-full" disabled={busy || running} onClick={() => void handleStart()}>
                {running ? '更新执行中' : '按指定版本更新'}
              </PrimaryButton>
            </div>
          </div>
        </div>
      </SectionCard>

      <SectionCard title="更新日志" description="仅展示最近日志尾部，并在服务端做基础脱敏。">
        <pre className="max-h-[420px] overflow-auto rounded-2xl bg-slate-950 p-4 text-xs leading-relaxed text-slate-100">
          {logTail.length ? logTail.join('\n') : '暂无更新日志'}
        </pre>
      </SectionCard>
    </div>
  );
}

export function AdminSystemPromptsPage({ onError }: { onError: (message: string) => void }) {
  const [prompts, setPrompts] = useState<AdminSystemPrompt[]>([]);
  const [editMap, setEditMap] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const { busy, run } = useBusyAction(onError);

  useEffect(() => {
    void run(async () => {
      const data = await getAdminSystemPrompts();
      setPrompts(Object.values(data));
    });
  }, []);

  async function handleSave(fullKey: string) {
    setSaving((prev) => ({ ...prev, [fullKey]: true }));
    try {
      await updateAdminSystemPrompts({ [fullKey]: editMap[fullKey] ?? '' });
      setPrompts((prev) => prev.map((p) => (p.key === fullKey ? { ...p, content: editMap[fullKey] ?? '' } : p)));
    } catch (err: any) {
      onError(err?.message || '保存失败');
    } finally {
      setSaving((prev) => ({ ...prev, [fullKey]: false }));
    }
  }

  return (
    <div className="space-y-5">
      <SectionCard title="系统默认提示词" description="管理全局生效的系统提示词模板。所有用户未自定义时的默认值，修改后即时生效。">
        <div className="space-y-6">
          {prompts.map((prompt) => {
            const fullKey = prompt.key;
            const value = editMap[fullKey] ?? prompt.content ?? '';
            return (
              <div key={fullKey}>
                <div className="mb-2 flex items-center justify-between">
                  <label className="text-sm font-medium text-slate-800">{prompt.name}</label>
                  <span className="text-xs text-slate-400">{fullKey}</span>
                </div>
                <TextArea
                  rows={6}
                  value={value}
                  onChange={(e) => setEditMap((prev) => ({ ...prev, [fullKey]: e.target.value }))}
                  placeholder="暂无提示词内容..."
                />
                <div className="mt-2 flex justify-end">
                  <PrimaryButton
                    disabled={busy || saving[fullKey] || value === (prompts.find((p) => p.key === fullKey)?.content ?? '')}
                    onClick={() => void handleSave(fullKey)}
                  >
                    {saving[fullKey] ? '保存中…' : '保存'}
                  </PrimaryButton>
                </div>
              </div>
            );
          })}
        </div>
      </SectionCard>
    </div>
  );
}

export { AdminRevenueDashboardPage } from './RevenueDashboard';
