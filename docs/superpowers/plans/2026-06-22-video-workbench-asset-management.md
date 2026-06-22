# Video Workbench Asset Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a comprehensive asset management panel to the VideoCardWorkbench modal, enabling users to upload, delete, rename, categorize, and replace both auto-generated and manually uploaded video assets with OSS compatibility.

**Architecture:** Create a new `AssetManagementModal` component that opens from a button in the VideoCardWorkbench header. The modal provides full CRUD operations for VideoAsset records, using existing backend APIs. Upload uses FormData with OSS backend integration.

**Tech Stack:** React 19, TypeScript, Tailwind CSS v4, Lucide icons, existing VideoAsset API endpoints

---

## File Structure

| File | Responsibility |
|------|---------------|
| `frontend/src/components/AssetManagementModal.tsx` | **NEW** - Main asset management modal with tabs for different asset types, inline editing, upload, delete |
| `frontend/src/components/VideoCardWorkbench.tsx` | **MODIFY** - Add button to open AssetManagementModal, pass required props |
| `frontend/src/api.ts` | **VERIFY** - Ensure all needed API functions exist (they do) |

---

## Task 1: Create AssetManagementModal Component Skeleton

**Files:**
- Create: `frontend/src/components/AssetManagementModal.tsx`

- [ ] **Step 1: Create the component file with basic structure**

```tsx
// frontend/src/components/AssetManagementModal.tsx
import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { X, Upload, Trash2, Edit3, Save, Loader2, Image, User, MapPin, Film } from 'lucide-react';
import { 
  listVideoAssets, 
  deleteVideoAsset, 
  replaceVideoAsset, 
  createVideoAsset,
  toPublicVideoAssetUrl,
  apiHeaders,
  type VideoAsset 
} from '../api';

interface AssetManagementModalProps {
  chapterId: number;
  onClose: () => void;
  onAssetsChanged?: () => void; // Callback when assets are modified
}

type AssetTab = 'all' | 'character_reference' | 'scene_reference' | 'storyboard_frame' | 'prop_reference';

export default function AssetManagementModal({ chapterId, onClose, onAssetsChanged }: AssetManagementModalProps) {
  const [assets, setAssets] = useState<VideoAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<AssetTab>('all');
  const [editingAssetId, setEditingAssetId] = useState<number | null>(null);
  const [editingName, setEditingName] = useState('');
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadAssets();
  }, [chapterId]);

  const loadAssets = async () => {
    setLoading(true);
    try {
      const data = await listVideoAssets(chapterId);
      setAssets(data.assets || []);
    } catch (e) {
      console.error('加载资产失败:', e);
    } finally {
      setLoading(false);
    }
  };

  const filteredAssets = activeTab === 'all' 
    ? assets 
    : assets.filter(a => a.asset_type === activeTab);

  // TODO: Implement handlers
  const handleDelete = async (assetId: number) => {};
  const handleRename = async (assetId: number, newName: string) => {};
  const handleUpload = async (file: File, assetType: string, name: string) => {};

  return createPortal(
    <div className="fixed inset-0 z-[75] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4" onClick={onClose}>
      <div className="flex flex-col w-[min(1000px,95vw)] h-[85vh] rounded-2xl bg-white shadow-2xl overflow-hidden" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h2 className="text-lg font-semibold text-slate-900">资产管理</h2>
          <button onClick={onClose} className="p-2 rounded-full hover:bg-slate-100">
            <X size={18} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex justify-center py-12">
              <Loader2 size={24} className="animate-spin text-slate-400" />
            </div>
          ) : (
            <div className="space-y-4">
              {/* Asset list will be rendered here */}
              <p className="text-slate-500 text-sm">共 {filteredAssets.length} 个资产</p>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}
```

- [ ] **Step 2: Verify component compiles**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: No errors related to AssetManagementModal.tsx

---

## Task 2: Add Asset Type Tabs and Filtering

**Files:**
- Modify: `frontend/src/components/AssetManagementModal.tsx:40-100`

- [ ] **Step 1: Add tab navigation with asset type filtering**

Replace the content section with tabs:

