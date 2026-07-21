import { useState, useEffect, useCallback, useRef } from 'react';
import { X, Loader2 } from 'lucide-react';
import { createPortal } from 'react-dom';
import { toast } from '../../lib/toast';
import type { ImageRedrawMode } from '../../api';
import ImageZoomView from './ImageZoomView';

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
  /** 覆盖层级，供嵌套弹窗中的二级工作台使用 */
  zIndexClassName?: string;
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
  zIndexClassName = 'z-[70]',
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

  // Canvas 绘制工具

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

  // 蒙版导出

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

  // 渲染

  const modal = (
    <div className={`fixed inset-0 ${zIndexClassName} flex items-center justify-center bg-[rgba(15,23,42,0.62)] p-4 backdrop-blur-sm`} onClick={onClose}>
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
            <div className="mx-auto flex h-[62vh] w-full items-center justify-center rounded-[24px] border border-white/10 bg-black/20 p-4">
              {mode === 'full' ? (
                <ImageZoomView
                  src={imageSrc}
                  alt={title}
                  className="h-full w-full rounded-2xl"
                />
              ) : (
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
                  <canvas
                    ref={canvasRef}
                    className={`absolute inset-0 h-full w-full rounded-2xl touch-none ${drawing ? 'cursor-grabbing' : 'cursor-crosshair'}`}
                    onPointerDown={handlePointerDown}
                    onPointerMove={handlePointerMove}
                    onPointerUp={handlePointerUp}
                    onPointerCancel={stopDrawing}
                    onLostPointerCapture={stopDrawing}
                  />
                </div>
              )}
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
