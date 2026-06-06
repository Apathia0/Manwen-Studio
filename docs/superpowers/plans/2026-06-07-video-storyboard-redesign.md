# 视频工作流工作台重设计 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重新设计视频工作台：章节直拆分镜、分页分镜列表、内联资产卡片、资产继承、二级图片重绘工作台

**Architecture:** 新建 `VideoStoryboardLayout` + 4 个子组件，提取共享 `ImageRedrawModal` 消除 3 处重复代码，仅新增 1 个 API 端点其余全部复用。漫画工作台零改动。

**Tech Stack:** React + TypeScript, 复用现有 API 层 (api.ts), 复用现有 UI 风格 (Tailwind CSS)

---

## 文件结构总览

```
frontend/src/
├── components/
│   ├── shared/
│   │   └── ImageRedrawModal.tsx    ★新建★ 统一图片重绘工作台
│   │
│   ├── VideoStoryboardLayout.tsx   ★新建★ 主布局容器
│   ├── ChapterListPanel.tsx        ★新建★ 可收起章节列表
│   ├── VideoStoryboardPanel.tsx    ★新建★ 分页分镜列表+工具栏
│   ├── AssetReferenceSelector.tsx  ★新建★ 参考资产选择弹窗
│   │
│   ├── WorkspacePage.tsx           ✎修改  video→用新布局
│   ├── MangaPanel.tsx              ✎修改  导入共享ImageRedrawModal
│   ├── VideoCharacterLibrary.tsx   ✎修改  导入共享ImageRedrawModal
│   └── ShotFrameRegenerationModal.tsx 保留   旧分镜系统使用，不修改
│
└── api.ts                          ✎修改  新增POST章节分镜生成
```

---

### Task 1: 提取共享 ImageRedrawModal 组件

**Files:**
- Create: `frontend/src/components/shared/ImageRedrawModal.tsx`
- Modify: `frontend/src/components/MangaPanel.tsx`
- Modify: `frontend/src/components/VideoCharacterLibrary.tsx`

**说明：** 当前 `MangaPanel.tsx` 中有 `ImageRedrawModal`(L2290-2614) 和 `RefPreviewModal`(L2616-2700+)，`VideoCharacterLibrary.tsx` 中有 `ImageRedrawModal`(L431-750+)。三份代码的 Canvas 涂抹逻辑、模式切换、蒙版导出逻辑完全一致。提取为统一共享组件，消除重复。

- [ ] **Step 1: 创建共享组件文件**

在 `frontend/src/components/shared/ImageRedrawModal.tsx` 写入：

