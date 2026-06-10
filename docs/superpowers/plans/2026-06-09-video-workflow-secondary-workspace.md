# 视频工作流二级工作台重构实现计划

> **对于代理工作者：** 必须使用子技能：推荐使用 superpowers:subagent-driven-development 或 superpowers:executing-plans 来逐任务实现此计划。步骤使用复选框（`- [ ]`）语法进行跟踪。

**目标：** 重构视频工作流布局，移除右侧320px内嵌工作区，实现点击卡片进入全屏二级工作台的功能。

**架构：** 创建统一的`VideoCardWorkbench`组件，复用漫画工作台的深色背景布局，支持三种卡片类型（角色资产、故事版、视频）的二级工作台功能。

**技术栈：** React 19, TypeScript 6, Tailwind CSS v4, Lucide React

---

## 文件结构

### 新建文件
- `frontend/src/components/VideoCardWorkbench.tsx` — 统一的二级工作台组件

### 修改文件
- `frontend/src/components/ChapterVideoWorkflowPanel.tsx` — 移除右侧工作台，添加二级工作台触发逻辑
- `frontend/src/components/VideoStoryboardLayout.tsx` — 调整布局，移除右侧工作台容器

### 复用文件
- `frontend/src/components/shared/ImageRedrawModal.tsx` — 重绘功能
- `frontend/src/components/MangaPanel.tsx` — 参考深色背景样式

---

## 任务1：创建VideoCardWorkbench基础组件

**文件：**
- 创建：`frontend/src/components/VideoCardWorkbench.tsx`

- [ ] **步骤1：创建组件基础结构**

```tsx
import { useState, useEffect, useCallback } from 'react';
import { ChevronLeft, ChevronRight, X, ZoomIn, ZoomOut, RotateCcw, Upload, Trash2, Wand2 } from 'lucide-react';
import ImageRedrawModal from './shared/ImageRedrawModal';

interface VideoCardWorkbenchProps {
  type: 'character' | 'storyboard' | 'video';
  shotId: number;
  assetId?: number;
  onClose: () => void;
}

interface WorkbenchState {
  currentIndex: number;
  zoomLevel: 1 | 1.35 | 1.7;
  isRedrawModalOpen: boolean;
  editingPrompt: string;
}

export default function VideoCardWorkbench({ type, shotId, assetId, onClose }: VideoCardWorkbenchProps) {
  const [state, setState] = useState<WorkbenchState>({
    currentIndex: 0,
    zoomLevel: 1,
    isRedrawModalOpen: false,
    editingPrompt: '',
  });

  // 键盘快捷键处理
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    switch (e.key) {
      case 'Escape':
        onClose();
        break;
      case 'ArrowLeft':
        // 上一个资源
        break;
      case 'ArrowRight':
        // 下一个资源
        break;
      case '+':
      case '=':
        // 放大
        break;
      case '-':
        // 缩小
        break;
      case 'r':
      case 'R':
        // 打开重绘
        break;
    }
  }, [onClose]);

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
        <button className="rounded-full bg-white/10 p-2 text-white hover:bg-white/20 disabled:opacity-50">
          <ChevronLeft size={20} />
        </button>
        <div className="flex-1 h-full overflow-auto rounded-[24px] bg-black/20 px-4 py-5">
          <div className="mx-auto h-full flex items-center justify-center text-white/50">
            预览区域
          </div>
        </div>
        <button className="rounded-full bg-white/10 p-2 text-white hover:bg-white/20 disabled:opacity-50">
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
          imageSrc=""
          prompt={state.editingPrompt}
          onClose={() => setState(s => ({ ...s, isRedrawModalOpen: false }))}
          onSubmit={(prompt, mask) => {
            // 提交重绘
            setState(s => ({ ...s, isRedrawModalOpen: false }));
          }}
        />
      )}
    </div>
  );
}
```

- [ ] **步骤2：运行TypeScript检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误或仅有警告

