import { describe, expect, it } from 'vitest';

import { creationPackFieldLabel, parseCreationPack, serializeCreationPack } from './chapterCreationPackPresentation';

describe('创作包易读视图', () => {
  it('解析标题、分区、人物条目并映射中文字段', () => {
    const parsed = parseCreationPack(`# 第1章创作包：仙草落凡

> 页面保存后的文本会原样发送。

## 人物设定

1.
  - name：陈玄
  - role：protagonist
2.
  - name：陈母
  - role：supporting`);

    expect(parsed.title).toBe('第1章创作包：仙草落凡');
    expect(parsed.notice).toContain('原样发送');
    expect(parsed.sections[0].title).toBe('人物设定');
    expect(parsed.sections[0].items).toHaveLength(2);
    expect(parsed.sections[0].items[0].fields).toEqual([
      { label: '姓名', value: '陈玄', depth: 1 },
      { label: '身份', value: '主角', depth: 1 },
    ]);
  });

  it('未知字段不丢失并移除下划线', () => {
    expect(creationPackFieldLabel('custom_rule')).toBe('custom rule');
  });

  it('嵌套人物信息不会覆盖人物姓名标题', () => {
    const parsed = parseCreationPack(`## 人物设定

1.
  - name：陈玄
  - role：protagonist
  - profile：
    - age：18`);

    expect(parsed.sections[0].items[0].title).toBeUndefined();
    expect(parsed.sections[0].items[0].fields[0].value).toBe('陈玄');
    expect(parsed.sections[0].items[0].fields.at(-1)?.label).toBe('age');
  });

  it('过滤内部引用且不把嵌套编号拆成数字卡片', () => {
    const parsed = parseCreationPack(`## 伏笔与剧情推进

1.
  - key：memory:loop:48405783db64745cba54
  - 标题：药费倒计时
  - payoff window：
    1. 1
    2. 2
  - expected payoff from：1
  - expected payoff to：2
  - related entities：
    1. legacy:character:e2d50aefcd512c010f50
  - 本章相关度：190`);

    expect(parsed.sections[0].items).toHaveLength(1);
    expect(parsed.sections[0].items[0].fields).toEqual([
      { label: '标题', value: '药费倒计时', depth: 1 },
      { label: '预计回收起始章', value: '1', depth: 1 },
      { label: '预计回收截止章', value: '2', depth: 1 },
    ]);
    expect(parsed.sections[0].items[0].notes).toEqual([]);
  });

  it('将事实谓词、线索类型和状态完整映射为中文', () => {
    const parsed = parseCreationPack(`## 本章有效事实

1.
  - predicate：acquired
  - status：archived
2.
  - predicate：improved
3.
  - predicate：possesses
4.
  - predicate：continuity

## 伏笔与剧情推进

1.
  - type：foreshadow
  - urgency：approaching`);

    const values = parsed.sections.flatMap((section) => section.items.flatMap((item) => item.fields.map((field) => field.value)));
    expect(values).toEqual(['获得', '已归档', '提升', '持有', '连续性', '伏笔', '临近回收']);
  });

  it('将卡片修改确定性序列化，并可再次解析为相同可见内容', () => {
    const parsed = parseCreationPack(`# 第8章创作包：灰市交易

## 本章有效事实

1.
  - 主体：陈玄
  - 内容：陈玄持有三枚灵珠
2.
  - 主体：周叔
  - 内容：周叔掌握灰市入口`);

    parsed.sections[0].items[0].fields[1].value = '陈玄持有五枚灵珠';
    const serialized = serializeCreationPack(parsed);
    const reparsed = parseCreationPack(serialized);

    expect(serialized).toContain('- 内容：陈玄持有五枚灵珠');
    expect(serialized).toContain('正文 Agent 实际接收');
    expect(reparsed.sections[0].items[0].fields[1].value).toBe('陈玄持有五枚灵珠');
    expect(reparsed.sections[0].items[1].fields[1].value).toBe('周叔掌握灰市入口');
  });

  it('保留卡片字段中的多行列表和补充说明', () => {
    const parsed = parseCreationPack(`## 章节规划

- 关键事件：
  1. 陈玄进入灰市
  2. 与周叔完成交易
- 写作指导：先压低气氛
  再用冲突提速`);

    expect(parsed.sections[0].items[0].fields[0].value).toBe('1. 陈玄进入灰市\n2. 与周叔完成交易');
    expect(parsed.sections[0].items[0].fields[1].value).toBe('先压低气氛\n再用冲突提速');

    const reparsed = parseCreationPack(serializeCreationPack(parsed));
    expect(reparsed.sections[0].items[0].fields.map((field) => field.value)).toEqual([
      '1. 陈玄进入灰市\n2. 与周叔完成交易',
      '先压低气氛\n再用冲突提速',
    ]);
  });

  it('保留后端渲染的嵌套对象父级语义', () => {
    const parsed = parseCreationPack(`## 本章相关人物与对象

1.
  - 姓名：陈玄
  - 人物信息：
    - age：18
    - current_state：负伤
    - relationships：
      - relation：同盟`);

    const fields = parsed.sections[0].items[0].fields;
    expect(fields.find((field) => field.label === 'age')?.parents).toEqual(['人物信息']);
    expect(fields.find((field) => field.label === '当前状态')?.parents).toEqual(['人物信息']);
    expect(fields.find((field) => field.label === '关系')?.parents).toEqual(['人物信息', '本章关系']);

    const serialized = serializeCreationPack(parsed);
    expect(serialized).toContain('  - 人物信息：\n    - age：18');
    expect(serialized).toContain('    - 本章关系：\n      - 关系：同盟');

    const reparsed = parseCreationPack(serialized);
    expect(reparsed.sections[0].items[0].fields.find((field) => field.label === '关系')?.parents).toEqual(['人物信息', '本章关系']);
  });

  it('保留嵌套对象列表中每个关系项的独立边界', () => {
    const parsed = parseCreationPack(`## 本章相关人物与对象

1.
  - 姓名：陈玄
  - 人物信息：
    - relationships：
      1.
        - to：周叔
        - relation：同盟
      2.
        - to：赵锋
        - relation：敌对`);

    const relationshipFields = parsed.sections[0].items[0].fields.filter((field) => field.parents?.includes('本章关系'));
    expect(relationshipFields.map((field) => [field.label, field.value, field.listItemIndex])).toEqual([
      ['关系对象', '周叔', 1],
      ['关系', '同盟', 1],
      ['关系对象', '赵锋', 2],
      ['关系', '敌对', 2],
    ]);

    const serialized = serializeCreationPack(parsed);
    expect(serialized).toContain('    - 本章关系：\n      1.\n        - 关系对象：周叔\n        - 关系：同盟\n      2.\n        - 关系对象：赵锋\n        - 关系：敌对');

    const reparsed = parseCreationPack(serialized);
    expect(reparsed.sections[0].items[0].fields.filter((field) => field.parents?.includes('本章关系')).map((field) => [field.value, field.listItemIndex])).toEqual([
      ['周叔', 1], ['同盟', 1], ['赵锋', 2], ['敌对', 2],
    ]);
  });
});