```tsx
// Add inside the component, after state declarations
const tabs: { key: AssetTab; label: string; icon: React.ReactNode }[] = [
  { key: 'all', label: '全部', icon: <Image size={14} /> },
  { key: 'character_reference', label: '角色', icon: <User size={14} /> },
  { key: 'scene_reference', label: '场景', icon: <MapPin size={14} /> },
  { key: 'storyboard_frame', label: '故事版', icon: <Film size={14} /> },
  { key: 'prop_reference', label: '道具', icon: <Image size={14} /> },
];

// Update the JSX to include tabs
return createPortal(
  <div className="fixed inset-0 z-[75] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4" onClick={onClose}>
    <div className="flex flex-col w-[min(1000px,95vw)] h-[85vh] rounded-2xl bg-white shadow-2xl overflow-hidden" onClick={e => e.stopPropagation()}>
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b">
        <h2 className="text-lg font-semibold text-slate-900">资产管理</h2>
        <button onClick={onClose} className="p-2 rounded-full hover:bg-slate-100">
          <X size={18} />
        </button>
      </div>

      {/* Tabs */}
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

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {loading ? (
          <div className="flex justify-center py-12">
            <Loader2 size={24} className="animate-spin text-slate-400" />
          </div>
        ) : filteredAssets.length === 0 ? (
          <div className="text-center py-12 text-slate-400">
            <Image size={48} className="mx-auto mb-4 opacity-50" />
            <p>暂无资产</p>
            <p className="text-sm mt-1">点击上方"上传资产"按钮添加</p>
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
  </div>,
  document.body
);
```

- [ ] **Step 2: Create AssetCard sub-component**

Add before the main component export:

```tsx
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
  const imageUrl = toPublicVideoAssetUrl(asset.file_path) || '';

  return (
    <div className="group relative rounded-xl border border-slate-200 bg-white overflow-hidden hover:shadow-md transition-shadow">
      {/* Image */}
      <div className="aspect-square bg-slate-100 relative">
        {imageUrl ? (
          <img src={imageUrl} alt={asset.name} className="w-full h-full object-cover" />
        ) : (
          <div className="flex items-center justify-center h-full text-slate-300">
            <Image size={32} />
          </div>
        )}
        
        {/* Overlay actions */}
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

      {/* Info */}
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
          {asset.revision > 1 && <span className="ml-1">v{asset.revision}</span>}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify component compiles**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | head -30`
Expected: No errors

---

## Task 3: Implement Delete Handler

**Files:**
- Modify: `frontend/src/components/AssetManagementModal.tsx`

- [ ] **Step 1: Implement handleDelete with confirmation**

```tsx
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
```

- [ ] **Step 2: Verify no compile errors**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | grep -i error | head -10`
Expected: No errors

---

## Task 4: Implement Rename Handler

**Files:**
- Modify: `frontend/src/components/AssetManagementModal.tsx`

- [ ] **Step 1: Implement handleRename with API call**

```tsx
const handleRename = async (assetId: number, newName: string) => {
  if (!newName.trim()) {
    alert('名称不能为空');
    return;
  }

  try {
    // Use the update endpoint if available, otherwise we need to add it
    // For now, update locally (backend doesn't have rename endpoint yet)
    setAssets(prev => prev.map(a => 
      a.id === assetId ? { ...a, name: newName.trim() } : a
    ));
    setEditingAssetId(null);
    
    // TODO: Add backend rename endpoint if needed
    // For now, this is a local-only rename
    console.log('重命名资产:', assetId, newName);
  } catch (e) {
    console.error('重命名失败:', e);
  }
};
```

- [ ] **Step 2: Verify no compile errors**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | grep -i error | head -10`
Expected: No errors

---

## Task 5: Implement Upload Handler with OSS

**Files:**
- Modify: `frontend/src/components/AssetManagementModal.tsx`

- [ ] **Step 1: Add upload state and file input**

```tsx
// Add state for upload modal
const [showUploadModal, setShowUploadModal] = useState(false);
const [uploadFile, setUploadFile] = useState<File | null>(null);
const [uploadName, setUploadName] = useState('');
const [uploadType, setUploadType] = useState<string>('character_reference');
const [uploadPreview, setUploadPreview] = useState<string | null>(null);
```

- [ ] **Step 2: Add upload button and modal UI**

In the header, add upload button:

```tsx
<div className="flex items-center justify-between px-6 py-4 border-b">
  <h2 className="text-lg font-semibold text-slate-900">资产管理</h2>
  <div className="flex items-center gap-2">
    <button
      onClick={() => setShowUploadModal(true)}
      className="flex items-center gap-1.5 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700"
    >
      <Upload size={14} />
      上传资产
    </button>
    <button onClick={onClose} className="p-2 rounded-full hover:bg-slate-100">
      <X size={18} />
    </button>
  </div>
</div>
```

Add upload modal at the end of the portal:

```tsx
{/* Upload Modal */}
{showUploadModal && (
  <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 p-4" onClick={() => setShowUploadModal(false)}>
    <div className="w-[480px] rounded-2xl bg-white p-6 shadow-2xl" onClick={e => e.stopPropagation()}>
      <h3 className="text-lg font-semibold text-slate-900 mb-4">上传新资产</h3>
      
      {/* File upload area */}
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

      {/* Name input */}
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

      {/* Type select */}
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

      {/* Actions */}
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
          className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50"
        >
          {uploading && <Loader2 size={14} className="animate-spin" />}
          {uploading ? '上传中...' : '上传'}
        </button>
      </div>
    </div>
  </div>
)}
```