- [ ] **步骤3：提交基础组件**

```bash
git add frontend/src/components/VideoCardWorkbench.tsx
git commit -m "feat: 创建VideoCardWorkbench基础组件"
```

---

## 任务2：实现导航和缩放功能

**文件：**
- 修改：`frontend/src/components/VideoCardWorkbench.tsx`

- [ ] **步骤1：添加资源列表状态**

```tsx
// 在VideoCardWorkbenchProps中添加
interface VideoCardWorkbenchProps {
  type: 'character' | 'storyboard' | 'video';
  shotId: number;
  assetId?: number;
  resources: Array<{ id: number; url: string; prompt?: string }>;
  onClose: () => void;
}

// 在组件中添加状态
const [currentIndex, setCurrentIndex] = useState(
  resources.findIndex(r => r.id === assetId) || 0
);
```

- [ ] **步骤2：实现导航函数**

```tsx
const handlePrev = () => {
  setCurrentIndex(i => (i > 0 ? i - 1 : resources.length - 1));
};

const handleNext = () => {
  setCurrentIndex(i => (i < resources.length - 1 ? i + 1 : 0));
};
```

- [ ] **步骤3：更新键盘快捷键**

```tsx
case 'ArrowLeft':
  handlePrev();
  break;
case 'ArrowRight':
  handleNext();
  break;
```

- [ ] **步骤4：更新预览区域显示**

```tsx
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
```

- [ ] **步骤5：运行TypeScript检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误

- [ ] **步骤6：提交导航功能**

```bash
git add frontend/src/components/VideoCardWorkbench.tsx
git commit -m "feat: 实现VideoCardWorkbench导航和缩放功能"
```

---

## 任务3：实现操作按钮功能

**文件：**
- 修改：`frontend/src/components/VideoCardWorkbench.tsx`

- [ ] **步骤1：添加操作回调props**

```tsx
interface VideoCardWorkbenchProps {
  type: 'character' | 'storyboard' | 'video';
  shotId: number;
  assetId?: number;
  resources: Array<{ id: number; url: string; prompt?: string }>;
  onRegenerate: (resourceId: number) => Promise<void>;
  onUploadReplace: (resourceId: number, file: File) => Promise<void>;
  onDelete: (resourceId: number) => Promise<void>;
  onRedraw: (resourceId: number, prompt: string, mask?: Blob) => Promise<void>;
  onClose: () => void;
}
```

- [ ] **步骤2：实现重新生成功能**

```tsx
const [regenerating, setRegenerating] = useState(false);

const handleRegenerate = async () => {
  const resource = resources[currentIndex];
  if (!resource) return;
  
  setRegenerating(true);
  try {
    await onRegenerate(resource.id);
  } finally {
    setRegenerating(false);
  }
};
```

- [ ] **步骤3：实现上传替换功能**

```tsx
const fileInputRef = useRef<HTMLInputElement>(null);

const handleUploadClick = () => {
  fileInputRef.current?.click();
};

const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
  const file = e.target.files?.[0];
  const resource = resources[currentIndex];
  if (!file || !resource) return;
  
  await onUploadReplace(resource.id, file);
  e.target.value = '';
};
```

- [ ] **步骤4：实现删除功能**

```tsx
const [deleting, setDeleting] = useState(false);

const handleDelete = async () => {
  const resource = resources[currentIndex];
  if (!resource) return;
  
  if (!confirm('确定要删除这个资源吗？')) return;
  
  setDeleting(true);
  try {
    await onDelete(resource.id);
    // 如果删除的是最后一个，关闭工作台
    if (resources.length === 1) {
      onClose();
    } else {
      // 切换到下一个
      handleNext();
    }
  } finally {
    setDeleting(false);
  }
};
```

- [ ] **步骤5：实现重绘功能**

