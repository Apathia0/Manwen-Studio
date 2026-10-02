import { Box, CircleHelp, Compass, FileText, Focus, Group, Hand, ImagePlus, LayoutTemplate, MousePointer2, Redo2, Type, Undo2, Video, Volume2, ZoomIn, ZoomOut } from 'lucide-react';
import type { ReactNode } from 'react';
import type { CanvasTool } from './useCanvasInteractions';

interface Props {
  scale: number;
  onScaleChange: (scale: number) => void;
  onReset: () => void;
  onFit: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onAutoLayout: () => void;
  onOpenAssetManagement: () => void;
  onGroup?: () => void;
  canGroup?: boolean;
  onToggleMiniMap?: () => void;
  miniMapOpen?: boolean;
  isAssetManagementDisabled?: boolean;
  /** 资产面板是否打开，以及是否有待处理项（未生成或缺引用） */
  assetPanelOpen?: boolean;
  assetAlert?: boolean;
  supportsAudio?: boolean;
  onTool: (tool: CanvasTool | 'help') => void;
  activeTool?: CanvasTool;
  onAddNode?: (type: string) => void;
}

function ToolButton({ title, onClick, active, disabled, children }: { title: string; onClick: () => void; active?: boolean; disabled?: boolean; children: ReactNode }) {
  return <button type="button" title={title} aria-label={title} disabled={disabled} onClick={onClick} className={`flex h-9 w-9 items-center justify-center rounded-lg transition-colors disabled:cursor-not-allowed disabled:opacity-30 ${active ? 'bg-[#423e3a] text-white' : 'text-[#948d87] hover:bg-[#35312e] hover:text-[#eee9e4]'}`}>{children}</button>;
}

export default function CanvasBottomToolbar({ scale, onScaleChange, onReset, onFit, onUndo, onRedo, onAutoLayout, onOpenAssetManagement, onGroup, canGroup = false, onToggleMiniMap, miniMapOpen = false, isAssetManagementDisabled = false, assetPanelOpen = false, assetAlert = false, supportsAudio = false, onTool, activeTool = 'select', onAddNode }: Props) {
  const chooseTool = (tool: CanvasTool) => { onTool(tool); };
  const addNode = (type: string) => { if (onAddNode) { onAddNode(type); } else { onTool(type as CanvasTool); } };
  return <>
    <div className="pointer-events-auto absolute bottom-[calc(.75rem+var(--safe-area-bottom))] left-3 z-40 flex h-12 items-center gap-0.5 rounded-2xl border border-[#393633] bg-[#211f1d]/95 px-1.5 shadow-[0_12px_30px_rgba(0,0,0,.32)] backdrop-blur-xl">
      <ToolButton title="缩小" onClick={() => onScaleChange(Math.max(0.1, scale / 1.15))}><ZoomOut className="h-4 w-4" /></ToolButton>
      <button type="button" title="点击重置视图（100%）" onClick={onReset} className="min-w-[46px] rounded-md px-1 py-1.5 text-center text-xs text-[#bcb5ae] hover:bg-[#35312e] hover:text-white">{Math.round(scale * 100)}%</button>
      <ToolButton title="放大" onClick={() => onScaleChange(Math.min(5, scale * 1.15))}><ZoomIn className="h-4 w-4" /></ToolButton>
      <div className="mx-1 h-5 w-px bg-[#403c38]" />
      <ToolButton title="适配窗口" onClick={onFit}><Focus className="h-4 w-4" /></ToolButton>
      <ToolButton title={miniMapOpen ? '关闭小地图' : '打开小地图'} active={miniMapOpen} onClick={() => onToggleMiniMap?.()}><Compass className="h-4 w-4" /></ToolButton>
      <ToolButton title="帮助" onClick={() => onTool('help')}><CircleHelp className="h-4 w-4" /></ToolButton>
    </div>
    <div className="pointer-events-auto absolute left-3 top-1/2 z-40 flex max-h-[calc(100%-9rem)] w-12 -translate-y-1/2 flex-col items-center gap-0.5 overflow-y-auto rounded-2xl border border-[#393633] bg-[#211f1d]/95 py-2 shadow-[0_12px_30px_rgba(0,0,0,.32)] backdrop-blur-xl">
      <ToolButton title="选择工具" active={activeTool === 'select'} onClick={() => chooseTool('select')}><MousePointer2 className="h-4 w-4" /></ToolButton>
      <ToolButton title="抓取/平移画布" active={activeTool === 'pan'} onClick={() => chooseTool('pan')}><Hand className="h-4 w-4" /></ToolButton>
      <ToolButton title="撤销" onClick={onUndo}><Undo2 className="h-4 w-4" /></ToolButton>
      <ToolButton title="重做" onClick={onRedo}><Redo2 className="h-4 w-4" /></ToolButton>
      <span className="my-1 h-px w-6 shrink-0 bg-[#403c38]" />
      <ToolButton title="添加剧本节点" onClick={() => addNode('screenplay')}><FileText className="h-4 w-4" /></ToolButton>
      <ToolButton title="添加文字节点" onClick={() => addNode('text')}><Type className="h-4 w-4" /></ToolButton>
      <ToolButton title="添加图片节点" onClick={() => addNode('image')}><ImagePlus className="h-4 w-4" /></ToolButton>
      <ToolButton title="添加视频节点" onClick={() => addNode('video')}><Video className="h-4 w-4" /></ToolButton>
      <ToolButton title={supportsAudio ? '添加音频节点' : '当前工作流暂不支持音频节点'} disabled={!supportsAudio} onClick={() => addNode('audio')}><Volume2 className="h-4 w-4" /></ToolButton>
      <ToolButton title="自动整理画布" onClick={onAutoLayout}><LayoutTemplate className="h-4 w-4" /></ToolButton>
      <ToolButton title="框选成组（Ctrl+G）" disabled={!canGroup} onClick={() => onGroup?.()}><Group className="h-4 w-4" /></ToolButton>
      <span className="relative"><ToolButton title="资产：角色 / 场景 / 道具" active={assetPanelOpen} disabled={isAssetManagementDisabled} onClick={onOpenAssetManagement}><Box className="h-4 w-4" /></ToolButton>{assetAlert && <span className="pointer-events-none absolute right-1 top-1 h-2 w-2 rounded-full bg-amber-400" />}</span>
    </div>
  </>;
}
