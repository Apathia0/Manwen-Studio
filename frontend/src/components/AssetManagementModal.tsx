import { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { X, Upload, Trash2, Edit3, Save, Loader2, Image, User, MapPin, Film, Download } from 'lucide-react';
import { 
  listVideoAssets, 
  createVideoAsset,
  deleteVideoAsset, 
  replaceVideoAsset, 
  updateVideoAsset,
  toPublicVideoAssetUrl,
  type VideoAsset 
} from '../api';
import { toast } from '../lib/toast';
import { normalizeErrorMessage } from '../lib/errors';
import { downloadImagesAsZip, sanitizeFilename } from '../lib/zipDownload';

interface AssetManagementModalProps {
  chapterId: number;
  onClose: () => void;
  onAssetsChanged?: () => void;
}

type AssetTab = 'all' | 'character_reference' | 'scene_reference' | 'storyboard_frame' | 'prop_reference';

const assetTypeLabel: Record<string, string> = {
  character_reference: '角色',
  scene_reference: '场景',
  storyboard_frame: '故事版',
  prop_reference: '道具',
};

const tabs: { key: AssetTab; label: string; icon: React.ReactNode }[] = [
  { key: 'all', label: '全部', icon: <Image size={14} /> },
  { key: 'character_reference', label: '角色', icon: <User size={14} /> },
  { key: 'scene_reference', label: '场景', icon: <MapPin size={14} /> },
  { key: 'storyboard_frame', label: '故事版', icon: <Film size={14} /> },
  { key: 'prop_reference', label: '道具', icon: <Image size={14} /> },
];

function AssetCard({ 
  asset, 
  isEditing, 
  editingName, 
  onEditName, 
  onStartEdit, 
  onCancelEdit, 
  onSaveEdit, 
  onDelete, 
  isDeleting 
}: {
  asset: VideoAsset;
  isEditing: boolean;
  editingName: string;
  onEditName: (name: string) => void;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onSaveEdit: () => void;
  onDelete: () => void;
  isDeleting: boolean;
}) {
  const imageUrl = asset.file_path ? toPublicVideoAssetUrl(asset.file_path) : '';

  return (
    <div className="group relative rounded-xl border border-slate-200 bg-white overflow-hidden hover:shadow-md transition-shadow">
      
      <div className="aspect-square bg-slate-100 relative">
        {imageUrl ? (
          <img src={imageUrl} alt={asset.name} className="w-full h-full object-cover" />
        ) : (
          <div className="flex items-center justify-center h-full text-slate-300">
            <Image size={32} />
          </div>
        )}
        
        <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors flex items-center justify-center gap-2 opacity-0 group-hover:opacity-100">
          <button
            onClick={onStartEdit}
            className="p-2 bg-white rounded-full shadow-lg hover:bg-slate-100"
            title="重命名"
          >
            <Edit3 size={14} className="text-slate-700" />
          </button>
          <button
            onClick={onDelete}
            disabled={isDeleting}
            className="p-2 bg-white rounded-full shadow-lg hover:bg-red-50 disabled:opacity-50"
            title="删除"
          >
            {isDeleting ? <Loader2 size={14} className="animate-spin text-red-500" /> : <Trash2 size={14} className="text-red-500" />}
          </button>
        </div>
      </div>

      <div className="p-3">
        {isEditing ? (
          <div className="flex items-center gap-1">
            <input
              type="text"
              value={editingName}
              onChange={e => onEditName(e.target.value)}
              className="flex-1 px-2 py-1 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-indigo-500"
              autoFocus
              onKeyDown={e => { if (e.key === 'Enter') onSaveEdit(); if (e.key === 'Escape') onCancelEdit(); }}
            />
            <button onClick={onSaveEdit} className="p-1 text-green-600 hover:bg-green-50 rounded">
              <Save size={14} />
            </button>
          </div>
        ) : (
          <div className="text-sm font-medium text-slate-800 truncate">{asset.name}</div>
        )}
        <div className="text-xs text-slate-400 mt-1">
          {asset.asset_type === 'character_reference' ? '角色' :
           asset.asset_type === 'scene_reference' ? '场景' :
           asset.asset_type === 'storyboard_frame' ? '故事版' :
           asset.asset_type === 'prop_reference' ? '道具' : asset.asset_type}
          {asset.revision && asset.revision > 1 && <span className="ml-1">v{asset.revision}</span>}
        </div>
      </div>
    </div>
  );
}

export default function AssetManagementModal({ chapterId, onClose, onAssetsChanged }: AssetManagementModalProps) {
  const [assets, setAssets] = useState<VideoAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<AssetTab>('all');
  const [editingAssetId, setEditingAssetId] = useState<number | null>(null);
  const [editingName, setEditingName] = useState('');
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadName, setUploadName] = useState('');
  const [uploadType, setUploadType] = useState<string>('character_reference');
  const [uploadPreview, setUploadPreview] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [downloadingAll, setDownloadingAll] = useState(false);
  const [downloadStatus, setDownloadStatus] = useState('');
  const exportAbortRef = useRef<AbortController | null>(null);

  const loadAssets = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listVideoAssets(chapterId);
      setAssets(data.assets || []);
    } catch (e) {
      console.error('加载资产失败:', e);
      setAssets([]);
    } finally {
      setLoading(false);
    }
  }, [chapterId]);

  useEffect(() => {
    loadAssets();
  }, [loadAssets]);

  const filteredAssets = activeTab === 'all' 
    ? assets 
    : assets.filter(a => a.asset_type === activeTab);

  const handleDelete = async (assetId: number) => {
    const asset = assets.find(a => a.id === assetId);
    if (!asset) return;
    
    if (!window.confirm(`确定删除资产"${asset.name}"吗？此操作不可恢复。`)) {
      return;
    }

    setDeletingId(assetId);
    try {
      await deleteVideoAsset(assetId);
      setAssets(prev => prev.filter(a => a.id !== assetId));
      onAssetsChanged?.();
    } catch (e) {
      console.error('删除资产失败:', e);
      alert('删除失败，请重试');
    } finally {
      setDeletingId(null);
    }
  };

  const handleRename = async (assetId: number, newName: string) => {
    if (!newName.trim()) return;

    try {
      await updateVideoAsset(assetId, { name: newName.trim() });
      setAssets(prev => prev.map(a => 
        a.id === assetId ? { ...a, name: newName.trim() } : a
      ));
      onAssetsChanged?.();
      setEditingAssetId(null);
    } catch (e) {
      console.error('重命名失败:', e);
      alert('重命名失败，请重试');
    }
  };

  const handleUpload = async () => {
    if (!uploadFile || !uploadName.trim()) return;

    setUploading(true);
    try {
      const newAsset = await createVideoAsset(chapterId, {
        asset_type: uploadType,
        name: uploadName.trim(),
        file_path: '',
        provider: 'manual_upload',
      });
      
      await replaceVideoAsset(newAsset.id, uploadFile);
      
      await loadAssets();
      onAssetsChanged?.();
      
      setShowUploadModal(false);
      setUploadFile(null);
      setUploadName('');
      setUploadPreview(null);
    } catch (e) {
      console.error('上传失败:', e);
      alert(e instanceof Error ? e.message : '上传失败，请重试');
    } finally {
      setUploading(false);
    }
  };

  const assetUrl = (asset: VideoAsset): string => {
    const url = toPublicVideoAssetUrl(asset.file_path);
    if (!url || typeof asset.revision !== 'number' || asset.revision <= 0) return url || '';
    return `${url}${url.includes('?') ? '&' : '?'}v=${encodeURIComponent(String(asset.revision))}`;
  };

  const assetFileExtension = (filePath: string): string => {
    const match = /\.([a-zA-Z0-9]+)(?:\?|$)/.exec(filePath || '');
    const ext = match ? match[1].toLowerCase() : '';
    return ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp'].includes(ext) ? ext : 'png';
  };

  // 复用公共下载工具，将当前筛选的资产图片打包为 ZIP 导出。
  const handleDownloadAll = async () => {
    const items = filteredAssets
      .map((asset) => ({ asset, url: assetUrl(asset) }))
      .filter((entry): entry is { asset: VideoAsset; url: string } => Boolean(entry.url))
      .map(({ asset, url }) => ({
        filename: `${assetTypeLabel[asset.asset_type] || '资产'}_${sanitizeFilename(asset.name)}.${assetFileExtension(asset.file_path)}`,
        url,
      }));
    if (items.length === 0) {
      toast.error('当前没有可下载的资产图片');
      return;
    }
    if (downloadingAll) return;
    exportAbortRef.current?.abort();
    const abortController = new AbortController();
    exportAbortRef.current = abortController;
    const isCurrentExport = () => (
      exportAbortRef.current === abortController && !abortController.signal.aborted
    );
    setDownloadingAll(true);
    setDownloadStatus('正在准备导出');
    try {
      const dateStr = new Date().toISOString().slice(0, 10);
      await downloadImagesAsZip(items, {
        zipName: `视频资产_${dateStr}.zip`,
        signal: abortController.signal,
        onStage: (stage) => {
          if (!isCurrentExport()) return;
          if (stage === 'preparing') setDownloadStatus('正在准备导出');
          if (stage === 'downloading') setDownloadStatus(`下载 0/${items.length}`);
          if (stage === 'archiving') setDownloadStatus('正在生成压缩包');
        },
        onProgress: (completed, total) => {
          if (isCurrentExport()) setDownloadStatus(`下载 ${completed}/${total}`);
        },
      });
      if (!isCurrentExport()) return;
      toast.success(`已下载 ${items.length} 张资产图片`);
    } catch (err) {
      if (exportAbortRef.current !== abortController) return;
      if (abortController.signal.aborted) return;
      toast.error(normalizeErrorMessage(err, '资产打包下载失败，请重试'));
    } finally {
      if (exportAbortRef.current === abortController) {
        exportAbortRef.current = null;
        setDownloadingAll(false);
        setDownloadStatus('');
      }
    }
  };

  return createPortal(
    <div className="fixed inset-0 z-[75] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4" onClick={onClose}>
      <div className="flex flex-col w-[min(1000px,95vw)] h-[85vh] rounded-2xl bg-white shadow-2xl overflow-hidden" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">故事视频资产管理</h2>
            <p className="mt-0.5 text-xs text-slate-500">收录当前故事内跨章节的视频工作流图片资产</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowUploadModal(true)}
              className="flex items-center gap-1.5 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 transition-colors"
            >
              <Upload size={14} />
              上传资产
            </button>
            <button
              onClick={() => void handleDownloadAll()}
              disabled={downloadingAll || filteredAssets.length === 0}
              className="flex items-center gap-1.5 px-4 py-2 border border-slate-300 bg-white text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
            >
              {downloadingAll ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
              {downloadingAll ? downloadStatus : '下载导出'}
            </button>
            <button onClick={onClose} className="p-2 rounded-full hover:bg-slate-100">
              <X size={18} />
            </button>
          </div>
        </div>

        <div className="flex gap-1 px-6 pt-4 bg-slate-50">
          {tabs.map(tab => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg transition ${
                activeTab === tab.key
                  ? 'bg-white text-indigo-700 shadow-sm'
                  : 'text-slate-500 hover:text-slate-700 hover:bg-white/50'
              }`}
            >
              {tab.icon}
              {tab.label}
              <span className="ml-1 text-xs text-slate-400">
                ({tab.key === 'all' ? assets.length : assets.filter(a => a.asset_type === tab.key).length})
              </span>
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex justify-center py-12">
              <Loader2 size={24} className="animate-spin text-slate-400" />
            </div>
          ) : filteredAssets.length === 0 ? (
            <div className="text-center py-12 text-slate-400">
              <Image size={48} className="mx-auto mb-4 opacity-50" />
              <p>暂无故事视频资产</p>
              <p className="text-sm mt-1">生成故事版、角色、场景、道具图片后会自动收录，也可点击上方"上传资产"添加</p>
            </div>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {filteredAssets.map(asset => (
                <AssetCard 
                  key={asset.id} 
                  asset={asset}
                  isEditing={editingAssetId === asset.id}
                  editingName={editingName}
                  onEditName={setEditingName}
                  onStartEdit={() => { setEditingAssetId(asset.id); setEditingName(asset.name); }}
                  onCancelEdit={() => setEditingAssetId(null)}
                  onSaveEdit={() => handleRename(asset.id, editingName)}
                  onDelete={() => handleDelete(asset.id)}
                  isDeleting={deletingId === asset.id}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {showUploadModal && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 p-4" onClick={() => setShowUploadModal(false)}>
          <div className="w-[480px] rounded-2xl bg-white p-6 shadow-2xl" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-slate-900 mb-4">上传新资产</h3>
            
            <div 
              className="border-2 border-dashed border-slate-300 rounded-xl p-8 text-center hover:border-indigo-400 transition-colors cursor-pointer"
              onClick={() => fileInputRef.current?.click()}
            >
              {uploadPreview ? (
                <img src={uploadPreview} alt="预览" className="max-h-40 mx-auto rounded-lg" />
              ) : (
                <>
                  <Upload size={48} className="mx-auto text-slate-300 mb-3" />
                  <p className="text-sm text-slate-500">点击选择图片</p>
                  <p className="text-xs text-slate-400 mt-1">支持 JPG, PNG, WebP</p>
                </>
              )}
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={e => {
                const file = e.target.files?.[0];
                if (file) {
                  setUploadFile(file);
                  setUploadName(file.name.replace(/\.[^/.]+$/, ''));
                  const reader = new FileReader();
                  reader.onload = () => setUploadPreview(reader.result as string);
                  reader.readAsDataURL(file);
                }
              }}
            />

            <div className="mt-4">
              <label className="block text-sm font-medium text-slate-700 mb-1">资产名称</label>
              <input
                type="text"
                value={uploadName}
                onChange={e => setUploadName(e.target.value)}
                className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
                placeholder="输入资产名称"
              />
            </div>

            <div className="mt-4">
              <label className="block text-sm font-medium text-slate-700 mb-1">资产类型</label>
              <select
                value={uploadType}
                onChange={e => setUploadType(e.target.value)}
                className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                <option value="character_reference">角色参考图</option>
                <option value="scene_reference">场景参考图</option>
                <option value="prop_reference">道具参考图</option>
                <option value="storyboard_frame">故事版帧</option>
              </select>
            </div>

            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => {
                  setShowUploadModal(false);
                  setUploadFile(null);
                  setUploadName('');
                  setUploadPreview(null);
                }}
                className="px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 rounded-lg"
              >
                取消
              </button>
              <button
                onClick={handleUpload}
                disabled={!uploadFile || !uploadName.trim() || uploading}
                className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
              >
                {uploading && <Loader2 size={14} className="animate-spin" />}
                {uploading ? '上传中...' : '上传'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>,
    document.body
  );
}
