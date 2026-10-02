import { describe, expect, it } from 'vitest';
import { collectConnectedReferencePreviews, syncCanvasMediaReferences } from './canvasReferenceSync';

const edge = { source: 'image-1', target: 'video-1', sourceHandle: 'image', targetHandle: 'image' };

function graph(source: Record<string, unknown>, targetConfig: Record<string, unknown> = {}) {
  return [
    { id: 'image-1', type: 'image', data: { config: {}, result: source } },
    { id: 'video-1', type: 'video', data: { config: targetConfig } },
  ];
}

describe('syncCanvasMediaReferences', () => {
  it('uses source result even when the outer asset list is stale', () => {
    const result = syncCanvasMediaReferences(graph({ asset_id: 17, url: '/static/manga/generated.png' }), [edge]);
    expect(result[1].data?.config).toMatchObject({
      reference_asset_ids: [17],
      reference_previews: [{ asset_id: 17, url: '/static/manga/generated.png', kind: 'image' }],
    });
  });

  it('supports the connect-first-then-generate flow', () => {
    const result = syncCanvasMediaReferences(graph({}), [edge]);
    expect(result[1].data?.config?.reference_asset_ids).toBeUndefined();
    const generated = syncCanvasMediaReferences(graph({ asset_id: 17, url: '/static/manga/generated.png' }), [edge]);
    expect(generated[1].data?.config?.reference_asset_ids).toEqual([17]);
  });

  it('keeps manual references and de-duplicates repeated edges', () => {
    const result = syncCanvasMediaReferences(
      graph({ asset_id: 17, url: '/static/manga/generated.png' }, {
        reference_asset_ids: [99, 17],
        reference_previews: [{ asset_id: 99, url: '/static/manga/manual.png', kind: 'image' }],
      }),
      [edge, edge],
    );
    expect(result[1].data?.config?.reference_asset_ids).toEqual([99, 17]);
    expect((result[1].data?.config?.reference_previews as unknown[]).length).toBe(2);
  });

  it('does not create a fake reference without an asset id', () => {
    const result = syncCanvasMediaReferences(graph({ url: '/static/manga/generated.png' }), [edge]);
    expect(result[1].data?.config?.reference_asset_ids).toBeUndefined();
  });

  it('fills a revision and falls back to the asset file path', () => {
    const result = syncCanvasMediaReferences(
      graph({ asset_id: 17 }),
      [edge],
      [{ id: 17, revision: 4, file_path: 'manga_outputs/generated.png', asset_type: 'storyboard_frame' }],
    );
    expect(result[1].data?.config).toMatchObject({
      reference_asset_revisions: [{ asset_id: 17, revision: 4 }],
      reference_previews: [{ asset_id: 17, url: '/static/manga/generated.png', kind: 'image' }],
    });
  });

  it('removes an edge-derived reference after the edge is deleted but keeps manual references', () => {
    const nodes = graph({ asset_id: 17, url: '/static/manga/edge.png' }, {
      reference_asset_ids: [99, 17],
      reference_provenance: [{ asset_id: 99, source: 'manual' }, { asset_id: 17, source: 'edge', source_node_id: 'image-1' }],
      reference_previews: [
        { asset_id: 99, url: '/static/manga/manual.png', kind: 'image' },
        { asset_id: 17, url: '/static/manga/edge.png', kind: 'image', source: 'edge' },
      ],
    });
    const result = syncCanvasMediaReferences(nodes, [], [{ id: 99, file_path: 'manual.png' }, { id: 17, file_path: 'edge.png' }]);
    expect(result[1].data?.config?.reference_asset_ids).toEqual([99]);
    expect(result[1].data?.config?.reference_previews).toEqual([{ asset_id: 99, url: '/static/manga/manual.png', kind: 'image' }]);
  });

  it('replaces an edge-derived asset when the upstream result changes', () => {
    const nodes = graph({ asset_id: 18, url: '/static/manga/new.png' }, {
      reference_asset_ids: [17],
      reference_provenance: [{ asset_id: 17, source: 'edge', source_node_id: 'image-1' }],
      reference_previews: [{ asset_id: 17, url: '/static/manga/old.png', kind: 'image', source: 'edge' }],
    });
    const result = syncCanvasMediaReferences(nodes, [edge], [{ id: 18, file_path: 'new.png' }]);
    expect(result[1].data?.config?.reference_asset_ids).toEqual([18]);
    expect(result[1].data?.config?.reference_previews).toEqual(expect.arrayContaining([expect.objectContaining({ asset_id: 18, source: 'edge' })]));
  });
});

