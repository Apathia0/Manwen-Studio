const INTERNAL_REFERENCE_PATTERN = /^(?:legacy:|entity:|character:|location:|faction:|item:|concept:|fact:|thread:|resource:)/i;
const HASH_LIKE_PATTERN = /^[a-f0-9]{16,}$/i;

const FIELD_LABELS: Record<string, string> = {
  name: '名称',
  canonical_name: '名称',
  role: '身份',
  gender: '性别',
  age: '年龄',
  occupation: '职业',
  realm: '境界',
  identity: '身份',
  description: '简介',
  personality: '性格',
  appearance: '外貌',
  background: '背景',
  ability: '能力',
  abilities: '能力',
  goal: '目标',
  motivation: '动机',
  status: '状态',
  relationship: '关系',
  relationships: '关系',
  arc: '人物发展',
  start: '初始阶段',
  middle: '发展阶段',
  end: '后续走向',
  to: '关联人物',
  type: '关系',
  faction: '所属势力',
  location: '所在地点',
  traits: '特征',
  tags: '标签',
  note: '备注',
  notes: '备注',
};

const VALUE_LABELS: Record<string, string> = {
  acquired: '获得',
  archived: '已归档',
  world_story: '世界剧情',
  world_concept: '世界概念',
  world_rule: '世界规则',
  continuity: '连续性',
  relationship: '人物关系',
  identity: '身份',
  status: '状态',
  belongs_to: '归属',
  located_at: '位于',
  owns: '持有',
  ally: '同盟',
  enemy: '敌对',
  parent_child: '亲子',
  sold_to: '出售给',
  traded_with: '交易对象',
  purchased_from: '购自',
  learned_from: '学自',
  informed: '告知',
  consumed: '使用',
  equipped: '装备',
  foreshadow: '伏笔',
  has_money: '持有资金',
  improved: '提升',
  note: '备注',
  possesses: '持有',
  active: '生效中',
  open: '待推进',
  resolved: '已完成',
  due: '本章处理',
  overdue: '已经逾期',
  approaching: '临近回收',
  pending: '待处理',
  completed: '已完成',
  inactive: '未启用',
  cancelled: '已取消',
  character: '人物',
  location: '地点',
  faction: '势力',
  item: '物品',
  concept: '概念',
  protagonist: '主角',
  supporting: '配角',
};

const HIDDEN_FIELDS = new Set([
  'id',
  'key',
  'entity_key',
  'subject_key',
  'object_key',
  'source_key',
  'source_type',
  'source_id',
  'source_chapter_id',
  'version',
  'revision',
  'relevance_score',
  '_receipt_key',
  'big_five',
  'dimensions',
  'scores',
  'metrics',
]);

function isInternalReference(value: string): boolean {
  return INTERNAL_REFERENCE_PATTERN.test(value) || HASH_LIKE_PATTERN.test(value);
}

function parseStructuredString(value: string): unknown {
  const trimmed = value.trim();
  if (!trimmed || (!trimmed.startsWith('{') && !trimmed.startsWith('['))) return value;
  try {
    return JSON.parse(trimmed);
  } catch {
    return value;
  }
}

function displayScalar(value: unknown, entityNames?: ReadonlyMap<string, string>): string {
  if (value == null || value === '') return '';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'number') return String(value);
  const text = String(value).trim();
  if (!text) return '';
  const entityName = entityNames?.get(text);
  if (entityName) return entityName;
  if (VALUE_LABELS[text]) return VALUE_LABELS[text];
  if (isInternalReference(text)) return '关联对象';
  return text;
}

function hasKnownFieldLabel(key: string): boolean {
  return Boolean(FIELD_LABELS[key]) || /[\u4e00-\u9fff]/.test(key);
}

export function formatContextValue(
  value: unknown,
  entityNames?: ReadonlyMap<string, string>,
  omittedFields: ReadonlySet<string> = HIDDEN_FIELDS,
): string {
  if (typeof value === 'string') {
    const parsed = parseStructuredString(value);
    if (parsed !== value) return formatContextValue(parsed, entityNames, omittedFields);
    return displayScalar(value, entityNames);
  }
  if (value == null || typeof value !== 'object') return displayScalar(value, entityNames);
  if (Array.isArray(value)) {
    return value.map((item) => formatContextValue(item, entityNames, omittedFields)).filter(Boolean).join('、');
  }
  return Object.entries(value as Record<string, unknown>)
    .filter(([key, item]) => {
      if (omittedFields.has(key) || item == null || item === '') return false;
      if (!hasKnownFieldLabel(key) && typeof item === 'number') return false;
      return true;
    })
    .map(([key, item]) => {
      const formatted = formatContextValue(item, entityNames, omittedFields);
      if (!formatted) return '';
      if (!hasKnownFieldLabel(key)) return formatted;
      const label = FIELD_LABELS[key] || key;
      return `${label}：${formatted}`;
    })
    .filter(Boolean)
    .join('；');
}

export function formatEntityProfile(profile: unknown, entityName: string): string {
  const hidden = new Set(HIDDEN_FIELDS);
  if (profile && typeof profile === 'object' && !Array.isArray(profile)) {
    for (const [key, value] of Object.entries(profile as Record<string, unknown>)) {
      if ((key === 'name' || key === 'canonical_name') && String(value || '').trim() === entityName.trim()) {
        hidden.add(key);
      }
    }
  }
  return formatContextValue(profile, undefined, hidden);
}

export function buildEntityNameMap(entities: Array<{ key?: string; name?: string }>): Map<string, string> {
  const names = new Map<string, string>();
  for (const entity of entities) {
    const key = String(entity.key || '').trim();
    const name = String(entity.name || '').trim();
    if (key && name) names.set(key, name);
  }
  return names;
}

export function formatFact(
  fact: Record<string, unknown>,
  entityNames: ReadonlyMap<string, string>,
): { title: string; detail: string } {
  const title = [fact.subject, fact.predicate, fact.object]
    .map((item) => displayScalar(item, entityNames))
    .filter(Boolean)
    .join(' · ');
  return {
    title: title || '设定事实',
    detail: formatContextValue(fact.value, entityNames),
  };
}

export function relevanceLabel(score: unknown): string {
  const value = Number(score || 0);
  if (value >= 100) return '高度相关';
  if (value >= 50) return '相关';
  return '参考';
}
