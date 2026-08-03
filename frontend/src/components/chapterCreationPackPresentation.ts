export interface CreationPackField {
  label: string;
  value: string;
  depth: number;
  parents?: string[];
  listParentIndex?: number;
  listItemIndex?: number;
}

export interface CreationPackItem {
  title?: string;
  fields: CreationPackField[];
  notes: string[];
}

export interface CreationPackSection {
  title: string;
  items: CreationPackItem[];
}

export interface CreationPackPresentation {
  title: string;
  notice: string;
  sections: CreationPackSection[];
}

const CREATION_PACK_NOTICE = '> 以下内容是本章正文 Agent 实际接收的完整创作包。页面保存后的文本会原样发送，不再压缩、裁剪或二次重组。';

const FIELD_LABELS: Record<string, string> = {
  name: '姓名',
  role: '身份',
  type: '类型',
  key: '标识',
  title: '标题',
  summary: '摘要',
  goal: '本章目标',
  conflict: '核心冲突',
  payoff: '剧情回报',
  hook: '章末钩子',
  highlight: '章节亮点',
  act: '故事阶段',
  writing_guidance: '写作指导',
  'writing guidance': '写作指导',
  chapter_number: '章节',
  'chapter number': '章节',
  key_events: '关键事件',
  'key events': '关键事件',
  aliases: '别名',
  profile: '人物信息',
  profile_json: '人物信息',
  'profile json': '人物信息',
  entity_type: '对象类型',
  'entity type': '对象类型',
  relevance_score: '本章相关度',
  'relevance score': '本章相关度',
  subject: '主体',
  subject_name: '主体',
  'subject name': '主体',
  subject_key: '主体',
  'subject key': '主体',
  predicate: '事实类型',
  object: '关联对象',
  object_name: '关联对象',
  'object name': '关联对象',
  object_key: '关联对象',
  'object key': '关联对象',
  value: '内容',
  value_text: '内容',
  'value text': '内容',
  description: '说明',
  status: '状态',
  priority: '优先级',
  urgency: '推进状态',
  setup_chapter: '埋设章节',
  'setup chapter': '埋设章节',
  expected_payoff_from: '预计回收起始章',
  'expected payoff from': '预计回收起始章',
  expected_payoff_to: '预计回收截止章',
  'expected payoff to': '预计回收截止章',
  current: '本章任务',
  valid_from: '生效章节',
  'valid from': '生效章节',
  valid_to: '失效章节',
  'valid to': '失效章节',
  related_entity_names: '关联人物与地点',
  'related entity names': '关联人物与地点',
  relationships: '本章关系',
  to: '关系对象',
  target: '关系对象',
  relation: '关系',
  identity: '身份',
  personality: '性格',
  motivation: '当前动机',
  ability: '能力',
  appearance: '外貌特征',
  current_state: '当前状态',
  'current state': '当前状态',
  realm: '当前境界',
  occupation: '职业',
  faction: '所属势力',
  location: '当前位置',
  weakness: '弱点与限制',
  previous: '上一章承接',
  next: '下一章边界',
  content: '内容',
  content_text: '内容',
  'content text': '内容',
};

const VALUE_LABELS: Record<string, string> = {
  acquired: '获得',
  ally: '同盟',
  archived: '已归档',
  character: '人物',
  completed: '已完成',
  consumed: '消耗',
  continuity: '连续性',
  location: '地点',
  faction: '势力',
  item: '物品',
  concept: '概念',
  world_concept: '世界概念',
  world_rule: '世界规则',
  protagonist: '主角',
  supporting: '配角',
  antagonist: '对手',
  belongs_to: '归属',
  enemy: '敌对',
  equipped: '装备',
  foreshadow: '伏笔',
  has_money: '持有资金',
  identity: '身份',
  improved: '提升',
  informed: '获知',
  learned_from: '学自',
  located_at: '位于',
  note: '备注',
  owns: '持有',
  parent_child: '亲子',
  possesses: '持有',
  purchased_from: '购自',
  relationship: '人物关系',
  sold_to: '出售给',
  status: '状态',
  traded_with: '交易对象',
  world_story: '世界剧情',
  due: '本章处理',
  overdue: '已经逾期',
  approaching: '临近回收',
  background: '暂不推进',
  active: '生效中',
  resolved: '已完成',
  open: '待推进',
  inactive: '未启用',
  pending: '待处理',
  cancelled: '已取消',
};

const NUMBERED_ITEM = /^\d+[.、]\s*(.*)$/;
const NESTED_NUMBERED_ITEM = /^\s+\d+[.、]\s*(.*)$/;
const FIELD_LINE = /^(\s*)-\s*([^：:]+)[：:]\s*(.*)$/;
const INTERNAL_REFERENCE = /^(?:legacy:|memory:loop:|story_memory:|ai_sync:|thread_\d+$|(?:character|location|faction|item|concept):[a-z0-9:_-]{5,})/i;
const HIDDEN_FIELD_LABELS = new Set([
  '标识', '本章相关度', 'source chapter id', 'source id', 'source type', 'version',
  'payoff window', 'related entities', 'big five', 'dimensions', 'scores', 'metrics',
]);

