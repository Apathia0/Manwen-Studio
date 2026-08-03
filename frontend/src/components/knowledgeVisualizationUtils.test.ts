import { describe, expect, it } from 'vitest';

import type { StoryKnowledgeItem } from '../api';
import {
  buildEntityGraph,
  buildRelationshipFactPayload,
  buildTimelineDomain,
  canCreateRelationship,
  chapterPosition,
  clampGraphPoint,
  mergeEntityGraphLayoutCache,
  parseEntityGraphLayoutCache,
  stringifyEntityGraphLayoutCache,
} from './knowledgeVisualizationUtils';

describe('作品知识可视化数据', () => {
  it('根据章节字段生成可读的时间轴范围', () => {
    const items = [
      { id: 1, kind: 'fact', valid_from_chapter: 3, valid_to_chapter: 18 },
      { id: 2, kind: 'fact', valid_from_chapter: 22 },
    ] as StoryKnowledgeItem[];

    const domain = buildTimelineDomain(items, 'fact');

    expect(domain.start).toBe(1);
    expect(domain.end).toBe(25);
    expect(domain.ticks[0]).toBe(1);
    expect(domain.ticks.at(-1)).toBe(25);
    expect(chapterPosition(13, domain)).toBe(50);
  });

  it('从事实和剧情线中构建人物关系图谱', () => {
    const entities = [
      { id: 1, kind: 'entity', entity_key: 'character:chen-xuan', canonical_name: '陈玄', entity_type: 'character', importance: 100 },
      { id: 2, kind: 'entity', entity_key: 'faction:chen-family', canonical_name: '陈家', entity_type: 'faction', importance: 80 },
      { id: 3, kind: 'entity', entity_key: 'location:wasteland', canonical_name: '荒域', entity_type: 'location', importance: 70 },
    ] as StoryKnowledgeItem[];
    const facts = [
      { id: 9, kind: 'fact', subject_key: '陈玄', object_key: 'faction:chen-family', predicate: '属于' },
    ] as StoryKnowledgeItem[];
    const threads = [
      { id: 10, kind: 'plot_thread', title: '荒域探索', related_entity_keys: ['character:chen-xuan', 'location:wasteland'] },
    ] as StoryKnowledgeItem[];

    const graph = buildEntityGraph(entities, facts, threads);

    expect(graph.nodes).toHaveLength(4);
    expect(graph.edges.map((edge) => edge.label)).toEqual(expect.arrayContaining(['属于', '荒域探索']));
    expect(graph.edges.find((edge) => edge.kind === 'plot_thread')?.directed).toBe(false);
    expect(graph.hiddenCount).toBe(0);
  });

  it('双向同谓词事实保留两个有向边', () => {
    const entities = [
      { id: 1, kind: 'entity', entity_key: 'character:a', canonical_name: '甲', entity_type: 'character', importance: 100 },
      { id: 2, kind: 'entity', entity_key: 'character:b', canonical_name: '乙', entity_type: 'character', importance: 90 },
    ] as StoryKnowledgeItem[];
    const facts = [
      { id: 1, kind: 'fact', subject_key: 'character:a', object_key: 'character:b', predicate: '信任' },
      { id: 2, kind: 'fact', subject_key: 'character:b', object_key: 'character:a', predicate: '信任' },
    ] as StoryKnowledgeItem[];

    const graph = buildEntityGraph(entities, facts, []);

    expect(graph.edges).toHaveLength(2);
    expect(graph.edges.every((edge) => edge.directed)).toBe(true);
    expect(graph.edges.map((edge) => `${edge.from.key}->${edge.to.key}`)).toEqual(expect.arrayContaining(['character:a->character:b', 'character:b->character:a']));
  });

  it('歧义名称和非精确短名不会生成事实连线', () => {
    const entities = [
      { id: 1, kind: 'entity', entity_key: 'character:chen-xuan', canonical_name: '陈玄', aliases_json: ['小陈'], entity_type: 'character', importance: 100 },
      { id: 2, kind: 'entity', entity_key: 'character:chen-yun', canonical_name: '陈云', aliases_json: ['小陈'], entity_type: 'character', importance: 90 },
      { id: 3, kind: 'entity', entity_key: 'faction:chen-family', canonical_name: '陈家', entity_type: 'faction', importance: 80 },
    ] as StoryKnowledgeItem[];
    const facts = [
      { id: 1, kind: 'fact', subject_key: '小陈', object_key: 'faction:chen-family', predicate: '属于' },
      { id: 2, kind: 'fact', subject_key: '陈', object_key: 'faction:chen-family', predicate: '关联' },
    ] as StoryKnowledgeItem[];

    const graph = buildEntityGraph(entities, facts, []);

    expect(graph.edges).toHaveLength(0);
  });

  it('剧情线生成独立节点并用无向语义连接实体', () => {
    const entities = [
      { id: 1, kind: 'entity', entity_key: 'character:chen-xuan', canonical_name: '陈玄', entity_type: 'character', importance: 100 },
      { id: 2, kind: 'entity', entity_key: 'location:wasteland', canonical_name: '荒域', entity_type: 'location', importance: 90 },
    ] as StoryKnowledgeItem[];
    const threads = [
      { id: 10, kind: 'plot_thread', title: '荒域探索', related_entity_keys: ['character:chen-xuan', 'location:wasteland'] },
    ] as StoryKnowledgeItem[];

    const graph = buildEntityGraph(entities, [], threads);
    const threadNode = graph.nodes.find((node) => node.kind === 'plot_thread');

    expect(threadNode?.name).toBe('荒域探索');
    expect(graph.edges).toHaveLength(2);
    expect(graph.edges.every((edge) => edge.kind === 'plot_thread' && !edge.directed && edge.from.id === threadNode?.id)).toBe(true);
  });

  it('没有关联实体的剧情线仍作为独立节点展示', () => {
    const graph = buildEntityGraph([], [], [{ id: 10, story_id: 1, kind: 'plot_thread', title: '孤立线索', related_entity_keys: [] }] as StoryKnowledgeItem[]);

    expect(graph.nodes.find((node) => node.kind === 'plot_thread')?.name).toBe('孤立线索');
    expect(graph.edges).toHaveLength(0);
  });

  it('相似但不相同的稳定键不会互相覆盖', () => {
    const entities = [
      { id: 1, kind: 'entity', entity_key: 'character:a-b', canonical_name: '甲', entity_type: 'character' },
      { id: 2, kind: 'entity', entity_key: 'character:ab', canonical_name: '乙', entity_type: 'character' },
    ] as StoryKnowledgeItem[];
    const facts = [{ id: 3, kind: 'fact', subject_key: 'character:a-b', object_key: 'character:ab', predicate: '敌对' }] as StoryKnowledgeItem[];

    const graph = buildEntityGraph(entities, facts, []);

    expect(graph.edges).toHaveLength(1);
    expect(graph.edges[0].from.itemId).toBe(1);
    expect(graph.edges[0].to.itemId).toBe(2);
  });

  it('限制图谱节点数量并报告隐藏数量', () => {
    const entities = Array.from({ length: 35 }, (_, index) => ({
      id: index + 1,
      kind: 'entity',
      entity_key: `character:${index}`,
      canonical_name: `人物${index}`,
      entity_type: 'character',
      importance: index,
    })) as StoryKnowledgeItem[];

    const graph = buildEntityGraph(entities, [], [], 30);

    expect(graph.nodes).toHaveLength(30);
    expect(graph.hiddenCount).toBe(5);
    expect(graph.hiddenThreadCount).toBe(0);
  });

  it('限制剧情线节点数量并报告隐藏数量', () => {
    const entities = [
      { id: 1, kind: 'entity', entity_key: 'character:a', canonical_name: '甲', entity_type: 'character', importance: 100 },
    ] as StoryKnowledgeItem[];
    const threads = Array.from({ length: 25 }, (_, index) => ({
      id: index + 1,
      kind: 'plot_thread',
      title: `剧情线${index + 1}`,
      priority: index,
      related_entity_keys: ['character:a'],
    })) as StoryKnowledgeItem[];

    const graph = buildEntityGraph(entities, [], threads);

    expect(graph.nodes.filter((node) => node.kind === 'plot_thread')).toHaveLength(20);
    expect(graph.hiddenThreadCount).toBe(5);
  });

  it('解析布局缓存时容错并过滤异常坐标', () => {
    expect(parseEntityGraphLayoutCache('{bad json', 900, 430).nodes).toEqual({});
    expect(parseEntityGraphLayoutCache(JSON.stringify({ v: 2, n: { a: [1, 2] } }), 900, 430).nodes).toEqual({});

    const cache = parseEntityGraphLayoutCache(JSON.stringify({ v: 1, n: { a: [10, 20], b: ['x', 100], c: { x: 860, y: 410 } } }), 900, 430);

    expect(cache.nodes.a).toEqual({ x: 88, y: 28 });
    expect(cache.nodes.b).toBeUndefined();
    expect(cache.nodes.c).toEqual({ x: 812, y: 402 });
  });

  it('序列化布局缓存为小体积版本化结构', () => {
    const raw = stringifyEntityGraphLayoutCache({ version: 1, nodes: { a: { x: 100.4, y: 200.6 } } });

    expect(raw).toBe('{"v":1,"n":{"a":[100,201]}}');
  });

  it('筛选后保存布局时保留当前不可见节点的位置', () => {
    const merged = mergeEntityGraphLayoutCache(
      { version: 1, nodes: { 'entity:1': { x: 120, y: 90 }, 'entity:2': { x: 320, y: 190 } } },
      { 'entity:1': { x: 180, y: 140 } },
    );

    expect(merged.nodes).toEqual({
      'entity:1': { x: 180, y: 140 },
      'entity:2': { x: 320, y: 190 },
    });
  });

  it('限制图谱坐标在卡片可见范围内', () => {
    expect(clampGraphPoint({ x: -100, y: 999 }, 900, 430)).toEqual({ x: 88, y: 402 });
    expect(clampGraphPoint({ x: 450, y: 120 }, 900, 430)).toEqual({ x: 450, y: 120 });
  });

  it('关系创建禁止自连接和剧情线端点', () => {
    const graph = buildEntityGraph(
      [
        { id: 1, kind: 'entity', entity_key: 'character:a', canonical_name: '甲', entity_type: 'character' },
        { id: 2, kind: 'entity', entity_key: 'character:b', canonical_name: '乙', entity_type: 'character' },
      ] as StoryKnowledgeItem[],
      [],
      [{ id: 3, story_id: 1, kind: 'plot_thread', title: '剧情线', related_entity_keys: [] }] as StoryKnowledgeItem[],
    );
    const first = graph.nodes.find((node) => node.key === 'character:a');
    const second = graph.nodes.find((node) => node.key === 'character:b');
    const thread = graph.nodes.find((node) => node.kind === 'plot_thread');

    expect(canCreateRelationship(first, second)).toBe(true);
    expect(canCreateRelationship(first, first)).toBe(false);
    expect(canCreateRelationship(first, thread)).toBe(false);
  });

  it('构建关系事实 payload', () => {
    expect(buildRelationshipFactPayload({ subjectKey: 'character:a', predicate: '信任', objectKey: 'character:b', description: '甲信任乙。' })).toEqual({
      subject_key: 'character:a',
      predicate: '信任',
      object_key: 'character:b',
      value_text: '甲信任乙。',
      status: 'active',
    });
    expect(buildRelationshipFactPayload({ subjectKey: '甲', predicate: '敌对', objectKey: '乙' }).value_text).toBe('甲 敌对 乙');
  });
});
