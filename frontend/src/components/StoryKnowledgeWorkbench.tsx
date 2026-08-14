import { useDeferredValue, useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react';
import { createPortal } from 'react-dom';
import { ArrowLeft, BookKey, BookOpen, Boxes, ChartNoAxesGantt, CheckCircle2, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, CircleAlert, Database, GitBranch, List, Loader2, Network, Pencil, Plus, RefreshCw, Save, Search, SlidersHorizontal, Sparkles, Trash2, X } from 'lucide-react';
import {
  createStoryKnowledge,
  createStoryKnowledgeCategory,
  deleteStoryKnowledge,
  deleteStoryKnowledgeCategory,
  getStoryChapterContext,
  getStoryChapterContexts,
  getStoryKnowledge,
  getBackgroundTaskStatus,
  syncStoryKnowledgeWithAI,
  regenerateStoryChapterContext,
  updateStoryBible,
  updateStoryKnowledge,
  updateStoryKnowledgeCategory,
  updateStoryChapterContext,
  type BackgroundTaskStatus,
  type ChapterContextPack,
  type ChapterContextSummary,
  type StoryBible,
  type StoryKnowledgeCategory,
  type StoryKnowledgeItem,
  type StoryKnowledgeKind,
  type StoryKnowledgeMutation,
  type StoryKnowledgeResponse,
  type StoryKnowledgeSyncScope,
} from '../api';
import { confirm } from '../lib/confirm';
import { normalizeErrorMessage } from '../lib/errors';
import { formatDateTime } from '../lib/format';
import { toast } from '../lib/toast';
import { Button } from './ui/Button';
import { Input, Select, TextArea } from './ui/Input';
import ReferenceMaterialsPanel from './ReferenceMaterialsPanel';
import KnowledgeVisualizations from './KnowledgeVisualizations';
import {
  parseCreationPack,
  serializeCreationPack,
  type CreationPackItem,
  type CreationPackPresentation,
  type CreationPackSection,
} from './chapterCreationPackPresentation';
import {
  buildReferenceMaterialPayload,
  buildReferenceMaterialSummary,
  type ReferenceMaterialForm,
} from './referenceMaterialsUtils';
import {
  asBibleRecord,
  buildStoryBiblePayload,
  collectBibleSections,
  createStoryBibleFormState,
  hasBibleValue,
  readBibleField,
  storyBibleFieldLabel,
  worldSettingRowsToObject,
  worldSettingToRows,
  type BibleFormState,
  type WorldSettingRow,
} from './storyBibleUtils';

interface Props {
  storyId: number;
  storyTitle: string;
  onClose: () => void;
  onContentUpdated?: () => void | Promise<void>;
}

type AISyncNotice = { tone: 'success' | 'warning' | 'error'; message: string; details?: string };

const SYNC_SCOPE_LABELS: Record<StoryKnowledgeSyncScope, string> = {
  all: '全部设定',
  entities: '人物与主体',
  facts: '事件与事实',
  plot_threads: '伏笔与剧情线',
};

export function buildAISyncNotice(task?: BackgroundTaskStatus | null): AISyncNotice | null {
  if (!task) return null;
  if (task.status === 'succeeded') {
    const result = task.result_json;
    const failedSources = Number(result?.failed_sources || 0);
    const counts = result?.counts;
    const details = counts
      ? `实体 ${counts.entities || 0} · 事实 ${counts.facts || 0} · 伏笔 ${counts.plot_threads || 0}${counts.archived_facts ? ` · 归档旧事实 ${counts.archived_facts}` : ''}`
      : undefined;
    return {
      tone: failedSources > 0 ? 'warning' : 'success',
      message: result?.message || '人物关系与时间轴已同步',
      details,
    };
  }
  if (['failed', 'cancelled', 'canceled'].includes(task.status)) {
    const completed = Number(task.metadata_json?.completed || 0);
    const total = Number(task.metadata_json?.total || 0);
    const details = total > 0 ? `已处理 ${completed}/${total} 组内容，本次未生成可保存结果` : undefined;
    return { tone: 'error', message: task.error_message || task.message || 'AI 同步失败', details };
  }
  return { tone: 'warning', message: task.message || 'AI 同步任务仍在后台运行' };
}

type ViewKey = 'chapter_context' | 'story_bible' | StoryKnowledgeKind;
type ResourceView = 'reference' | 'library';
type KnowledgeDisplayMode = 'list' | 'visual';
type FieldType = 'text' | 'textarea' | 'number' | 'object' | 'list' | 'status' | 'category' | 'resource_type' | 'entity_type' | 'entity_ref';

interface FieldDefinition {
  key: keyof StoryKnowledgeMutation;
  label: string;
  type?: FieldType;
  required?: boolean;
  placeholder?: string;
}

type KeyValueRow = WorldSettingRow;

const VIEW_TABS: Array<{
  key: ViewKey;
  label: string;
  description: string;
  icon: typeof Database;
  collection?: keyof Pick<StoryKnowledgeResponse, 'resources' | 'entities' | 'facts' | 'plot_threads'>;
}> = [
  { key: 'chapter_context', label: '章节创作包', description: '全部章节的创作包与生成状态', icon: ChartNoAxesGantt },
  { key: 'story_bible', label: '作品圣经', description: '创意核心、世界规则、写作约束', icon: BookOpen },
  { key: 'resource', label: '资料', description: '写作参考、规则与自定义资料', icon: Database, collection: 'resources' },
  { key: 'entity', label: '人物与地点', description: '人物、地点、势力、物品', icon: Boxes, collection: 'entities' },
  { key: 'fact', label: '事实', description: '带章节有效期的连续性事实', icon: BookKey, collection: 'facts' },
  { key: 'plot_thread', label: '伏笔与剧情线', description: '埋设、推进与回收窗口', icon: GitBranch, collection: 'plot_threads' },
];

const FIELD_DEFINITIONS: Record<StoryKnowledgeKind, FieldDefinition[]> = {
  resource: [
    { key: 'title', label: '资料标题', required: true, placeholder: '例如：灵石等级规则' },
    { key: 'resource_type', label: '资料类型', type: 'resource_type' },
    { key: 'summary', label: '摘要', type: 'textarea' },
    { key: 'content_text', label: '正文内容', type: 'textarea' },
    { key: 'content_json', label: '结构化补充', type: 'object' },
    { key: 'importance', label: '重要度', type: 'number' },
    { key: 'valid_from_chapter', label: '起始章节', type: 'number' },
    { key: 'valid_to_chapter', label: '结束章节', type: 'number' },
    { key: 'status', label: '状态', type: 'status' },
  ],
  entity: [
    { key: 'canonical_name', label: '名称', required: true, placeholder: '人物、地点、势力或物品名称' },
    { key: 'entity_type', label: '类型', type: 'entity_type' },
    { key: 'aliases_json', label: '别名', type: 'list', placeholder: '每行一个别名' },
    { key: 'profile_json', label: '档案字段', type: 'object' },
    { key: 'first_chapter', label: '首次出现章节', type: 'number' },
    { key: 'last_chapter', label: '最后出现章节', type: 'number' },
    { key: 'importance', label: '重要度', type: 'number' },
    { key: 'status', label: '状态', type: 'status' },
  ],
  fact: [
    { key: 'category_id', label: '分类', type: 'category' },
    { key: 'subject_key', label: '关系起点', type: 'entity_ref' },
    { key: 'predicate', label: '关系', placeholder: '例如：属于、敌对、位于、持有' },
    { key: 'object_key', label: '关系终点', type: 'entity_ref' },
    { key: 'value_text', label: '事实描述', type: 'textarea', required: true, placeholder: '用一句明确的话记录不可前后矛盾的事实' },
    { key: 'valid_from_chapter', label: '生效章节', type: 'number' },
    { key: 'valid_to_chapter', label: '失效章节', type: 'number' },
    { key: 'confidence', label: '可信度', type: 'number' },
    { key: 'status', label: '状态', type: 'status' },
  ],
  plot_thread: [
    { key: 'category_id', label: '分类', type: 'category' },
    { key: 'title', label: '标题', required: true },
    { key: 'description', label: '线索说明', type: 'textarea' },
    { key: 'setup_chapter', label: '埋设章节', type: 'number' },
    { key: 'expected_payoff_from', label: '最早回收章节', type: 'number' },
    { key: 'expected_payoff_to', label: '最晚回收章节', type: 'number' },
    { key: 'actual_payoff_chapter', label: '实际回收章节', type: 'number' },
    { key: 'related_entity_keys', label: '关联对象', type: 'list', placeholder: '每行一个人物、地点或物品' },
    { key: 'priority', label: '优先级', type: 'number' },
    { key: 'status', label: '状态', type: 'status' },
  ],
};

const EMPTY_RESPONSE: StoryKnowledgeResponse = {
  story_id: 0,
  knowledge_revision: 1,
  story_bible: {},
  categories: [],
  counts: {},
  resources: [],
  entities: [],
  facts: [],
  plot_threads: [],
};

const STATUS_OPTIONS: Record<StoryKnowledgeKind, Array<{ value: string; label: string }>> = {
  resource: [
    { value: 'active', label: '有效' },
    { value: 'archived', label: '已归档' },
    { value: 'superseded', label: '已取代' },
  ],
  entity: [
    { value: 'active', label: '有效' },
    { value: 'archived', label: '已归档' },
    { value: 'superseded', label: '已取代' },
  ],
  fact: [
    { value: 'active', label: '有效' },
    { value: 'archived', label: '已归档' },
    { value: 'superseded', label: '已取代' },
  ],
  plot_thread: [
    { value: 'open', label: '待推进' },
    { value: 'active', label: '推进中' },
    { value: 'due', label: '待回收' },
    { value: 'resolved', label: '已回收' },
    { value: 'archived', label: '已归档' },
    { value: 'abandoned', label: '已放弃' },
  ],
};

const SOURCE_OPTIONS = [
  { value: 'manual', label: '人工维护' },
  { value: 'system', label: '系统生成' },
  { value: 'agent', label: 'AI 助手' },
  { value: 'import', label: '导入分析' },
  { value: 'legacy_projection', label: '作品角色同步' },
  { value: 'story_memory', label: '章节记忆同步' },
  { value: 'story_bible', label: '作品圣经同步' },
];

const ENTITY_TYPE_OPTIONS = [
  { value: 'character', label: '人物' },
  { value: 'faction', label: '势力' },
  { value: 'location', label: '地点' },
  { value: 'item', label: '物品' },
  { value: 'concept', label: '概念' },
];

const PROFILE_FIELD_LABELS: Record<string, string> = {
  name: '姓名', role: '角色定位', big_five: '性格特征', arc: '人物弧光', relationships: '人物关系', description: '人物简介',
  appearance: '外貌', background: '背景', motivation: '动机', goal: '目标', conflict: '冲突', ability: '能力',
};

function formatProfileValue(key: string, value: string): string {
  if (key === 'big_five') {
    return value
      .replace(/O\s*[:：]/g, '开放性：')
      .replace(/C\s*[:：]/g, '尽责性：')
      .replace(/E\s*[:：]/g, '外向性：')
      .replace(/A\s*[:：]/g, '宜人性：')
      .replace(/N\s*[:：]/g, '情绪敏感度：')
      .replace(/(\d)(?=[\u4e00-\u9fff]+：)/g, '$1 · ')
      .replace(/\s{2,}/g, ' · ');
  }
  if (key === 'arc') {
    return value.replace(/\bstart\s*:/gi, '起点：').replace(/\bmiddle\s*:/gi, '中段：').replace(/\bend\s*:/gi, '终点：');
  }
  if (key === 'relationships') {
    return value.replace(/\bto\s*:/gi, '对象：').replace(/\btype\s*:/gi, '；类型：').replace(/\bdescription\s*:/gi, '；说明：');
  }
  return value;
}

function itemTitle(item: StoryKnowledgeItem): string {
  return item.title || item.canonical_name || item.value_text || item.subject_key || '未命名设定';
}

function itemSummary(item: StoryKnowledgeItem): string {
  return item.summary || item.description || item.value_text || item.content_text || '';
}

function isRelationshipFact(item: StoryKnowledgeItem): boolean {
  return Boolean(item.subject_key && item.predicate && item.object_key);
}

function sanitizeKnowledgeText(value: string, entities: StoryKnowledgeItem[]): string {
  const names = new Map<string, string>();
  for (const entity of entities) {
    const name = entity.canonical_name || entity.title;
    if (!name) continue;
    for (const key of [entity.entity_key, entity.canonical_name, ...(entity.aliases_json || [])]) {
      if (key) names.set(key, name);
    }
  }
  return value.replace(/(?:legacy:)?(?:character|faction|location|item|concept):[A-Za-z0-9_-]+/g, (token) => names.get(token) || names.get(token.replace(/^legacy:/, '')) || '对象');
}

function displayItemTitle(item: StoryKnowledgeItem, entities: StoryKnowledgeItem[]): string {
  return sanitizeKnowledgeText(itemTitle(item), entities);
}

function displayItemSummary(item: StoryKnowledgeItem, entities: StoryKnowledgeItem[]): string {
  return sanitizeKnowledgeText(itemSummary(item), entities);
}

function itemChapterRange(item: StoryKnowledgeItem): string {
  const start = item.valid_from_chapter ?? item.first_chapter ?? item.setup_chapter;
  const end = item.valid_to_chapter ?? item.last_chapter ?? item.expected_payoff_to;
  if (!start && !end) return '全书有效';
  if (start && end) return `第 ${start}-${end} 章`;
  return start ? `第 ${start} 章起` : `截至第 ${end} 章`;
}

function sourceLabel(value?: string | null): string {
  if (!value) return '未标注来源';
  return SOURCE_OPTIONS.find((option) => option.value === value)?.label || '系统生成';
}

function statusLabel(kind: StoryKnowledgeKind, value?: string | null): string {
  const fallback = kind === 'plot_thread' ? '待推进' : '有效';
  if (!value) return fallback;
  return STATUS_OPTIONS[kind].find((option) => option.value === value)?.label || fallback;
}

function getCollection(data: StoryKnowledgeResponse, kind: StoryKnowledgeKind): StoryKnowledgeItem[] {
  if (kind === 'resource') return data.resources;
  if (kind === 'entity') return data.entities;
  if (kind === 'fact') return data.facts;
  return data.plot_threads;
}

function countFor(data: StoryKnowledgeResponse, key: ViewKey): number {
  if (key === 'chapter_context') return 0;
  if (key === 'story_bible') return data.story_bible && Object.keys(data.story_bible).length > 0 ? 1 : 0;
  if (key === 'fact') return data.facts.filter((item) => !isRelationshipFact(item)).length;
  const fromServer = data.counts?.[key];
  return typeof fromServer === 'number' ? fromServer : getCollection(data, key).length;
}

function matchesQuery(item: StoryKnowledgeItem, query: string): boolean {
  if (!query) return true;
  const haystack = [
    itemTitle(item),
    itemSummary(item),
    item.category_name,
    item.resource_type,
    item.entity_type,
    item.thread_type,
    item.subject_key,
    item.predicate,
    item.object_key,
  ].filter(Boolean).join(' ').toLocaleLowerCase();
  return haystack.includes(query.toLocaleLowerCase());
}

function overlapsChapter(item: StoryKnowledgeItem, chapterText: string): boolean {
  const chapter = Number(chapterText);
  if (!chapterText || Number.isNaN(chapter)) return true;
  const start = item.valid_from_chapter ?? item.first_chapter ?? item.setup_chapter;
  const end = item.valid_to_chapter ?? item.last_chapter ?? item.actual_payoff_chapter ?? item.expected_payoff_to;
  return (start == null || start <= chapter) && (end == null || end >= chapter);
}

export default function StoryKnowledgeWorkbench({ storyId, storyTitle, onClose, onContentUpdated }: Props) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const knowledgeRequestRef = useRef(0);
  const [data, setData] = useState<StoryKnowledgeResponse>(EMPTY_RESPONSE);
  const [activeView, setActiveView] = useState<ViewKey>('chapter_context');
  const [resourceView, setResourceView] = useState<ResourceView>('reference');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [entityTypeFilter, setEntityTypeFilter] = useState('');
  const [chapterFilter, setChapterFilter] = useState('');
  const [displayModes, setDisplayModes] = useState<Partial<Record<StoryKnowledgeKind, KnowledgeDisplayMode>>>({});
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<StoryKnowledgeItem | null>(null);
  const [creatingKind, setCreatingKind] = useState<StoryKnowledgeKind | null>(null);
  const [aiSyncing, setAiSyncing] = useState(false);
  const [aiSyncMessage, setAiSyncMessage] = useState('');
  const [aiSyncScope, setAiSyncScope] = useState<StoryKnowledgeSyncScope | null>(null);
  const [aiSyncNotice, setAiSyncNotice] = useState<AISyncNotice | null>(null);
  const [bibleEditing, setBibleEditing] = useState(false);
  const [bibleSaving, setBibleSaving] = useState(false);
  const [referenceSaving, setReferenceSaving] = useState(false);
  const deferredSearch = useDeferredValue(search.trim());
  const activeKind = activeView === 'story_bible' || activeView === 'chapter_context' ? null : activeView;
  const referenceSummary = useMemo(() => buildReferenceMaterialSummary(data.story_bible || {}), [data.story_bible]);
  const activeCategories = useMemo(
    () => (data.categories || []).filter((category) => category.knowledge_kind === activeKind).sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0)),
    [data.categories, activeKind],
  );
  const activeItems = useMemo(() => {
    if (!activeKind) return [];
    const collection = getCollection(data, activeKind);
    return activeKind === 'fact' ? collection.filter((item) => !isRelationshipFact(item)) : collection;
  }, [data, activeKind]);
  const filteredItems = useMemo(
    () => activeItems.filter((item) => {
      if (!matchesQuery(item, deferredSearch)) return false;
      if (statusFilter && (item.status || defaultStatus(activeKind!)) !== statusFilter) return false;
      if (sourceFilter && (item.source_type || '') !== sourceFilter) return false;
      if (categoryFilter && String(item.category_id || '') !== categoryFilter) return false;
      if (activeKind === 'entity' && entityTypeFilter && (item.entity_type || '') !== entityTypeFilter) return false;
      return overlapsChapter(item, chapterFilter);
    }),
    [activeItems, deferredSearch, statusFilter, sourceFilter, categoryFilter, entityTypeFilter, chapterFilter, activeKind],
  );
  const visualizationFacts = useMemo(
    () => data.facts.filter((item) => isActiveStatus(item.status) && overlapsChapter(item, chapterFilter)),
    [data.facts, chapterFilter],
  );
  const visualizationPlotThreads = useMemo(
    () => data.plot_threads.filter((item) => isActiveStatus(item.status) && overlapsChapter(item, chapterFilter)),
    [data.plot_threads, chapterFilter],
  );
  const displayMode = activeKind ? displayModes[activeKind] || 'list' : 'list';
  const editorKind = editing?.kind || creatingKind || activeKind;
  const editorCategories = useMemo(
    () => (data.categories || []).filter((category) => category.knowledge_kind === editorKind).sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0)),
    [data.categories, editorKind],
  );

  useEffect(() => {
    let cancelled = false;
    const requestId = ++knowledgeRequestRef.current;
    getStoryKnowledge(storyId)
      .then((response) => {
        if (!cancelled && requestId === knowledgeRequestRef.current) {
          setData({ ...EMPTY_RESPONSE, ...response });
          setAiSyncNotice(buildAISyncNotice(response.ai_sync_status));
        }
      })
      .catch((error) => { if (!cancelled && requestId === knowledgeRequestRef.current) toast.error(normalizeErrorMessage(error, '加载作品设定失败')); })
      .finally(() => { if (!cancelled && requestId === knowledgeRequestRef.current) setLoading(false); });
    return () => {
      cancelled = true;
      if (requestId === knowledgeRequestRef.current) knowledgeRequestRef.current += 1;
    };
  }, [storyId]);

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
        return;
      }
      if (event.key !== 'Tab' || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )).filter((element) => element.offsetParent !== null);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      previousFocus?.focus();
    };
  }, [onClose]);

  async function reload() {
    const requestId = ++knowledgeRequestRef.current;
    const response = await getStoryKnowledge(storyId);
    if (requestId === knowledgeRequestRef.current) setData({ ...EMPTY_RESPONSE, ...response });
  }

  async function handleReferencesChanged() {
    await reload();
    await onContentUpdated?.();
  }

  async function handleReferenceSave(form: ReferenceMaterialForm): Promise<boolean> {
    try {
      setReferenceSaving(true);
      const payload = buildReferenceMaterialPayload(data.story_bible || {}, form);
      await updateStoryBible(storyId, payload, data.knowledge_revision);
      await reload();
      await onContentUpdated?.();
      toast.success('写作参考已保存');
      return true;
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '保存写作参考失败'));
      return false;
    } finally {
      setReferenceSaving(false);
    }
  }

  function resetFilters() {
    setSearch('');
    setStatusFilter('');
    setSourceFilter('');
    setCategoryFilter('');
    setEntityTypeFilter('');
    setChapterFilter('');
  }

  async function handleDelete(item: StoryKnowledgeItem) {
    const approved = await confirm({
      title: '删除设定记录',
      message: `确定删除「${itemTitle(item)}」吗？删除后 AI 将不再读取这条信息。`,
      confirmText: '删除',
      danger: true,
    });
    if (!approved) return;
    try {
      await deleteStoryKnowledge(storyId, item.kind, item.id, item.version || 1);
      await reload();
      toast.success('设定记录已删除');
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '删除设定记录失败'));
    }
  }

  async function handleSave(payload: StoryKnowledgeMutation) {
    if (editing) {
      await updateStoryKnowledge(storyId, editing.kind, editing.id, { ...payload, expected_version: editing.version || 1 });
    } else if (creatingKind || activeKind) {
      await createStoryKnowledge(storyId, creatingKind || activeKind!, payload);
    }
    await reload();
    setEditing(null);
    setCreatingKind(null);
    toast.success(editing ? '设定记录已更新' : '设定记录已新增');
  }

  async function handleQuickCreateEntity(payload: StoryKnowledgeMutation) {
    try {
      await createStoryKnowledge(storyId, 'entity', payload);
      await reload();
      toast.success('对象已新增');
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '新增对象失败'));
      throw error;
    }
  }

  async function handleGraphCreateFact(payload: StoryKnowledgeMutation) {
    try {
      await createStoryKnowledge(storyId, 'fact', payload);
      await reload();
      toast.success('关系已新增');
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '新增关系失败'));
      throw error;
    }
  }

  async function handleAISync(
    scope: StoryKnowledgeSyncScope = 'all',
    mode: 'full' | 'incremental' = scope === 'all' ? 'full' : 'incremental',
  ) {
    if (aiSyncing) return;
    setAiSyncing(true);
    setAiSyncScope(scope);
    setAiSyncMessage(`${mode === 'full' ? '正在全量扫描' : '正在增量同步'}${SYNC_SCOPE_LABELS[scope]}`);
    setAiSyncNotice(null);
    try {
      const submitted = await syncStoryKnowledgeWithAI(storyId, { mode, scope });
      for (let attempt = 0; attempt < 800; attempt += 1) {
        const task = await getBackgroundTaskStatus(submitted.task_id);
        const metadataMessage = typeof task.metadata_json?.message === 'string' ? task.metadata_json.message : '';
        setAiSyncMessage(task.message || metadataMessage || `正在同步${SYNC_SCOPE_LABELS[scope]}`);
        if (task.status === 'succeeded') {
          await reload();
          const notice = buildAISyncNotice(task) || { tone: 'success' as const, message: '人物关系与时间轴已同步' };
          setAiSyncNotice(notice);
          if (notice.tone === 'warning') toast.warning(notice.message);
          else toast.success(notice.message);
          return;
        }
        if (['failed', 'cancelled', 'canceled'].includes(task.status)) {
          throw new Error(task.error_message || 'AI 同步失败');
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
      }
      throw new Error('AI 同步耗时较长，请稍后刷新查看');
    } catch (error) {
      const message = normalizeErrorMessage(error, 'AI 同步失败');
      setAiSyncNotice({ tone: 'error', message });
      toast.error(message);
    } finally {
      setAiSyncing(false);
      setAiSyncScope(null);
      setAiSyncMessage('');
    }
  }

  async function handleBibleSave(payload: Partial<StoryBible>) {
    try {
      setBibleSaving(true);
      await updateStoryBible(storyId, payload, data.knowledge_revision);
      await reload();
      await onContentUpdated?.();
      setBibleEditing(false);
      toast.success('作品圣经已保存');
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '保存作品圣经失败'));
    } finally {
      setBibleSaving(false);
    }
  }

  const modal = (
    <div className="fixed inset-0 z-[90] flex items-end justify-center bg-slate-950/55 backdrop-blur-sm md:items-center md:p-5" onMouseDown={onClose}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="story-knowledge-title" className="relative flex h-[100dvh] w-full flex-col overflow-hidden rounded-none border-0 bg-white shadow-2xl md:h-[min(900px,94vh)] md:max-w-7xl md:rounded-lg md:border md:border-slate-200" onMouseDown={(event) => event.stopPropagation()}>
        <header className="flex shrink-0 items-center gap-3 border-b border-slate-200 px-4 py-4 max-md:pt-[calc(1rem+env(safe-area-inset-top))] md:px-5">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-blue-600 text-white">
            <Database size={20} aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h2 id="story-knowledge-title" className="truncate text-base font-semibold text-slate-900">作品设定中心</h2>
            <p className="truncate text-xs text-slate-500">{storyTitle} · 设定已同步</p>
          </div>
          <Button
            size="sm"
            variant="secondary"
            className="max-md:min-h-11"
            icon={aiSyncing && aiSyncScope === 'all' ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            disabled={aiSyncing}
            onClick={() => void handleAISync('all', 'full')}
          >{aiSyncing && aiSyncScope === 'all' ? '全量同步中' : '一键全量同步'}</Button>
          <button ref={closeButtonRef} type="button" title="关闭" aria-label="关闭作品设定中心" onClick={onClose} className="ml-auto flex h-9 w-9 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100 hover:text-slate-800 max-md:h-11 max-md:w-11">
            <X size={18} />
          </button>
        </header>

        <div className="grid min-h-0 flex-1 grid-cols-1 grid-rows-[auto_minmax(0,1fr)] md:grid-cols-[240px_minmax(0,1fr)] md:grid-rows-1">
          <nav className="flex shrink-0 gap-2 overflow-x-auto border-b border-slate-200 bg-slate-50 p-3 md:flex-col md:border-b-0 md:border-r">
            {VIEW_TABS.map((tab) => {
              const Icon = tab.icon;
              const selected = activeView === tab.key;
              return (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => { setActiveView(tab.key); setEditing(null); setCreatingKind(null); setBibleEditing(false); resetFilters(); }}
                  className={`flex min-w-[170px] items-center gap-3 rounded-md px-3 py-2.5 text-left max-md:min-h-11 md:min-w-0 ${selected ? 'bg-blue-600 text-white' : 'text-slate-700 hover:bg-white'}`}
                >
                  <Icon size={17} className="shrink-0" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-semibold">{tab.label}</span>
                    <span className={`block truncate text-xs max-md:hidden ${selected ? 'text-blue-100' : 'text-slate-400'}`}>{tab.description}</span>
                  </span>
                  {tab.key !== 'chapter_context' ? (
                    <span className={`text-xs ${selected ? 'text-white' : 'text-slate-400'}`}>
                      {countFor(data, tab.key) + (tab.key === 'resource' && referenceSummary.hasContent ? 1 : 0)}
                    </span>
                  ) : null}
                </button>
              );
            })}
          </nav>

          <main className="flex min-h-0 flex-col max-md:pb-[env(safe-area-inset-bottom)]">
            {aiSyncNotice ? (
              <div
                role={aiSyncNotice.tone === 'error' ? 'alert' : 'status'}
                className={`flex shrink-0 items-start gap-2 border-b px-4 py-2.5 text-xs ${aiSyncNotice.tone === 'success' ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : aiSyncNotice.tone === 'warning' ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-red-200 bg-red-50 text-red-800'}`}
              >
                {aiSyncNotice.tone === 'success' ? <CheckCircle2 size={16} className="mt-0.5 shrink-0" /> : <CircleAlert size={16} className="mt-0.5 shrink-0" />}
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{aiSyncNotice.message}</p>
                  {aiSyncNotice.details ? <p className="mt-0.5 opacity-80">{aiSyncNotice.details}</p> : null}
                </div>
                <button type="button" onClick={() => setAiSyncNotice(null)} className="flex h-11 w-11 shrink-0 items-center justify-center rounded text-current opacity-60 hover:bg-white/70 hover:opacity-100" title="关闭同步结果" aria-label="关闭同步结果">
                  <X size={14} />
                </button>
              </div>
            ) : null}
            {activeView === 'chapter_context' ? (
              <ChapterContextDashboard key={`${storyId}-context`} storyId={storyId} />
            ) : activeKind === 'resource' ? (
              <>
                <ResourceModeBar value={resourceView} onChange={(value) => { setResourceView(value); setCreatingKind(null); setEditing(null); resetFilters(); }} />
                {resourceView === 'reference' ? (
                  <ReferenceMaterialsPanel
                    storyId={storyId}
                    storyBible={data.story_bible || {}}
                    summary={referenceSummary}
                    saving={referenceSaving}
                    onCreateResource={() => { setResourceView('library'); setEditing(null); setCreatingKind('resource'); }}
                    onReferencesChanged={handleReferencesChanged}
                    onSaveReference={handleReferenceSave}
                  />
                ) : (
                  <>
                  <FilterBar
                      kind="resource"
                      categories={activeCategories}
                      search={search}
                      statusFilter={statusFilter}
                      sourceFilter={sourceFilter}
                      categoryFilter={categoryFilter}
                      entityTypeFilter={entityTypeFilter}
                      chapterFilter={chapterFilter}
                      onSearch={setSearch}
                      onStatus={setStatusFilter}
                      onSource={setSourceFilter}
                      onCategory={setCategoryFilter}
                      onEntityType={setEntityTypeFilter}
                      onChapter={setChapterFilter}
                      onClear={resetFilters}
                      onCreate={() => { setEditing(null); setCreatingKind(activeKind); }}
                    />
                    <KnowledgeList
                      loading={loading}
                      kind="resource"
                      items={filteredItems}
                      entities={data.entities}
                      onEdit={(item) => { setCreatingKind(null); setEditing(item); }}
                      onDelete={handleDelete}
                    />
                  </>
                )}
              </>
            ) : activeKind ? (
              <>
                <FilterBar
                  kind={activeKind}
                  categories={activeCategories}
                  search={search}
                  statusFilter={statusFilter}
                  sourceFilter={sourceFilter}
                  categoryFilter={categoryFilter}
                  entityTypeFilter={entityTypeFilter}
                  chapterFilter={chapterFilter}
                  onSearch={setSearch}
                  onStatus={setStatusFilter}
                  onSource={setSourceFilter}
                  onCategory={setCategoryFilter}
                  onEntityType={setEntityTypeFilter}
                  onChapter={setChapterFilter}
                  onClear={resetFilters}
                  onCreate={() => { setEditing(null); setCreatingKind(activeKind); }}
                  onSync={activeKind === 'entity' || activeKind === 'fact' || activeKind === 'plot_thread' ? () => void handleAISync(activeKind === 'entity' ? 'entities' : activeKind === 'fact' ? 'facts' : 'plot_threads') : undefined}
                  syncing={aiSyncing}
                  syncMessage={aiSyncMessage}
                  displayMode={activeKind === 'entity' || activeKind === 'fact' || activeKind === 'plot_thread' ? displayMode : undefined}
                  onDisplayMode={activeKind === 'entity' || activeKind === 'fact' || activeKind === 'plot_thread' ? (mode) => setDisplayModes((current) => ({ ...current, [activeKind]: mode })) : undefined}
                />
                {(activeKind === 'fact' || activeKind === 'plot_thread') ? (
                  <CategoryManager storyId={storyId} kind={activeKind} categories={activeCategories} onChanged={reload} />
                ) : null}
                {displayMode === 'visual' && (activeKind === 'entity' || activeKind === 'fact' || activeKind === 'plot_thread') ? (
                  <KnowledgeVisualizations
                    storyId={storyId}
                    kind={activeKind}
                    items={filteredItems}
                    facts={visualizationFacts}
                    plotThreads={visualizationPlotThreads}
                    categories={activeCategories}
                    onEdit={(item) => { setCreatingKind(null); setEditing(item); }}
                    onCreateRelation={() => { setEditing(null); setCreatingKind('fact'); }}
                    onCreateEntity={handleQuickCreateEntity}
                    onCreateFact={handleGraphCreateFact}
                    onSync={() => void handleAISync(activeKind === 'entity' ? 'entities' : activeKind === 'fact' ? 'facts' : 'plot_threads')}
                    syncing={aiSyncing}
                    syncMessage={aiSyncMessage}
                  />
                ) : (
                  <KnowledgeList
                    loading={loading}
                    kind={activeKind}
                    items={filteredItems}
                    entities={data.entities}
                    onEdit={(item) => { setCreatingKind(null); setEditing(item); }}
                    onDelete={handleDelete}
                  />
                )}
              </>
            ) : (
              <StoryBiblePanel
                storyBible={data.story_bible || {}}
                editing={bibleEditing}
                saving={bibleSaving}
                onEdit={() => setBibleEditing(true)}
                onCancel={() => setBibleEditing(false)}
                onSave={handleBibleSave}
              />
            )}
          </main>
        </div>

        {(creatingKind || editing) && editorKind ? (
          <KnowledgeEditor
            kind={editorKind}
            item={editing}
            categories={editorCategories}
            entities={data.entities}
            onCancel={() => { setCreatingKind(null); setEditing(null); }}
            onSave={handleSave}
          />
        ) : null}
      </div>
    </div>
  );

  return createPortal(modal, document.body);
}