export function parseCreationPack(content: string): CreationPackPresentation {
  const result: CreationPackPresentation = { title: '本章创作包', notice: '', sections: [] };
  let section: CreationPackSection | null = null;
  let item: CreationPackItem | null = null;
  let pendingListField: CreationPackField | null = null;
  let pendingParent: { field: CreationPackField; target: CreationPackItem; depth: number } | null = null;
  let lastField: CreationPackField | null = null;
  let lastFieldIndent = -1;
  let hiddenParentDepth: number | null = null;
  let activeListContext: { parentDepth: number; parentIndex: number; itemIndex: number } | null = null;
  const activeParentLabels: string[] = [];

  const ensureItem = () => {
    if (!section) return null;
    if (!item) {
      item = { fields: [], notes: [] };
      section.items.push(item);
    }
    return item;
  };

  for (const rawLine of String(content || '').split(/\r?\n/)) {
    const line = rawLine.trimEnd();
    if (!line.trim()) continue;
    if (line.startsWith('# ')) {
      result.title = line.slice(2).trim() || result.title;
      continue;
    }
    if (line.startsWith('## ')) {
      section = { title: line.slice(3).trim(), items: [] };
      result.sections.push(section);
      item = null;
      pendingListField = null;
      pendingParent = null;
      lastField = null;
      hiddenParentDepth = null;
      activeListContext = null;
      activeParentLabels.length = 0;
      continue;
    }
    if (line.trimStart().startsWith('>')) {
      result.notice = line.trimStart().slice(1).trim();
      continue;
    }
    if (!section) continue;

    const numbered = line.match(NUMBERED_ITEM);
    if (numbered) {
      item = { title: numbered[1].trim() || undefined, fields: [], notes: [] };
      section.items.push(item);
      pendingListField = null;
      pendingParent = null;
      lastField = null;
      hiddenParentDepth = null;
      activeListContext = null;
      activeParentLabels.length = 0;
      continue;
    }
    const nestedNumbered = line.match(NESTED_NUMBERED_ITEM);
    if (nestedNumbered) {
      const listItemText = nestedNumbered[1].trim();
      if (!listItemText && pendingParent) {
        pendingParent.target.fields = pendingParent.target.fields.filter((entry) => entry !== pendingParent?.field);
        activeParentLabels[pendingParent.depth] = pendingParent.field.label;
        activeParentLabels.length = pendingParent.depth + 1;
        activeListContext = {
          parentDepth: pendingParent.depth,
          parentIndex: activeParentLabels.filter(Boolean).length - 1,
          itemIndex: Number.parseInt(line.trim(), 10) || 1,
        };
        pendingListField = null;
        pendingParent = null;
        lastField = null;
        continue;
      }
      if (!listItemText && activeListContext) {
        activeListContext = { ...activeListContext, itemIndex: Number.parseInt(line.trim(), 10) || activeListContext.itemIndex + 1 };
        lastField = null;
        continue;
      }
      const targetListField = pendingListField || lastField;
      if (targetListField) {
        const listValue = line.trim();
        targetListField.value = targetListField.value ? `${targetListField.value}\n${listValue}` : listValue;
      }
      pendingParent = null;
      continue;
    }
    const field = line.match(FIELD_LINE);
    if (field) {
      const target = ensureItem();
      if (!target) continue;
      const depth = Math.max(0, Math.floor(field[1].length / 2));
      const label = creationPackFieldLabel(field[2]);
      const fieldValue = creationPackValueLabel(field[3]);
      pendingListField = null;
      lastField = null;
      lastFieldIndent = -1;
      if (hiddenParentDepth !== null) {
        if (depth > hiddenParentDepth) continue;
        hiddenParentDepth = null;
      }
      if (activeListContext && depth <= activeListContext.parentDepth) activeListContext = null;
      if (pendingParent) {
        if (depth > pendingParent.depth) {
          pendingParent.target.fields = pendingParent.target.fields.filter((entry) => entry !== pendingParent?.field);
          activeParentLabels[pendingParent.depth] = pendingParent.field.label;
        }
        pendingParent = null;
      }
      activeParentLabels.length = depth;
      if (HIDDEN_FIELD_LABELS.has(label.toLowerCase())) {
        if (!field[3].trim()) hiddenParentDepth = depth;
        continue;
      }
      if (INTERNAL_REFERENCE.test(fieldValue) && ['标识', '主体', '关联对象', '内容'].includes(label)) continue;
      if (!field[3].trim()) {
        pendingListField = {
          label,
          value: '',
          depth,
          ...(activeParentLabels.filter(Boolean).length > 0 ? { parents: activeParentLabels.filter(Boolean) } : {}),
        };
        target.fields.push(pendingListField);
        pendingParent = { field: pendingListField, target, depth };
        lastField = null;
        if (depth === 0 && (target.title || target.fields.length > 0 || target.notes.length > 0)) {
          pendingListField = target.fields.at(-1) || null;
        }
        continue;
      }
      const nextField = {
        label,
        value: fieldValue,
        depth,
        ...(activeParentLabels.filter(Boolean).length > 0 ? { parents: activeParentLabels.filter(Boolean) } : {}),
        ...(activeListContext && depth > activeListContext.parentDepth ? {
          listParentIndex: activeListContext.parentIndex,
          listItemIndex: activeListContext.itemIndex,
        } : {}),
      };
      target.fields.push(nextField);
      lastField = nextField;
      lastFieldIndent = field[1].length;
      continue;
    }
    const leadingSpaces = line.length - line.trimStart().length;
    if (lastField && leadingSpaces > lastFieldIndent) {
      lastField.value = `${lastField.value}\n${line.trim()}`.trim();
      continue;
    }
    pendingListField = null;
    pendingParent = null;
    lastField = null;
    ensureItem()?.notes.push(line.trim());
  }

  result.sections = result.sections
    .map((entry) => ({
      ...entry,
      items: entry.items
        .map((entryItem) => ({
          ...entryItem,
          fields: entryItem.fields.filter((entryField) => entryField.value.trim()),
        }))
        .filter(hasCreationPackItemContent),
    }))
    .filter((entry) => entry.items.some((entryItem) => entryItem.fields.length > 0 || entryItem.notes.length > 0 || entryItem.title));
  return result;
}