```tsx
const handleRedrawClick = () => {
  setState(s => ({ ...s, isRedrawModalOpen: true }));
};

const handleRedrawSubmit = async (prompt: string, mask?: Blob) => {
  const resource = resources[currentIndex];
  if (!resource) return;
  
  await onRedraw(resource.id, prompt, mask);
  setState(s => ({ ...s, isRedrawModalOpen: false }));
};
```

- [ ] **步骤6：更新底部操作栏**

```tsx
{/* 底部操作栏 */}
<div className="border-t border-white/10 px-5 py-4">
  <div className="flex flex-wrap gap-2">
    <button onClick={handleRegenerate} disabled={regenerating} className="flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700 disabled:opacity-50">
      <RotateCcw size={12} /> {regenerating ? '生成中...' : '重新生成'}
    </button>
    <button onClick={handleUploadClick} className="flex items-center gap-2 rounded-lg border border-white/20 px-3 py-1.5 text-xs text-white hover:bg-white/10">
      <Upload size={12} /> 上传替换
    </button>
    <button onClick={handleDelete} disabled={deleting} className="flex items-center gap-2 rounded-lg border border-white/20 px-3 py-1.5 text-xs text-white hover:bg-white/10 disabled:opacity-50">
      <Trash2 size={12} /> {deleting ? '删除中...' : '删除'}
    </button>
    <button onClick={handleRedrawClick} className="flex items-center gap-2 rounded-lg border border-white/20 px-3 py-1.5 text-xs text-white hover:bg-white/10">
      <Wand2 size={12} /> 重绘
    </button>
  </div>
  <input ref={fileInputRef} type="file" accept="image/*" onChange={handleFileChange} className="hidden" />
</div>
```

- [ ] **步骤7：运行TypeScript检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误

- [ ] **步骤8：提交操作按钮功能**

```bash
git add frontend/src/components/VideoCardWorkbench.tsx
git commit -m "feat: 实现VideoCardWorkbench操作按钮功能"
```

---

## 任务4：实现提示词编辑功能

**文件：**
- 修改：`frontend/src/components/VideoCardWorkbench.tsx`

- [ ] **步骤1：添加提示词编辑状态**

```tsx
const [editingPrompt, setEditingPrompt] = useState(
  resources[currentIndex]?.prompt || ''
);

// 当currentIndex变化时更新editingPrompt
useEffect(() => {
  setEditingPrompt(resources[currentIndex]?.prompt || '');
}, [currentIndex, resources]);
```

- [ ] **步骤2：添加提示词编辑区域**

```tsx
{/* 提示词编辑区域 */}
<div className="border-t border-white/10 px-5 py-4">
  <div className="mb-2 flex items-center justify-between">
    <span className="text-xs text-white/70">提示词</span>
    <button 
      onClick={() => setState(s => ({ ...s, showPrompt: !s.showPrompt }))}
      className="text-xs text-white/50 hover:text-white/70"
    >
      {state.showPrompt ? '收起' : '展开'}
    </button>
  </div>
  {state.showPrompt && (
    <textarea
      value={editingPrompt}
      onChange={(e) => setEditingPrompt(e.target.value)}
      className="h-32 w-full rounded-lg border border-white/20 bg-white/5 p-3 text-sm text-white placeholder-white/30 focus:border-white/40 focus:outline-none"
      placeholder="输入提示词..."
    />
  )}
</div>
```

- [ ] **步骤3：添加保存提示词功能**

```tsx
interface VideoCardWorkbenchProps {
  // ... 其他props
  onSavePrompt: (resourceId: number, prompt: string) => Promise<void>;
}

const handleSavePrompt = async () => {
  const resource = resources[currentIndex];
  if (!resource) return;
  
  await onSavePrompt(resource.id, editingPrompt);
};
```

- [ ] **步骤4：更新提示词编辑区域**

