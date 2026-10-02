import { describe, expect, it } from 'vitest';
import { clampOverlayPosition, computeFocusViewport, placeInspector } from './overlayPlacement';

describe('clampOverlayPosition', () => {
  it('keeps a menu inside the bottom-right edge', () => {
    expect(clampOverlayPosition({ x: 760, y: 560 }, { width: 300, height: 260 }, { width: 900, height: 700 })).toEqual({ x: 588, y: 428 });
  });

  it('respects safe insets on a narrow canvas', () => {
    expect(clampOverlayPosition({ x: 0, y: 0 }, { width: 320, height: 180 }, { width: 390, height: 430 }, { left: 16, top: 24, right: 16, bottom: 32 })).toEqual({ x: 16, y: 24 });
  });
});

describe('placeInspector', () => {
  it('places the inspector below a node when there is room', () => {
    expect(placeInspector({ anchor: { x: 120, y: 80, width: 420, height: 220 }, size: { width: 500, height: 180 }, bounds: { width: 900, height: 700 } })).toEqual({ x: 120, y: 316 });
  });

  it('keeps the inspector below the node even near the bottom, clamping only the side', () => {
    expect(placeInspector({ anchor: { x: 760, y: 560, width: 120, height: 100 }, size: { width: 500, height: 180 }, bounds: { width: 900, height: 700 } })).toEqual({ x: 388, y: 676 });
  });
});

describe('computeFocusViewport', () => {
  it('centers the node in the area above the input panel', () => {
    const v = computeFocusViewport({ node: { x: 100, y: 200, width: 300, height: 200 }, bounds: { width: 1200, height: 900 }, reserved: { top: 76, bottom: 438 } });
    expect(v.k).toBeLessThanOrEqual(1);
    expect((100 + 150) * v.k + v.x).toBeCloseTo(600);
    expect((200 + 100) * v.k + v.y).toBeCloseTo(76 + (900 - 76 - 438) / 2);
  });
  it('never exceeds max scale for small nodes', () => {
    const v = computeFocusViewport({ node: { x: 0, y: 0, width: 50, height: 50 }, bounds: { width: 1200, height: 900 }, reserved: { top: 76, bottom: 438 } });
    expect(v.k).toBe(1);
  });
});
