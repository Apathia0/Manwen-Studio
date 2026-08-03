import { describe, expect, it } from 'vitest';

import {
  buildEntityNameMap,
  formatContextValue,
  formatEntityProfile,
  formatFact,
  relevanceLabel,
} from './chapterContextPresentation';

describe('章节创作包展示脱敏', () => {
  it('将人物资料对象转为中文摘要且不显示 JSON 结构', () => {
    const text = formatEntityProfile({
      name: '陈玄',
      role: 'protagonist',
      big_five: { O: 80, C: 100, E: 20, A: 100, N: 100 },
      arc: {
        start: '底层起步',
        middle: '积累资源',
        end: '追求超脱',
      },
      personality: ['沉着', '果断'],
      entity_key: 'legacy:character:secret',
    }, '陈玄');

    expect(text).toBe('身份：主角；人物发展：初始阶段：底层起步；发展阶段：积累资源；后续走向：追求超脱；性格：沉着、果断');
    expect(text).not.toContain('{');
    expect(text).not.toContain('legacy:');
    expect(text).not.toContain('80');
    expect(text).not.toContain('信息：');
  });

  it('用人物名称和中文分类替换事实中的内部键', () => {
    const names = buildEntityNameMap([
      { key: 'legacy:character:chen', name: '陈玄' },
      { key: 'legacy:character:mother', name: '陈母' },
    ]);
    const relation = formatFact({
      subject: 'legacy:character:chen',
      predicate: '母子',
      object: 'legacy:character:mother',
    }, names);
    const continuity = formatFact({
      subject: 'world_story',
      predicate: 'continuity',
      value: '城郊荒域是官方开放的低危资源区',
    }, names);

    expect(relation.title).toBe('陈玄 · 母子 · 陈母');
    expect(continuity.title).toBe('世界剧情 · 连续性');
    expect(continuity.detail).toBe('城郊荒域是官方开放的低危资源区');
  });

  it('隐藏未知内部引用并将分数转换为用户语言', () => {
    expect(formatContextValue('legacy:character:unknown')).toBe('关联对象');
    expect(formatContextValue('character:goat_beard')).toBe('关联对象');
    expect(formatContextValue({ affinity_score: 90, weight: 50, note: '保持距离' })).toBe('备注：保持距离');
    expect(relevanceLabel(148)).toBe('高度相关');
    expect(relevanceLabel(68)).toBe('相关');
    expect(relevanceLabel(12)).toBe('参考');
  });

  it('将常见事实关系映射为中文', () => {
    const fact = formatFact({
      subject: 'legacy:character:chen',
      predicate: 'sold_to',
      object: 'character:goat_beard',
      value: '三根鸡骨野猪后腿骨，获得110银珠',
    }, new Map([['legacy:character:chen', '陈玄']]));

    expect(fact.title).toBe('陈玄 · 出售给 · 关联对象');
    expect(fact.detail).toBe('三根鸡骨野猪后腿骨，获得110银珠');
  });

  it('覆盖数据库中现有事实谓词、类型和状态枚举', () => {
    expect(formatContextValue(['acquired', 'improved', 'possesses', 'continuity'])).toBe('获得、提升、持有、连续性');
    expect(formatContextValue(['foreshadow', 'world_concept', 'world_rule'])).toBe('伏笔、世界概念、世界规则');
    expect(formatContextValue(['active', 'archived', 'open', 'resolved'])).toBe('生效中、已归档、待推进、已完成');
  });
});