/** 将卡片编辑结果确定性还原为正文 Agent 直接读取的创作包原文。 */
export function serializeCreationPack(presentation: CreationPackPresentation): string {
  const title = String(presentation.title || '本章创作包').trim();
  const lines = [`# ${title}`, '', CREATION_PACK_NOTICE];

  for (const section of presentation.sections) {
    const items = section.items.filter(hasCreationPackItemContent);
    if (items.length === 0) continue;
    lines.push('', `## ${String(section.title || '未命名分区').trim()}`, '');
    const numbered = items.length > 1 || items.some((item) => Boolean(item.title?.trim()));
    items.forEach((item, itemIndex) => {
      if (numbered) lines.push(`${itemIndex + 1}.${item.title?.trim() ? ` ${item.title.trim()}` : ''}`);
      const minimumDepth = numbered ? 1 : 0;
      let emittedParents: string[] = [];
      let emittedListSignature = '';
      for (const field of item.fields) {
        const label = String(field.label || '内容').trim();
        const valueLines = String(field.value || '').split(/\r?\n/);
        const depth = Math.max(minimumDepth, Number.isFinite(field.depth) ? field.depth : minimumDepth);
        const parents = (field.parents || []).map((parent) => String(parent || '').trim()).filter(Boolean);
        const hasListContext = Number.isInteger(field.listParentIndex) && Number.isInteger(field.listItemIndex);
        const listParentIndex = hasListContext ? Math.max(0, Math.min(parents.length - 1, field.listParentIndex || 0)) : -1;
        const listSignature = hasListContext ? `${parents.join('\u0000')}\u0000${field.listItemIndex}` : '';
        const commonParentCount = parents.findIndex((parent, index) => emittedParents[index] !== parent);
        const startParentIndex = commonParentCount < 0 ? Math.min(parents.length, emittedParents.length) : commonParentCount;
        const parentBaseDepth = Math.max(minimumDepth, depth - parents.length - (hasListContext ? 1 : 0));
        for (let parentIndex = startParentIndex; parentIndex < parents.length; parentIndex += 1) {
          lines.push(`${'  '.repeat(parentBaseDepth + parentIndex)}- ${parents[parentIndex]}：`);
        }
        if (hasListContext && listSignature !== emittedListSignature) {
          const parentKeyChanged = parents.join('\u0000') !== emittedParents.join('\u0000');
          if (parentKeyChanged && startParentIndex > listParentIndex) {
            lines.push(`${'  '.repeat(parentBaseDepth + listParentIndex)}- ${parents[listParentIndex]}：`);
          }
          lines.push(`${'  '.repeat(parentBaseDepth + listParentIndex + 1)}${field.listItemIndex}.`);
        }
        emittedParents = parents;
        emittedListSignature = listSignature;
        const indent = '  '.repeat(depth);
        lines.push(`${indent}- ${label}：${valueLines[0] || ''}`);
        for (const continuation of valueLines.slice(1)) {
          lines.push(`${indent}  ${continuation}`);
        }
      }
      for (const note of item.notes) {
        const indent = numbered ? '  ' : '';
        for (const noteLine of String(note || '').split(/\r?\n/)) {
          if (noteLine.trim()) lines.push(`${indent}${noteLine.trim()}`);
        }
      }
    });
  }

  return lines.join('\n').trim();
}

function hasCreationPackItemContent(item: CreationPackItem): boolean {
  return Boolean(item.title?.trim() || item.fields.some((field) => field.label.trim() || field.value.trim()) || item.notes.some((note) => note.trim()));
}

export function creationPackFieldLabel(key: string): string {
  const normalized = String(key || '').trim().toLowerCase();
  return FIELD_LABELS[normalized] || String(key || '').trim().replaceAll('_', ' ');
}

function creationPackValueLabel(value: string): string {
  const trimmed = String(value || '').trim();
  return VALUE_LABELS[trimmed.toLowerCase()] || trimmed;
}