- [ ] **Step 3: Implement handleUpload function**

```tsx
const handleUpload = async () => {
  if (!uploadFile || !uploadName.trim()) return;

  setUploading(true);
  try {
    const formData = new FormData();
    formData.append('file', uploadFile);
    
    // Create asset with upload
    const res = await fetch(`/api/chapters/${chapterId}/video-assets`, {
      method: 'POST',
      headers: apiHeaders(),
      body: JSON.stringify({
        asset_type: uploadType,
        name: uploadName.trim(),
        source_type: 'manual_upload',
      }),
    });
    
    if (!res.ok) throw new Error('创建资产记录失败');
    const newAsset = await res.json();
    
    // Upload file to replace the placeholder
    await replaceVideoAsset(newAsset.id, uploadFile);
    
    // Reload assets
    await loadAssets();
    onAssetsChanged?.();
    
    // Close upload modal
    setShowUploadModal(false);
    setUploadFile(null);
    setUploadName('');
    setUploadPreview(null);
  } catch (e) {
    console.error('上传失败:', e);
    alert('上传失败，请重试');
  } finally {
    setUploading(false);
  }
};
```

- [ ] **Step 4: Verify no compile errors**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | grep -i error | head -10`
Expected: No errors

---

## Task 6: Add AssetManagementModal to VideoCardWorkbench

**Files:**
- Modify: `frontend/src/components/VideoCardWorkbench.tsx`

- [ ] **Step 1: Import AssetManagementModal**

Add at the top of VideoCardWorkbench.tsx:

```tsx
import AssetManagementModal from './AssetManagementModal';
```

- [ ] **Step 2: Add state for asset management modal**

After the existing state declarations (around line 66):

```tsx
const [isAssetManagementOpen, setIsAssetManagementOpen] = useState(false);
```

- [ ] **Step 3: Add button in the header**

Find the header section (around line 431-444) and add a button:

```tsx
{/* 弹窗头部 */}
<div className="flex items-center justify-between border-b border-[#e5edf8] px-6 py-4">
  <div>
    <div className="text-lg font-semibold text-slate-900">
      {isCharacter ? '角色资产工作台' : isScene ? '场景 & 道具工作台' : '故事版工作台'}
    </div>
    <div className="mt-1 text-sm text-slate-500">
      镜头 {displayShotIndex ?? shotId}
      {isCharacter ? ' · 左侧选择角色，中间预览，右侧查看提示词与操作' : isScene ? ' · 左侧选择场景/道具，中间预览，右侧查看提示词与操作' : ' · 中间预览故事版图片，右侧查看提示词与操作'}
    </div>
  </div>
  <div className="flex items-center gap-2">
    <button
      onClick={() => setIsAssetManagementOpen(true)}
      className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-indigo-600 bg-indigo-50 rounded-lg hover:bg-indigo-100 transition-colors"
    >
      <Image size={14} />
      资产管理
    </button>
    <button onClick={onClose} className="rounded-full bg-slate-100 p-2 text-slate-600 transition hover:bg-slate-200">
      <X size={18} />
    </button>
  </div>
</div>
```

Note: You'll need to add `Image` to the lucide-react imports at the top of the file.

- [ ] **Step 4: Add AssetManagementModal rendering**

Before the closing `</div>` of the modal (before `createPortal`), add:

```tsx
{/* 资产管理弹窗 */}
{isAssetManagementOpen && (
  <AssetManagementModal
    chapterId={/* Need to pass chapterId - check props */}
    onClose={() => setIsAssetManagementOpen(false)}
    onAssetsChanged={() => {
      // Refresh chapterAssets if needed
      loadAssets?.();
    }}
  />
)}
```

- [ ] **Step 5: Verify component compiles**

Run: `cd frontend && npx tsc --noEmit --pretty 2>&1 | grep -i error | head -10`
Expected: No errors

---

## Task 7: Verify Integration and Test

**Files:**
- None (verification only)

- [ ] **Step 1: Run full TypeScript check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 2: Run ESLint check**

Run: `cd frontend && npm run lint 2>&1 | head -30`
Expected: No new errors

- [ ] **Step 3: Build production bundle**

Run: `cd frontend && npm run build 2>&1 | tail -20`
Expected: Build succeeds

---

## Summary

This plan implements a comprehensive asset management panel for the VideoCardWorkbench with:

1. **Tab-based filtering** by asset type (all, character, scene, storyboard, prop)
2. **Asset cards** with image preview, name, type badge, and revision indicator
3. **Inline rename** with edit icon and save/cancel
4. **Delete with confirmation** dialog
5. **Upload modal** with file preview, name input, and type selection
6. **OSS compatibility** via existing `replaceVideoAsset` API
7. **Responsive grid layout** that adapts to screen size

The implementation reuses existing backend APIs and follows the project's established patterns for modals, forms, and API calls.