function ResourceModeBar({ value, onChange }: { value: ResourceView; onChange: (value: ResourceView) => void }) {
  return (
    <div className="shrink-0 border-b border-slate-200 px-4 py-3 sm:px-6">
      <div className="inline-flex rounded-md bg-slate-100 p-1" role="tablist" aria-label="资料视图">
        <button type="button" role="tab" aria-selected={value === 'reference'} onClick={() => onChange('reference')} className={`rounded px-4 py-2.5 text-xs font-medium max-md:min-h-11 ${value === 'reference' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800'}`}>写作参考</button>
        <button type="button" role="tab" aria-selected={value === 'library'} onClick={() => onChange('library')} className={`rounded px-4 py-2.5 text-xs font-medium max-md:min-h-11 ${value === 'library' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800'}`}>自定义资料</button>
      </div>
    </div>
  );
}

function FilterBar({
  kind,
  categories,
  search,
  statusFilter,
  sourceFilter,
  categoryFilter,
  entityTypeFilter,
  chapterFilter,
  onSearch,
  onStatus,
  onSource,
  onCategory,
  onEntityType,
  onChapter,
  onClear,
  onCreate,
  onSync,
  syncing,
  syncMessage,
  displayMode,
  onDisplayMode,
}: {
  kind: StoryKnowledgeKind;
  categories: StoryKnowledgeCategory[];
  search: string;
  statusFilter: string;
  sourceFilter: string;
  categoryFilter: string;
  entityTypeFilter: string;
  chapterFilter: string;
  onSearch: (value: string) => void;
  onStatus: (value: string) => void;
  onSource: (value: string) => void;
  onCategory: (value: string) => void;
  onEntityType: (value: string) => void;
  onChapter: (value: string) => void;
  onClear: () => void;
  onCreate: () => void;
  onSync?: () => void;
  syncing?: boolean;
  syncMessage?: string;
  displayMode?: KnowledgeDisplayMode;
  onDisplayMode?: (mode: KnowledgeDisplayMode) => void;
}) {
  const label = VIEW_TABS.find((tab) => tab.key === kind)?.label || '设定';
  return (
    <div className="shrink-0 border-b border-slate-200 px-4 py-3">
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-[minmax(150px,1fr)_repeat(3,120px)_100px_auto_auto_auto]">
        <label className="relative min-w-0">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <Input value={search} onChange={(event) => onSearch(event.target.value)} placeholder={`搜索${label}`} className="rounded-md pl-9 max-md:min-h-11" />
        </label>
        {kind === 'entity' ? (
          <Select value={entityTypeFilter} onChange={(event) => onEntityType(event.target.value)} className="rounded-md max-md:min-h-11">
            <option value="">全部类型</option>
            {ENTITY_TYPE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </Select>
        ) : (
          <Select value={categoryFilter} onChange={(event) => onCategory(event.target.value)} className="rounded-md max-md:min-h-11">
            <option value="">全部分类</option>
            {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
          </Select>
        )}
        <Select value={statusFilter} onChange={(event) => onStatus(event.target.value)} className="rounded-md max-md:min-h-11">
          <option value="">全部状态</option>
          {STATUS_OPTIONS[kind].map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </Select>
        <Select value={sourceFilter} onChange={(event) => onSource(event.target.value)} className="rounded-md max-md:min-h-11">
          <option value="">全部来源</option>
          {SOURCE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </Select>
        <Input value={chapterFilter} onChange={(event) => onChapter(event.target.value)} type="number" min={1} placeholder="章节" className="rounded-md max-md:min-h-11" />
        {displayMode && onDisplayMode ? <KnowledgeViewToggle kind={kind} value={displayMode} onChange={onDisplayMode} /> : null}
        {onSync ? <Button variant="secondary" size="sm" className="max-md:min-h-11" icon={syncing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} disabled={syncing} onClick={onSync}>{syncing ? syncMessage || '同步中' : '同步本类'}</Button> : null}
        <Button variant="secondary" size="sm" className="max-md:min-h-11" icon={<SlidersHorizontal size={14} />} onClick={onClear}>清除筛选</Button>
        <Button size="sm" className="max-md:min-h-11" icon={<Plus size={15} />} onClick={onCreate}>新增</Button>
      </div>
    </div>
  );
}

function KnowledgeViewToggle({ kind, value, onChange }: { kind: StoryKnowledgeKind; value: KnowledgeDisplayMode; onChange: (mode: KnowledgeDisplayMode) => void }) {
  const visualLabel = kind === 'entity' ? '图谱' : '时间轴';
  const VisualIcon = kind === 'entity' ? Network : ChartNoAxesGantt;
  return (
    <div className="inline-flex h-11 shrink-0 rounded-md border border-slate-200 bg-slate-50 p-0.5" role="group" aria-label="查看方式">
      <button type="button" title="列表查看" aria-pressed={value === 'list'} onClick={() => onChange('list')} className={`flex h-10 items-center gap-1 rounded px-3 text-xs font-medium max-md:min-h-11 ${value === 'list' ? 'bg-white text-blue-700 shadow-sm' : 'text-slate-500 hover:text-slate-800'}`}><List size={13} />列表</button>
      <button type="button" title={`${visualLabel}查看`} aria-pressed={value === 'visual'} onClick={() => onChange('visual')} className={`flex h-10 items-center gap-1 rounded px-3 text-xs font-medium max-md:min-h-11 ${value === 'visual' ? 'bg-white text-blue-700 shadow-sm' : 'text-slate-500 hover:text-slate-800'}`}><VisualIcon size={13} />{visualLabel}</button>
    </div>
  );
}

function CategoryManager({ storyId, kind, categories, onChanged }: { storyId: number; kind: StoryKnowledgeKind; categories: StoryKnowledgeCategory[]; onChanged: () => Promise<void> }) {
  const [name, setName] = useState('');
  const [busyId, setBusyId] = useState<number | null>(null);
  const title = kind === 'fact' ? '事实分类' : '剧情线分类';

  async function createCategory() {
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      await createStoryKnowledgeCategory(storyId, { knowledge_kind: kind, name: trimmed, color: '#2563eb', sort_order: categories.length + 1 });
      setName('');
      await onChanged();
      toast.success('分类已新增');
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '新增分类失败'));
    }
  }

  async function renameCategory(category: StoryKnowledgeCategory) {
    const next = window.prompt('请输入新的分类名称', category.name)?.trim();
    if (!next || next === category.name) return;
    setBusyId(category.id);
    try {
      await updateStoryKnowledgeCategory(storyId, category.id, { name: next, expected_version: category.version || 1 });
      await onChanged();
      toast.success('分类已更新');
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '更新分类失败'));
    } finally {
      setBusyId(null);
    }
  }

  async function removeCategory(category: StoryKnowledgeCategory) {
    const approved = await confirm({ title: '删除分类', message: `确定删除「${category.name}」吗？仅未被事实或伏笔使用的分类可以删除。`, confirmText: '删除', danger: true });
    if (!approved) return;
    setBusyId(category.id);
    try {
      await deleteStoryKnowledgeCategory(storyId, category.id, category.version || 1);
      await onChanged();
      toast.success('分类已删除');
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '删除分类失败'));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="shrink-0 border-b border-slate-200 bg-slate-50 px-4 py-3">
      <div className="mb-2 text-xs font-semibold text-slate-600">{title}</div>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="flex flex-wrap gap-2">
          {categories.length === 0 ? <span className="text-xs text-slate-400">暂无分类</span> : null}
          {categories.map((category) => (
            <span key={category.id} className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-600">
              <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: category.color || '#2563eb' }} />
              <span className="max-w-[10rem] truncate">{category.name}</span>
              <button type="button" disabled={busyId === category.id} onClick={() => void renameCategory(category)} className="flex h-11 w-11 items-center justify-center rounded-full text-slate-400 hover:text-blue-600 max-md:-m-1" title="改名"><Pencil size={13} /></button>
              <button type="button" disabled={busyId === category.id} onClick={() => void removeCategory(category)} className="flex h-11 w-11 items-center justify-center rounded-full text-slate-400 hover:text-red-600 max-md:-m-1" title="删除"><Trash2 size={13} /></button>
            </span>
          ))}
        </div>
        <div className="flex min-w-0 gap-2 sm:ml-auto">
          <Input value={name} onChange={(event) => setName(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void createCategory(); }} placeholder="新分类名称" className="h-11 rounded-md text-xs max-md:min-w-0" />
          <Button size="sm" variant="secondary" className="max-md:min-h-11 shrink-0" onClick={() => void createCategory()}>新增分类</Button>
        </div>
      </div>
    </div>
  );
}

