import { beforeEach, describe, expect, it, vi } from 'vitest';
import { canvasDraftKey, isNewerCanvasDraft, readCanvasDraft, removeCanvasDraft, writeCanvasDraft, type CanvasDraftEnvelope } from './canvasDraftStore';

const draft: CanvasDraftEnvelope = {
  version: 1,
  storyId: 1,
  chapterId: 2,
  canvasId: 3,
  baseDefinitionRevision: 4,
  baseLayoutRevision: 5,
  clientRevision: 6,
  graph: { schema_version: 1, nodes: [], edges: [], groups: [], metadata: {} },
  layout: { nodes: {}, viewport: { x: 0, y: 0, zoom: 1 } },
  updatedAt: Date.now(),
};

describe('canvasDraftStore', () => {
  beforeEach(() => {
    const store = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => { store.set(key, value); },
      removeItem: (key: string) => { store.delete(key); },
      clear: () => store.clear(),
    });
  });

  it('读写并按画布范围生成 key', () => {
    const key = canvasDraftKey(1, 2, 3);
    expect(writeCanvasDraft(key, draft)).toBe(true);
    expect(readCanvasDraft(key)).toEqual(draft);
    expect(key).toContain('1.2.3');
  });

  it('损坏数据安全返回空并支持删除', () => {
    const key = canvasDraftKey(1, undefined, 3);
    localStorage.setItem(key, '{bad');
    expect(readCanvasDraft(key)).toBeNull();
    writeCanvasDraft(key, draft);
    removeCanvasDraft(key);
    expect(readCanvasDraft(key)).toBeNull();
  });

  it('仅同一服务端 revision 基线的草稿可恢复', () => {
    expect(isNewerCanvasDraft(draft, { id: 3, definition_revision: 4, layout_revision: 5 })).toBe(true);
    expect(isNewerCanvasDraft(draft, { id: 3, definition_revision: 5, layout_revision: 5 })).toBe(false);
    expect(isNewerCanvasDraft(draft, { id: 4, definition_revision: 4, layout_revision: 5 })).toBe(false);
  });
});