```tsx
{state.showPrompt && (
  <div className="mt-2">
    <textarea
      value={editingPrompt}
      onChange={(e) => setEditingPrompt(e.target.value)}
      className="h-32 w-full rounded-lg border border-white/20 bg-white/5 p-3 text-sm text-white placeholder-white/30 focus:border-white/40 focus:outline-none"
      placeholder="输入提示词..."
    />
    <div className="mt-2 flex justify-end">
      <button onClick={handleSavePrompt} className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700">
        保存提示词
      </button>
    </div>
  </div>
)}
```

- [ ] **步骤5：运行TypeScript检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误

- [ ] **步骤6：提交提示词编辑功能**

```bash
git add frontend/src/components/VideoCardWorkbench.tsx
git commit -m "feat: 实现VideoCardWorkbench提示词编辑功能"
```

---

## 任务5：集成到ChapterVideoWorkflowPanel

**文件：**
- 修改：`frontend/src/components/ChapterVideoWorkflowPanel.tsx`

- [ ] **步骤1：添加二级工作台状态**

```tsx
import VideoCardWorkbench from './VideoCardWorkbench';

// 在组件中添加状态
const [workbenchState, setWorkbenchState] = useState<{
  type: 'character' | 'storyboard' | 'video';
  shotId: number;
  assetId?: number;
} | null>(null);
```

- [ ] **步骤2：添加卡片点击处理函数**

```tsx
const handleCardClick = (type: 'character' | 'storyboard' | 'video', shotId: number, assetId?: number) => {
  setWorkbenchState({ type, shotId, assetId });
};
```

- [ ] **步骤3：修改卡片渲染逻辑**

```tsx
// 在镜头卡片渲染中添加点击事件
<div 
  className="cursor-pointer rounded-xl border border-[#d7e3f4] bg-white p-3 shadow-sm hover:shadow-md"
  onClick={() => handleCardClick('character', shot.id)}
>
  <div className="text-xs font-medium text-slate-700">角色资产</div>
  {/* ... 其他内容 */}
</div>

<div 
  className="cursor-pointer rounded-xl border border-[#d7e3f4] bg-white p-3 shadow-sm hover:shadow-md"
  onClick={() => handleCardClick('storyboard', shot.id)}
>
  <div className="text-xs font-medium text-slate-700">故事版</div>
  {/* ... 其他内容 */}
</div>

<div 
  className="cursor-pointer rounded-xl border border-[#d7e3f4] bg-white p-3 shadow-sm hover:shadow-md"
  onClick={() => handleCardClick('video', shot.id)}
>
  <div className="text-xs font-medium text-slate-700">视频</div>
  {/* ... 其他内容 */}
</div>
```

- [ ] **步骤4：渲染二级工作台**

```tsx
{/* 在组件末尾添加二级工作台渲染 */}
{workbenchState && (
  <VideoCardWorkbench
    type={workbenchState.type}
    shotId={workbenchState.shotId}
    assetId={workbenchState.assetId}
    resources={[]} // 需要根据类型获取资源列表
    onRegenerate={async (resourceId) => {
      // 调用相应的重新生成API
    }}
    onUploadReplace={async (resourceId, file) => {
      // 调用相应的上传替换API
    }}
    onDelete={async (resourceId) => {
      // 调用相应的删除API
    }}
    onRedraw={async (resourceId, prompt, mask) => {
      // 调用相应的重绘API
    }}
    onSavePrompt={async (resourceId, prompt) => {
      // 调用相应的保存提示词API
    }}
    onClose={() => setWorkbenchState(null)}
  />
)}
```

- [ ] **步骤5：运行TypeScript检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误

- [ ] **步骤6：提交集成**

```bash
git add frontend/src/components/ChapterVideoWorkflowPanel.tsx
git commit -m "feat: 集成VideoCardWorkbench到ChapterVideoWorkflowPanel"
```

---

## 任务6：移除右侧工作台

**文件：**
- 修改：`frontend/src/components/ChapterVideoWorkflowPanel.tsx`

- [ ] **步骤1：移除右侧工作台状态**

