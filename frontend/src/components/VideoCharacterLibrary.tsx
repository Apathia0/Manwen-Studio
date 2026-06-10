import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  listVideoCharacters,
  generateVideoCharacters,
  createCharacterVersion,
  deleteCharacterVersion,
  generateCharacterRefImage,
  deleteVideoCharacterRefImage,
  redrawCharacterRefImage,
  type VideoCharacter,
  type CharacterVersion,
  type ImageRedrawMode,
} from '../api';
import { ChevronLeft, ChevronRight, X, Loader2 } from 'lucide-react';
import { confirm } from '../lib/confirm';
import { toast } from '../lib/toast';

interface Props {
  storyId: number;
}

export default function VideoCharacterLibrary({ storyId }: Props) {
  const [characters, setCharacters] = useState<VideoCharacter[]>([]);
  const [selectedName, setSelectedName] = useState<string>('');
  const [selectedVersion, setSelectedVersion] = useState<CharacterVersion | null>(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genRefLoading, setGenRefLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingCard, setEditingCard] = useState<string>('');
  const [newVersionLabel, setNewVersionLabel] = useState('');
  const [showNewVersion, setShowNewVersion] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [stylePresets, setStylePresets] = useState<Array<{ id: number; name: string; category: string }>>([]);
  const [selectedStyle, setSelectedStyle] = useState<string>('');
  const [previewOpen, setPreviewOpen] = useState(false);
  const [lightboxZoom, setLightboxZoom] = useState<1 | 1.35 | 1.7>(1.35);
  const [redrawTarget, setRedrawTarget] = useState<{ imageSrc: string; prompt: string; title: string } | null>(null);
  const [redrawBusy, setRedrawBusy] = useState(false);

  const loadStyles = useCallback(async () => {
    try {
      const res = await fetch('/api/video-style-presets', { headers: { 'Content-Type': 'application/json' } });
      const data = await res.json();
      setStylePresets(data.presets || []);
    } catch {}
  }, []);

  useEffect(() => { void loadStyles(); }, [loadStyles]);

  const loadCharacters = useCallback(async () => {
    if (!storyId) return;
    setLoading(true);
    try {
      const data = await listVideoCharacters(storyId);
      setCharacters(data.characters || []);
      setError(null);
    } catch (err: any) {
      if (!String(err.message || '').includes('404')) setError(err.message || '加载角色库失败');
    } finally {
      setLoading(false);
    }
  }, [storyId]);

  useEffect(() => { void loadCharacters(); }, [loadCharacters]);

  useEffect(() => {
    if (characters.length && !selectedName) {
      setSelectedName(characters[0].name);
    }
    const current = characters.find(c => c.name === selectedName);
    if (current) {
      const dv = current.versions.find(v => v.is_default) || current.versions[0];
      setSelectedVersion(dv || null);
      setEditingCard(dv?.appearance_card || '');
    }
  }, [characters, selectedName]);

  const handleGenerateAll = async () => {
    setGenerating(true);
    try {
      const data = await generateVideoCharacters(storyId);
      setCharacters(data.characters || []);
    } catch (err: any) {
      setError(err.message || '生成角色卡失败');
    } finally {
      setGenerating(false);
    }
  };

  const handleSaveVersion = async () => {
    if (!selectedVersion || !selectedName) return;
    try {
      const { version } = await createCharacterVersion(storyId, selectedName, {
        version_label: selectedVersion.label,
        appearance_card: editingCard,
        set_default: selectedVersion.is_default,
      });
      await loadCharacters();
      setSelectedVersion(version);
    } catch (err: any) {
      setError(err.message || '保存失败');
    }
  };

  const handleCreateVersion = async () => {
    if (!selectedName || !newVersionLabel.trim()) return;
    try {
      await createCharacterVersion(storyId, selectedName, {
        version_label: newVersionLabel.trim(),
        appearance_card: editingCard,
        set_default: false,
      });
      setNewVersionLabel('');
      setShowNewVersion(false);
      await loadCharacters();
    } catch (err: any) {
      setError(err.message || '创建版本失败');
    }
  };

  const handleDeleteVersion = async (versionId: number) => {
    if (!(await confirm({ message: '确认删除此版本？' }))) return;
    try {
      await deleteCharacterVersion(storyId, selectedName, versionId);
      await loadCharacters();
    } catch (err: any) {
      setError(err.message || '删除失败');
    }
  };

  const handleSetDefault = async (version: CharacterVersion) => {
    try {
      await createCharacterVersion(storyId, selectedName, {
        version_label: version.label,
        appearance_card: version.appearance_card,
        set_default: true,
      });
      await loadCharacters();
    } catch (err: any) {
      setError(err.message || '设置默认版本失败');
    }
  };

  const handleGenerateRef = async () => {
    if (!selectedVersion || !selectedName) return;
    setGenRefLoading(true);
    try {
      await generateCharacterRefImage(storyId, selectedName, selectedVersion.id, selectedStyle || undefined);
      await loadCharacters();
    } catch (err: any) {
      setError(err.message || '生成参考图失败');
    } finally {
      setGenRefLoading(false);
    }
  };

  const handleDeleteRef = async () => {
    if (!selectedVersion || !selectedName) return;
    if (!(await confirm({ message: '确认删除当前版本的参考图？' }))) return;
    try {
      await deleteVideoCharacterRefImage(storyId, selectedName, selectedVersion.id);
      await loadCharacters();
    } catch (err: any) {
      setError(err.message || '删除参考图失败');
    }
  };

  const handleRedrawSubmit = async (payload: { prompt: string; mode: ImageRedrawMode; mask?: string }) => {
    if (!selectedVersion || !selectedName) return;
    setRedrawBusy(true);
    try {
      await redrawCharacterRefImage(storyId, selectedName, selectedVersion.id, payload);
      setRedrawTarget(null);
      setPreviewOpen(false);
      await loadCharacters();
    } catch (err: any) {
      setError(err.message || '重绘参考图失败');
    } finally {
      setRedrawBusy(false);
    }
  };

  const char = characters.find(c => c.name === selectedName);
  const versions = char?.versions || [];

  return (
    <div className="flex h-full min-h-[400px] gap-0 relative">
      {/* 可折叠角色列表侧边栏 */}
      <div className={`${sidebarOpen ? 'w-[120px]' : 'w-0'} shrink-0 overflow-hidden transition-all duration-200 border-r border-[#d7e3f4]`}>
        <div className="p-2 space-y-1">
          <button
            onClick={handleGenerateAll}
            disabled={generating}
            className="w-full rounded-lg bg-[#2563eb] px-2 py-1.5 text-xs font-medium text-white hover:bg-[#1d4ed8] disabled:opacity-50"
          >
            {generating ? '生成中...' : '生成全部'}
          </button>
          {characters.map(c => (
            <button
              key={c.name}
              onClick={() => { setSelectedName(c.name); setEditingCard(c.versions.find(v => v.is_default)?.appearance_card || ''); }}
              className={`w-full rounded-lg px-2 py-1.5 text-left text-xs transition ${
                selectedName === c.name ? 'bg-[#e0ecff] text-[#1d4ed8] font-medium' : 'text-slate-600 hover:bg-slate-50'
              }`}
            >
              {c.versions.some(v => v.is_default && v.ref_asset_id) ? '★ ' : ''}{c.name}
            </button>
          ))}
          {!characters.length && !loading && (
            <div className="text-[11px] text-slate-400 px-1">暂无角色</div>
          )}
        </div>
      </div>

      <button
        onClick={() => setSidebarOpen(!sidebarOpen)}
        className="absolute -left-1 top-1/2 -translate-y-1/2 z-10 flex h-6 w-4 items-center justify-center rounded-r bg-[#d7e3f4] text-slate-500 hover:bg-[#93c5fd] hover:text-[#1d4ed8] transition"
      >
        {sidebarOpen ? <ChevronLeft size={10} /> : <ChevronRight size={10} />}
      </button>

      {/* 主区域 */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-3">
        {selectedName ? (
          <>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-slate-800">{selectedName}</span>
              </div>
              <div className="flex flex-wrap gap-1">
                {versions.map(v => (
                  <button
                    key={v.id}
                    onClick={() => { setSelectedVersion(v); setEditingCard(v.appearance_card); }}
                    className={`rounded-full px-2 py-0.5 text-[11px] transition ${
                      selectedVersion?.id === v.id
                        ? 'bg-[#2563eb] text-white'
                        : v.is_default
                        ? 'border border-[#93c5fd] bg-[#eff6ff] text-[#1d4ed8]'
                        : 'border border-[#d7e3f4] bg-white text-slate-500 hover:border-[#93c5fd]'
                    }`}
                  >
                    {v.label}{v.is_default ? ' 默认' : ''}
                  </button>
                ))}
                <button
                  onClick={() => setShowNewVersion(!showNewVersion)}
                  className="rounded-full border border-dashed border-[#93c5fd] px-2 py-0.5 text-[11px] text-[#1d4ed8] hover:bg-[#eff6ff]"
                >
                  +
                </button>
              </div>
              {showNewVersion && (
                <div className="flex gap-1 rounded border border-[#d7e3f4] p-1.5">
                  <input value={newVersionLabel} onChange={e => setNewVersionLabel(e.target.value)} placeholder="版本标签" className="flex-1 rounded border border-[#d7e3f4] px-2 py-1 text-[11px]" />
                  <button onClick={handleCreateVersion} disabled={!newVersionLabel.trim()} className="rounded bg-[#2563eb] px-2 py-1 text-[11px] text-white hover:bg-[#1d4ed8] disabled:opacity-50">确定</button>
                </div>
              )}
              <div className="flex flex-wrap gap-1.5">
                <button onClick={handleSaveVersion} className="rounded bg-[#2563eb] px-2.5 py-1 text-[11px] text-white hover:bg-[#1d4ed8]">保存</button>
                <button onClick={handleGenerateRef} disabled={genRefLoading || !editingCard.trim()} className="rounded border border-[#2563eb] px-2.5 py-1 text-[11px] text-[#2563eb] hover:bg-[#eff6ff] disabled:opacity-50">
                  {genRefLoading ? '生成中...' : '生成参考图'}
                </button>
                {selectedVersion && (
                  <button onClick={() => handleSetDefault(selectedVersion)} disabled={selectedVersion.is_default}
                    className="rounded border border-[#d7e3f4] px-2.5 py-1 text-[11px] text-slate-500 hover:text-[#1d4ed8] disabled:opacity-30">设默认</button>
                )}
                {versions.length > 1 && selectedVersion && (
                  <button onClick={() => handleDeleteVersion(selectedVersion.id)}
                    className="rounded border border-[#d7e3f4] px-2.5 py-1 text-[11px] text-rose-500 hover:bg-rose-50">删除</button>
                )}
              </div>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-[11px] text-slate-400 shrink-0">风格</span>
              <select value={selectedStyle} onChange={e => setSelectedStyle(e.target.value)}
                className="flex-1 rounded border border-[#d7e3f4] px-2 py-1 text-[11px] text-slate-600 bg-white"
              >
                <option value="">默认风格</option>
                {stylePresets.map(p => (
                  <option key={p.id} value={p.name}>{p.name} ({p.category})</option>
                ))}
              </select>
            </div>

            <textarea
              value={editingCard}
              onChange={e => setEditingCard(e.target.value)}
              className="h-36 w-full rounded-lg border border-[#d7e3f4] p-3 text-xs leading-relaxed resize-y focus:border-[#93c5fd] focus:outline-none"
              placeholder="编辑角色外貌卡..."
            />

            {selectedVersion?.ref_asset_url ? (
              <div className="space-y-1">
                <div className="text-[11px] text-slate-400 font-medium">参考图预览</div>
                <div className="relative group w-32 h-32">
                  <img
                    src={selectedVersion.ref_asset_url}
                    alt={selectedName}
                    className="w-32 h-32 rounded-lg border border-[#d7e3f4] object-cover cursor-pointer"
                    loading="lazy"
                    decoding="async"
                    onClick={() => setPreviewOpen(true)}
                  />
                  {/* hover 遮罩 */}
                  <div className="absolute inset-0 rounded-lg bg-black/0 group-hover:bg-black/40 transition-colors flex items-center justify-center opacity-0 group-hover:opacity-100 cursor-pointer"
                    onClick={() => setPreviewOpen(true)}
                  >
                    <span className="text-white text-[11px] font-medium">点击放大</span>
                  </div>
                  {/* hover 重绘按钮 */}
                  <button
                    onClick={(e) => { e.stopPropagation(); setRedrawTarget({ imageSrc: selectedVersion.ref_asset_url || '', prompt: editingCard, title: `重绘 - ${selectedName}` }); }}
                    className="absolute top-1 right-1 rounded bg-[#1d4ed8] px-1.5 py-0.5 text-[10px] text-white opacity-0 group-hover:opacity-100 transition-opacity hover:bg-[#1e40af]"
                  >
                    重绘
                  </button>
                </div>
                <button onClick={handleDeleteRef} className="rounded border border-[#d7e3f4] px-2 py-0.5 text-[11px] text-rose-500 hover:bg-rose-50">删除参考图</button>
              </div>
            ) : (
              <div className="flex h-20 items-center justify-center rounded-lg border border-dashed border-[#d7e3f4] text-[11px] text-slate-400">
                暂无参考图，请先编辑外貌卡并点击「生成参考图」
              </div>
            )}
          </>
        ) : (
          <div className="text-sm text-slate-400 py-8 text-center">
            {sidebarOpen ? '请从左侧选择角色' : '点击 ◀ 展开角色列表'}
          </div>
        )}
      </div>

      {/* 预览工作台 */}
      {previewOpen && selectedVersion?.ref_asset_url && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(15,23,42,0.62)] p-4 backdrop-blur-sm" onClick={() => setPreviewOpen(false)}>
          <div
            className="flex h-[88vh] w-[min(1400px,94vw)] flex-col overflow-hidden rounded-[30px] border border-[#d7e3f4] bg-[linear-gradient(180deg,_#0b1220_0%,_#111827_100%)] shadow-[0_30px_90px_rgba(15,23,42,0.28)]"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
              <div>
                <div className="text-lg font-semibold text-white">{selectedName}</div>
                <div className="mt-1 text-sm text-white/50">角色参考图预览</div>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-white/60">缩放</span>
                {[1, 1.35, 1.7].map((zoom) => (
                  <button
                    key={zoom}
                    type="button"
                    onClick={() => setLightboxZoom(zoom as 1 | 1.35 | 1.7)}
                    className={`rounded-full px-3 py-1.5 text-xs transition-colors ${
                      lightboxZoom === zoom ? 'bg-white text-slate-900' : 'bg-white/10 text-white hover:bg-white/20'
                    }`}
                  >
                    {Math.round(zoom * 100)}%
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => setPreviewOpen(false)}
                  className="rounded-full bg-white/10 p-2 text-white transition-colors hover:bg-white/20"
                >
                  <X size={20} />
                </button>
              </div>
            </div>

            <div className="flex flex-1 items-center justify-center overflow-auto p-6">
              <img
                src={selectedVersion.ref_asset_url}
                alt={selectedName}
                loading="lazy"
                decoding="async"
                className={`mx-auto h-auto object-contain rounded-xl shadow-2xl ${
                  lightboxZoom === 1
                    ? 'max-w-[92%] max-h-none'
                    : lightboxZoom === 1.35
                      ? 'max-w-none w-[780px]'
                      : 'max-w-none w-[940px]'
                }`}
              />
            </div>

            <div className="flex justify-center gap-3 border-t border-white/10 px-6 py-4">
              <button
                type="button"
                onClick={() => setRedrawTarget({ imageSrc: selectedVersion.ref_asset_url || '', prompt: editingCard, title: `重绘 - ${selectedName}` })}
                className="rounded-2xl bg-[#1d4ed8] px-4 py-2 text-sm font-medium text-white hover:bg-[#1e40af]"
              >
                重绘
              </button>
              <button
                type="button"
                onClick={() => setPreviewOpen(false)}
                className="rounded-2xl border border-white/20 px-4 py-2 text-sm font-medium text-white hover:bg-white/10"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 重绘模态框 */}
      {redrawTarget && (
        <ImageRedrawModal
          target={redrawTarget}
          busy={redrawBusy}
          onClose={() => setRedrawTarget(null)}
          onSubmit={handleRedrawSubmit}
        />
      )}

      {error && (
        <div className="absolute bottom-2 left-2 right-2 rounded-lg bg-rose-50 px-3 py-2 text-[11px] text-rose-600 z-20">
          {error}
          <button onClick={() => setError(null)} className="ml-2 text-rose-400 hover:text-rose-600">x</button>
        </div>
      )}
    </div>
  );
}

// ── ImageRedrawModal（角色参考图重绘工作台） ──

function ImageRedrawModal({
  target,
  busy,
  onClose,
  onSubmit,
}: {
  target: { imageSrc: string; prompt: string; title: string };
  busy: boolean;
  onClose: () => void;
  onSubmit: (payload: { prompt: string; mode: ImageRedrawMode; mask?: string }) => Promise<void>;
}) {
  const [mode, setMode] = useState<ImageRedrawMode>('full');
  const [prompt, setPrompt] = useState(target.prompt);
  const [brushSize, setBrushSize] = useState(36);
  const [drawing, setDrawing] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const drawingRef = useRef(false);
  const lastPointRef = useRef<{ x: number; y: number } | null>(null);
  const [canvasReady, setCanvasReady] = useState(false);

  useEffect(() => {
    setPrompt(target.prompt);
    setMode('full');
    setImageLoaded(false);
    setCanvasReady(false);
  }, [target]);

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
  }, [mode, target.imageSrc, syncCanvasSize]);

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
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
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

  const exportMask = useCallback(() => {
    const overlay = canvasRef.current;
    const img = imageRef.current;
    if (!overlay || !img || !canvasReady) return '';
    const raw = overlay.getContext('2d')?.getImageData(0, 0, overlay.width, overlay.height);
    if (!raw) return '';
    let hasPaint = false;
    for (let i = 3; i < raw.data.length; i += 4) {
      if (raw.data[i] > 10) {
        hasPaint = true;
        break;
      }
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

  const modal = (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-[rgba(15,23,42,0.62)] p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className="flex h-[88vh] w-[min(1400px,94vw)] flex-col overflow-hidden rounded-[30px] border border-[#d7e3f4] bg-white shadow-[0_30px_90px_rgba(15,23,42,0.28)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[#e5edf8] px-6 py-4">
          <div>
            <div className="text-lg font-semibold text-slate-900">{target.title}</div>
            <div className="mt-1 text-sm text-slate-500">左侧查看和涂抹图片，右侧填写重绘说明并提交。</div>
          </div>
          <button onClick={onClose} className="rounded-full bg-slate-100 p-2 text-slate-600 transition hover:bg-slate-200">
            <X size={18} />
          </button>
        </div>
        <div className="grid flex-1 gap-0 overflow-hidden lg:grid-cols-[minmax(0,1.5fr)_420px]">
          <div className="overflow-auto bg-[linear-gradient(180deg,_#0f172a_0%,_#111827_100%)] p-6">
            <div className="mb-4 flex items-center justify-between text-white/80">
              <div className="text-sm font-medium">选中图片</div>
              <div className="text-xs">{mode === 'partial' ? '在左图直接涂抹需要修改的区域' : '整图将按右侧说明整体重绘'}</div>
            </div>
            <div className="mx-auto flex min-h-[62vh] w-full items-center justify-center rounded-[24px] border border-white/10 bg-black/20 p-4">
              <div className="relative inline-block">
                <img
                  ref={imageRef}
                  src={target.imageSrc}
                  alt={target.title}
                  onLoad={() => {
                    setImageLoaded(true);
                    syncCanvasSize();
                  }}
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
                    清除涂抹
                  </button>
                </div>
              )}

              <div className="rounded-2xl border border-[#d7e3f4] bg-white p-4">
                <div className="text-sm font-medium text-slate-800">重绘说明</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">描述希望修改的内容，越具体效果越好。</div>
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  rows={6}
                  className="mt-3 w-full rounded-2xl border border-[#d7e3f4] bg-[#f8fbff] px-3 py-3 text-sm leading-6 text-slate-900 outline-none focus:border-[#93c5fd]"
                  placeholder="描述您希望修改的内容..."
                />
              </div>

              <div className="flex gap-3">
                <button
                  type="button"
                  disabled={busy || !prompt.trim()}
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
