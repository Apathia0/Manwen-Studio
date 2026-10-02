import { describe, expect, it } from 'vitest';
import { layoutDirectorUnits, unitNodeId } from './directorLayout';

describe('unitNodeId', () => {
  it('同一场景同一单元生成稳定 ID', () => {
    expect(unitNodeId('scene-1', 'u-001')).toBe(unitNodeId('scene-1', 'u-001'));
    expect(unitNodeId('scene-1', 'u-001')).not.toBe(unitNodeId('scene-1', 'u-002'));
    expect(unitNodeId('scene-1', 'u-001')).not.toBe(unitNodeId('scene-2', 'u-001'));
  });

  it('清理非法字符避免与图节点 ID 校验冲突', () => {
    expect(unitNodeId('scene-1', 'u/001 x')).not.toMatch(/[^A-Za-z0-9_-]/);
  });
});

describe('layoutDirectorUnits', () => {
  const units = [
    { sequence: 2, unit_id: 'u-002' },
    { sequence: 1, unit_id: 'u-001' },
    { sequence: 3, unit_id: 'u-003' },
  ];

  it('按 sequence 顺序横向排列', () => {
    const positions = layoutDirectorUnits(units, { x: 100, y: 100 }, []);
    const first = positions.get('u-001');
    const second = positions.get('u-002');
    const third = positions.get('u-003');
    expect(first).toBeDefined();
    expect(second).toBeDefined();
    expect(third).toBeDefined();
    expect(second!.x).toBeGreaterThan(first!.x);
    expect(third!.x).toBeGreaterThan(second!.x);
    expect(first!.y).toBe(second!.y);
  });

  it('避让已有节点', () => {
    const positions = layoutDirectorUnits(
      [{ sequence: 1, unit_id: 'u-001' }],
      { x: 100, y: 100 },
      [{ x: 100, y: 100, width: 340, height: 220 }],
    );
    const placed = positions.get('u-001')!;
    expect(placed.x).toBeGreaterThanOrEqual(100 + 340);
  });

  it('重复调用结果稳定', () => {
    const a = layoutDirectorUnits(units, { x: 0, y: 0 }, []);
    const b = layoutDirectorUnits(units, { x: 0, y: 0 }, []);
    expect([...a.entries()]).toEqual([...b.entries()]);
  });
});