```tsx
// 删除以下状态
const [workspaceTab, setWorkspaceTab] = useState<'final' | 'storyboard' | 'video' | 'characters'>('final');
```

- [ ] **步骤2：移除右侧工作台渲染**

```tsx
{/* 删除整个右侧工作台div，从第617行到第750行 */}
```

- [ ] **步骤3：调整布局样式**

```tsx
// 将原来的三栏布局改为两栏布局
<div className="flex flex-1 gap-4 overflow-hidden">
  {/* 左侧章节列表 */}
  <div className="w-64 shrink-0 overflow-hidden rounded-2xl border border-[#d7e3f4] bg-white shadow-sm">
    {/* ... 章节列表内容 */}
  </div>
  
  {/* 中间分镜流水线 */}
  <div className="flex-1 overflow-hidden rounded-2xl border border-[#d7e3f4] bg-white shadow-sm">
    {/* ... 分镜流水线内容 */}
  </div>
</div>
```

- [ ] **步骤4：运行TypeScript检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误

- [ ] **步骤5：提交移除右侧工作台**

```bash
git add frontend/src/components/ChapterVideoWorkflowPanel.tsx
git commit -m "feat: 移除ChapterVideoWorkflowPanel中的右侧工作台"
```

---

## 任务7：调整VideoStoryboardLayout布局

**文件：**
- 修改：`frontend/src/components/VideoStoryboardLayout.tsx`

- [ ] **步骤1：读取当前布局结构**

```bash
cat frontend/src/components/VideoStoryboardLayout.tsx
```

- [ ] **步骤2：移除右侧工作台容器**

```tsx
// 如果有右侧工作台容器，移除它
```

- [ ] **步骤3：调整布局样式**

```tsx
// 确保布局适应新的两栏结构
```

- [ ] **步骤4：运行TypeScript检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误

- [ ] **步骤5：提交布局调整**

```bash
git add frontend/src/components/VideoStoryboardLayout.tsx
git commit -m "feat: 调整VideoStoryboardLayout布局"
```

---

## 任务8：实现类型特定的功能

**文件：**
- 修改：`frontend/src/components/VideoCardWorkbench.tsx`

- [ ] **步骤1：实现角色资产特定功能**

```tsx
// 根据type属性显示不同的操作按钮
const renderCharacterActions = () => (
  <>
    <button onClick={handleRegenerate} disabled={regenerating} className="flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700 disabled:opacity-50">
      <RotateCcw size={12} /> {regenerating ? '生成中...' : '重新生成'}
    </button>
    <button onClick={handleUploadClick} className="flex items-center gap-2 rounded-lg border border-white/20 px-3 py-1.5 text-xs text-white hover:bg-white/10">
      <Upload size={12} /> 上传替换
    </button>
    <button onClick={handleDelete} disabled={deleting} className="flex items-center gap-2 rounded-lg border border-white/20 px-3 py-1.5 text-xs text-white hover:bg-white/10 disabled:opacity-50">
      <Trash2 size={12} /> {deleting ? '删除中...' : '删除'}
    </button>
    <button onClick={handleRedrawClick} className="flex items-center gap-2 rounded-lg border border-white/20 px-3 py-1.5 text-xs text-white hover:bg-white/10">
      <Wand2 size={12} /> 重绘
    </button>
  </>
);
```

- [ ] **步骤2：实现故事版特定功能**

