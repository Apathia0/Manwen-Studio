import { describe, expect, it } from 'vitest';
import {
  computeGroupBounds,
  expandGroupMove,
  getContainerMemberIds,
  isMembershipEdge,
  orderNodesForRender,
  refitContainerBounds,
  remapContainerMembership,
  stripContainerMembership,
  GROUP_PADDING_TOP,
} from './containerGroup';
import type { CanvasSceneNode } from './CanvasEditorSurface';

function image(id: string, x: number, y: number): CanvasSceneNode {
  return { id, type: 'image', position: { x, y }, data: { config: {} } };
}

function group(id: string, memberIds: string[], extra: Record<string, unknown> = {}): CanvasSceneNode {
  return {
    id,
    type: 'container',
    position: { x: 0, y: 0 },
    data: { config: { node_role: 'container', node_label: id, member_ids: memberIds, ...extra } },
  };
}

describe('getContainerMemberIds', () => {
  it('优先 member_ids，其次旧 tabs，最后成员边', () => {
    const nodes = [image('a', 0, 0), image('b', 0, 0), group('g', ['a'])];
    expect(getContainerMemberIds(nodes, [], 'g')).toEqual(['a']);

    const legacy: CanvasSceneNode[] = [
      image('a', 0, 0),
      image('b', 0, 0),
      { id: 'g2', type: 'container', position: { x: 0, y: 0 }, data: { config: { tabs: [{ nodes: ['b'] }] } } },
    ];
    expect(getContainerMemberIds(legacy, [], 'g2')).toEqual(['b']);

    const edgeOnly: CanvasSceneNode[] = [image('a', 0, 0), { id: 'g3', type: 'container', position: { x: 0, y: 0 }, data: { config: {} } }];
    expect(getContainerMemberIds(
      edgeOnly,
      [{ source: 'a', target: 'g3', targetHandle: 'items' }],
      'g3',
    )).toEqual(['a']);
  });

  it('去重、剔除不存在与自身', () => {
    const nodes = [image('a', 0, 0), group('g', ['a', 'a', 'missing', 'g'])];
    expect(getContainerMemberIds(nodes, [], 'g')).toEqual(['a']);
  });
});

describe('computeGroupBounds / refitContainerBounds', () => {
  it('组框包住成员并留出标题栏与内边距', () => {
    const members = [image('a', 100, 200), image('b', 400, 300)];
    const bounds = computeGroupBounds(members)!;
    // 图片节点默认 420x236：x 100..820，y 200..536
    expect(bounds.x).toBe(100 - 32);
    expect(bounds.y).toBe(200 - GROUP_PADDING_TOP);
    expect(bounds.width).toBe(720 + 64);
    expect(bounds.height).toBe(336 + GROUP_PADDING_TOP + 32);
  });

  it('把组框移动到成员外围，且幂等', () => {
    const nodes = [image('a', 100, 200), group('g', ['a'], { })];
    nodes[1] = { ...nodes[1], data: { ...nodes[1].data, ui: { width: 999, height: 999 } } };
    const first = refitContainerBounds(nodes, []);
    expect(first.changed).toBe(true);
    const g = first.nodes.find((node) => node.id === 'g')!;
    const member = first.nodes.find((node) => node.id === 'a')!;
    expect(g.position.x).toBeLessThan(member.position.x);
    expect(g.data.ui?.width).toBe(420 + 64);

    const second = refitContainerBounds(first.nodes, []);
    expect(second.changed).toBe(false);
    expect(second.nodes).toBe(first.nodes);
  });

  it('嵌套组由内到外包住内层组框', () => {
    const nodes = [
      image('a', 0, 0),
      group('inner', ['a']),
      group('outer', ['inner']),
    ];
    const { nodes: refitted } = refitContainerBounds(nodes, []);
    const inner = refitted.find((node) => node.id === 'inner')!;
    const outer = refitted.find((node) => node.id === 'outer')!;
    // 外框必须完全包住内框
    expect(outer.position.x).toBeLessThanOrEqual(inner.position.x);
    expect(outer.position.y).toBeLessThanOrEqual(inner.position.y);
    expect(outer.position.x + (outer.data.ui?.width || 0))
      .toBeGreaterThanOrEqual(inner.position.x + (inner.data.ui?.width || 0));
    expect(outer.position.y + (outer.data.ui?.height || 0))
      .toBeGreaterThanOrEqual(inner.position.y + (inner.data.ui?.height || 0));
  });

  it('剔除已删除成员并报告 pruned', () => {
    const nodes = [group('g', ['a', 'ghost'])];
    const result = refitContainerBounds(nodes, []);
    expect(result.pruned).toBe(true);
    expect((result.nodes[0].data.config as { member_ids: string[] }).member_ids).toEqual([]);
  });
});

describe('expandGroupMove', () => {
  it('拖组框时带上全部成员（含嵌套）且去重', () => {
    const nodes = [image('a', 0, 0), image('b', 0, 0), group('inner', ['b']), group('outer', ['a', 'inner'])];
    const moved = expandGroupMove(['outer'], nodes, []);
    expect(moved.sort()).toEqual(['a', 'b', 'inner', 'outer']);
  });

  it('拖普通节点不带出组框', () => {
    const nodes = [image('a', 0, 0), group('g', ['a'])];
    expect(expandGroupMove(['a'], nodes, [])).toEqual(['a']);
  });
});

describe('orderNodesForRender', () => {
  it('组框按外→内排在普通节点之前，普通节点保持原顺序', () => {
    const nodes = [image('a', 0, 0), group('inner', ['a']), image('b', 0, 0), group('outer', ['inner'])];
    expect(orderNodesForRender(nodes, []).map((node) => node.id)).toEqual(['outer', 'inner', 'a', 'b']);
  });
});

describe('isMembershipEdge', () => {
  const nodes = [image('a', 0, 0), image('x', 0, 0), group('g', ['a'])];

  it('成员名单内或带 member 标记的边是成员边', () => {
    expect(isMembershipEdge({ source: 'a', target: 'g', targetHandle: 'items' }, nodes)).toBe(true);
    expect(isMembershipEdge({ source: 'x', target: 'g', targetHandle: 'items', data: { member: true } }, nodes)).toBe(true);
  });

  it('外部馈入边（不在名单内、无标记）正常显示', () => {
    expect(isMembershipEdge({ source: 'x', target: 'g', targetHandle: 'items' }, nodes)).toBe(false);
    expect(isMembershipEdge({ source: 'a', target: 'x', targetHandle: 'prompt' }, nodes)).toBe(false);
  });
});

describe('strip/remap membership', () => {
  it('剥离副本成员关系', () => {
    const stripped = stripContainerMembership(group('g', ['a']));
    expect((stripped.data.config as { member_ids: string[] }).member_ids).toEqual([]);
  });

  it('粘贴时按 idMap 重映射，映射不到的丢弃', () => {
    const remapped = remapContainerMembership(group('g', ['a', 'b']), new Map([['a', 'a2']]));
    expect((remapped.data.config as { member_ids: string[] }).member_ids).toEqual(['a2']);
  });
});
