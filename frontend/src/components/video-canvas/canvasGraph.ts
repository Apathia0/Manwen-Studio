import type { VideoCanvasGraph } from '../../api';

export const PUBLIC_CANVAS_NODE_TYPES = new Set(['text', 'screenplay', 'scene', 'image', 'video', 'audio', 'container', 'concat']);

function projectLegacyNode(node: VideoCanvasGraph['nodes'][number]): VideoCanvasGraph['nodes'][number] {
  if (PUBLIC_CANVAS_NODE_TYPES.has(node.type)) return node;
  const legacyConfig = node.data.config || {};
  const isVideo = node.type === 'video_generation' || node.type === 'video_asset' || node.type === 'concat';
  const isImage = node.type === 'image_generation' || node.type === 'storyboard' || node.type === 'asset';
  const type = isVideo ? 'video' : isImage ? 'image' : 'text';
  const textParts = [legacyConfig.content, legacyConfig.story_summary, legacyConfig.dialogue, legacyConfig.camera_plan, legacyConfig.motion_plan, legacyConfig.storyboard_prompt, legacyConfig.video_prompt].filter((value) => String(value || '').trim());
  const config = type === 'text'
    ? { ...legacyConfig, content: textParts.join('\n\n') }
    : { ...legacyConfig, prompt: String(legacyConfig.prompt || legacyConfig.storyboard_prompt || legacyConfig.video_prompt || '') };
  return { ...node, type, data: { ...node.data, label: node.data.label || (type === 'text' ? '文本' : type === 'image' ? '图片' : '视频'), config } };
}

export function projectLegacyGraph(graph: VideoCanvasGraph): VideoCanvasGraph {
  const nodes = graph.nodes.map((node) => projectLegacyNode(node) as VideoCanvasGraph['nodes'][number]);
  const nodeIds = new Set(nodes.map((node) => node.id));
  const nodeTypeById = new Map(nodes.map((node) => [node.id, node.type]));
  const originalTypes = new Map(graph.nodes.map(node => [node.id, node.type]));
  const edges = graph.edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target)).map((edge) => {
    const targetType = nodeTypeById.get(edge.target);
    const sourceType = nodeTypeById.get(edge.source);
    const targetHandle = targetType === 'text' ? 'source' : targetType === 'screenplay' ? 'source' : targetType === 'scene' ? 'screenplay' : targetType === 'video' && edge.targetHandle === 'image' ? 'image' : targetType === 'image' && edge.targetHandle === 'references' ? 'references' : 'prompt';
    const sourceHandle = sourceType === 'text' ? 'text' : sourceType === 'screenplay' ? 'screenplay' : sourceType === 'scene' ? 'shot' : sourceType === 'image' ? 'image' : 'video';
    return { ...edge, sourceHandle: PUBLIC_CANVAS_NODE_TYPES.has(originalTypes.get(edge.source) || '') ? edge.sourceHandle : sourceHandle, targetHandle: PUBLIC_CANVAS_NODE_TYPES.has(originalTypes.get(edge.target) || '') ? edge.targetHandle : targetHandle };
  });
  return { ...graph, nodes, edges };
}