```tsx
import { useState, useEffect, useCallback, useRef } from 'react';
import { X, Loader2 } from 'lucide-react';
import { createPortal } from 'react-dom';
import { toast } from '../../lib/toast';
import type { ImageRedrawMode } from '../../api';

/** 通用的图片重绘弹窗 Props */
export interface ImageRedrawModalProps {
  /** 原图 URL */
  imageSrc: string;
  /** 弹窗标题 */
  title: string;
  /** 当前提示词 */
  prompt: string;
  /** 是否处理中 */
  busy: boolean;
  /** 关闭回调 */
  onClose: () => void;
  /** 提交重绘，payload 含 mode 和可选 mask(base64 png) */
  onSubmit: (payload: { prompt: string; mode: ImageRedrawMode; mask?: string }) => Promise<void>;
}

/**
 * 通用图片重绘工作台 (二级工作台)
 *
 * 支持「整图重绘」和「局部重绘」两种模式。
 * 局部模式下用户在左侧图片上使用画笔涂抹需要修改的区域，
 * 系统自动生成蒙版并提交。
 *
 * 被 MangaPanel、VideoCharacterLibrary、VideoStoryboardPanel 共用。
 */
export function ImageRedrawModal({
  imageSrc,
  title,
  prompt: initialPrompt,
  busy,
  onClose,
  onSubmit,
}: ImageRedrawModalProps) {
  const [mode, setMode] = useState<ImageRedrawMode>('full');
  const [prompt, setPrompt] = useState(initialPrompt);
  const [brushSize, setBrushSize] = useState(36);
  const [drawing, setDrawing] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const drawingRef = useRef(false);
  const lastPointRef = useRef<{ x: number; y: number } | null>(null);
  const [canvasReady, setCanvasReady] = useState(false);

  // 目标变化时重置
  useEffect(() => {
    setPrompt(initialPrompt);
    setMode('full');
    setImageLoaded(false);
    setCanvasReady(false);
  }, [initialPrompt, imageSrc]);

  // 同步 Canvas 尺寸
  const syncCanvasSize = useCallback(() => {
    const img = imageRef.current;
    const canvas = canvasRef.current;
    if (!img || !canvas) return;
    const rect = img.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) return;
    canvas.width = Math.round(rect.width);
    canvas.height = Math.round(rect.height);
    canvas.style.width = `${Math.round(rect.width)}px`;
    canvas.style.height = `${Math.round(rect.height)}px`;
    setCanvasReady(true);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(syncCanvasSize, 50);
    window.addEventListener('resize', syncCanvasSize);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener('resize', syncCanvasSize);
    };
  }, [syncCanvasSize]);

  useEffect(() => {
    if (mode !== 'partial') return;
    const timer = window.setTimeout(syncCanvasSize, 30);
    return () => window.clearTimeout(timer);
  }, [mode, imageSrc, syncCanvasSize]);

  // ── Canvas 绘制工具 ──────────────────────────────

  const drawAt = useCallback((x: number, y: number) => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;
    ctx.fillStyle = 'rgba(239, 68, 68, 0.45)';
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.beginPath();
    ctx.arc(x, y, brushSize / 2, 0, Math.PI * 2);
    ctx.fill();
  }, [brushSize]);

  const drawSegment = useCallback((from: { x: number; y: number }, to: { x: number; y: number }) => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;
    ctx.strokeStyle = 'rgba(239, 68, 68, 0.45)';
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.lineWidth = brushSize;
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x, to.y);
    ctx.stroke();
  }, [brushSize]);

  const getCanvasPoint = (event: any) => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };

  const stopDrawing = useCallback(() => {
    drawingRef.current = false;
    lastPointRef.current = null;
    setDrawing(false);
  }, []);

  const handlePointerDown = useCallback((event: React.PointerEvent<HTMLCanvasElement>) => {
    event.preventDefault();
    const point = getCanvasPoint(event);
    if (!point) return;
    drawingRef.current = true;
    lastPointRef.current = point;
    setDrawing(true);
    event.currentTarget.setPointerCapture(event.pointerId);
    drawAt(point.x, point.y);
  }, [drawAt]);

  const handlePointerMove = useCallback((event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawingRef.current) return;
    event.preventDefault();
    const point = getCanvasPoint(event);
    if (!point) return;
    if (lastPointRef.current) {
      drawSegment(lastPointRef.current, point);
    } else {
      drawAt(point.x, point.y);
    }
    lastPointRef.current = point;
  }, [drawAt, drawSegment]);

  const handlePointerUp = useCallback((event: React.PointerEvent<HTMLCanvasElement>) => {
    event.preventDefault();
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    stopDrawing();
  }, [stopDrawing]);

  // ── 蒙版导出 ──────────────────────────────────────

  const exportMask = useCallback(() => {
    const overlay = canvasRef.current;
    const img = imageRef.current;
    if (!overlay || !img || !canvasReady) return '';
    const raw = overlay.getContext('2d')?.getImageData(0, 0, overlay.width, overlay.height);
    if (!raw) return '';
    let hasPaint = false;
    for (let i = 3; i < raw.data.length; i += 4) {
      if (raw.data[i] > 10) { hasPaint = true; break; }
    }
    if (!hasPaint) return '';

    const maskCanvas = document.createElement('canvas');
    maskCanvas.width = overlay.width;
    maskCanvas.height = overlay.height;
    const maskCtx = maskCanvas.getContext('2d');
    if (!maskCtx) return '';
    maskCtx.fillStyle = 'rgba(255,255,255,1)';
    maskCtx.fillRect(0, 0, maskCanvas.width, maskCanvas.height);
    const maskData = maskCtx.getImageData(0, 0, maskCanvas.width, maskCanvas.height);
    for (let i = 0; i < raw.data.length; i += 4) {
      const alpha = raw.data[i + 3];
      maskData.data[i] = 255;
      maskData.data[i + 1] = 255;
      maskData.data[i + 2] = 255;
      maskData.data[i + 3] = alpha > 10 ? 0 : 255;
    }
    maskCtx.putImageData(maskData, 0, 0);

    if (img.naturalWidth && img.naturalHeight && (img.naturalWidth !== overlay.width || img.naturalHeight !== overlay.height)) {
      const scaledCanvas = document.createElement('canvas');
      scaledCanvas.width = img.naturalWidth;
      scaledCanvas.height = img.naturalHeight;
      const scaledCtx = scaledCanvas.getContext('2d');
      if (!scaledCtx) return maskCanvas.toDataURL('image/png');
      scaledCtx.drawImage(maskCanvas, 0, 0, scaledCanvas.width, scaledCanvas.height);
      return scaledCanvas.toDataURL('image/png');
    }
    return maskCanvas.toDataURL('image/png');
  }, [canvasReady]);

  // ── 渲染 ──────────────────────────────────────────

  const modal = (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-[rgba(15,23,42,0.62)] p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className="flex h-[88vh] w-[min(1400px,94vw)] flex-col overflow-hidden rounded-[30px] border border-[#d7e3f4] bg-white shadow-[0_30px_90px_rgba(15,23,42,0.28)]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 标题栏 */}
        <div className="flex items-center justify-between border-b border-[#e5edf8] px-6 py-4">
          <div>
            <div className="text-lg font-semibold text-slate-900">{title}</div>
            <div className="mt-1 text-sm text-slate-500">左侧查看和涂抹图片，右侧填写重绘说明并提交。</div>
          </div>
          <button onClick={onClose} className="rounded-full bg-slate-100 p-2 text-slate-600 transition hover:bg-slate-200">
            <X size={18} />
          </button>
        </div>

        <div className="grid flex-1 gap-0 overflow-hidden lg:grid-cols-[minmax(0,1.5fr)_420px]">
          {/* 左侧：图片显示区 */}
          <div className="overflow-auto bg-[linear-gradient(180deg,_#0f172a_0%,_#111827_100%)] p-6">
            <div className="mb-4 flex items-center justify-between text-white/80">
              <div className="text-sm font-medium">选中图片</div>
              <div className="text-xs">{mode === 'partial' ? '在左图直接涂抹需要修改的区域' : '整图将按右侧说明整体重绘'}</div>
            </div>
            <div className="mx-auto flex min-h-[62vh] w-full items-center justify-center rounded-[24px] border border-white/10 bg-black/20 p-4">
              <div className="relative inline-block">
                <img
                  ref={imageRef}
                  src={imageSrc}
                  alt={title}
                  onLoad={() => { setImageLoaded(true); syncCanvasSize(); }}
                  draggable={false}
                  loading="lazy"
                  decoding="async"
                  className={`block max-h-[72vh] max-w-full rounded-2xl object-contain shadow-2xl ${imageLoaded ? 'opacity-100' : 'opacity-0'}`}
                />
                {!imageLoaded && (
                  <div className="absolute inset-0 flex min-h-[420px] min-w-[320px] items-center justify-center rounded-2xl bg-[linear-gradient(180deg,_#08111d_0%,_#111827_100%)] text-white/70">
                    <Loader2 size={24} className="animate-spin" />
                  </div>
                )}
                {mode === 'partial' && (
                  <canvas
                    ref={canvasRef}
                    className={`absolute inset-0 h-full w-full rounded-2xl touch-none ${drawing ? 'cursor-grabbing' : 'cursor-crosshair'}`}
                    onPointerDown={handlePointerDown}
                    onPointerMove={handlePointerMove}
                    onPointerUp={handlePointerUp}
                    onPointerCancel={stopDrawing}
                    onLostPointerCapture={stopDrawing}
                  />
                )}
              </div>
            </div>
          </div>

          {/* 右侧：控制面板 */}
          <div className="overflow-auto border-l border-[#e5edf8] bg-[#f8fbff] p-6">
            <div className="space-y-5">
              <div>
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">重绘方式</div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setMode('full')}
                    className={`rounded-2xl px-3 py-2 text-sm transition ${mode === 'full' ? 'bg-[#1d4ed8] text-white' : 'bg-white text-slate-700 border border-[#d7e3f4]'}`}
                  >
                    整图重绘
                  </button>
                  <button
                    type="button"
                    onClick={() => setMode('partial')}
                    className={`rounded-2xl px-3 py-2 text-sm transition ${mode === 'partial' ? 'bg-[#1d4ed8] text-white' : 'bg-white text-slate-700 border border-[#d7e3f4]'}`}
                  >
                    局部重绘
                  </button>
                </div>
              </div>

              {mode === 'partial' && (
                <div className="rounded-2xl border border-[#d7e3f4] bg-white p-4">
                  <div className="text-sm font-medium text-slate-800">局部涂抹区域</div>
                  <div className="mt-1 text-xs leading-5 text-slate-500">在左侧图片上直接涂抹需要修改的区域，未涂抹部分会尽量保持不变。</div>
                  <div className="mt-3">
                    <div className="mb-1 flex items-center justify-between text-xs text-slate-500">
                      <span>画笔大小</span>
                      <span>{brushSize}px</span>
                    </div>
                    <input type="range" min={12} max={120} value={brushSize} onChange={(e) => setBrushSize(Number(e.target.value))} className="w-full" />
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      const canvas = canvasRef.current;
                      const ctx = canvas?.getContext('2d');
                      if (canvas && ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
                    }}
                    className="mt-3 rounded-xl border border-[#d7e3f4] bg-[#f8fbff] px-3 py-2 text-xs text-slate-700"
                  >
                    清空涂抹
                  </button>
                </div>
              )}

              <div>
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">修改提示</div>
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  rows={12}
                  className="w-full rounded-2xl border border-[#d7e3f4] bg-white px-3 py-3 text-sm text-slate-900 outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe]"
                  placeholder="描述你想调整的局部或整图效果…"
                />
              </div>

              <div className="flex gap-3">
                <button
                  type="button"
                  disabled={busy}
                  onClick={async () => {
                    const payload: { prompt: string; mode: ImageRedrawMode; mask?: string } = { prompt: prompt.trim(), mode };
                    if (mode === 'partial') {
                      const mask = exportMask();
                      if (!mask) {
                        toast.error('请先在左侧图片上涂抹需要修改的区域。');
                        return;
                      }
                      payload.mask = mask;
                    }
                    await onSubmit(payload);
                  }}
                  className="rounded-2xl bg-[#1d4ed8] px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
                >
                  {busy ? '处理中...' : '开始重绘'}
                </button>
                <button
                  type="button"
                  onClick={onClose}
                  className="rounded-2xl border border-[#d7e3f4] bg-white px-4 py-2 text-sm font-medium text-slate-700"
                >
                  取消
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(modal, document.body);
}
```

- [ ] **Step 2: 修改 MangaPanel.tsx — 替换内部 ImageRedrawModal 为共享导入**

在 `MangaPanel.tsx` 顶部导入区加入：
```typescript
import { ImageRedrawModal } from './shared/ImageRedrawModal';
```

删除 MangaPanel 内部的 `ImageRedrawModal` 函数定义（L2290-2614 整段），以及删除局部类型 `ImageEditTarget` (L71-85) 中与重绘无关的字段引用。`RefPreviewModal` 保留不动（它与漫画角色卡业务紧密耦合）。

需要在 L779 附近的 `handleApplyImageRedraw` 函数中调整调用方式，确保传给共享组件的数据格式匹配。共享组件 props 只需要 `imageSrc`, `title`, `prompt`, `busy`, `onClose`, `onSubmit`。

具体改动：MangaPanel 的 `imageEditTarget` 状态保留，用于存储当前打开重绘的目标信息。打开重绘时从 `imageEditTarget` 解构传给 `ImageRedrawModal`：

```typescript
// MangaPanel.tsx 中替换调用处 (约 L238~L260 区域)
{imageEditTarget && (
  <ImageRedrawModal
    imageSrc={imageEditTarget.imageSrc}
    title={imageEditTarget.title}
    prompt={imageEditTarget.prompt}
    busy={imageEditBusy}
    onClose={() => setImageEditTarget(null)}
    onSubmit={handleApplyImageRedraw}
  />
)}
```

`handleApplyImageRedraw` 中回调使用 `regenerateImage` 或 `redrawChapterRefImage` API（现有逻辑不变）。

- [ ] **Step 3: 修改 VideoCharacterLibrary.tsx — 替换内部 ImageRedrawModal 为共享导入**

在 `VideoCharacterLibrary.tsx` 顶部导入区加入：
```typescript
import { ImageRedrawModal } from './shared/ImageRedrawModal';
```