```tsx
const renderStoryboardActions = () => (
  <>
    <button onClick={handleRegenerate} disabled={regenerating} className="flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700 disabled:opacity-50">
      <RotateCcw size={12} /> {regenerating ? '生成中...' : '重新生成'}
    </button>
    <button onClick={handleUploadClick} className="flex items-center gap-2 rounded-lg border border-white/20 px-3 py-1.5 text-xs text-white hover:bg-white/10">
      <Upload size={12} /> 上传替换
    </button>
    <button onClick={handleDelete} disabled={deleting} className="flex items-center gap-2 rounded-lg border border-white/20 px-3 py-1.5 text-xs text-white hover:bg-white/10 disabled:opacity-50">
      <Trash2 size={12} /> {deleting ? '删除中...' : '删除'}
    </button>
    <button onClick={handleRedrawClick} className="flex items-center gap-2 rounded-lg border border-white/20 px-3 py-1.5 text-xs text-white hover:bg-white/10">
      <Wand2 size={12} /> 重绘
    </button>
    <button onClick={handleAnalyzePrompt} className="flex items-center gap-2 rounded-lg border border-white/20 px-3 py-1.5 text-xs text-white hover:bg-white/10">
      <Sparkles size={12} /> 分析提示词
    </button>
  </>
);
```

- [ ] **步骤3：实现视频特定功能**

```tsx
const renderVideoActions = () => (
  <>
    <button onClick={handleRegenerate} disabled={regenerating} className="flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700 disabled:opacity-50">
      <RotateCcw size={12} /> {regenerating ? '生成中...' : '重新生成'}
    </button>
    <button onClick={handleDelete} disabled={deleting} className="flex items-center gap-2 rounded-lg border border-white/20 px-3 py-1.5 text-xs text-white hover:bg-white/10 disabled:opacity-50">
      <Trash2 size={12} /> {deleting ? '删除中...' : '删除'}
    </button>
  </>
);
```

- [ ] **步骤4：根据type渲染对应的操作按钮**

```tsx
{/* 底部操作栏 */}
<div className="border-t border-white/10 px-5 py-4">
  <div className="flex flex-wrap gap-2">
    {type === 'character' && renderCharacterActions()}
    {type === 'storyboard' && renderStoryboardActions()}
    {type === 'video' && renderVideoActions()}
  </div>
  <input ref={fileInputRef} type="file" accept="image/*" onChange={handleFileChange} className="hidden" />
</div>
```

- [ ] **步骤5：运行TypeScript检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误

- [ ] **步骤6：提交类型特定功能**

```bash
git add frontend/src/components/VideoCardWorkbench.tsx
git commit -m "feat: 实现VideoCardWorkbench类型特定功能"
```

---

## 任务9：测试和修复

- [ ] **步骤1：运行TypeScript检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误

- [ ] **步骤2：运行ESLint检查**

Run: `cd frontend && npm run lint`
Expected: 无错误

- [ ] **步骤3：构建项目**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **步骤4：手动测试功能**

1. 启动开发服务器：`cd frontend && npm run dev`
2. 访问视频工作流页面
3. 测试点击角色资产卡片进入二级工作台
4. 测试点击故事版卡片进入二级工作台
5. 测试点击视频卡片进入二级工作台
6. 测试导航功能（左右箭头、键盘快捷键）
7. 测试缩放功能
8. 测试操作按钮（重新生成、上传替换、删除、重绘）
9. 测试提示词编辑功能
10. 测试关闭二级工作台

- [ ] **步骤5：修复发现的问题**

- [ ] **步骤6：提交最终版本**

```bash
git add .
git commit -m "feat: 完成视频工作流二级工作台重构"
```

---

## 验证清单

- [ ] 移除右侧320px内嵌工作台
- [ ] 点击卡片进入全屏二级工作台
- [ ] 二级工作台支持深色背景布局
- [ ] 支持三级缩放（100%/135%/170%）
- [ ] 支持键盘导航（左右箭头、ESC）
- [ ] 支持重新生成功能
- [ ] 支持上传替换功能
- [ ] 支持删除功能（带确认）
- [ ] 支持重绘功能（集成ImageRedrawModal）
- [ ] 支持提示词编辑功能
- [ ] 不同卡片类型显示对应的操作按钮
- [ ] 所有TypeScript检查通过
- [ ] 所有ESLint检查通过
- [ ] 项目构建成功
- [ ] 手动测试通过