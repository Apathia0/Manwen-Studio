import { describe, expect, it } from 'vitest';
import { supportsNodeInspector } from './inspectorGate';

describe('supportsNodeInspector', () => {
  it('有专用内联 UI 的节点不弹通用属性面板', () => {
    expect(supportsNodeInspector('screenplay')).toBe(false);
    expect(supportsNodeInspector('scene')).toBe(false);
    expect(supportsNodeInspector('container')).toBe(false);
    expect(supportsNodeInspector('concat')).toBe(false);
  });

  it('常规生成节点继续使用通用属性面板', () => {
    expect(supportsNodeInspector('text')).toBe(true);
    expect(supportsNodeInspector('image')).toBe(true);
    expect(supportsNodeInspector('video')).toBe(true);
    expect(supportsNodeInspector('shot')).toBe(true);
  });
});