function KnowledgeList({ loading, kind, items, entities, onEdit, onDelete }: { loading: boolean; kind: StoryKnowledgeKind; items: StoryKnowledgeItem[]; entities: StoryKnowledgeItem[]; onEdit: (item: StoryKnowledgeItem) => void; onDelete: (item: StoryKnowledgeItem) => void }) {
  const EmptyIcon = VIEW_TABS.find((tab) => tab.key === kind)?.icon || Database;
  if (loading) {
    return <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500"><Loader2 size={18} className="animate-spin" />加载中...</div>;
  }
  if (items.length === 0) {
    return (
      <div className="flex h-full min-h-52 flex-col items-center justify-center p-6 text-center text-slate-400">
        <EmptyIcon size={30} className="mb-3" />
        <p className="text-sm font-medium text-slate-600">暂无匹配设定</p>
        <p className="mt-1 text-xs">新增后，AI 会在相关创作任务中按需读取。</p>
      </div>
    );
  }
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4">
      <div className="space-y-2 [content-visibility:auto]">
        {items.map((item) => (
          <article key={`${item.kind}-${item.id}`} className="rounded-md border border-slate-200 bg-white px-4 py-3 hover:border-blue-200 hover:bg-blue-50/30">
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="min-w-0 break-words text-sm font-semibold leading-6 text-slate-900">{displayItemTitle(item, entities)}</h3>
                  {item.category_name ? <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[11px] text-blue-700">{item.category_name}</span> : null}
                  <span className={`rounded px-1.5 py-0.5 text-[11px] ${isActiveStatus(item.status) ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>{statusLabel(kind, item.status)}</span>
                </div>
                {itemSummary(item) ? <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-600">{displayItemSummary(item, entities)}</p> : null}
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-400">
                  <span>{itemChapterRange(item)}</span>
                  <span>{sourceLabel(item.source_type)}</span>
                  {item.version ? <span>记录版本 {item.version}</span> : null}
                </div>
              </div>
              <div className="flex shrink-0 gap-1">
                <button type="button" title="编辑" onClick={() => onEdit(item)} className="flex h-11 w-11 items-center justify-center rounded-md text-slate-500 hover:bg-blue-100 hover:text-blue-700"><Pencil size={14} /></button>
                {item.source_type === 'manual' ? (
                  <button type="button" title="删除" onClick={() => void onDelete(item)} className="flex h-11 w-11 items-center justify-center rounded-md text-slate-500 hover:bg-red-100 hover:text-red-600"><Trash2 size={14} /></button>
                ) : null}
              </div>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function KnowledgeEditor({ kind, item, categories, entities, onCancel, onSave }: { kind: StoryKnowledgeKind; item: StoryKnowledgeItem | null; categories: StoryKnowledgeCategory[]; entities: StoryKnowledgeItem[]; onCancel: () => void; onSave: (payload: StoryKnowledgeMutation) => Promise<void> }) {
  const definitions = FIELD_DEFINITIONS[kind];
  const [values, setValues] = useState<Record<string, string>>(() => {
    const initial = buildInitialValues(definitions, item);
    if (kind === 'fact' && initial.value_text) initial.value_text = sanitizeKnowledgeText(initial.value_text, entities);
    return initial;
  });
  const [objects, setObjects] = useState<Record<string, KeyValueRow[]>>(() => buildInitialObjectValues(definitions, item));
  const [saving, setSaving] = useState(false);
  const title = VIEW_TABS.find((tab) => tab.key === kind)?.label || '设定';

  async function submit() {
    try {
      setSaving(true);
      await onSave(buildPayload(kind, definitions, values, objects));
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '请检查表单内容'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="absolute inset-0 z-10 flex w-full flex-col bg-white shadow-2xl md:inset-y-0 md:right-0 md:max-w-xl md:border-l md:border-slate-200">
      <div className="flex items-center border-b border-slate-200 px-5 py-4 max-md:pt-[calc(1rem+env(safe-area-inset-top))]">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-slate-900">{item ? '编辑' : '新增'}{title}</h3>
          <p className="mt-0.5 text-xs text-slate-400">保存后会立即更新 AI 可读取的作品设定。</p>
        </div>
        <button type="button" title="返回" aria-label="返回列表" onClick={onCancel} className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100 md:hidden">
          <ArrowLeft size={18} />
        </button>
        <button type="button" title="关闭编辑" onClick={onCancel} className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100"><X size={16} /></button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {definitions.map((field) => (
            <KnowledgeField
              key={String(field.key)}
              kind={kind}
              field={field}
              value={values[String(field.key)] || ''}
              rows={objects[String(field.key)] || []}
              categories={categories}
              entities={entities}
              onChange={(value) => setValues((current) => ({ ...current, [field.key]: value }))}
              onRowsChange={(rows) => setObjects((current) => ({ ...current, [field.key]: rows }))}
            />
          ))}
        </div>
      </div>
      <div className="flex justify-end gap-2 border-t border-slate-200 px-5 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))]">
        <Button variant="secondary" className="max-md:min-h-11" onClick={onCancel}>取消</Button>
        <Button className="max-md:min-h-11" loading={saving} onClick={() => void submit()}>保存</Button>
      </div>
    </div>
  );
}

function KnowledgeField({ kind, field, value, rows, categories, entities, onChange, onRowsChange }: { kind: StoryKnowledgeKind; field: FieldDefinition; value: string; rows: KeyValueRow[]; categories: StoryKnowledgeCategory[]; entities: StoryKnowledgeItem[]; onChange: (value: string) => void; onRowsChange: (rows: KeyValueRow[]) => void }) {
  const id = `knowledge-${String(field.key)}`;
  const common = { id, value, placeholder: field.placeholder, onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => onChange(event.target.value) };
  return (
    <label htmlFor={id} className={`block min-w-0 ${field.type === 'textarea' || field.type === 'object' || field.type === 'list' ? 'sm:col-span-2' : ''}`}>
      <span className="mb-1.5 block text-xs font-medium text-slate-700">{field.label}{field.required ? <span className="ml-1 text-red-500">*</span> : null}</span>
      {field.type === 'textarea' ? (
        <TextArea {...common} rows={3} className="rounded-md text-xs leading-5" />
      ) : field.type === 'object' ? (
        <KeyValueRows rows={rows} onChange={onRowsChange} />
      ) : field.type === 'list' ? (
        <TextArea {...common} rows={4} className="rounded-md text-xs leading-5" />
      ) : field.type === 'status' ? (
        <Select {...common} className="rounded-md max-md:min-h-11">
          <option value="">使用默认状态</option>
          {STATUS_OPTIONS[kind].map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </Select>
      ) : field.type === 'category' ? (
        <Select {...common} className="rounded-md max-md:min-h-11">
          <option value="">不归入分类</option>
          {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
        </Select>
      ) : field.type === 'resource_type' ? (
        <Select {...common} className="rounded-md max-md:min-h-11">
          <option value="manual_note">通用资料</option>
          <option value="world_rule">世界规则</option>
          <option value="style_profile">写作风格</option>
          <option value="character_rule">人物规则</option>
        </Select>
      ) : field.type === 'entity_type' ? (
        <Select {...common} className="rounded-md max-md:min-h-11">
          <option value="character">人物</option>
          <option value="location">地点</option>
          <option value="faction">势力</option>
          <option value="item">物品</option>
          <option value="concept">概念</option>
        </Select>
      ) : field.type === 'entity_ref' ? (
        <Select {...common} className="rounded-md max-md:min-h-11">
          <option value="">{field.key === 'subject_key' ? '全书设定（不生成关系线）' : '无明确关联对象'}</option>
          {entities.filter((entity) => entity.status !== 'archived').map((entity) => <option key={entity.id} value={entity.entity_key || entity.canonical_name || ''}>{entity.canonical_name || entity.title || '未命名对象'}</option>)}
        </Select>
      ) : (
        <Input {...common} type={field.type === 'number' ? 'number' : 'text'} step={field.key === 'confidence' ? '0.01' : '1'} className="rounded-md max-md:min-h-11" />
      )}
    </label>
  );
}

function ChapterContextDashboard({ storyId }: { storyId: number }) {
  const [list, setList] = useState<ChapterContextSummary[] | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState('');
  const [selected, setSelected] = useState<ChapterContextSummary | null>(null);
  const [missing, setMissing] = useState(false);
  const [value, setValue] = useState<ChapterContextPack | null>(null);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<CreationPackPresentation | null>(null);
  const [draftBaseline, setDraftBaseline] = useState('');
  const [saving, setSaving] = useState(false);
  const [previewMode, setPreviewMode] = useState<'readable' | 'source'>('readable');
  const [refreshTaskId, setRefreshTaskId] = useState<string | null>(null);
  const [refreshMessage, setRefreshMessage] = useState('');
  const activeTaskRef = useRef<{ chapterNumber: number; missing: boolean } | null>(null);
  const selectedRef = useRef<ChapterContextSummary | null>(null);
  useEffect(() => {
    selectedRef.current = selected;
  }, [selected]);
  const presentation = useMemo(() => parseCreationPack(value?.content || ''), [value?.content]);
  const draftContent = useMemo(() => draft ? serializeCreationPack(draft) : '', [draft]);
  const dirty = editing && draftContent !== draftBaseline;

  const resetDraft = (content: string) => {
    const nextDraft = parseCreationPack(content);
    setDraft(nextDraft);
    setDraftBaseline(serializeCreationPack(nextDraft));
  };

  const loadList = async () => {
    setListLoading(true);
    setListError('');
    try {
      const response = await getStoryChapterContexts(storyId);
      setList(response.chapters);
    } catch (error) {
      const message = normalizeErrorMessage(error, '加载章节列表失败');
      setListError(message);
      toast.error(message);
    } finally {
      setListLoading(false);
    }
  };

  useEffect(() => { void loadList(); }, [storyId]);

  const openChapter = async (summary: ChapterContextSummary) => {
    setSelected(summary);
    setMissing(false);
    setValue(null);
    setEditing(false);
    setLoading(true);
    try {
      const response = await getStoryChapterContext(storyId, summary.chapter_number);
      setValue(response);
    } catch (error) {
      const status = (error as { status?: number }).status;
      if (status === 404) {
        setMissing(true);
      } else {
        toast.error(normalizeErrorMessage(error, '加载章节创作包失败'));
      }
    } finally {
      setLoading(false);
    }
  };

  const backToList = () => {
    setSelected(null);
    setMissing(false);
    setValue(null);
    setEditing(false);
    setRefreshTaskId(null);
    setRefreshMessage('');
    void loadList();
  };

  const save = async () => {
    if (!selected || !draft || !draftContent.trim()) {
      toast.error('创作包不能为空');
      return;
    }
    setSaving(true);
    try {
      const response = await updateStoryChapterContext(storyId, selected.chapter_number, draftContent, value?.version || 1);
      setValue(response);
      setEditing(false);
      toast.success(hasNovel ? '创作包已保存。本章已有正文，修改不会自动同步到正文，如需生效请重新生成该章正文' : '创作包已保存，正文 Agent 将原样读取');
      void loadList();
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '保存本章创作包失败'));
    } finally {
      setSaving(false);
    }
  };

  const startRegenerate = async (summary: ChapterContextSummary, expectedVersion: number, missingPack: boolean) => {
    setSaving(true);
    try {
      const submitted = await regenerateStoryChapterContext(storyId, summary.chapter_number, expectedVersion);
      setRefreshTaskId(submitted.task_id);
      setRefreshMessage(missingPack ? `正在生成第${summary.chapter_number}章创作包` : '任务已提交，正在提取最新创作包');
      activeTaskRef.current = { chapterNumber: summary.chapter_number, missing: missingPack };
      toast.success('创作包提取任务已提交');
    } catch (error) {
      toast.error(normalizeErrorMessage(error, '生成创作包失败'));
    } finally {
      setSaving(false);
    }
  };

  const regenerate = async () => {
    if (!selected) return;
    const accepted = await confirm({ title: '重新提取创作包', message: '将按当前作品设定覆盖本章创作包，现有手动修改会丢失。', confirmText: '重新提取', danger: true });
    if (!accepted) return;
    await startRegenerate(selected, value?.version || 1, false);
  };

  const generateForMissing = async () => {
    if (!selected) return;
    await startRegenerate(selected, selected.version || 1, true);
  };

  useEffect(() => {
    // 恢复进行中的提取任务：组件重新挂载时列表摘要携带 refresh_task，据此恢复轮询
    if (refreshTaskId || !list) return;
    const active = list.find((item) => item.refresh_task && ['pending', 'running', 'retrying', 'cancel_requested'].includes(item.refresh_task.status));
    if (active?.refresh_task) {
      setRefreshTaskId(active.refresh_task.task_id);
      setRefreshMessage(active.refresh_task.message || String(active.refresh_task.metadata_json?.message || '正在提取最新创作包'));
      activeTaskRef.current = { chapterNumber: active.chapter_number, missing: !active.has_pack };
    }
  }, [list, refreshTaskId]);

  useEffect(() => {
    const task = value?.refresh_task;
    if (task && ['pending', 'running', 'retrying', 'cancel_requested'].includes(task.status)) {
      setRefreshTaskId(task.task_id);
      setRefreshMessage(task.message || String(task.metadata_json?.message || '正在提取最新创作包'));
      return;
    }
    if (!task || ['succeeded', 'failed', 'cancelled', 'canceled'].includes(task.status)) {
      setRefreshTaskId(null);
      if (!task || task.status !== 'succeeded') setRefreshMessage('');
    }
  }, [value?.refresh_task?.task_id, value?.refresh_task?.status]);

  useEffect(() => {
    if (!refreshTaskId) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const task = await getBackgroundTaskStatus(refreshTaskId);
        if (cancelled) return;
        setRefreshMessage(task.message || String(task.metadata_json?.message || '正在提取最新创作包'));
        if (task.status === 'succeeded') {
          const target = activeTaskRef.current;
          activeTaskRef.current = null;
          // 仅当当前打开的章节正好是任务目标章节时才回填内容，避免串台到其他章节视图
          if (target && !cancelled && selectedRef.current?.chapter_number === target.chapterNumber) {
            try {
              const response = await getStoryChapterContext(storyId, target.chapterNumber);
              if (!cancelled) {
                setValue(response);
                setMissing(false);
                resetDraft(response.content);
                setEditing(false);
                toast.success(target.missing ? '创作包已生成' : '已按当前设定重新提取');
              }
            } catch (error) {
              // 拉取失败（如瞬时 404）：保留当前视图，仅刷新列表摘要
              if (!cancelled) toast.error(normalizeErrorMessage(error, '读取最新创作包失败'));
            }
          }
          if (!cancelled) {
            setRefreshTaskId(null);
            setRefreshMessage('');
            void loadList();
          }
          return;
        }
        if (['failed', 'cancelled', 'canceled'].includes(task.status)) {
          if (!cancelled) {
            setRefreshTaskId(null);
            setRefreshMessage('');
            toast.error(task.error_message || '创作包提取失败');
          }
          return;
        }
        window.setTimeout(() => void poll(), 1000);
      } catch (error) {
        if (!cancelled) {
          setRefreshTaskId(null);
          setRefreshMessage('');
          toast.error(normalizeErrorMessage(error, '查询创作包任务失败'));
        }
      }
    };
    void poll();
    return () => { cancelled = true; };
  }, [refreshTaskId, storyId]);

  if (selected === null) {
    return <ChapterContextListView loading={listLoading} error={listError} chapters={list || []} onRetry={() => void loadList()} onOpen={(item) => void openChapter(item)} />;
  }

  const hasNovel = selected.has_novel;
  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-50/60">
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-3">
        <button type="button" onClick={backToList} className="flex h-11 items-center gap-1 rounded-md px-2 text-xs font-medium text-slate-500 hover:bg-slate-100 hover:text-slate-800">
          <ArrowLeft size={15} />返回列表
        </button>
        <span className="h-5 w-px bg-slate-200" />
        <label className="flex items-center gap-2 text-xs font-medium text-slate-600">
          章节
          <span className="rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-sm font-semibold text-slate-800">第{selected.chapter_number}章</span>
        </label>
        {selected.title ? <span className="max-w-[200px] truncate text-xs text-slate-500">{selected.title}</span> : null}
        {hasNovel ? <span className="rounded border border-slate-200 bg-slate-100 px-2 py-1 text-xs text-slate-600">已写正文</span> : selected.is_current ? <span className="rounded border border-blue-200 bg-blue-50 px-2 py-1 text-xs text-blue-700">当前创作章节</span> : null}
        {missing ? <span className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-700">尚未生成创作包</span> : null}
        {value?.is_manual ? <span className="rounded border border-blue-200 bg-blue-50 px-2 py-1 text-xs text-blue-700">已手动调整</span> : null}
        {value?.is_stale ? <span className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-700">作品设定已有更新</span> : null}
        {!editing && !missing && value ? <div className="flex h-11 items-center rounded-md border border-slate-200 bg-slate-100 p-0.5" role="group" aria-label="创作包查看模式">
          <button type="button" onClick={() => setPreviewMode('readable')} className={`h-10 px-3 text-xs font-medium transition-colors max-md:min-h-11 ${previewMode === 'readable' ? 'rounded bg-white text-blue-700 shadow-sm' : 'text-slate-500 hover:text-slate-800'}`}>易读视图</button>
          <button type="button" onClick={() => setPreviewMode('source')} className={`h-10 px-3 text-xs font-medium transition-colors max-md:min-h-11 ${previewMode === 'source' ? 'rounded bg-white text-blue-700 shadow-sm' : 'text-slate-500 hover:text-slate-800'}`}>原文核对</button>
        </div> : null}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {loading || refreshTaskId ? <span className="inline-flex max-w-[260px] items-center gap-1.5 truncate text-xs text-blue-700"><Loader2 size={13} className="shrink-0 animate-spin" />{refreshMessage || '正在提取'}</span> : null}
          {missing ? (
            <Button size="sm" className="max-md:min-h-11" icon={refreshTaskId ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />} disabled={saving || loading || Boolean(refreshTaskId)} onClick={() => void generateForMissing()}>生成创作包</Button>
          ) : (
            <>
              <Button size="sm" variant="secondary" className="max-md:min-h-11" icon={refreshTaskId ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} disabled={saving || loading || Boolean(refreshTaskId)} onClick={() => void regenerate()}>手动更新同步</Button>
              {editing ? <>
                <Button size="sm" variant="secondary" className="max-md:min-h-11" disabled={saving} onClick={() => { resetDraft(value?.content || ''); setEditing(false); }}>取消</Button>
                <Button size="sm" className="max-md:min-h-11" icon={saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} disabled={saving || !dirty} onClick={() => void save()}>保存</Button>
              </> : <Button size="sm" className="max-md:min-h-11" icon={<Pencil size={14} />} disabled={!value || loading} onClick={() => { resetDraft(value?.content || ''); setEditing(true); }}>编辑创作包</Button>}
            </>
          )}
        </div>
      </div>

      {missing ? (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 p-10 text-center">
          <Boxes size={30} className="text-slate-300" />
          <p className="text-sm font-medium text-slate-600">第{selected.chapter_number}章尚未生成创作包</p>
          <p className="max-w-md text-xs leading-5 text-slate-400">生成后可在本页查看、编辑正文 Agent 实际读取的设定内容。</p>
          <Button size="sm" className="max-md:min-h-11" icon={refreshTaskId ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />} disabled={saving || Boolean(refreshTaskId)} onClick={() => void generateForMissing()}>生成创作包</Button>
        </div>
      ) : !value && loading ? null : !value ? (
        <div className="p-10 text-center text-sm text-slate-400">暂无本章创作包</div>
      ) : editing ? (
        <CreationPackCardEditor value={draft || presentation} onChange={(nextDraft) => {
          setDraft(nextDraft);
        }} />
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {previewMode === 'readable' ? <CreationPackReadableView title={presentation.title} sections={presentation.sections} /> : <pre className="mx-auto max-w-5xl whitespace-pre-wrap break-words rounded-md border border-slate-200 bg-white p-5 font-mono text-sm leading-7 text-slate-800 shadow-sm">{value.content}</pre>}
        </div>
      )}
    </div>
  );
}

function ChapterContextListView({ loading, error, chapters, onRetry, onOpen }: { loading: boolean; error: string; chapters: ChapterContextSummary[]; onRetry: () => void; onOpen: (item: ChapterContextSummary) => void }) {
  // 分页状态：当前页 + 每页条数（纯前端分页，数据一次性获取后本地切片，不改后端接口）
  const [currentPage, setCurrentPage] = useState(1);
  const [pageInput, setPageInput] = useState('');
  const [pageSize] = useState(20);

  const totalPages = Math.max(1, Math.ceil(chapters.length / pageSize));

  // 当 chapters 变化（引用变化或长度变化）时钳制页码，避免越界
  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    } else if (currentPage < 1) {
      setCurrentPage(1);
    }
  }, [chapters, currentPage, totalPages]);

  // 页码输入框跳转：支持回车与点击「跳转」，越界时自动钳制
  const goToPage = () => {
    const parsed = parseInt(pageInput, 10);
    if (Number.isNaN(parsed)) return;
    const clamped = Math.min(Math.max(parsed, 1), totalPages);
    setCurrentPage(clamped);
    setPageInput('');
  };

  // 当前页切片
  const pagedChapters = chapters.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  if (loading) {
    return <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500"><Loader2 size={18} className="animate-spin" />加载中...</div>;
  }
  if (error) {
    return (
      <div className="flex h-full min-h-52 flex-col items-center justify-center gap-3 p-6 text-center text-slate-400">
        <CircleAlert size={30} />
        <p className="text-sm font-medium text-slate-600">{error}</p>
        <Button size="sm" variant="secondary" className="max-md:min-h-11" icon={<RefreshCw size={14} />} onClick={onRetry}>重试</Button>
      </div>
    );
  }
  if (chapters.length === 0) {
    return (
      <div className="flex h-full min-h-52 flex-col items-center justify-center p-6 text-center text-slate-400">
        <ChartNoAxesGantt size={30} className="mb-3" />
        <p className="text-sm font-medium text-slate-600">暂无章节</p>
        <p className="mt-1 text-xs">大纲生成后即可查看各章节创作包。</p>
      </div>
    );
  }
  const written = chapters.filter((item) => item.has_novel).length;
  const withPack = chapters.filter((item) => item.has_pack).length;
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
      <div className="w-full">
        <p className="mb-3 px-1 text-xs text-slate-500">
          {totalPages > 1 ? `第 ${currentPage} / ${totalPages} 页 · ` : ''}共 {chapters.length} 章 · 已写正文 {written} 章 · 创作包 {withPack} 章
        </p>
        <div className="space-y-2">
          {pagedChapters.map((item) => {
            const activeTask = item.refresh_task && ['pending', 'running', 'retrying', 'cancel_requested'].includes(item.refresh_task.status) ? item.refresh_task : null;
            const badge = activeTask
              ? { text: '提取中', className: 'border-blue-200 bg-blue-50 text-blue-700' }
              : item.has_novel
                ? { text: '已写正文', className: 'border-slate-200 bg-slate-100 text-slate-600' }
                : item.is_current
                  ? { text: '当前创作章节', className: 'border-blue-200 bg-blue-50 text-blue-700' }
                  : item.has_pack
                    ? { text: '创作包已生成', className: 'border-emerald-200 bg-emerald-50 text-emerald-700' }
                    : { text: '未生成创作包', className: 'border-amber-200 bg-amber-50 text-amber-700' };
            const subtitle = activeTask
              ? (activeTask.message || '正在提取创作包')
              : item.has_novel
                ? (item.word_count > 0 ? `正文 ${item.word_count} 字` : '已写正文')
                : item.pack_updated_at
                  ? `创作包更新于 ${formatDateTime(item.pack_updated_at)}`
                  : item.is_current ? '当前待创作的章节' : '选中后可生成创作包';
            return (
              <button key={item.chapter_number} type="button" onClick={() => onOpen(item)} className="flex w-full items-center gap-3 rounded-md border border-slate-200 bg-white px-4 py-3 text-left transition-colors hover:border-blue-200 hover:bg-blue-50/40">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-slate-100 text-sm font-semibold text-slate-700">{item.chapter_number}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold text-slate-900">{item.title}</span>
                  <span className="mt-0.5 block truncate text-[11px] text-slate-400">{subtitle}</span>
                </span>
                <span className={`shrink-0 rounded border px-2 py-1 text-[11px] font-medium ${badge.className}`}>{badge.text}</span>
                <ChevronRight size={15} className="shrink-0 text-slate-300" />
              </button>
            );
          })}
        </div>
        {totalPages > 1 && (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-3">
            <div className="flex flex-wrap items-center gap-1.5">
              <Button size="sm" variant="secondary" className="max-md:min-h-11" icon={<ChevronsLeft size={14} />} onClick={() => setCurrentPage(1)} disabled={currentPage === 1}>首页</Button>
              <Button size="sm" variant="secondary" className="max-md:min-h-11" icon={<ChevronLeft size={14} />} onClick={() => setCurrentPage(currentPage - 1)} disabled={currentPage === 1}>上一页</Button>
              <Button size="sm" variant="secondary" className="max-md:min-h-11" onClick={() => setCurrentPage(currentPage + 1)} disabled={currentPage === totalPages}>下一页<ChevronRight size={14} /></Button>
              <Button size="sm" variant="secondary" className="max-md:min-h-11" onClick={() => setCurrentPage(totalPages)} disabled={currentPage === totalPages}>末页<ChevronsRight size={14} /></Button>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-slate-500">第</span>
              <Input
                type="number"
                min={1}
                max={totalPages}
                value={pageInput}
                onChange={(e) => setPageInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') goToPage(); }}
                className="w-16 rounded-md px-2 py-1 text-center text-xs max-md:min-h-11"
              />
              <span className="text-xs text-slate-500">/ {totalPages} 页</span>
              <Button size="sm" variant="secondary" className="max-md:min-h-11" onClick={goToPage} disabled={!pageInput}>跳转</Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const REPEATABLE_CREATION_PACK_SECTIONS = new Set(['前文章节', '人物设定', '本章相关人物与对象', '本章有效事实', '伏笔与剧情推进']);

function CreationPackCardEditor({ value, onChange }: { value: CreationPackPresentation; onChange: (value: CreationPackPresentation) => void }) {
  const updateItem = (sectionIndex: number, itemIndex: number, nextItem: CreationPackItem) => {
    onChange({
      ...value,
      sections: value.sections.map((section, currentSectionIndex) => currentSectionIndex !== sectionIndex ? section : {
        ...section,
        items: section.items.map((item, currentItemIndex) => currentItemIndex === itemIndex ? nextItem : item),
      }),
    });
  };

  const removeItem = (sectionIndex: number, itemIndex: number) => {
    onChange({
      ...value,
      sections: value.sections.map((section, currentSectionIndex) => currentSectionIndex !== sectionIndex ? section : {
        ...section,
        items: section.items.filter((_, currentItemIndex) => currentItemIndex !== itemIndex),
      }),
    });
  };

  const addItem = (sectionIndex: number) => {
    onChange({
      ...value,
      sections: value.sections.map((section, currentSectionIndex) => currentSectionIndex !== sectionIndex ? section : {
        ...section,
        items: [...section.items, { title: '新条目', fields: [{ label: '内容', value: '', depth: 1 }], notes: [] }],
      }),
    });
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-5">
      <div className="mx-auto max-w-6xl space-y-5">
        <header className="border-b border-slate-200 bg-white px-1 pb-4">
          <p className="text-xs font-medium text-blue-700">卡片式编辑</p>
          <h3 className="mt-1 text-lg font-semibold text-slate-950">{value.title}</h3>
          <p className="mt-1 text-xs text-slate-500">保存后，这些卡片内容会生成同一份创作包原文供正文 Agent 读取。</p>
        </header>
        {value.sections.map((section, sectionIndex) => (
          <section key={`${section.title}-${sectionIndex}`} className="border-b border-slate-200 pb-5 last:border-0">
            <div className="mb-3 flex items-center gap-2">
              <span className="grid h-7 w-7 shrink-0 place-items-center rounded bg-blue-50 text-xs font-semibold text-blue-700">{section.title.slice(0, 1)}</span>
              <h4 className="text-sm font-semibold text-slate-900">{section.title}</h4>
              <span className="text-xs text-slate-400">{section.items.length} 项</span>
              {REPEATABLE_CREATION_PACK_SECTIONS.has(section.title) ? (
                <Button size="sm" variant="secondary" icon={<Plus size={13} />} className="ml-auto max-md:min-h-11" onClick={() => addItem(sectionIndex)}>新增卡片</Button>
              ) : null}
            </div>
            {section.items.length > 0 ? (
              <div className={section.items.length > 1 ? 'grid gap-3 md:grid-cols-2 xl:grid-cols-3' : ''}>
                {section.items.map((item, itemIndex) => (
                  <CreationPackEditableItem
                    key={`${section.title}-${itemIndex}`}
                    item={item}
                    canRemove={REPEATABLE_CREATION_PACK_SECTIONS.has(section.title)}
                    onChange={(nextItem) => updateItem(sectionIndex, itemIndex, nextItem)}
                    onRemove={() => removeItem(sectionIndex, itemIndex)}
                  />
                ))}
              </div>
            ) : <div className="rounded-md border border-dashed border-slate-300 bg-white p-6 text-center text-sm text-slate-400">暂无内容，可新增卡片补充。</div>}
          </section>
        ))}
      </div>
    </div>
  );
}

function CreationPackEditableItem({ item, canRemove, onChange, onRemove }: { item: CreationPackItem; canRemove: boolean; onChange: (item: CreationPackItem) => void; onRemove: () => void }) {
  return (
    <article className="min-w-0 rounded-md border border-slate-200 bg-white p-4 shadow-sm">
      {item.title !== undefined || canRemove ? <div className="mb-3 flex items-center gap-2 border-b border-slate-100 pb-3">
        {item.title !== undefined ? <Input
            aria-label="卡片标题"
            value={item.title}
            placeholder="卡片标题"
            onChange={(event) => onChange({ ...item, title: event.target.value })}
            className="h-11 rounded-md border-0 bg-slate-50 px-2 font-semibold"
        /> : <span className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-800">{item.fields.find((field) => ['姓名', '标题', '主体'].includes(field.label))?.value || '内容卡片'}</span>}
        {canRemove ? <Button size="sm" variant="secondary" className="max-md:min-h-11 shrink-0" icon={<Trash2 size={14} />} aria-label="删除卡片" title="删除卡片" onClick={onRemove} /> : null}
      </div> : null}
      <div className="space-y-3">
        {item.fields.map((field, fieldIndex) => (
          <label key={`${field.label}-${fieldIndex}`} className="block min-w-0">
            <span className="mb-1 block text-xs font-medium text-slate-500">{[...(field.parents || []), field.label].join(' / ')}</span>
            <TextArea
              value={field.value}
              rows={field.value.includes('\n') || field.value.length > 60 ? 3 : 2}
              onChange={(event) => onChange({
                ...item,
                fields: item.fields.map((currentField, currentFieldIndex) => currentFieldIndex === fieldIndex ? { ...currentField, value: event.target.value } : currentField),
              })}
              className="resize-y rounded-md bg-white text-sm leading-6"
            />
          </label>
        ))}
        {item.notes.map((note, noteIndex) => (
          <label key={`note-${noteIndex}`} className="block min-w-0">
            <span className="mb-1 block text-xs font-medium text-slate-500">补充说明</span>
            <TextArea
              value={note}
              rows={3}
              onChange={(event) => onChange({
                ...item,
                notes: item.notes.map((currentNote, currentNoteIndex) => currentNoteIndex === noteIndex ? event.target.value : currentNote),
              })}
              className="resize-y rounded-md bg-white text-sm leading-6"
            />
          </label>
        ))}
      </div>
    </article>
  );
}

function CreationPackReadableView({ title, sections }: { title: string; sections: CreationPackSection[] }) {
  if (sections.length === 0) {
    return <div className="mx-auto max-w-5xl rounded-md border border-dashed border-slate-300 bg-white p-10 text-center text-sm text-slate-400">当前创作包暂无可展示内容，可切换到原文核对。</div>;
  }
  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <header className="border-b border-slate-200 bg-white px-1 pb-4">
        <p className="text-xs font-medium text-blue-700">本章正文依据</p>
        <h3 className="mt-1 text-lg font-semibold text-slate-950">{title}</h3>
      </header>
      {sections.map((section) => <CreationPackSectionView key={section.title} section={section} />)}
    </div>
  );
}

function CreationPackSectionView({ section }: { section: CreationPackSection }) {
  const populatedItems = section.items.filter((item) => item.fields.length > 0 || item.notes.length > 0 || item.title);
  const useGrid = populatedItems.length > 1;
  return (
    <section className="border-b border-slate-200 pb-5 last:border-0">
      <div className="mb-3 flex items-center gap-2">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded bg-blue-50 text-xs font-semibold text-blue-700">{section.title.slice(0, 1)}</span>
        <h4 className="text-sm font-semibold text-slate-900">{section.title}</h4>
        <span className="text-xs text-slate-400">{populatedItems.length} 项</span>
      </div>
      <div className={useGrid ? 'grid gap-3 md:grid-cols-2 xl:grid-cols-3' : ''}>
        {populatedItems.map((item, index) => (
          <CreationPackItemView key={`${section.title}-${index}`} item={item} useGrid={useGrid} />
        ))}
      </div>
    </section>
  );
}

function CreationPackItemView({ item, useGrid }: { item: CreationPackSection['items'][number]; useGrid: boolean }) {
  const identityField = item.fields.find((field) => ['姓名', '标题', '主体'].includes(field.label) && field.value);
  const heading = item.title || identityField?.value;
  const detailFields = identityField && !item.title ? item.fields.filter((field) => field !== identityField) : item.fields;
  return (
    <article className={useGrid ? 'min-w-0 rounded-md border border-slate-200 bg-white p-4 shadow-sm' : 'min-w-0 bg-white px-4 py-3'}>
      {heading ? <h5 className="mb-3 border-b border-slate-100 pb-2 text-sm font-semibold text-slate-900">{heading}</h5> : null}
      {detailFields.length > 0 ? <dl className="space-y-2.5">{detailFields.map((field, fieldIndex) => (
              <div key={`${field.label}-${fieldIndex}`} className={`grid min-w-0 gap-1 ${useGrid ? '' : 'sm:grid-cols-[130px_minmax(0,1fr)] sm:gap-4'}`}>
                <dt className="text-xs font-medium text-slate-500">{[...(field.parents || []), field.label].join(' / ')}</dt>
                <dd className="min-w-0 whitespace-pre-wrap break-words text-sm leading-6 text-slate-800">{field.value || '未填写'}</dd>
              </div>
      ))}</dl> : null}
      {item.notes.map((note, noteIndex) => <p key={noteIndex} className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">{note}</p>)}
    </article>
  );
}

function StoryBiblePanel({ storyBible, editing, saving, onEdit, onCancel, onSave }: { storyBible: StoryBible; editing: boolean; saving: boolean; onEdit: () => void; onCancel: () => void; onSave: (payload: Partial<StoryBible>) => Promise<void> }) {
  if (editing) return <StoryBibleEditor storyBible={storyBible} saving={saving} onCancel={onCancel} onSave={onSave} />;
  const sections = collectBibleSections(storyBible);
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="text-base font-semibold text-slate-900">作品圣经</h3>
          <p className="mt-1 text-xs text-slate-500">集中维护故事定位、世界规则、写作约束和长期状态。</p>
        </div>
        <Button size="sm" className="max-md:min-h-11" icon={<Pencil size={14} />} onClick={onEdit}>编辑作品圣经</Button>
      </div>
      {sections.length === 0 ? (
        <div className="rounded-md border border-dashed border-slate-300 p-8 text-center text-sm text-slate-400">暂无作品圣经内容</div>
      ) : (
        <div className="grid items-start gap-3 xl:grid-cols-2">
          {sections.map((section) => <BibleSection key={section.key} title={section.title} value={section.value} />)}
        </div>
      )}
    </div>
  );
}

function BibleSection({ title, value }: { title: string; value: unknown }) {
  return (
    <section className="min-w-0 rounded-md border border-slate-200 bg-white p-4">
      <h4 className="text-sm font-semibold text-slate-900">{title}</h4>
      <div className="mt-3">{renderBibleValue(value)}</div>
    </section>
  );
}

function renderBibleValue(value: unknown): React.ReactNode {
  if (value == null || value === '') return <p className="text-xs text-slate-400">暂无内容</p>;
  if (Array.isArray(value)) {
    if (value.length === 0) return <p className="text-xs text-slate-400">暂无内容</p>;
    return (
      <div className="space-y-2">
        {value.map((item, index) => (
          <div key={index} className="border-l-2 border-slate-200 pl-3 text-sm leading-6 text-slate-700">
            {typeof item === 'object' && item !== null ? renderBibleValue(item) : stringifyValue(item)}
          </div>
        ))}
      </div>
    );
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).filter(([, item]) => hasBibleValue(item));
    if (entries.length === 0) return <p className="text-xs text-slate-400">暂无内容</p>;
    return (
      <dl className="space-y-3">
        {entries.map(([key, item]) => (
          <div key={key} className="min-w-0">
            <dt className="text-xs font-medium text-slate-500">{storyBibleFieldLabel(key)}</dt>
            <dd className="mt-1 min-w-0 whitespace-pre-wrap break-words text-sm leading-6 text-slate-800">
              {typeof item === 'object' && item !== null ? renderBibleValue(item) : stringifyValue(item)}
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  return <p className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-800">{stringifyValue(value)}</p>;
}

function StoryBibleEditor({ storyBible, saving, onCancel, onSave }: { storyBible: StoryBible; saving: boolean; onCancel: () => void; onSave: (payload: Partial<StoryBible>) => Promise<void> }) {
  const [form, setForm] = useState<BibleFormState>(() => createStoryBibleFormState(storyBible));
  const brief = asBibleRecord(storyBible.creative_brief);
  const [worldRows, setWorldRows] = useState<KeyValueRow[]>(() => worldSettingToRows(readBibleField(brief, 'world_setting', '世界观设定'), cryptoId));

  function setField(key: keyof BibleFormState, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function submit() {
    void onSave(buildStoryBiblePayload(form, storyBible, worldSettingRowsToObject(worldRows)));
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="text-base font-semibold text-slate-900">编辑作品圣经</h3>
          <p className="mt-1 text-xs text-slate-500">参考作者画像、分析报告和风格样本已归入资料页，保存核心设定不会改动这些内容。</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" className="max-md:min-h-11" onClick={onCancel}>取消</Button>
          <Button size="sm" className="max-md:min-h-11" loading={saving} onClick={submit}>保存</Button>
        </div>
      </div>
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <BibleEditSection title="创意摘要">
          <SimpleField label="作品定位" value={form.project_positioning} onChange={(value) => setField('project_positioning', value)} multiline />
          <SimpleField label="题材" value={form.genre} onChange={(value) => setField('genre', value)} />
          <SimpleField label="受众" value={form.audience} onChange={(value) => setField('audience', value)} />
          <SimpleField label="风格基调" value={form.tone} onChange={(value) => setField('tone', value)} multiline />
          <SimpleField label="核心卖点" value={form.core_hook} onChange={(value) => setField('core_hook', value)} multiline />
          <SimpleField label="一句话梗概" value={form.one_line_premise} onChange={(value) => setField('one_line_premise', value)} multiline />
          <SimpleField label="主角核心" value={form.protagonist_core} onChange={(value) => setField('protagonist_core', value)} multiline />
          <SimpleField label="主线矛盾" value={form.main_conflict} onChange={(value) => setField('main_conflict', value)} multiline />
          <SimpleField label="长线悬念" value={form.longline_mystery} onChange={(value) => setField('longline_mystery', value)} multiline />
          <SimpleField label="目标篇幅" value={form.serial_length_target} onChange={(value) => setField('serial_length_target', value)} />
          <SimpleField label="揭秘策略" value={form.reveal_strategy} onChange={(value) => setField('reveal_strategy', value)} multiline />
          <SimpleField label="节奏策略" value={form.pacing_strategy} onChange={(value) => setField('pacing_strategy', value)} multiline />
          <SimpleField label="必须保留" value={form.must_keep_rules} onChange={(value) => setField('must_keep_rules', value)} multiline rows={5} />
          <SimpleField label="开放笔记" value={form.open_story_notes} onChange={(value) => setField('open_story_notes', value)} multiline rows={5} />
        </BibleEditSection>
        <BibleEditSection title="写作指导">
          <SimpleField label="开书策略" value={form.opening_strategy} onChange={(value) => setField('opening_strategy', value)} multiline />
          <SimpleField label="章节密度策略" value={form.chapter_density_strategy} onChange={(value) => setField('chapter_density_strategy', value)} multiline />
          <SimpleField label="中段驱动力" value={form.midgame_engine} onChange={(value) => setField('midgame_engine', value)} multiline />
          <SimpleField label="后期方向" value={form.late_game_direction} onChange={(value) => setField('late_game_direction', value)} multiline />
          <SimpleField label="避免的模式" value={form.forbidden_patterns} onChange={(value) => setField('forbidden_patterns', value)} multiline rows={5} />
          <SimpleField label="推荐情节模式" value={form.preferred_plot_patterns} onChange={(value) => setField('preferred_plot_patterns', value)} multiline rows={5} />
        </BibleEditSection>
        <BibleEditSection title="世界观设定" fullWidth>
          <KeyValueRows rows={worldRows} onChange={setWorldRows} />
        </BibleEditSection>
        <BibleEditSection title="原始输入">
          <SimpleField label="原始创意" value={form.raw_idea} onChange={(value) => setField('raw_idea', value)} multiline />
          <SimpleField label="篇幅目标" value={form.raw_length_goal} onChange={(value) => setField('raw_length_goal', value)} />
          <SimpleField label="必保留要素" value={form.raw_must_keep} onChange={(value) => setField('raw_must_keep', value)} multiline />
          <SimpleField label="原始笔记" value={form.raw_notes} onChange={(value) => setField('raw_notes', value)} multiline />
          <SimpleField label="隐藏设定" value={form.raw_hidden_setting} onChange={(value) => setField('raw_hidden_setting', value)} multiline />
        </BibleEditSection>
        <BibleEditSection title="导入指导">
          <SimpleField label="导入素材类型" value={form.import_material_type} onChange={(value) => setField('import_material_type', value)} />
          <SimpleField label="必须保留" value={form.import_must_keep} onChange={(value) => setField('import_must_keep', value)} multiline />
          <SimpleField label="作者目标" value={form.author_goal} onChange={(value) => setField('author_goal', value)} multiline />
          <SimpleField label="调整范围" value={form.adjustment_scope} onChange={(value) => setField('adjustment_scope', value)} multiline />
          <SimpleField label="长线预案" value={form.longline_plan} onChange={(value) => setField('longline_plan', value)} multiline />
          <SimpleField label="风格护栏" value={form.tone_guardrails} onChange={(value) => setField('tone_guardrails', value)} multiline />
        </BibleEditSection>
        <BibleEditSection title="故事状态" fullWidth>
          <SimpleField label="故事状态" value={form.story_state_text} onChange={(value) => setField('story_state_text', value)} multiline />
          <SimpleField label="连续性事实（每行一条）" value={form.continuity_facts} onChange={(value) => setField('continuity_facts', value)} multiline rows={6} />
          <SimpleField label="未闭合线索（每行一条）" value={form.open_loops} onChange={(value) => setField('open_loops', value)} multiline rows={6} />
        </BibleEditSection>
      </div>
    </div>
  );
}

function BibleEditSection({ title, fullWidth = false, children }: { title: string; fullWidth?: boolean; children: React.ReactNode }) {
  return (
    <section className={`rounded-md border border-slate-200 p-4 ${fullWidth ? 'lg:col-span-2' : ''}`}>
      <h4 className="mb-3 text-sm font-semibold text-slate-900">{title}</h4>
      <div className="grid gap-3 sm:grid-cols-2">{children}</div>
    </section>
  );
}

function SimpleField({ label, value, onChange, multiline = false, rows = 3 }: { label: string; value: string; onChange: (value: string) => void; multiline?: boolean; rows?: number }) {
  return (
    <label className={`block min-w-0 ${multiline ? 'sm:col-span-2' : ''}`}>
      <span className="mb-1.5 block text-xs font-medium text-slate-700">{label}</span>
      {multiline ? (
        <TextArea value={value} onChange={(event) => onChange(event.target.value)} rows={rows} className="rounded-md text-xs leading-5" />
      ) : (
        <Input value={value} onChange={(event) => onChange(event.target.value)} className="rounded-md max-md:min-h-11" />
      )}
    </label>
  );
}

function KeyValueRows({ rows, onChange }: { rows: KeyValueRow[]; onChange: (rows: KeyValueRow[]) => void }) {
  function update(id: string, patch: Partial<KeyValueRow>) {
    onChange(rows.map((row) => row.id === id ? { ...row, ...patch } : row));
  }
  function remove(id: string) {
    onChange(rows.filter((row) => row.id !== id));
  }
  return (
    <div className="space-y-2">
      {rows.map((row) => (
        <div key={row.id} className="grid gap-2 sm:grid-cols-[minmax(120px,0.45fr)_minmax(160px,1fr)_auto]">
          <Input value={PROFILE_FIELD_LABELS[row.key] || row.key} onChange={(event) => update(row.id, { key: Object.entries(PROFILE_FIELD_LABELS).find(([, label]) => label === event.target.value)?.[0] || event.target.value })} placeholder="字段名称" className="rounded-md text-xs max-md:min-h-11" />
          <Input value={formatProfileValue(row.key, row.value)} onChange={(event) => update(row.id, { value: event.target.value })} placeholder="字段内容" className="rounded-md text-xs max-md:min-h-11" />
          <button type="button" title="删除字段" onClick={() => remove(row.id)} className="flex h-11 w-11 items-center justify-center rounded-md text-slate-400 hover:bg-red-50 hover:text-red-600">
            <Trash2 size={14} />
          </button>
        </div>
      ))}
      <Button type="button" variant="secondary" size="sm" className="max-md:min-h-11" icon={<Plus size={14} />} onClick={() => onChange([...rows, { id: cryptoId(), key: '', value: '' }])}>新增字段</Button>
    </div>
  );
}

function buildInitialValues(definitions: FieldDefinition[], item: StoryKnowledgeItem | null): Record<string, string> {
  const values: Record<string, string> = {};
  for (const field of definitions) {
    const value = item?.[field.key as keyof StoryKnowledgeItem];
    if (field.type === 'object') continue;
    if (value == null && field.type === 'resource_type') {
      values[String(field.key)] = 'manual_note';
      continue;
    }
    if (value == null && field.type === 'entity_type') {
      values[String(field.key)] = 'character';
      continue;
    }
    if (field.type === 'list' && Array.isArray(value)) values[String(field.key)] = value.join('\n');
    else values[String(field.key)] = value == null ? '' : String(value);
  }
  return values;
}

function buildInitialObjectValues(definitions: FieldDefinition[], item: StoryKnowledgeItem | null): Record<string, KeyValueRow[]> {
  const values: Record<string, KeyValueRow[]> = {};
  for (const field of definitions) {
    if (field.type !== 'object') continue;
    values[String(field.key)] = worldSettingToRows(item?.[field.key as keyof StoryKnowledgeItem], cryptoId);
  }
  return values;
}

function buildPayload(kind: StoryKnowledgeKind, definitions: FieldDefinition[], values: Record<string, string>, objects: Record<string, KeyValueRow[]>): StoryKnowledgeMutation {
  const payload: Record<string, unknown> = {};
  for (const field of definitions) {
    const key = String(field.key);
    const raw = (values[key] || '').trim();
    if (field.required && !raw) throw new Error(`${field.label}不能为空`);
    if (field.type === 'status' && !raw) continue;
    if (field.type === 'object') payload[key] = worldSettingRowsToObject(objects[key] || []);
    else if (field.type === 'list') payload[key] = lineList(raw);
    else if (field.type === 'number' || field.type === 'category') payload[key] = raw ? Number(raw) : null;
    else payload[key] = raw || null;
  }
  if (!payload.status) payload.status = defaultStatus(kind);
  return payload as StoryKnowledgeMutation;
}

function lineList(value: string): string[] {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

function stringifyValue(value: unknown): string {
  if (value == null) return '';
  if (Array.isArray(value)) return value.map((item) => stringifyValue(item)).join('\n');
  if (typeof value === 'object') return Object.entries(value as Record<string, unknown>).map(([key, item]) => `${key}：${stringifyValue(item)}`).join('\n');
  return String(value);
}

function defaultStatus(kind: StoryKnowledgeKind): string {
  return kind === 'plot_thread' ? 'open' : 'active';
}

function isActiveStatus(status?: string | null): boolean {
  return !status || ['active', 'open', 'due'].includes(status);
}

function cryptoId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
