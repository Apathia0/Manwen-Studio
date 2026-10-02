import type { VideoCanvasGraph } from '../../api';

export interface CanvasDraftLayout {
  nodes: Record<string, { x: number; y: number }>;
  viewport: { x: number; y: number; zoom: number };
}

export interface CanvasDraftEnvelope {
  version: 1;
  storyId: number;
  chapterId?: number;
  canvasId: number;
  baseDefinitionRevision: number;
  baseLayoutRevision: number;
  clientRevision: number;
  graph: VideoCanvasGraph;
  layout: CanvasDraftLayout;
  updatedAt: number;
}

export function canvasDraftKey(storyId: number, chapterId: number | undefined, canvasId: number): string {
  return `storycanvas.video-canvas-draft.${storyId}.${chapterId ?? 'story'}.${canvasId}`;
}

export function readCanvasDraft(key: string): CanvasDraftEnvelope | null {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<CanvasDraftEnvelope>;
    if (value.version !== 1 || !value.graph || !value.layout || typeof value.updatedAt !== 'number') return null;
    return value as CanvasDraftEnvelope;
  } catch {
    return null;
  }
}

export function writeCanvasDraft(key: string, draft: CanvasDraftEnvelope): boolean {
  try {
    localStorage.setItem(key, JSON.stringify(draft));
    return true;
  } catch {
    return false;
  }
}

export function removeCanvasDraft(key: string): void {
  try { localStorage.removeItem(key); } catch { /* storage may be unavailable */ }
}

export function isNewerCanvasDraft(
  draft: CanvasDraftEnvelope,
  server: { id: number; definition_revision: number; layout_revision: number },
): boolean {
  return draft.canvasId === server.id
    && draft.baseDefinitionRevision === server.definition_revision
    && draft.baseLayoutRevision === server.layout_revision
    && draft.updatedAt > 0;
}