删除 VideoCharacterLibrary 内部的 `ImageRedrawModal` 函数定义（L431-750+ 整段）。

替换调用处：将原有的 `ImageRedrawModal` JSX 替换为共享组件：

```typescript
// VideoCharacterLibrary.tsx 中替换调用处
{redrawTarget && (
  <ImageRedrawModal
    imageSrc={redrawTarget.imageSrc}
    title={redrawTarget.title}
    prompt={redrawTarget.prompt}
    busy={redrawBusy}
    onClose={() => setRedrawTarget(null)}
    onSubmit={handleRedrawSubmit}
  />
)}
```

其中 `handleRedrawSubmit` 现有逻辑（使用 `regenerateVideoAsset`）保持不变。

- [ ] **Step 4: 验证 — 确认两个文件编译无错误**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -50`
Expected: 无新增类型错误。如果 MangaPanel 或 VideoCharacterLibrary 引用了旧的局部类型报错，修正即可。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/shared/ImageRedrawModal.tsx \
        frontend/src/components/MangaPanel.tsx \
        frontend/src/components/VideoCharacterLibrary.tsx
git commit -m "refactor: extract shared ImageRedrawModal, dedupe MangaPanel/VideoCharacterLibrary

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: 创建 ChapterListPanel 组件

**Files:**
- Create: `frontend/src/components/ChapterListPanel.tsx`

**说明：** 替代 FrameworkPanel 在视频工作台的位置。左侧面板，可展开/收起，显示章节序号+标题+分镜进度。收起时缩成窄条，展开时显示完整章节列表。

- [ ] **Step 1: 创建组件**

```tsx
import { ChevronLeft, ChevronRight, FileText } from 'lucide-react';
import type { Chapter } from '../api';

interface ChapterInfo {
  chapter: Chapter;
  shotCount: number;   // 该章已有分镜数，0 表示未分镜
  hasFrames: boolean;  // 是否已有首尾帧
}

interface ChapterListPanelProps {
  chapters: ChapterInfo[];
  selectedChapterId: number | null;
  collapsed: boolean;
  onSelect: (chapter: Chapter) => void;
  onToggleCollapse: () => void;
}

/**
 * 视频工作台左侧章节选择面板
 * 信息版：显示章节序号+标题+分镜进度状态
 * 折叠时仅显示展开按钮，释放主工作区空间
 */
