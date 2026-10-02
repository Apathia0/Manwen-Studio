/**
 * 判断节点是否应打开通用属性面板（CanvasNodePropertyPanel）。
 * 有专用内联 UI 的节点（剧本、场景审核、容器、合片）必须排除，
 * 否则点击节点会弹出不相干的图片/视频生成输入框。
 */
const INSPECTOR_EXCLUDED_TYPES = new Set(['container', 'concat', 'screenplay', 'scene']);

export function supportsNodeInspector(type: string): boolean {
  return !INSPECTOR_EXCLUDED_TYPES.has(type);
}
