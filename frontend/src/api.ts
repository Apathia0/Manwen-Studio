export interface CanvasContainerTab {
  title: string;
  color: string;
  nodes: string[];
}

export async function createNodeContainer(canvasId: number, payload: {
  name: string;
  node_ids: string[];
}): Promise<{ ok: boolean; container_id: string; tab_count: number; node_count: number }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/containers/create`, {
    method: 'POST', headers: apiHeaders(true), body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export interface VideoCanvasAssetAnalysisRequest {
  scene_node_id: string;
  expected_definition_revision?: number;
}

export interface CanvasSceneAsset {
  role: 'character' | 'scene' | 'prop';
  name: string;
  prompt: string;
  scene_ids: Array<string | number>;
  unit_count: number;
}

export async function analyzeCanvasAssets(canvasId: number, sceneNodeId: string, expectedDefinitionRevision?: number): Promise<{
  ok: boolean;
  scene_node_id: string;
  assets: CanvasSceneAsset[];
  warnings: string[];
  failed_calls: number;
  definition_revision: number;
}> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/asset-analysis`, {
    method: 'POST', headers: apiHeaders(true),
    body: JSON.stringify({ scene_node_id: sceneNodeId, ...(expectedDefinitionRevision ? { expected_definition_revision: expectedDefinitionRevision } : {}) }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export type VideoCanvasGraphEdgeData = { sequence?: number; unit_id?: string };
export type VideoCanvasNodeCatalogItem = {
  type: string;
  label: string;
  category: string;
  icon?: string;
  inputs: VideoCanvasPort[];
  outputs: VideoCanvasPort[];
  executable?: boolean;
};