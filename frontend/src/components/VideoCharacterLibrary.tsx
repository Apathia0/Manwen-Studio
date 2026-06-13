import { useCallback, useEffect, useState } from 'react';
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
import { ImageRedrawModal } from './shared/ImageRedrawModal';
import { ChevronLeft, ChevronRight, X } from 'lucide-react';
import { confirm } from '../lib/confirm';

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
  const [selectedStyle, setSelectedStyle] = useState<string>(() => {
    try { return localStorage.getItem('video_char_lib_style') || ''; } catch { return ''; }
  });
  const [previewOpen, setPreviewOpen] = useState(false);
  const [lightboxZoom, setLightboxZoom] = useState<1 | 1.35 | 1.7>(1.35);
  const [redrawTarget, setRedrawTarget] = useState<{ imageSrc: string; prompt: string; title: string } | null>(null);
  const [redrawBusy, setRedrawBusy] = useState(false);

  // 从 localStorage 恢复选中风格
  useEffect(() => {
    try {
      const lsKey = `video_char_lib_style_${storyId}`;
      const saved = localStorage.getItem(lsKey) || localStorage.getItem('video_char_lib_style') || '';
      if (saved) setSelectedStyle(saved);
    } catch {}
  }, [storyId]);

  // 选中风格变化时持久化到 localStorage
  useEffect(() => {
    try {
      localStorage.setItem('video_char_lib_style', selectedStyle);
      if (storyId) localStorage.setItem(`video_char_lib_style_${storyId}`, selectedStyle);
    } catch {}
  }, [selectedStyle, storyId]);

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
          imageSrc={redrawTarget.imageSrc}
          title={redrawTarget.title}
          prompt={redrawTarget.prompt}
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