export default function ChapterListPanel({
  chapters,
  selectedChapterId,
  collapsed,
  onSelect,
  onToggleCollapse,
}: ChapterListPanelProps) {
  if (collapsed) {
    return (
      <div className="w-10 shrink-0 flex flex-col items-center pt-4 border-r border-[#d7e3f4] bg-[rgba(255,255,255,0.92)]">
        <button
          onClick={onToggleCollapse}
          className="rounded-lg p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition"
          title="展开章节列表"
        >
          <ChevronRight size={18} />
        </button>
      </div>
    );
  }

  return (
    <div className="w-[280px] shrink-0 flex flex-col overflow-hidden rounded-[24px] border border-[#d7e3f4] bg-[rgba(255,255,255,0.92)] shadow-[0_18px_42px_rgba(59,130,246,0.12)] backdrop-blur-xl">
      {/* 标题栏 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#e5edf8]">
        <h3 className="text-sm font-semibold text-slate-900">章节选择</h3>
        <button
          onClick={onToggleCollapse}
          className="rounded-lg p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition"
          title="收起章节列表"
        >
          <ChevronLeft size={16} />
        </button>
      </div>

      {/* 列表 */}
      <div className="flex-1 overflow-y-auto py-2">
        {chapters.length === 0 ? (
          <div className="px-4 py-8 text-center text-xs text-slate-400">
            <FileText size={24} className="mx-auto mb-2 opacity-50" />
            暂无章节
          </div>
        ) : (
          chapters.map((info) => (
            <button
              key={info.chapter.id}
              onClick={() => onSelect(info.chapter)}
              className={`w-full text-left px-4 py-2.5 transition-colors ${
                selectedChapterId === info.chapter.id
                  ? 'bg-blue-50 border-r-2 border-[#2563eb]'
                  : 'hover:bg-slate-50 border-r-2 border-transparent'
              }`}
            >
              <div className="flex items-center gap-2">
                <span className={`text-sm font-medium ${
                  selectedChapterId === info.chapter.id ? 'text-[#2563eb]' : 'text-slate-800'
                }`}>
                  第{info.chapter.chapter_number}章
                </span>
                {info.shotCount > 0 && (
                  <span className="px-1.5 py-0.5 rounded bg-emerald-50 text-[10px] text-emerald-600 font-medium">
                    {info.shotCount}镜
                  </span>
                )}
                {info.hasFrames && (
                  <span className="text-[10px] text-emerald-500">✓</span>
                )}
              </div>
              {info.chapter.title && (
                <p className="mt-0.5 text-xs text-slate-500 truncate">{info.chapter.title}</p>
              )}
            </button>
          ))
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 验证编译**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | grep -i "ChapterListPanel" || echo "no errors for ChapterListPanel"`
Expected: 无类型错误

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/ChapterListPanel.tsx
git commit -m "feat: add ChapterListPanel for video workspace

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: 创建 AssetReferenceSelector 组件

**Files:**
- Create: `frontend/src/components/AssetReferenceSelector.tsx`

**说明：** 视频生成前选择参考资产的弹窗。支持预设模板 + 手动勾选。显示本章节所有可用资产。

- [ ] **Step 1: 创建组件**

```tsx
import { useState } from 'react';
import { X } from 'lucide-react';
import type { VideoAsset } from '../api';

interface AssetReferenceSelectorProps {
  /** 可用资产列表 (本章节+跨章角色库) */
  availableAssets: VideoAsset[];
  /** 当前已选资产 ID 集合 */
  selectedIds: number[];
  /** 确认回调 */
  onConfirm: (selectedIds: number[]) => void;
  /** 关闭回调 */
  onClose: () => void;
}

type PresetKey = 'first_frame_only' | 'first_frame_and_chars' | 'all' | 'custom';

const PRESETS: { key: PresetKey; label: string; description: string }[] = [
  { key: 'first_frame_only', label: '仅首帧', description: '仅使用该镜首帧图作为参考' },
  { key: 'first_frame_and_chars', label: '首帧+人物', description: '首帧图 + 所有出场人物图' },
  { key: 'all', label: '全部资产', description: '使用本章所有已生成资产' },
  { key: 'custom', label: '自定义', description: '手动勾选需要的资产' },
];

/** 通过资产类型识别文件名，便于展示 */
function assetLabel(a: VideoAsset): string {
  if (a.asset_type === 'character') return `👤 ${a.name}`;
  if (a.asset_type === 'scene' || a.asset_type === 'background') return `🏞 ${a.name}`;
  if (a.asset_type === 'first_frame') return `🖼 首帧-${a.name}`;
  if (a.asset_type === 'last_frame') return `🖼 尾帧-${a.name}`;
  if (a.asset_type === 'storyboard') return `🎬 ${a.name}`;
  return a.name;
}

/**
 * 参考资产选择弹窗
 *
 * 提供 4 种预设模板快速勾选 + 手动微调。
 * 用于分镜生成视频前指定哪些已生成资产作为参考。
 */
export default function AssetReferenceSelector({
  availableAssets,
  selectedIds,
  onConfirm,
  onClose,
}: AssetReferenceSelectorProps) {
  const [currentPreset, setCurrentPreset] = useState<PresetKey>(
    selectedIds.length === 0 ? 'first_frame_and_chars' : 'custom'
  );
  const [checked, setChecked] = useState<Set<number>>(new Set(selectedIds));

  const applyPreset = (key: PresetKey) => {
    setCurrentPreset(key);
    if (key === 'first_frame_only') {
      const ids = availableAssets.filter(a => a.asset_type === 'first_frame' && a.is_master).map(a => a.id);
      setChecked(new Set(ids));
    } else if (key === 'first_frame_and_chars') {
      const ids = availableAssets.filter(a =>
        (a.asset_type === 'first_frame' && a.is_master) || a.asset_type === 'character'
      ).map(a => a.id);
      setChecked(new Set(ids));
    } else if (key === 'all') {
      setChecked(new Set(availableAssets.map(a => a.id)));
    }
    // 'custom' 保持当前勾选不变
  };

  const toggle = (id: number) => {
    setChecked(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
    setCurrentPreset('custom');
  };

  const categorized = {
    storyboard: availableAssets.filter(a => a.asset_type === 'storyboard'),
    characters: availableAssets.filter(a => a.asset_type === 'character'),
    scene: availableAssets.filter(a => a.asset_type === 'scene' || a.asset_type === 'background'),
    frames: availableAssets.filter(a => a.asset_type === 'first_frame' || a.asset_type === 'last_frame'),
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[rgba(15,23,42,0.5)] p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-[min(640px,94vw)] max-h-[80vh] flex flex-col overflow-hidden rounded-2xl border border-[#d7e3f4] bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 标题栏 */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-[#e5edf8]">
          <div>
            <div className="text-base font-semibold text-slate-900">选择参考资产</div>
            <div className="text-xs text-slate-500">已选 {checked.size} 个资产</div>
          </div>
          <button onClick={onClose} className="rounded-full p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100">
            <X size={16} />
          </button>
        </div>

        {/* 预设模板 */}
        <div className="px-5 py-3 border-b border-[#e5edf8]">
          <div className="text-xs font-medium text-slate-500 mb-2">快速选择</div>
          <div className="flex flex-wrap gap-2">
            {PRESETS.map(p => (
              <button
                key={p.key}
                onClick={() => applyPreset(p.key)}
                className={`px-3 py-1.5 rounded-lg text-xs transition ${
                  currentPreset === p.key
                    ? 'bg-[#2563eb] text-white'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
                title={p.description}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* 资产列表 */}
        <div className="flex-1 overflow-y-auto px-5 py-3 space-y-4">
          {([
            ['分镜图', categorized.storyboard],
            ['人物图', categorized.characters],
            ['场景图', categorized.scene],
            ['首尾帧图', categorized.frames],
          ] as const).map(([label, items]) =>
            items.length > 0 && (
              <div key={label}>
                <div className="text-xs font-medium text-slate-500 mb-1.5">{label}</div>
                <div className="space-y-1">
                  {items.map(a => (
                    <label
                      key={a.id}
                      className={`flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition ${
                        checked.has(a.id) ? 'bg-blue-50' : 'hover:bg-slate-50'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked.has(a.id)}
                        onChange={() => toggle(a.id)}
                        className="rounded border-slate-300 text-[#2563eb] focus:ring-[#2563eb]"
                      />
                      <span className="text-xs text-slate-700">{assetLabel(a)}</span>
                      {a.is_master && (
                        <span className="px-1.5 py-0.5 rounded bg-blue-100 text-[9px] text-blue-600">主版</span>
                      )}
                    </label>
                  ))}
                </div>
              </div>
            )
          )}
          {availableAssets.length === 0 && (
            <div className="py-8 text-center text-xs text-slate-400">暂无可用资产，请先生成首尾帧或人物图</div>
          )}
        </div>

        {/* 底部按钮 */}
        <div className="flex justify-end gap-3 px-5 py-3 border-t border-[#e5edf8]">
          <button
            onClick={onClose}
            className="rounded-xl border border-[#d7e3f4] px-4 py-2 text-xs text-slate-600 hover:bg-slate-50"
          >
            取消
          </button>
          <button
            onClick={() => onConfirm(Array.from(checked))}
            className="rounded-xl bg-[#2563eb] px-4 py-2 text-xs text-white hover:bg-blue-700"
          >
            确认选择 ({checked.size})
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 验证编译**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | grep -i "AssetReferenceSelector" || echo "no errors"`
Expected: 无类型错误

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/AssetReferenceSelector.tsx
git commit -m "feat: add AssetReferenceSelector for video generation reference assets

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: 创建 VideoStoryboardPanel 组件 (核心)

**Files:**
- Create: `frontend/src/components/VideoStoryboardPanel.tsx`

**说明：** 这是视频工作台的核心组件。包含顶部工具栏（一键分镜/批量操作/勾选）+ 分页分镜列表。每个分镜行内联展示资产紧凑卡片。这是工作量最大的组件。

- [ ] **Step 1: 创建组件文件第一部分 — 类型定义与工具函数**

```tsx
import { useState, useMemo, useCallback } from 'react';
import { Loader2, ImageIcon, Film, CheckSquare, Square, ChevronLeft, ChevronRight, Trash2, Upload } from 'lucide-react';
import type { VideoShot, VideoAsset, ShotFramesResponse, EntitlementResponse } from '../api';
import {
  generateShotFrames,
  parseShotAssetPrompts,
  renderShotVideo,
  deleteVideoAsset,
  getShotFrames,
  regenerateShotFrame,
  type ShotAssetPromptDraft,
} from '../api';
import { ImageRedrawModal } from './shared/ImageRedrawModal';
import AssetReferenceSelector from './AssetReferenceSelector';
import { toast } from '../lib/toast';

// ── 类型定义 ──────────────────────────────────────────────

/** 增强的分镜数据，包含前端运行时状态 */
interface EnrichedShot extends VideoShot {
  /** AI 分析出的资产提示词 (undefined=未分析) */
  promptDraft?: ShotAssetPromptDraft;
  /** 首尾帧数据 (undefined=未生成) */
  frames?: ShotFramesResponse;
  /** 前端操作状态 */
  _analyzing?: boolean;
  _generatingFrame?: boolean;
  _generatingVideo?: boolean;
  _deletingAssetId?: number | null;
}

interface VideoStoryboardPanelProps {
  shots: EnrichedShot[];
  shotsLoading: boolean;
  generatingStoryboard: boolean;
  checkedShotIds: Set<number>;
  page: number;
  perPage: number;
  totalShots: number;
  entitlements?: EntitlementResponse | null;
  /** 本章节可用资产（用于 AssetReferenceSelector） */
  chapterAssets: VideoAsset[];
  onCheckToggle: (shotId: number) => void;
  onCheckAll: (checked: boolean) => void;
  onPageChange: (page: number) => void;
  onGenerateStoryboard: () => void;
  /** 批量分析提示词（仅勾选） */
  onBatchAnalyzePrompts: (shotIds: number[]) => Promise<void>;
  /** 批量生成首尾帧（仅勾选） */
  onBatchGenerateFrames: (shotIds: number[]) => Promise<void>;
  /** 单镜操作 */
  onShotsChange: (shots: EnrichedShot[]) => void;
  /** 生成视频 */
  onGenerateVideo: (shotId: number, referenceAssetIds: number[]) => Promise<void>;
}

/** 获取资产文件的展示 URL */
function toAssetUrl(filePath?: string | null): string {
  if (!filePath) return '';
  if (filePath.startsWith('http') || filePath.startsWith('/static/')) return filePath;
  return `/static/video/${filePath.replace(/\\/g, '/')}`;
}

/** 分页计算 */
function paginate<T>(items: T[], page: number, perPage: number): T[] {
  const start = (page - 1) * perPage;
  return items.slice(start, start + perPage);
}
```

- [ ] **Step 2: 创建组件文件第二部分 — 资产缩略卡片子组件**

```tsx
/** 资产缩略图操作按钮组 */
function AssetCard({
  asset,
  shotId,
  onView,
  onRedraw,
  onDelete,
  onReplace,
  deleting,
}: {
  asset: VideoAsset;
  shotId: number;
  onView: () => void;
  onRedraw: () => void;
  onDelete: (assetId: number) => void;
  onReplace: (assetId: number) => void;
  deleting: boolean;
}) {
  const url = toAssetUrl(asset.file_path);
  return (
    <div className="group relative w-16 h-16 shrink-0 rounded-lg overflow-hidden border border-slate-200 bg-slate-100">
      {url ? (
        <img
          src={url}
          alt={asset.name}
          className="w-full h-full object-cover cursor-pointer"
          onClick={onView}
          onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-slate-300">
          <ImageIcon size={20} />
        </div>
      )}
      {/* Hover 操作层 */}
      <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-1">
        <button onClick={onView} className="p-0.5 rounded bg-white/90 text-slate-700 hover:bg-white" title="查看">
          <ImageIcon size={11} />
        </button>
        <button onClick={onRedraw} className="p-0.5 rounded bg-white/90 text-blue-600 hover:bg-white" title="重绘">
          <Film size={11} />
        </button>
        <button
          onClick={() => onDelete(asset.id)}
          disabled={deleting}
          className="p-0.5 rounded bg-white/90 text-rose-600 hover:bg-white disabled:opacity-50"
          title="删除"
        >
          {deleting ? <Loader2 size={11} className="animate-spin" /> : <Trash2 size={11} />}
        </button>
        <button
          onClick={() => onReplace(asset.id)}
          className="p-0.5 rounded bg-white/90 text-amber-600 hover:bg-white"
          title="替换上传"
        >
          <Upload size={11} />
        </button>
      </div>
      {asset.is_master && (
        <span className="absolute top-0.5 left-0.5 px-1 rounded bg-blue-500 text-[7px] text-white">主</span>
      )}
    </div>
  );
}
```

- [ ] **Step 3: 创建组件文件第三部分 — 单个分镜行**

```tsx
/** 单行分镜 */
function ShotRow({
  shot,
  checked,
  index,
  chapterAssets,
  onCheckToggle,
  onViewAsset,
  onRedrawAsset,
  onDeleteAsset,
  onReplaceAsset,
  onGenerateVideo,
}: {
  shot: EnrichedShot;
  checked: boolean;
  index: number;
  chapterAssets: VideoAsset[];
  onCheckToggle: (id: number) => void;
  onViewAsset: (asset: VideoAsset) => void;
  onRedrawAsset: (asset: VideoAsset) => void;
  onDeleteAsset: (shotId: number, assetId: number) => void;
  onReplaceAsset: (shotId: number, assetId: number) => void;
  onGenerateVideo: (shotId: number) => void;
}) {
  const shotId = shot.id;
  const [refSelectorOpen, setRefSelectorOpen] = useState(false);
  const [selectedRefIds, setSelectedRefIds] = useState<number[]>([]);

  // 收集该镜已知的资产卡片
  const charAssets = useMemo(() => chapterAssets.filter(a =>
    a.shot_id === shotId && a.asset_type === 'character'
  ), [chapterAssets, shotId]);
  const sceneAssets = useMemo(() => chapterAssets.filter(a =>
    a.shot_id === shotId && (a.asset_type === 'scene' || a.asset_type === 'background')
  ), [chapterAssets, shotId]);
  const frameAssets = useMemo(() => chapterAssets.filter(a =>
    a.shot_id === shotId && (a.asset_type === 'first_frame' || a.asset_type === 'last_frame')
  ), [chapterAssets, shotId]);

  // AI 分析出的人物信息
  const characterNames = useMemo(() => {
    if (shot.promptDraft?.character_prompts) return shot.promptDraft.character_prompts.map(c => c.name);
    if (shot.character_involvement) {
      try { return JSON.parse(shot.character_involvement) as string[]; } catch { return [shot.character_involvement]; }
    }
    return [];
  }, [shot]);

  return (
    <div className={`rounded-xl border bg-white ${checked ? 'border-blue-300 ring-1 ring-blue-100' : 'border-[#d7e3f4]'}`}>
      <div className="flex items-center gap-3 p-3">
        {/* 复选框 */}
        <button onClick={() => onCheckToggle(shotId)} className="shrink-0 text-slate-400 hover:text-blue-600">
          {checked ? <CheckSquare size={18} className="text-blue-600" /> : <Square size={18} />}
        </button>

        {/* 分镜信息 */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-slate-900 whitespace-nowrap">分镜 {shot.shot_number}</span>
            <span className="text-sm text-slate-700 truncate">{shot.title}</span>
            <span className="hidden sm:inline text-xs text-slate-400">{shot.shot_type || 'medium'}</span>
          </div>
          <p className="text-xs text-slate-500 mt-0.5 line-clamp-1">{shot.action_description || '暂无描述'}</p>
        </div>

        {/* 操作区 */}
        <div className="shrink-0 flex items-center gap-1.5">
          {shot.promptDraft && (
            <span className="text-[10px] text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">提示词✓</span>
          )}
          {(frameAssets.length > 0) && (
            <span className="text-[10px] text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">帧图✓</span>
          )}
          <button
            onClick={() => setRefSelectorOpen(true)}
            className="rounded-lg border border-[#d7e3f4] px-2 py-1 text-xs text-slate-600 hover:bg-white"
          >
            参考资产
          </button>
          <button
            onClick={() => onGenerateVideo(shotId)}
            disabled={shot._generatingVideo}
            className="rounded-lg bg-[#2563eb] px-3 py-1 text-xs text-white disabled:opacity-60 flex items-center gap-1"
          >
            {shot._generatingVideo ? (
              <><Loader2 size={12} className="animate-spin" /> 生成中</>
            ) : (
              '生成视频'
            )}
          </button>
        </div>
      </div>

      {/* 资产紧凑卡片区 */}
      {(charAssets.length > 0 || sceneAssets.length > 0 || frameAssets.length > 0 || characterNames.length > 0) && (
        <div className="border-t border-[#e5edf8] px-3 py-2">
          <div className="flex flex-wrap items-center gap-3 text-xs">
            {/* AI 分析人物名（无图时显示） */}
            {characterNames.length > 0 && charAssets.length === 0 && (
              <div className="flex items-center gap-1 text-slate-500">
                <span className="font-medium">人物:</span>
                {characterNames.map((name, i) => (
                  <span key={i} className="px-1.5 py-0.5 rounded bg-slate-100 text-[10px]">{name}</span>
                ))}
              </div>
            )}
            {/* 人物资产图 */}
            {charAssets.map(a => (
              <div key={a.id} className="flex flex-col items-center gap-0.5">
                <AssetCard
                  asset={a}
                  shotId={shotId}
                  onView={() => onViewAsset(a)}
                  onRedraw={() => onRedrawAsset(a)}
                  onDelete={(assetId) => onDeleteAsset(shotId, assetId)}
                  onReplace={(assetId) => onReplaceAsset(shotId, assetId)}
                  deleting={shot._deletingAssetId === a.id}
                />
                <span className="text-[9px] text-slate-500 truncate max-w-[64px]">{a.name}</span>
              </div>
            ))}
            {/* 场景资产图 */}
            {sceneAssets.map(a => (
              <div key={a.id} className="flex flex-col items-center gap-0.5">
                <AssetCard
                  asset={a}
                  shotId={shotId}
                  onView={() => onViewAsset(a)}
                  onRedraw={() => onRedrawAsset(a)}
                  onDelete={(assetId) => onDeleteAsset(shotId, assetId)}
                  onReplace={(assetId) => onReplaceAsset(shotId, assetId)}
                  deleting={shot._deletingAssetId === a.id}
                />
                <span className="text-[9px] text-slate-500 truncate max-w-[64px]">{a.name}</span>
              </div>
            ))}
            {/* 首尾帧图 */}
            {frameAssets.map(a => (
              <div key={a.id} className="flex flex-col items-center gap-0.5">
                <AssetCard
                  asset={a}
                  shotId={shotId}
                  onView={() => onViewAsset(a)}
                  onRedraw={() => onRedrawAsset(a)}
                  onDelete={(assetId) => onDeleteAsset(shotId, assetId)}
                  onReplace={(assetId) => onReplaceAsset(shotId, assetId)}
                  deleting={shot._deletingAssetId === a.id}
                />
                <span className="text-[9px] text-slate-500">{a.asset_type === 'first_frame' ? '首帧' : '尾帧'}</span>
              </div>
            ))}
            {shot._generatingFrame && (
              <div className="flex items-center gap-1 text-blue-600">
                <Loader2 size={12} className="animate-spin" />
                <span className="text-[10px]">生成帧中...</span>
              </div>
            )}
            {shot._analyzing && (
              <div className="flex items-center gap-1 text-violet-600">
                <Loader2 size={12} className="animate-spin" />
                <span className="text-[10px]">分析提示词...</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 参考资产选择弹窗 */}
      {refSelectorOpen && (
        <AssetReferenceSelector
          availableAssets={chapterAssets}
          selectedIds={selectedRefIds}
          onConfirm={(ids) => {
            setSelectedRefIds(ids);
            setRefSelectorOpen(false);
          }}
          onClose={() => setRefSelectorOpen(false)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 4: 创建组件文件第四部分 — 主面板组件**

```tsx
/** 视频分镜面板 — 工具栏 + 分页列表 + 图片重绘 */
export default function VideoStoryboardPanel({
  shots,
  shotsLoading,
  generatingStoryboard,
  checkedShotIds,
  page,
  perPage,
  totalShots,
  chapterAssets,
  onCheckToggle,
  onCheckAll,
  onPageChange,
  onGenerateStoryboard,
  onBatchAnalyzePrompts,
  onBatchGenerateFrames,
  onShotsChange,
  onGenerateVideo,
}: VideoStoryboardPanelProps) {
  const [redrawTarget, setRedrawTarget] = useState<{ asset: VideoAsset; shotId: number } | null>(null);
  const [redrawBusy, setRedrawBusy] = useState(false);
  const [viewImage, setViewImage] = useState<string | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null);

  const totalPages = Math.max(1, Math.ceil(totalShots / perPage));
  const pageShots = paginate(shots, page, perPage);
  const allChecked = pageShots.length > 0 && pageShots.every(s => checkedShotIds.has(s.id));

  // ── 资产操作 ──────────────────────────────────────

  const handleViewAsset = useCallback((asset: VideoAsset) => {
    setViewImage(toAssetUrl(asset.file_path));
  }, []);

  const handleRedrawAsset = useCallback((asset: VideoAsset) => {
    setRedrawTarget({ asset, shotId: asset.shot_id || 0 });
  }, []);

  const handleDeleteAsset = useCallback(async (shotId: number, assetId: number) => {
    if (deleteConfirmId === assetId) {
      try {
        await deleteVideoAsset(assetId);
        toast.success('资产已删除');
        // 从本地状态移除
        onShotsChange(shots.map(s => {
          if (s.id === shotId) {
            const newFrames = s.frames ? {
              ...s.frames,
              first_frames: s.frames.first_frames.filter(f => f.id !== assetId),
              last_frames: s.frames.last_frames.filter(f => f.id !== assetId),
            } : undefined;
            return { ...s, frames: newFrames, _deletingAssetId: null };
          }
          return s;
        }));
        setDeleteConfirmId(null);
      } catch (err: any) {
        toast.error(`删除失败: ${err.message}`);
      }
    } else {
      setDeleteConfirmId(assetId);
      setTimeout(() => setDeleteConfirmId(prev => prev === assetId ? null : prev), 3000);
    }
  }, [deleteConfirmId, shots, onShotsChange]);

  const handleReplaceAsset = useCallback(async (shotId: number, assetId: number) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/png,image/jpeg,image/webp';
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      const formData = new FormData();
      formData.append('file', file);
      try {
        const res = await fetch(`/api/video/assets/${assetId}/replace`, {
          method: 'POST',
          body: formData,
        });
        if (!res.ok) throw new Error(await res.text());
        toast.success('资产图已替换');
        // 刷新该镜资产（通过重新获取帧）
        if (shotId) {
          const frames = await getShotFrames(shotId);
          onShotsChange(shots.map(s => s.id === shotId ? { ...s, frames } : s));
        }
      } catch (err: any) {
        toast.error(`替换失败: ${err.message}`);
      }
    };
    input.click();
  }, [shots, onShotsChange]);

  const handleRedrawSubmit = useCallback(async (payload: { prompt: string; mode: 'full' | 'partial'; mask?: string }) => {
    if (!redrawTarget) return;
    setRedrawBusy(true);
    try {
      await regenerateShotFrame(redrawTarget.shotId, {
        asset_id: redrawTarget.asset.id,
        prompt: payload.prompt,
        mode: payload.mode,
        mask: payload.mask || null,
      });
      toast.success('重绘完成');
      // 刷新帧数据
      if (redrawTarget.shotId) {
        const frames = await getShotFrames(redrawTarget.shotId);
        onShotsChange(shots.map(s => s.id === redrawTarget.shotId ? { ...s, frames } : s));
      }
      setRedrawTarget(null);
    } catch (err: any) {
      toast.error(`重绘失败: ${err.message}`);
    } finally {
      setRedrawBusy(false);
    }
  }, [redrawTarget, shots, onShotsChange]);

  const handleGenerateVideo = useCallback(async (shotId: number) => {
    const shot = shots.find(s => s.id === shotId);
    if (!shot) return;
    // 从 selectedRefIds 获取参考资产，这里通过闭包从 ShotRow 传入
    // 实际在 ShotRow 中管理 refIds 并调用 onGenerateVideo
    await onGenerateVideo(shotId, []);
  }, [shots, onGenerateVideo]);

  // ── 渲染 ──────────────────────────────────────────

  // 空状态：未选择章节或未生成分镜
  if (!shotsLoading && shots.length === 0 && !generatingStoryboard) {
    return (
      <div className="flex flex-col h-full">
        {/* 工具栏 */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#d7e3f4]">
          <span className="text-sm font-medium text-slate-900">分镜列表</span>
          <button
            onClick={onGenerateStoryboard}
            className="rounded-xl bg-[#2563eb] px-4 py-2 text-sm text-white hover:bg-blue-700 transition"
          >
            一键分镜
          </button>
        </div>
        {/* 空状态引导 */}
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center text-slate-400">
            <Film size={48} className="mx-auto mb-3 opacity-30" />
            <p className="text-sm">点击顶部「一键分镜」将本章拆分为分镜</p>
            <p className="text-xs mt-1">AI 将自动分析每镜出场人物、场景和镜头类型</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* 工具栏 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#d7e3f4] bg-white/80 backdrop-blur">
        <div className="flex items-center gap-3">
          <button onClick={() => onCheckAll(!allChecked)} className="text-slate-400 hover:text-blue-600" title="全选/取消">
            {allChecked ? <CheckSquare size={18} className="text-blue-600" /> : <Square size={18} />}
          </button>
          <span className="text-sm font-medium text-slate-900">
            分镜列表
            {checkedShotIds.size > 0 && (
              <span className="ml-1 text-xs text-blue-600">(已选 {checkedShotIds.size} 镜)</span>
            )}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onGenerateStoryboard}
            disabled={generatingStoryboard}
            className="rounded-lg border border-[#d7e3f4] px-3 py-1.5 text-xs text-slate-600 hover:bg-white disabled:opacity-60"
          >
            {generatingStoryboard ? (
              <span className="flex items-center gap-1"><Loader2 size={12} className="animate-spin" /> 拆分中</span>
            ) : shots.length > 0 ? '重新分镜' : '一键分镜'}
          </button>
          <button
            onClick={() => onBatchAnalyzePrompts(Array.from(checkedShotIds))}
            disabled={checkedShotIds.size === 0}
            className="rounded-lg bg-violet-600 px-3 py-1.5 text-xs text-white disabled:opacity-40"
          >
            批量分析提示词
          </button>
          <button
            onClick={() => onBatchGenerateFrames(Array.from(checkedShotIds))}
            disabled={checkedShotIds.size === 0}
            className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs text-white disabled:opacity-40"
          >
            批量生成首尾帧
          </button>
        </div>
      </div>

      {/* 加载状态 */}
      {shotsLoading && (
        <div className="flex-1 flex items-center justify-center">
          <Loader2 size={24} className="animate-spin text-slate-400" />
        </div>
      )}

      {/* 分镜列表 */}
      {!shotsLoading && (
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
          {pageShots.map((shot, idx) => (
            <ShotRow
              key={shot.id}
              shot={shot}
              checked={checkedShotIds.has(shot.id)}
              index={(page - 1) * perPage + idx}
              chapterAssets={chapterAssets}
              onCheckToggle={onCheckToggle}
              onViewAsset={handleViewAsset}
              onRedrawAsset={handleRedrawAsset}
              onDeleteAsset={handleDeleteAsset}
              onReplaceAsset={handleReplaceAsset}
              onGenerateVideo={handleGenerateVideo}
            />
          ))}
        </div>
      )}

      {/* 底部分页控件 */}
      {!shotsLoading && totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 px-4 py-3 border-t border-[#d7e3f4]">
          <button
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1}
            className="p-1 rounded text-slate-400 hover:text-slate-700 disabled:opacity-30"
          >
            <ChevronLeft size={16} />
          </button>
          <span className="text-xs text-slate-600">
            {page} / {totalPages}
          </span>
          <input
            type="number"
            min={1}
            max={totalPages}
            value={page}
            onChange={(e) => {
              const v = Number(e.target.value);
              if (v >= 1 && v <= totalPages) onPageChange(v);
            }}
            className="w-12 text-center rounded border border-[#d7e3f4] text-xs py-1"
          />
          <button
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages}
            className="p-1 rounded text-slate-400 hover:text-slate-700 disabled:opacity-30"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}

      {/* 全屏图片查看 */}
      {viewImage && (
        <div
          className="fixed inset-0 z-[65] bg-black/80 flex items-center justify-center cursor-zoom-out"
          onClick={() => setViewImage(null)}
        >
          <img src={viewImage} alt="预览" className="max-h-[90vh] max-w-[90vw] object-contain rounded-xl shadow-2xl" />
        </div>
      )}

      {/* 二级重绘工作台 */}
      {redrawTarget && (
        <ImageRedrawModal
          imageSrc={toAssetUrl(redrawTarget.asset.file_path)}
          title={`${redrawTarget.asset.name} 重绘`}
          prompt={redrawTarget.asset.prompt || ''}
          busy={redrawBusy}
          onClose={() => setRedrawTarget(null)}
          onSubmit={handleRedrawSubmit}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 5: 验证编译**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -60`
Expected: 无类型错误。如有类型不匹配，根据实际 api.ts 中的函数签名微调。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/VideoStoryboardPanel.tsx
git commit -m "feat: add VideoStoryboardPanel with paginated shot list and asset cards

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: 创建 VideoStoryboardLayout 主布局

**Files:**
- Create: `frontend/src/components/VideoStoryboardLayout.tsx`

**说明：** 替代 VideoWorkspaceLayout 的顶层布局组件。组合 ChapterListPanel + VideoStoryboardPanel，管理全局状态（章节选择、分镜数据、资产列表、勾选集合）。

- [ ] **Step 1: 创建主布局组件**

```tsx
import { useCallback, useEffect, useState, useMemo } from 'react';
import {
  type Story,
  type Chapter,
  type EntitlementResponse,
  apiHeaders,
  listVideoAssets,
  getShotFrames,
} from '../api';
import ChapterListPanel from './ChapterListPanel';
import VideoStoryboardPanel, { type EnrichedShot } from './VideoStoryboardPanel';
import { toast } from '../lib/toast';

interface Props {
  story: Story;
  chapters: Chapter[];
  currentChapter: Chapter | null;
  entitlements?: EntitlementResponse | null;
  onChapterChange: (chapter: Chapter) => void;
  onContentUpdated: () => void | Promise<void>;
}

const SHOTS_PER_PAGE = 10;

/**
 * 视频分镜工作台主布局
 *
 * 左：ChapterListPanel (可收起)
 * 右：VideoStoryboardPanel (分页分镜列表)
 */
export default function VideoStoryboardLayout({
  story,
  chapters,
  currentChapter,
  entitlements,
  onChapterChange,
  onContentUpdated,
}: Props) {
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [shots, setShots] = useState<EnrichedShot[]>([]);
  const [shotsLoading, setShotsLoading] = useState(false);
  const [generatingStoryboard, setGeneratingStoryboard] = useState(false);
  const [checkedShotIds, setCheckedShotIds] = useState<Set<number>>(new Set());
  const [page, setPage] = useState(1);
  const [chapterAssets, setChapterAssets] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  const resolvedChapter = currentChapter;

  // ── 章节切换时重置 ────────────────────────────

  useEffect(() => {
    if (!resolvedChapter?.id) return;
    setShots([]);
    setPage(1);
    setCheckedShotIds(new Set());
    setError(null);
    loadExistingShots(resolvedChapter.id);
    loadChapterAssets(resolvedChapter.id);
  }, [resolvedChapter?.id]);

  // ── 加载已有分镜 ──────────────────────────────

  async function loadExistingShots(chapterId: number) {
    setShotsLoading(true);
    try {
      const res = await fetch(`/api/chapters/${chapterId}/storyboard`, {
        headers: apiHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        // 尝试加载每镜的帧数据
        const enriched: EnrichedShot[] = await Promise.all(
          (data.shots || []).map(async (shot: any) => {
            try {
              const frames = await getShotFrames(shot.id);
              return { ...shot, frames };
            } catch {
              return { ...shot };
            }
          })
        );
        setShots(enriched);
      }
      // 404 = 还没生成过分镜，正常
    } catch (err) {
      // 静默处理
    } finally {
      setShotsLoading(false);
    }
  }

  async function loadChapterAssets(chapterId: number) {
    try {
      const res = await listVideoAssets(chapterId);
      setChapterAssets(res.assets || []);
    } catch {
      setChapterAssets([]);
    }
  }

  // ── 章节列表信息 ──────────────────────────────

  const chapterInfos = useMemo(() => chapters.map(ch => ({
    chapter: ch,
    shotCount: ch.id === resolvedChapter?.id ? shots.length : 0, // 简化，实际可查
    hasFrames: ch.id === resolvedChapter?.id ? shots.some(s => s.frames?.first_frames?.length) : false,
  })), [chapters, resolvedChapter, shots]);

  // ── 一键分镜 ──────────────────────────────────

  const handleGenerateStoryboard = useCallback(async () => {
    if (!resolvedChapter?.id) return;
    setGeneratingStoryboard(true);
    setError(null);
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 150_000);

      const res = await fetch(`/api/chapters/${resolvedChapter.id}/storyboard/generate`, {
        method: 'POST',
        headers: apiHeaders(true),
        body: JSON.stringify({}),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setShots(data.shots || []);
      setPage(1);
      setCheckedShotIds(new Set());
      toast.success(`已生成 ${data.shots.length} 个分镜`);
    } catch (err: any) {
      const msg = err.name === 'AbortError' ? '一键分镜超时 (150s)，请重试' : err.message;
      setError(msg);
      toast.error(msg);
    } finally {
      setGeneratingStoryboard(false);
    }
  }, [resolvedChapter?.id]);

  // ── 批量分析提示词 ────────────────────────────

  const handleBatchAnalyzePrompts = useCallback(async (shotIds: number[]) => {
    if (shotIds.length === 0) return;
    toast.info(`开始分析 ${shotIds.length} 个分镜的提示词...`);

    // 标记为分析中
    setShots(prev => prev.map(s => shotIds.includes(s.id) ? { ...s, _analyzing: true } : s));

    let successCount = 0;
    const maxConcurrent = 3;

    const processShot = async (shotId: number) => {
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 150_000);
          const draft = await parseShotAssetPrompts(shotId);
          clearTimeout(timeoutId);
          setShots(prev => prev.map(s => s.id === shotId ? { ...s, promptDraft: draft, _analyzing: false } : s));
          successCount++;
          return;
        } catch (err) {
          if (attempt === 2) {
            setShots(prev => prev.map(s => s.id === shotId ? { ...s, _analyzing: false } : s));
            throw err;
          }
          await new Promise(r => setTimeout(r, 2000 * (attempt + 1)));
        }
      }
    };

    // 并发控制
    const queue = [...shotIds];
    const workers = Array.from({ length: maxConcurrent }, async () => {
      while (queue.length > 0) {
        const id = queue.shift()!;
        try { await processShot(id); } catch { /* 单镜失败已标记 */ }
      }
    });
    await Promise.all(workers);

    if (successCount < shotIds.length) {
      toast.warning(`${successCount}/${shotIds.length} 个分镜分析成功，${shotIds.length - successCount} 个失败`);
    } else {
      toast.success(`${successCount} 个分镜提示词分析完成`);
    }
  }, []);

  // ── 批量生成首尾帧 ────────────────────────────

  const handleBatchGenerateFrames = useCallback(async (shotIds: number[]) => {
    if (shotIds.length === 0) return;
    toast.info(`开始生成 ${shotIds.length} 个分镜的首尾帧...`);

    setShots(prev => prev.map(s => shotIds.includes(s.id) ? { ...s, _generatingFrame: true } : s));

    let successCount = 0;
    const maxConcurrent = 3;

    const processShot = async (shotId: number) => {
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 150_000);
          const frames = await generateShotFrames(shotId, {
            frame_type: 'both',
            inherit_character_assets: true,
            inherit_scene_assets: true,
            inherit_storyboard_asset: true,
          });
          clearTimeout(timeoutId);
          setShots(prev => prev.map(s => s.id === shotId ? { ...s, frames, _generatingFrame: false } : s));
          successCount++;
          return;
        } catch (err) {
          if (attempt === 2) {
            setShots(prev => prev.map(s => s.id === shotId ? { ...s, _generatingFrame: false } : s));
            throw err;
          }
          await new Promise(r => setTimeout(r, 2000 * (attempt + 1)));
        }
      }
    };

    const queue = [...shotIds];
    const workers = Array.from({ length: maxConcurrent }, async () => {
      while (queue.length > 0) {
        const id = queue.shift()!;
        try { await processShot(id); } catch { /* 单镜失败 */ }
      }
    });
    await Promise.all(workers);

    // 刷新资产列表
    if (resolvedChapter?.id) await loadChapterAssets(resolvedChapter.id);

    if (successCount < shotIds.length) {
      toast.warning(`${successCount}/${shotIds.length} 首尾帧生成成功`);
    } else {
      toast.success('全部首尾帧生成完成');
    }
  }, [resolvedChapter?.id]);

  // ── 生成视频 ───────────────────────────────────

  const handleGenerateVideo = useCallback(async (shotId: number, referenceAssetIds: number[]) => {
    setShots(prev => prev.map(s => s.id === shotId ? { ...s, _generatingVideo: true } : s));
    try {
      await renderShotVideo(shotId, {
        reference_asset_ids: referenceAssetIds.length > 0 ? referenceAssetIds : undefined,
      });
      toast.success('视频生成已提交');
    } catch (err: any) {
      toast.error(`视频生成失败: ${err.message}`);
    } finally {
      setShots(prev => prev.map(s => s.id === shotId ? { ...s, _generatingVideo: false } : s));
    }
  }, []);

  // ── 勾选操作 ──────────────────────────────────

  const handleCheckToggle = useCallback((shotId: number) => {
    setCheckedShotIds(prev => {
      const next = new Set(prev);
      if (next.has(shotId)) next.delete(shotId); else next.add(shotId);
      return next;
    });
  }, []);

  const handleCheckAll = useCallback((checked: boolean) => {
    if (checked) {
      const start = (page - 1) * SHOTS_PER_PAGE;
      const pageIds = shots.slice(start, start + SHOTS_PER_PAGE).map(s => s.id);
      setCheckedShotIds(prev => new Set([...prev, ...pageIds]));
    } else {
      const start = (page - 1) * SHOTS_PER_PAGE;
      const pageIds = new Set(shots.slice(start, start + SHOTS_PER_PAGE).map(s => s.id));
      setCheckedShotIds(prev => new Set([...prev].filter(id => !pageIds.has(id))));
    }
  }, [page, shots]);

  // ── 渲染 ───────────────────────────────────────

  if (!story) {
    return (
      <div className="flex h-full items-center justify-center text-slate-400">
        <p className="text-sm">请先在「作品」页面选择一个项目再进入工作台。</p>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 gap-4 bg-[linear-gradient(180deg,_#f4f8ff_0%,_#eef4ff_100%)] p-4">
      {/* 左侧章节列表 */}
      <ChapterListPanel
        chapters={chapterInfos}
        selectedChapterId={resolvedChapter?.id ?? null}
        collapsed={leftCollapsed}
        onSelect={(ch) => {
          onChapterChange(ch);
          setPage(1);
          setCheckedShotIds(new Set());
        }}
        onToggleCollapse={() => setLeftCollapsed(v => !v)}
      />

      {/* 主工作区 */}
      <div className="flex-1 min-w-0 overflow-hidden rounded-[24px] border border-[#d7e3f4] bg-[rgba(255,255,255,0.92)] shadow-[0_18px_42px_rgba(59,130,246,0.12)] backdrop-blur-xl">
        {/* Error banner */}
        {error && (
          <div className="flex items-center justify-between px-4 py-2 bg-rose-50 border-b border-rose-200 text-sm text-rose-700">
            <span>{error}</span>
            <button onClick={() => setError(null)} className="text-rose-400 hover:text-rose-600">✕</button>
          </div>
        )}

        <VideoStoryboardPanel
          shots={shots}
          shotsLoading={shotsLoading}
          generatingStoryboard={generatingStoryboard}
          checkedShotIds={checkedShotIds}
          page={page}
          perPage={SHOTS_PER_PAGE}
          totalShots={shots.length}
          chapterAssets={chapterAssets}
          entitlements={entitlements}
          onCheckToggle={handleCheckToggle}
          onCheckAll={handleCheckAll}
          onPageChange={setPage}
          onGenerateStoryboard={handleGenerateStoryboard}
          onBatchAnalyzePrompts={handleBatchAnalyzePrompts}
          onBatchGenerateFrames={handleBatchGenerateFrames}
          onShotsChange={(newShots) => setShots(newShots)}
          onGenerateVideo={handleGenerateVideo}
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 更新 VideoStoryboardPanel 导出** — 确保 `EnrichedShot` 类型被导出

在 `VideoStoryboardPanel.tsx` 末尾确认带 `export`：
```typescript
export type { EnrichedShot };
```

- [ ] **Step 3: 验证编译**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -80`
Expected: 无类型错误

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/VideoStoryboardLayout.tsx \
        frontend/src/components/VideoStoryboardPanel.tsx
git commit -m "feat: add VideoStoryboardLayout main video workspace

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: 修改 WorkspacePage 接入新布局

**Files:**
- Modify: `frontend/src/components/WorkspacePage.tsx`

**说明：** 将 `WorkspacePage` 中的 video 分支从 `VideoWorkspaceLayout` 切换到 `VideoStoryboardLayout`。

- [ ] **Step 1: 修改导入和渲染**

在 `WorkspacePage.tsx` 中：
```typescript
// 替换导入
- import VideoWorkspaceLayout from './VideoWorkspaceLayout';
+ import VideoStoryboardLayout from './VideoStoryboardLayout';

// 替换条件渲染
- <VideoWorkspaceLayout
+ <VideoStoryboardLayout
    story={story}
    chapters={chapters}
    currentChapter={currentChapter}
    entitlements={entitlements}
    onChapterChange={onChapterChange}
    onContentUpdated={onContentUpdated}
  />
```

- [ ] **Step 2: 验证编译**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | grep -iE "WorkspacePage|VideoStoryboardLayout" | head -20`
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/WorkspacePage.tsx
git commit -m "feat: route video workspace to new VideoStoryboardLayout

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: 新增章节分镜生成 API

**Files:**
- Modify: `frontend/src/api.ts`

**说明：** 在 api.ts 中新增章节级分镜生成 API 函数（对应后端 `POST /api/chapters/{chapter_id}/storyboard/generate`）。

- [ ] **Step 1: 在 api.ts 中添加 API 函数**

在 `api.ts` 中（例如靠近其他 storyboard 相关函数的位置，约 L2755 附近）添加：

```typescript
/** 章节一键分镜 — 将整章拆分为分镜并 AI 分析资产 */
export async function generateChapterStoryboard(
  chapterId: number,
  payload?: {
    shot_count_hint?: number;
    style_preset?: string;
  }
): Promise<{ shots: VideoShot[]; total_count: number }> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/storyboard/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload || {}),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
```

- [ ] **Step 2: 更新 VideoStoryboardLayout 导入**

在 `VideoStoryboardLayout.tsx` 中将 fetch 调用改为使用新的 API 函数：
```typescript
import { generateChapterStoryboard, ... } from '../api';

// 替换 handleGenerateStoryboard 中的 fetch 调用
const data = await generateChapterStoryboard(resolvedChapter.id, {});
```

- [ ] **Step 3: 验证编译**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | grep -E "generateChapterStoryboard|error" | head -10`
Expected: 无错误

- [ ] **Step 4: 提交**

```bash
git add frontend/src/api.ts frontend/src/components/VideoStoryboardLayout.tsx
git commit -m "feat: add chapter-level storyboard generation API

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: 集成测试与验证

**Files:** 无需新建，验证所有改动

- [ ] **Step 1: TypeScript 编译检查**

```bash
cd frontend && npx tsc --noEmit --pretty 2>&1
```
Expected: 零类型错误

- [ ] **Step 2: 运行前端开发服务器**

```bash
cd frontend && npm run dev
```
检查：
- 视频工作台页面正常加载
- 左侧章节列表可展开/收起
- 切换章节正常工作
- 一键分镜按钮可见
- 漫画工作台功能完全正常（MangaPanel 导入共享组件后无变化）

- [ ] **Step 3: 检查漫画工作台回归**

- 打开漫画/小说工作台
- 点击漫画格放大 → 重绘弹窗正常工作
- 局部涂抹/整图重绘功能正常
- 角色参考图重绘正常

- [ ] **Step 4: 提交**

```bash
git add -A
git commit -m "chore: integration verification for video storyboard redesign

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 任务依赖图

```
Task 1 (提取共享 ImageRedrawModal)
  └──→ Task 2 (ChapterListPanel - 独立)
  └──→ Task 3 (AssetReferenceSelector - 独立)
  └──→ Task 4 (VideoStoryboardPanel - 依赖 Task 1, Task 3)
         └──→ Task 5 (VideoStoryboardLayout - 依赖 Task 2, Task 4)
                └──→ Task 6 (WorkspacePage 接入 - 依赖 Task 5)
                       └──→ Task 7 (API 函数 - 依赖 Task 5)
                              └──→ Task 8 (集成验证 - 依赖全部)
```

Task 2 和 Task 3 可并行执行。Task 7 可与 Task 4-6 并行。
