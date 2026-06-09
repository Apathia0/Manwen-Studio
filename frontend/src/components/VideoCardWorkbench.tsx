import { useState, useEffect, useCallback } from 'react';
import { ChevronLeft, ChevronRight, RotateCcw, Upload, Trash2, Wand2, X } from 'lucide-react';
import { ImageRedrawModal } from './shared/ImageRedrawModal';

interface VideoCardWorkbenchProps {
  type: 'character' | 'storyboard' | 'video';
  shotId: number;
  assetId?: number;
  resources: Array<{ id: number; url: string; prompt?: string }>;
  onClose: () => void;
}

interface WorkbenchState {
  currentIndex: number;
  zoomLevel: 1 | 1.35 | 1.7;
  isRedrawModalOpen: boolean;
  editingPrompt: string;
}

export default function VideoCardWorkbench({ type, shotId, assetId, resources, onClose }: VideoCardWorkbenchProps) {
  const [state, setState] = useState<WorkbenchState>({
    currentIndex: Math.max(0, resources.findIndex(r => r.id === assetId)),
    zoomLevel: 1,
    isRedrawModalOpen: false,
    editingPrompt: '',
  });

  const { currentIndex } = state;

  // 导航函数
  const handlePrev = useCallback(() => {
    setState(s => ({
      ...s,
      currentIndex: s.currentIndex > 0 ? s.currentIndex - 1 : resources.length - 1,
      editingPrompt: resources[s.currentIndex > 0 ? s.currentIndex - 1 : resources.length - 1]?.prompt || '',
    }));
  }, [resources]);

  const handleNext = useCallback(() => {
    setState(s => ({
      ...s,
      currentIndex: s.currentIndex < resources.length - 1 ? s.currentIndex + 1 : 0,
      editingPrompt: resources[s.currentIndex < resources.length - 1 ? s.currentIndex + 1 : 0]?.prompt || '',
    }));
  }, [resources]);

  // 键盘快捷键处理
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    switch (e.key) {
      case 'Escape':
        onClose();
        break;
      case 'ArrowLeft':
        handlePrev();
        break;
      case 'ArrowRight':
        handleNext();
        break;
      case '+':
      case '=':
        setState(s => ({ ...s, zoomLevel: s.zoomLevel < 1.7 ? (s.zoomLevel === 1 ? 1.35 : 1.7) : 1 }));
        break;
      case '-':
        setState(s => ({ ...s, zoomLevel: s.zoomLevel > 1 ? (s.zoomLevel === 1.7 ? 1.35 : 1) : 1 }));
        break;
      case 'r':
      case 'R':
        setState(s => ({ ...s, isRedrawModalOpen: true }));
        break;
    }
  }, [onClose, handlePrev, handleNext]);

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[linear-gradient(180deg,_#0b1220_0%,_#111827_100%)]">
      {/* 顶部栏 */}
      <div className="flex items-center justify-between border-b border-white/10 px-5 py-4 text-white">
        <button onClick={onClose} className="flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm hover:bg-white/10">
          <ChevronLeft size={16} /> 返回工作台
        </button>
        <div className="text-sm font-medium">
          镜头 {shotId} · {type === 'character' ? '角色资产' : type === 'storyboard' ? '故事版' : '视频'}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setState(s => ({ ...s, zoomLevel: 1 }))} className={`rounded-lg px-2 py-1 text-xs ${state.zoomLevel === 1 ? 'bg-white/20' : 'hover:bg-white/10'}`}>100%</button>
          <button onClick={() => setState(s => ({ ...s, zoomLevel: 1.35 }))} className={`rounded-lg px-2 py-1 text-xs ${state.zoomLevel === 1.35 ? 'bg-white/20' : 'hover:bg-white/10'}`}>135%</button>
          <button onClick={() => setState(s => ({ ...s, zoomLevel: 1.7 }))} className={`rounded-lg px-2 py-1 text-xs ${state.zoomLevel === 1.7 ? 'bg-white/20' : 'hover:bg-white/10'}`}>170%</button>
          <button onClick={onClose} className="ml-2 rounded-lg p-1.5 hover:bg-white/10">
            <X size={16} />
          </button>
        </div>
      </div>

      {/* 预览区域 */}
      <div className="flex flex-1 items-center justify-between gap-3 overflow-hidden px-4 py-4">
        <button onClick={handlePrev} disabled={resources.length <= 1} className="rounded-full bg-white/10 p-2 text-white hover:bg-white/20 disabled:opacity-50">
          <ChevronLeft size={20} />
        </button>
        <div className="flex-1 h-full overflow-auto rounded-[24px] bg-black/20 px-4 py-5">
          {resources[currentIndex]?.url ? (
            <img
              src={resources[currentIndex].url}
              alt="预览"
              className="mx-auto h-auto max-h-full object-contain rounded-xl shadow-2xl"
              style={{ transform: `scale(${state.zoomLevel})` }}
            />
          ) : (
            <div className="mx-auto h-full flex items-center justify-center text-white/50">
              暂无内容
            </div>
          )}
        </div>
        <button onClick={handleNext} disabled={resources.length <= 1} className="rounded-full bg-white/10 p-2 text-white hover:bg-white/20 disabled:opacity-50">
          <ChevronRight size={20} />
        </button>
      </div>

      {/* 底部操作栏 */}
      <div className="border-t border-white/10 px-5 py-4">
        <div className="flex flex-wrap gap-2">
          <button className="flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700">
            <RotateCcw size={12} /> 重新生成
          </button>
          <button className="flex items-center gap-2 rounded-lg border border-white/20 px-3 py-1.5 text-xs text-white hover:bg-white/10">
            <Upload size={12} /> 上传替换
          </button>
          <button className="flex items-center gap-2 rounded-lg border border-white/20 px-3 py-1.5 text-xs text-white hover:bg-white/10">
            <Trash2 size={12} /> 删除
          </button>
          <button className="flex items-center gap-2 rounded-lg border border-white/20 px-3 py-1.5 text-xs text-white hover:bg-white/10">
            <Wand2 size={12} /> 重绘
          </button>
        </div>
      </div>

      {/* 重绘弹窗 */}
      {state.isRedrawModalOpen && (
        <ImageRedrawModal
          title="重绘图片"
          imageSrc=""
          prompt={state.editingPrompt}
          busy={false}
          onClose={() => setState(s => ({ ...s, isRedrawModalOpen: false }))}
          onSubmit={async (payload) => {
            setState(s => ({ ...s, isRedrawModalOpen: false }));
            console.log('重绘提交', payload);
          }}
        />
      )}
    </div>
  );
}