describe('collectConnectedReferencePreviews', () => {
  it('reads the upstream result even without an asset id (connect-then-upload)', () => {
    const previews = collectConnectedReferencePreviews(graph({ url: '/static/manga/uploaded.png' }), [edge], 'video-1');
    expect(previews).toEqual([{
      key: 'connected:image-1',
      nodeId: 'image-1',
      label: 'image',
      url: '/static/manga/uploaded.png',
    }]);
  });

  it('returns nothing before the source has a result', () => {
    expect(collectConnectedReferencePreviews(graph({}), [edge], 'video-1')).toEqual([]);
  });

  it('skips disabled edges and non-image sources', () => {
    const nodes = [
      ...graph({ url: '/static/manga/a.png' }),
      { id: 'video-src', type: 'video', data: { config: {}, result: { url: '/static/video/clip.mp4' } } },
      { id: 'video-dst', type: 'video', data: { config: {} } },
    ];
    const previews = collectConnectedReferencePreviews(nodes, [
      { ...edge, data: { disabled: true } },
      { source: 'video-src', target: 'video-dst', sourceHandle: 'video', targetHandle: 'image' },
    ], 'video-1');
    expect(previews).toEqual([]);
  });

  it('de-duplicates repeated edges and preserves edge order', () => {
    const nodes = [
      ...graph({ url: '/static/manga/a.png' }),
      { id: 'image-2', type: 'image', data: { config: {}, result: { url: '/static/manga/b.png' } } },
    ];
    const previews = collectConnectedReferencePreviews(nodes, [
      edge,
      edge,
      { source: 'image-2', target: 'video-1', sourceHandle: 'image', targetHandle: 'image' },
    ], 'video-1');
    expect(previews.map((item) => item.url)).toEqual(['/static/manga/a.png', '/static/manga/b.png']);
  });
});

describe('collectConnectedReferencePreviews group expansion', () => {
  const groupEdge = { source: 'group-1', target: 'video-1', sourceHandle: 'assets', targetHandle: 'image' };

  it('expands a connected group into all image member thumbnails', () => {
    const nodes = [
      { id: 'img-a', type: 'image', data: { label: '形象', config: {}, result: { url: '/static/manga/char.png' } } },
      { id: 'img-b', type: 'asset', data: { label: '服装', config: {}, result: { url: '/static/manga/costume.png' } } },
      { id: 'clip', type: 'video_asset', data: { label: '动作', config: {}, result: { url: '/static/video/action.mp4' } } },
      { id: 'group-1', type: 'container', data: { label: '角色组', config: { member_ids: ['img-a', 'img-b', 'clip'] } } },
      { id: 'video-1', type: 'video', data: { config: {} } },
    ];
    const previews = collectConnectedReferencePreviews(nodes, [groupEdge], 'video-1');
    expect(previews.map((item) => item.url)).toEqual(['/static/manga/char.png', '/static/manga/costume.png']);
    expect(previews[0].label).toBe('形象');
  });

  it('expands nested groups and dedupes', () => {
    const nodes = [
      { id: 'img-a', type: 'image', data: { config: {}, result: { url: '/static/manga/a.png' } } },
      { id: 'inner', type: 'container', data: { config: { member_ids: ['img-a'] } } },
      { id: 'outer', type: 'container', data: { config: { member_ids: ['inner', 'img-a'] } } },
      { id: 'video-1', type: 'video', data: { config: {} } },
    ];
    const previews = collectConnectedReferencePreviews(
      nodes,
      [{ source: 'outer', target: 'video-1', sourceHandle: 'assets', targetHandle: 'image' }],
      'video-1',
    );
    expect(previews.map((item) => item.url)).toEqual(['/static/manga/a.png']);
  });

  it('survives membership cycles', () => {
    const nodes = [
      { id: 'g1', type: 'container', data: { config: { member_ids: ['g2'] } } },
      { id: 'g2', type: 'container', data: { config: { member_ids: ['g1'] } } },
      { id: 'video-1', type: 'video', data: { config: {} } },
    ];
    expect(() => collectConnectedReferencePreviews(
      nodes,
      [{ source: 'g1', target: 'video-1', sourceHandle: 'assets', targetHandle: 'image' }],
      'video-1',
    )).not.toThrow();
  });

  it('ignores disabled group edges', () => {
    const nodes = [
      { id: 'img-a', type: 'image', data: { config: {}, result: { url: '/static/manga/a.png' } } },
      { id: 'group-1', type: 'container', data: { config: { member_ids: ['img-a'] } } },
      { id: 'video-1', type: 'video', data: { config: {} } },
    ];
    const previews = collectConnectedReferencePreviews(
      nodes,
      [{ ...groupEdge, data: { disabled: true } }],
      'video-1',
    );
    expect(previews).toEqual([]);
  });
});
