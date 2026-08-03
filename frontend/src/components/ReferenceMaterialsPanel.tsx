import { useEffect, useMemo, useState } from 'react';
import {
  BookMarked,
  BookOpen,
  Check,
  ChevronDown,
  FileText,
  Lightbulb,
  ListChecks,
  Loader2,
  Pencil,
  Plus,
  ShieldAlert,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';

import {
  addDeconstructionRef,
  listDeconstructionRefs,
  listDeconstructionWorks,
  removeDeconstructionRef,
  type DeconstructionRefItem,
  type DeconstructionWorkItem,
  type StoryBible,
} from '../api';
import { normalizeErrorMessage } from '../lib/errors';
import { toast } from '../lib/toast';
import type {
  ReferenceMaterialForm,
  ReferenceMaterialSummary,
  ReferenceRoutine,
  ReferenceSummaryItem,
} from './referenceMaterialsUtils';
import { createReferenceMaterialForm, referenceValueText } from './referenceMaterialsUtils';
import { Button } from './ui/Button';
import { Input, TextArea } from './ui/Input';

interface Props {
  storyId: number;
  storyBible: StoryBible;
  summary: ReferenceMaterialSummary;
  saving: boolean;
  onCreateResource: () => void;
  onReferencesChanged: () => void | Promise<void>;
  onSaveReference: (form: ReferenceMaterialForm) => Promise<boolean>;
}

type ReferenceHeaderProps = Pick<Props, 'summary' | 'onCreateResource'> & { onEdit: () => void };

export default function ReferenceMaterialsPanel({ storyId, storyBible, summary, saving, onCreateResource, onReferencesChanged, onSaveReference }: Props) {
  const [showAllRoutines, setShowAllRoutines] = useState(false);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<ReferenceMaterialForm>(() => createReferenceMaterialForm(storyBible));
  const visibleRoutines = showAllRoutines ? summary.routines : summary.routines.slice(0, 6);

  function startEditing() {
    setForm(createReferenceMaterialForm(storyBible));
    setEditing(true);
  }

  async function saveReference() {
    if (await onSaveReference(form)) setEditing(false);
  }

  if (editing) {
    return (
      <ReferenceMaterialEditor
        form={form}
        saving={saving}
        onChange={setForm}
        onCancel={() => setEditing(false)}
        onSave={() => void saveReference()}
      />
    );
  }

  if (!summary.hasContent) {
    return (
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-4 sm:p-6">
        <ReferenceHeader summary={summary} onCreateResource={onCreateResource} onEdit={startEditing} />
        <DeconstructionSourceManager storyId={storyId} onReferencesChanged={onReferencesChanged} />
        <div className="mt-6 rounded-md border border-dashed border-slate-300 px-5 py-12 text-center">
          <BookMarked className="mx-auto text-slate-300" size={30} aria-hidden="true" />
          <p className="mt-3 text-sm font-medium text-slate-700">暂无写作参考</p>
          <p className="mt-1 text-xs text-slate-500">导入并分析参考作品后，系统会在这里整理作者画像与可执行写作规划。</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
      <ReferenceHeader summary={summary} onCreateResource={onCreateResource} onEdit={startEditing} />
      <DeconstructionSourceManager storyId={storyId} onReferencesChanged={onReferencesChanged} />

      {summary.positioning ? (
        <section className="mt-5 border-l-4 border-blue-500 bg-blue-50 px-4 py-3">
          <p className="text-xs font-semibold text-blue-700">一句话风格定位</p>
          <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-6 text-slate-800">{summary.positioning}</p>
        </section>
      ) : null}

      <div className="mt-6 grid items-start gap-6 xl:grid-cols-2">
        <PlanSection title="表达规划" icon={<Sparkles size={16} />} items={summary.expressionPlan} />
        <PlanSection title="节奏规划" icon={<ListChecks size={16} />} items={summary.rhythmPlan} />
      </div>

      {(summary.mustDo.length || summary.avoid.length || summary.promptNotes.length) ? (
        <section className="mt-7 border-t border-slate-200 pt-6">
          <h4 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <Lightbulb size={16} className="text-amber-500" aria-hidden="true" />正文执行规划
          </h4>
          <div className="mt-4 grid gap-5 lg:grid-cols-3">
            <Checklist title="正文执行清单" icon={<Check size={15} />} values={summary.mustDo} tone="green" />
            <Checklist title="避免事项" icon={<ShieldAlert size={15} />} values={summary.avoid} tone="red" />
            <Checklist title="创作提示" icon={<FileText size={15} />} values={summary.promptNotes} tone="blue" />
          </div>
        </section>
      ) : null}

      {summary.routines.length ? (
        <section className="mt-7 border-t border-slate-200 pt-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h4 className="text-sm font-semibold text-slate-900">可复用写作模式</h4>
            <span className="text-xs text-slate-500">共 {summary.routines.length} 个模式</span>
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            {visibleRoutines.map((routine, index) => (
              <article key={`${routine.name}-${index}`} className="min-w-0 rounded-md border border-slate-200 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <h5 className="break-words text-sm font-semibold text-slate-900">{routine.name}</h5>
                  {routine.category ? <span className="rounded bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">{routine.category}</span> : null}
                </div>
                {routine.structure ? <RoutineField label="结构" value={routine.structure} /> : null}
                {routine.emotionCurve ? <RoutineField label="情绪走向" value={routine.emotionCurve} /> : null}
                {routine.evidence ? <RoutineField label="适用依据" value={routine.evidence} /> : null}
              </article>
            ))}
          </div>
          {summary.routines.length > 6 ? (
            <button type="button" onClick={() => setShowAllRoutines((value) => !value)} className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700">
              <ChevronDown size={14} className={showAllRoutines ? 'rotate-180' : ''} />
              {showAllRoutines ? '收起模式' : `查看其余 ${summary.routines.length - 6} 个模式`}
            </button>
          ) : null}
        </section>
      ) : null}

      <SupplementaryMaterials summary={summary} />

      {(summary.report || summary.samples.length) ? (
        <section className="mt-7 space-y-3 border-t border-slate-200 pt-6">
          <h4 className="text-sm font-semibold text-slate-900">分析依据</h4>
          {summary.report ? (
            <details className="group rounded-md border border-slate-200 bg-white">
              <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-medium text-slate-800">
                <FileText size={15} className="text-slate-500" />完整分析报告
                <ChevronDown size={14} className="ml-auto text-slate-400 group-open:rotate-180" />
              </summary>
              <div className="max-h-[420px] overflow-y-auto border-t border-slate-200 px-4 py-4 whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">{summary.report}</div>
            </details>
          ) : null}
          {summary.samples.length ? (
            <details className="group rounded-md border border-slate-200 bg-white">
              <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-medium text-slate-800">
                <BookMarked size={15} className="text-slate-500" />风格样本（{summary.samples.length}）
                <ChevronDown size={14} className="ml-auto text-slate-400 group-open:rotate-180" />
              </summary>
              <div className="space-y-4 border-t border-slate-200 px-4 py-4">
                {summary.samples.map((sample, index) => (
                  <div key={`${sample.label}-${index}`}>
                    <p className="text-xs font-semibold text-slate-600">{sample.label}</p>
                    <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">{sample.snippet}</p>
                  </div>
                ))}
              </div>
            </details>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

function DeconstructionSourceManager({
  storyId,
  onReferencesChanged,
}: {
  storyId: number;
  onReferencesChanged: () => void | Promise<void>;
}) {
  const [expanded, setExpanded] = useState(false);
  const [refs, setRefs] = useState<DeconstructionRefItem[]>([]);
  const [works, setWorks] = useState<DeconstructionWorkItem[]>([]);
  const [refsLoading, setRefsLoading] = useState(true);
  const [worksLoading, setWorksLoading] = useState(false);
  const [actionKey, setActionKey] = useState<string | null>(null);

  const availableWorks = useMemo(
    () => works.filter((work) => work.decon_status === 'completed' && !refs.some((ref) => ref.work_id === work.id)),
    [works, refs],
  );

  useEffect(() => {
    let cancelled = false;
    listDeconstructionRefs(storyId)
      .then((items) => {
        if (!cancelled) setRefs(items);
      })
      .catch((error) => {
        if (!cancelled) toast.error(normalizeErrorMessage(error, '加载参考来源失败'));
      })
      .finally(() => {
        if (!cancelled) setRefsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [storyId]);

  async function reloadRefs() {
    setRefs(await listDeconstructionRefs(storyId));
  }

  async function loadWorks() {
    if (worksLoading) return;
    setWorksLoading(true);
    try {
      setWorks(await listDeconstructionWorks());
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '加载可引用作品失败'));
    } finally {
      setWorksLoading(false);
    }
  }

  async function toggleExpanded() {
    const nextExpanded = !expanded;
    setExpanded(nextExpanded);
    if (nextExpanded) await loadWorks();
  }

  async function handleAdd(workId: number) {
    if (actionKey) return;
    setActionKey(`add-${workId}`);
    try {
      await addDeconstructionRef(storyId, workId);
      await reloadRefs();
      await onReferencesChanged();
      toast.success('参考来源已加入写作参考');
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '加入参考来源失败'));
    } finally {
      setActionKey(null);
    }
  }

  async function handleRemove(refId: number) {
    if (actionKey) return;
    setActionKey(`remove-${refId}`);
    try {
      await removeDeconstructionRef(storyId, refId);
      await reloadRefs();
      await onReferencesChanged();
      toast.success('参考来源已移除');
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '移除参考来源失败'));
    } finally {
      setActionKey(null);
    }
  }

  return (
    <section className="mt-5 rounded-md border border-slate-200 bg-slate-50 px-4 py-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h4 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <BookOpen size={15} className="text-blue-600" aria-hidden="true" />
            参考来源
          </h4>
          <p className="mt-1 text-xs text-slate-500">引用已完成分析的拆书作品，作为作者画像和写作风格参考。</p>
        </div>
        <button
          type="button"
          onClick={() => void toggleExpanded()}
          className="inline-flex items-center justify-center rounded-md border border-[#d7e3f4] bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-[#eff6ff]"
        >
          {expanded ? '收起来源' : '管理来源'}
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {refsLoading ? (
          <span className="inline-flex items-center gap-1 text-xs text-slate-500">
            <Loader2 size={13} className="animate-spin" aria-hidden="true" />
            加载来源中...
          </span>
        ) : refs.length ? (
          refs.map((ref) => (
            <span key={ref.id} className="inline-flex max-w-full items-center gap-1 rounded-md bg-white px-2.5 py-1 text-xs text-slate-700 ring-1 ring-slate-200">
              <Check size={12} className="shrink-0 text-emerald-600" aria-hidden="true" />
              <span className="min-w-0 truncate">{ref.title}</span>
              {expanded ? (
                <button
                  type="button"
                  title="移除参考来源"
                  disabled={Boolean(actionKey)}
                  onClick={() => void handleRemove(ref.id)}
                  className="ml-1 flex h-5 w-5 shrink-0 items-center justify-center rounded text-slate-400 hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {actionKey === `remove-${ref.id}` ? <Loader2 size={12} className="animate-spin" /> : <X size={12} />}
                </button>
              ) : null}
            </span>
          ))
        ) : (
          <p className="text-xs text-slate-500">暂未引用参考来源。</p>
        )}
      </div>

      {expanded ? (
        <div className="mt-4 border-t border-slate-200 pt-3">
          <p className="text-xs font-medium text-slate-700">可引用来源</p>
          {worksLoading ? (
            <p className="mt-2 inline-flex items-center gap-1 text-xs text-slate-500">
              <Loader2 size={13} className="animate-spin" aria-hidden="true" />
              加载可引用作品中...
            </p>
          ) : availableWorks.length ? (
            <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {availableWorks.map((work) => (
                <button
                  key={work.id}
                  type="button"
                  disabled={Boolean(actionKey)}
                  onClick={() => void handleAdd(work.id)}
                  className="min-w-0 rounded-md border border-slate-200 bg-white px-3 py-2 text-left text-xs text-slate-700 transition hover:border-blue-200 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    {actionKey === `add-${work.id}` ? <Loader2 size={13} className="shrink-0 animate-spin text-blue-600" /> : <Plus size={13} className="shrink-0 text-blue-600" />}
                    <span className="min-w-0 truncate font-medium">{work.title}</span>
                  </span>
                  <span className="mt-1 block truncate text-[11px] text-slate-500">{work.genre || '已完成作者画像分析'}</span>
                </button>
              ))}
            </div>
          ) : (
            <p className="mt-2 text-xs text-slate-500">暂无可引用的已完成拆书作品，请先在拆书库完成分析。</p>
          )}
        </div>
      ) : null}
    </section>
  );
}

function ReferenceHeader({ summary, onCreateResource, onEdit }: ReferenceHeaderProps) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <h3 className="text-base font-semibold text-slate-900">参考写作规划</h3>
        <p className="mt-1 text-xs text-slate-500">将参考作品分析提炼为正文生成时可直接执行的写作要求。</p>
        {summary.hasContent ? (
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
            <span>来源：{summary.sourceLabel}</span>
            {summary.sampledChapterCount ? <span>分析样本：{summary.sampledChapterCount} 章</span> : null}
            {summary.confidencePercent != null ? <span>可信度：{summary.confidencePercent}%</span> : null}
          </div>
        ) : null}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" icon={<Pencil size={14} />} onClick={onEdit}>{summary.hasContent ? '编辑写作参考' : '新建写作参考'}</Button>
        <Button size="sm" variant="secondary" icon={<Plus size={14} />} onClick={onCreateResource}>新增自定义资料</Button>
      </div>
    </div>
  );
}

const EDIT_EXPRESSION_FIELDS: Array<{ key: keyof ReferenceMaterialForm; label: string }> = [
  { key: 'sentence', label: '句式节奏' },
  { key: 'dialogue', label: '对话组织' },
  { key: 'description', label: '描写方式' },
  { key: 'emotionExpression', label: '情绪表达' },
  { key: 'povAndNarration', label: '叙事视角' },
];

const EDIT_RHYTHM_FIELDS: Array<{ key: keyof ReferenceMaterialForm; label: string; rows?: number }> = [
  { key: 'openingHook', label: '开篇抓力' },
  { key: 'chapterEndHooks', label: '章尾钩子（每行一条）', rows: 4 },
  { key: 'emotionCycle', label: '情绪循环' },
  { key: 'infoReleasePattern', label: '信息释放' },
];

function ReferenceMaterialEditor({ form, saving, onChange, onCancel, onSave }: {
  form: ReferenceMaterialForm;
  saving: boolean;
  onChange: (form: ReferenceMaterialForm) => void;
  onCancel: () => void;
  onSave: () => void;
}) {
  function setField(key: keyof ReferenceMaterialForm, value: string) {
    onChange({ ...form, [key]: value });
  }

  function updateRoutine(index: number, patch: Partial<ReferenceRoutine>) {
    onChange({ ...form, routines: form.routines.map((routine, routineIndex) => routineIndex === index ? { ...routine, ...patch } : routine) });
  }

  function removeRoutine(index: number) {
    onChange({ ...form, routines: form.routines.filter((_, routineIndex) => routineIndex !== index) });
  }

  function addRoutine() {
    onChange({ ...form, routines: [...form.routines, { name: '', category: '', structure: '', emotionCurve: '', evidence: '' }] });
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
      <div className="flex flex-col gap-3 border-b border-slate-200 pb-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="text-base font-semibold text-slate-900">编辑写作参考</h3>
          <p className="mt-1 text-xs text-slate-500">人工修订会直接成为后续大纲、章节规划和正文生成的写作规则。</p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="secondary" disabled={saving} onClick={onCancel}>取消</Button>
          <Button size="sm" loading={saving} onClick={onSave}>保存修改</Button>
        </div>
      </div>

      <div className="mt-5 grid items-start gap-6 xl:grid-cols-2">
        <EditSection title="表达规划">
          {EDIT_EXPRESSION_FIELDS.map((field) => (
            <EditTextArea key={field.key} label={field.label} value={String(form[field.key])} onChange={(value) => setField(field.key, value)} />
          ))}
        </EditSection>
        <EditSection title="节奏规划">
          {EDIT_RHYTHM_FIELDS.map((field) => (
            <EditTextArea key={field.key} label={field.label} rows={field.rows} value={String(form[field.key])} onChange={(value) => setField(field.key, value)} />
          ))}
        </EditSection>
        <EditSection title="正文执行规划">
          <EditTextArea label="正文执行清单（每行一条）" rows={6} value={form.mustDo} onChange={(value) => setField('mustDo', value)} />
          <EditTextArea label="避免事项（每行一条）" rows={6} value={form.avoid} onChange={(value) => setField('avoid', value)} />
          <EditTextArea label="创作提示（每行一条）" rows={6} value={form.promptNotes} onChange={(value) => setField('promptNotes', value)} />
        </EditSection>
        <EditSection title="分析报告">
          <EditTextArea label="报告内容" rows={18} value={form.report} onChange={(value) => setField('report', value)} />
        </EditSection>
      </div>

      <section className="mt-7 border-t border-slate-200 pt-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h4 className="text-sm font-semibold text-slate-900">可复用写作模式</h4>
            <p className="mt-1 text-xs text-slate-500">整理可在正文中重复使用的冲突、转折和情绪结构。</p>
          </div>
          <Button type="button" variant="secondary" size="sm" icon={<Plus size={14} />} onClick={addRoutine}>新增模式</Button>
        </div>
        {form.routines.length ? (
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            {form.routines.map((routine, index) => (
              <div key={index} className="rounded-md border border-slate-200 p-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  <label>
                    <span className="mb-1.5 block text-xs font-medium text-slate-700">模式名称</span>
                    <Input value={routine.name} onChange={(event) => updateRoutine(index, { name: event.target.value })} className="rounded-md" />
                  </label>
                  <label>
                    <span className="mb-1.5 block text-xs font-medium text-slate-700">分类</span>
                    <Input value={routine.category} onChange={(event) => updateRoutine(index, { category: event.target.value })} className="rounded-md" />
                  </label>
                  <EditTextArea label="结构" value={routine.structure} onChange={(value) => updateRoutine(index, { structure: value })} />
                  <EditTextArea label="情绪走向" value={routine.emotionCurve} onChange={(value) => updateRoutine(index, { emotionCurve: value })} />
                  <div className="sm:col-span-2">
                    <EditTextArea label="适用依据" value={routine.evidence} onChange={(value) => updateRoutine(index, { evidence: value })} />
                  </div>
                </div>
                <button type="button" onClick={() => removeRoutine(index)} className="mt-3 inline-flex items-center gap-1 text-xs text-red-500 hover:text-red-600">
                  <Trash2 size={13} />删除模式
                </button>
              </div>
            ))}
          </div>
        ) : <p className="mt-4 text-xs text-slate-500">暂无写作模式，可以按需要新增。</p>}
      </section>
    </div>
  );
}

function EditSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="min-w-0">
      <h4 className="text-sm font-semibold text-slate-900">{title}</h4>
      <div className="mt-3 space-y-3">{children}</div>
    </section>
  );
}

function EditTextArea({ label, value, rows = 3, onChange }: { label: string; value: string; rows?: number; onChange: (value: string) => void }) {
  return (
    <label className="block min-w-0">
      <span className="mb-1.5 block text-xs font-medium text-slate-700">{label}</span>
      <TextArea value={value} rows={rows} onChange={(event) => onChange(event.target.value)} className="rounded-md text-xs leading-5" />
    </label>
  );
}

function PlanSection({ title, icon, items }: { title: string; icon: React.ReactNode; items: ReferenceSummaryItem[] }) {
  if (!items.length) return null;
  return (
    <section className="min-w-0">
      <h4 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
        <span className="text-blue-600">{icon}</span>{title}
      </h4>
      <dl className="mt-3 divide-y divide-slate-100 border-y border-slate-200">
        {items.map((item) => (
          <div key={item.key} className="grid gap-1 py-3 sm:grid-cols-[88px_minmax(0,1fr)]">
            <dt className="text-xs font-medium text-slate-500">{item.label}</dt>
            <dd className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-800">{item.text}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function Checklist({ title, icon, values, tone }: { title: string; icon: React.ReactNode; values: string[]; tone: 'green' | 'red' | 'blue' }) {
  if (!values.length) return null;
  const toneClass = tone === 'green' ? 'text-emerald-600' : tone === 'red' ? 'text-red-500' : 'text-blue-600';
  return (
    <div className="min-w-0">
      <h5 className={`flex items-center gap-2 text-xs font-semibold ${toneClass}`}>{icon}{title}</h5>
      <ul className="mt-2 space-y-2">
        {values.map((value, index) => <li key={index} className="break-words border-l-2 border-slate-200 pl-3 text-sm leading-6 text-slate-700">{value}</li>)}
      </ul>
    </div>
  );
}

function RoutineField({ label, value }: { label: string; value: string }) {
  return <p className="mt-2 break-words text-xs leading-5 text-slate-600"><span className="font-medium text-slate-700">{label}：</span>{value}</p>;
}

function SupplementaryMaterials({ summary }: { summary: ReferenceMaterialSummary }) {
  const groups = [
    { title: '已提炼写作技法', values: summary.learnedTechniques },
    { title: '参考剧情结构', values: summary.referencePlots },
    { title: '参考节奏模型', values: summary.referenceRhythm == null ? [] : [summary.referenceRhythm] },
    { title: '参考情绪模块', values: summary.emotionModules == null ? [] : [summary.emotionModules] },
  ].filter((group) => group.values.some((value) => referenceValueText(value)));
  if (!groups.length) return null;
  return (
    <section className="mt-7 border-t border-slate-200 pt-6">
      <h4 className="text-sm font-semibold text-slate-900">其他写作资料</h4>
      <div className="mt-3 grid gap-4 lg:grid-cols-2">
        {groups.map((group) => (
          <div key={group.title} className="min-w-0">
            <h5 className="text-xs font-medium text-slate-500">{group.title}</h5>
            <ul className="mt-2 space-y-2">
              {group.values.map((value, index) => <li key={index} className="break-words text-sm leading-6 text-slate-700">{referenceValueText(value)}</li>)}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
