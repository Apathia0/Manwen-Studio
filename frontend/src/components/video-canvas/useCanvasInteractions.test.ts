import { describe, expect, it } from 'vitest';
import { canConnectPorts, canCreateConnection, connectionDropTarget, type CanvasSceneNode } from './useCanvasInteractions';
import type { VideoCanvasNodeCatalogItem } from '../../api';

const catalog: VideoCanvasNodeCatalogItem[] = [{
  type: 'video', label: '视频', category: '媒体',
  inputs: [{ key: 'prompt', type: 'text' }, { key: 'image', type: 'image' }],
  outputs: [{ key: 'video', type: 'video' }],
}];
const nodes: CanvasSceneNode[] = [{ id: 'target', type: 'video', position: { x: 100, y: 100 }, data: {} }];
const source = { nodeId: 'source', handleType: 'source' as const, handleKey: 'image' };

describe('连线落点', () => {
  it('第二端口靠内和靠外半区都连接图片输入，不回退到提示词输入', () => {
    for (const x of [96, 100, 104]) {
      expect(connectionDropTarget({ x, y: 310 }, 1, nodes, catalog, source)).toMatchObject({ nodeId: 'target', handleKey: 'image' });
    }
  });

  it('缩放后仍保持端口优先于节点内部', () => {
    expect(connectionDropTarget({ x: 105, y: 310 }, 0.5, nodes, catalog, source).handleKey).toBe('image');
  });

  it('不在端口附近时允许拖至节点内部连接默认输入', () => {
    expect(connectionDropTarget({ x: 300, y: 200 }, 1, nodes, catalog, source).handleKey).toBe('prompt');
  });

  it('禁止连接自身，空白区域没有目标', () => {
    expect(connectionDropTarget({ x: 100, y: 310 }, 1, nodes, catalog, { ...source, nodeId: 'target' }).nodeId).toBeNull();
    expect(connectionDropTarget({ x: -500, y: -500 }, 1, nodes, catalog, source)).toEqual({ nodeId: null, handleKey: null, isNearNode: false });
  });

  it('组框不吃内部/扩展落点：让位给框内子节点与空白', () => {
    const groupCatalog: VideoCanvasNodeCatalogItem[] = [
      ...catalog,
      {
        type: 'container', label: '节点组', category: '管理',
        inputs: [{ key: 'items', type: 'any', multiple: true }],
        outputs: [{ key: 'assets', type: 'any', multiple: true }],
      },
    ];
    const frame: CanvasSceneNode = { id: 'group', type: 'container', position: { x: 0, y: 0 }, data: { ui: { width: 600, height: 400 } } };
    const withFrame = [frame, nodes[0]];
    // 落点在子节点内部（非端口）→ 命中子节点而不是组框
    expect(connectionDropTarget({ x: 300, y: 200 }, 1, withFrame, groupCatalog, source))
      .toMatchObject({ nodeId: 'target', handleKey: 'prompt' });
    // 落点只在组框内、不在任何子节点 → 组框不接管
    expect(connectionDropTarget({ x: 550, y: 380 }, 1, withFrame, groupCatalog, source).nodeId).toBeNull();
  });
});


describe('端口类型兼容', () => {
  it('来源或目标为 any 时允许连接，反向端口仍拒绝', () => {
    expect(canConnectPorts({ side: 'output', dataType: 'any' }, { side: 'input', dataType: 'image' })).toBe(true);
    expect(canConnectPorts({ side: 'output', dataType: 'image' }, { side: 'input', dataType: 'any' })).toBe(true);
    expect(canConnectPorts({ side: 'output', dataType: 'text' }, { side: 'input', dataType: 'image' })).toBe(false);
    expect(canConnectPorts({ side: 'input', dataType: 'any' }, { side: 'output', dataType: 'any' })).toBe(false);
  });

  it('视频输出不能连接图片类输入', () => {
    expect(canConnectPorts({ side: 'output', dataType: 'video' }, { side: 'input', dataType: 'image' })).toBe(false);
    expect(canConnectPorts({ side: 'output', dataType: 'image' }, { side: 'input', dataType: 'image' })).toBe(true);
    expect(canConnectPorts({ side: 'output', dataType: 'any' }, { side: 'input', dataType: 'video' })).toBe(true);
  });
});

describe('连线创建类型过滤', () => {
  const catalogFull: VideoCanvasNodeCatalogItem[] = [
    {
      type: 'image', label: '图片', category: '媒体',
      inputs: [{ key: 'prompt', type: 'any', multiple: true }, { key: 'references', type: 'image', multiple: true }],
      outputs: [{ key: 'image', type: 'any' }],
    },
    {
      type: 'video', label: '视频', category: '媒体',
      inputs: [{ key: 'prompt', type: 'any', multiple: true }, { key: 'image', type: 'image', multiple: true }],
      outputs: [{ key: 'video', type: 'video' }],
    },
    {
      type: 'concat', label: '成片合成', category: '交付',
      inputs: [{ key: 'videos', type: 'video', multiple: true }],
      outputs: [{ key: 'video', type: 'video' }],
    },
  ];
  const scene: CanvasSceneNode[] = [
    { id: 'asset', type: 'image', position: { x: 0, y: 0 }, data: {} },
    { id: 'board', type: 'image', position: { x: 500, y: 0 }, data: {} },
    { id: 'video', type: 'video', position: { x: 1000, y: 0 }, data: {} },
    { id: 'video-b', type: 'video', position: { x: 1500, y: 0 }, data: {} },
    { id: 'concat', type: 'concat', position: { x: 2000, y: 0 }, data: {} },
  ];

  it('资产图输出可连分镜 references、视频 image 与拼接输入', () => {
    expect(canCreateConnection(scene, catalogFull, 'asset', 'image', 'board', 'references')).toBe(true);
    expect(canCreateConnection(scene, catalogFull, 'asset', 'image', 'video', 'image')).toBe(true);
    expect(canCreateConnection(scene, catalogFull, 'video', 'video', 'concat', 'videos')).toBe(true);
    expect(canCreateConnection(scene, catalogFull, 'board', 'image', 'concat', 'videos')).toBe(true);
  });

  it('视频输出不能连 image.references 或 video.image', () => {
    expect(canCreateConnection(scene, catalogFull, 'video', 'video', 'board', 'references')).toBe(false);
    expect(canCreateConnection(scene, catalogFull, 'video', 'video', 'video-b', 'image')).toBe(false);
  });

  it('同节点、未知节点与未知端口一律拒绝', () => {
    expect(canCreateConnection(scene, catalogFull, 'board', 'image', 'board', 'references')).toBe(false);
    expect(canCreateConnection(scene, catalogFull, 'missing', 'image', 'board', 'references')).toBe(false);
    expect(canCreateConnection(scene, catalogFull, 'video', 'video', 'board', 'missing-handle')).toBe(false);
  });
});
