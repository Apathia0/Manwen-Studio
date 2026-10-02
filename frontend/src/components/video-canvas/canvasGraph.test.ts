import { describe, expect, it } from 'vitest';
import type { VideoCanvasGraph } from '../../api';
import { projectLegacyGraph } from './canvasGraph';

describe('画布语义保留', () => {
  it('打开并投影时保留容器、合片的类型和真实端口', () => {
    const graph: VideoCanvasGraph = {
      schema_version: 1,
      nodes: [
        { id: 'clip', type: 'video', data: {}, position: { x: 0, y: 0 } },
        { id: 'group', type: 'container', data: {}, position: { x: 0, y: 0 } },
        { id: 'final', type: 'concat', data: {}, position: { x: 0, y: 0 } },
      ],
      edges: [
        { id: 'e1', source: 'clip', target: 'group', sourceHandle: 'video', targetHandle: 'items' },
        { id: 'e2', source: 'group', target: 'final', sourceHandle: 'assets', targetHandle: 'videos' },
      ],
      groups: [], metadata: { director: '保留' },
    };
    const result = projectLegacyGraph(graph);
    expect(result.nodes.map(node => node.type)).toEqual(['video', 'container', 'concat']);
    expect(result.edges).toEqual(graph.edges);
    expect(result.metadata).toEqual(graph.metadata);
    expect(graph.nodes[2].type).toBe('concat');
  });
});
