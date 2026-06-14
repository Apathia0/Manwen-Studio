# 视频生成任务卡片级loading状态跟踪实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为视频生成任务添加卡片级loading状态跟踪，让用户关闭工作台弹窗后能在卡片区域看到任务生成中的状态。

**Architecture:** 扩展现有的videoGenStore和pollWorkflowUntilSettled机制，在提交生成时为每个镜头创建状态，在轮询完成时更新状态，在卡片区域订阅显示loading状态。

**Tech Stack:** React 19, TypeScript, Vite, Tailwind CSS v4, videoGenStore (localStorage持久化)

---

## 文件结构

### 修改文件
- `frontend/src/components/VideoStoryboardLayout.tsx` - 修改handleGenerateVideos函数，添加videoGenStore状态初始化
- `frontend/src/components/ChapterVideoWorkflowPanel.tsx` - 修改视频卡片区域，添加loading状态显示
- `frontend/src/videoGenStore.ts` - 无需修改，现有API已满足需求

### 测试文件
- `frontend/src/components/videoWorkbenchUtils.test.ts` - 添加videoGenStore相关测试

---

## 任务分解

### Task 1: 在VideoStoryboardLayout中添加videoGenStore状态初始化

**Files:**
- Modify: `frontend/src/components/VideoStoryboardLayout.tsx:414-430`

- [ ] **Step 1: 导入videoGenStore**

在VideoStoryboardLayout.tsx文件顶部添加导入：
```typescript
import { videoGenStore } from '../videoGenStore';
```

- [ ] **Step 2: 修改handleGenerateVideos函数**

在handleGenerateVideos函数中，为每个选中的镜头创建videoGenStore状态：
```typescript
const handleGenerateVideos = useCallback(async (shotIds: number[]) => {
  if (!workflow) return;
  if (shotIds.length === 0) {
    toast.error('请先勾选需要生成视频的镜头');
    return;
  }
  try {
    setWorkflowRunning(true);
    
    // 为每个选中的镜头创建初始状态
    shotIds.forEach(shotId => {
      videoGenStore.startJob(shotId, 0);
    });
    
    const status = await generateChapterWorkflowVideos(workflow.id, { shot_ids: shotIds });
    setWorkflow((prev) => (prev && prev.id === workflow.id ? { ...prev, ...(status as Partial<ChapterVideoWorkflow>) } : prev));
    toast.success('视频生成任务已提交');
    void pollWorkflowUntilSettled(workflow.id);
  } catch (error: any) {
    setWorkflowRunning(false);
    toast.error(`视频生成失败: ${error.message || '未知错误'}`);
  }
}, [pollWorkflowUntilSettled, workflow]);
```

- [ ] **Step 3: 验证修改**

运行TypeScript检查：
```bash
cd frontend && npx tsc --noEmit
```
预期：无类型错误

- [ ] **Step 4: 提交修改**

```bash
git add frontend/src/components/VideoStoryboardLayout.tsx
git commit -m "feat: 在视频生成提交时初始化videoGenStore状态"
```

---

### Task 2: 在pollWorkflowUntilSettled中更新videoGenStore状态

**Files:**
- Modify: `frontend/src/components/VideoStoryboardLayout.tsx:114-146`

- [ ] **Step 1: 修改pollWorkflowUntilSettled函数**

在pollWorkflowUntilSettled函数中，当工作流完成时更新所有镜头状态：
```typescript
const pollWorkflowUntilSettled = useCallback(async (workflowId: number) => {
  stopPolling();

  // 只有后台真正在处理的状态才算 running，等待用户操作的空闲状态不算
  const ACTIVE_STATUSES = new Set(['parsing_shots', 'generating_storyboards', 'generating_videos', 'reanalyzing_prompts', 'generating_details']);

  const tick = async () => {
    try {
      const status = await getChapterVideoWorkflowStatus(workflowId);
      const detail = await getChapterVideoWorkflow(workflowId);
      setWorkflow({ ...detail, ...status });

      const running = ACTIVE_STATUSES.has(status.workflow_status);
      setWorkflowRunning(running);

      if (running) {
        pollTimerRef.current = window.setTimeout(() => {
          void tick();
        }, 4000);
        return;
      }

      // 工作流完成，更新所有镜头状态
      detail.shots.forEach(shot => {
        if (shot.status === 'video_ready') {
          videoGenStore.markSucceeded(shot.id);
        } else if (shot.status === 'failed') {
          videoGenStore.markFailed(shot.id, '视频生成失败');
        }
      });

      // 解析完成，清除 parsing 状态
      setParsing(false);
      await loadChapterAssets(status.chapter_id);
    } catch (error: any) {
      setWorkflowRunning(false);
      toast.error(`刷新视频工作流失败: ${error.message || '未知错误'}`);
    }
  };

  void tick();
}, [loadChapterAssets, stopPolling]);
```

- [ ] **Step 2: 验证修改**

运行TypeScript检查：
```bash
cd frontend && npx tsc --noEmit
```
预期：无类型错误

- [ ] **Step 3: 提交修改**

```bash
git add frontend/src/components/VideoStoryboardLayout.tsx
git commit -m "feat: 在轮询完成时更新videoGenStore状态"
```

---

### Task 3: 在ChapterVideoWorkflowPanel中添加视频卡片loading状态显示

**Files:**
- Modify: `frontend/src/components/ChapterVideoWorkflowPanel.tsx:513-532`

- [ ] **Step 1: 导入videoGenStore**

在ChapterVideoWorkflowPanel.tsx文件顶部添加导入：
```typescript
import { videoGenStore } from '../videoGenStore';
```

- [ ] **Step 2: 修改视频卡片渲染逻辑**

在视频卡片区域，添加loading状态显示：
```typescript
// 在ChapterVideoWorkflowPanel组件中，找到视频卡片按钮（约第513-532行）
// 修改为：
<button
  type="button"
  onClick={() => setVideoWorkbench({ shotId: shot.id, type: 'video' })}
  className="rounded-xl border border-[#e5edf8] bg-slate-50 p-2 text-left transition hover:border-blue-300 hover:bg-white"
>
  <div className="mb-2 flex items-center gap-1 text-xs font-medium text-slate-600">
    <Film size={12} /> 视频
  </div>
  {(() => {
    const videoState = videoGenStore.get(shot.id);
    const isGenerating = videoState?.active && videoState.status === 'pending';
    
    if (hasVideo) {
      return (
        <video
          src={toAssetUrl(shot.video_url)}
          controls
          className="h-32 w-full rounded-lg bg-slate-950 object-contain"
        />
      );
    } else if (isGenerating) {
      return (
        <div className="flex h-32 flex-col items-center justify-center rounded-lg border-2 border-dashed border-blue-200 bg-blue-50">
          <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
          <span className="mt-2 text-sm text-blue-600">视频生成中...</span>
          {videoState.statusMsg && (
            <span className="mt-1 text-xs text-blue-500">{videoState.statusMsg}</span>
          )}
        </div>
      );
    } else {
      return (
        <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-[#d7e3f4] bg-white text-xs text-slate-400">
          暂无视频
        </div>
      );
    }
  })()}
</button>
```

- [ ] **Step 3: 验证修改**

运行TypeScript检查：
```bash
cd frontend && npx tsc --noEmit
```
预期：无类型错误

- [ ] **Step 4: 提交修改**

```bash
git add frontend/src/components/ChapterVideoWorkflowPanel.tsx
git commit -m "feat: 在视频卡片区域显示loading状态"
```

---

### Task 4: 添加videoGenStore单元测试

**Files:**
- Modify: `frontend/src/components/videoWorkbenchUtils.test.ts`

- [ ] **Step 1: 添加videoGenStore测试用例**

在videoWorkbenchUtils.test.ts文件中添加videoGenStore相关测试：
```typescript
// 在文件末尾添加
describe('videoGenStore', () => {
  beforeEach(() => {
    // 清除localStorage
    localStorage.clear();
  });

  it('should store and retrieve video generation state', () => {
    const shotId = 123;
    const jobId = 456;
    
    // 开始任务
    videoGenStore.startJob(shotId, jobId);
    
    // 获取状态
    const state = videoGenStore.get(shotId);
    expect(state).toBeDefined();
    expect(state?.active).toBe(true);
    expect(state?.jobId).toBe(jobId);
    expect(state?.status).toBe('pending');
  });

  it('should update progress', () => {
    const shotId = 123;
    const jobId = 456;
    
    videoGenStore.startJob(shotId, jobId);
    videoGenStore.updateProgress(shotId, 'running', 50, '正在生成...');
    
    const state = videoGenStore.get(shotId);
    expect(state?.status).toBe('running');
    expect(state?.progress).toBe(50);
    expect(state?.statusMsg).toBe('正在生成...');
  });

  it('should mark as succeeded', () => {
    const shotId = 123;
    const jobId = 456;
    
    videoGenStore.startJob(shotId, jobId);
    videoGenStore.markSucceeded(shotId);
    
    const state = videoGenStore.get(shotId);
    expect(state?.active).toBe(false);
    expect(state?.status).toBe('succeeded');
    expect(state?.progress).toBe(100);
  });

  it('should mark as failed', () => {
    const shotId = 123;
    const jobId = 456;
    
    videoGenStore.startJob(shotId, jobId);
    videoGenStore.markFailed(shotId, '生成失败');
    
    const state = videoGenStore.get(shotId);
    expect(state?.active).toBe(false);
    expect(state?.status).toBe('failed');
    expect(state?.errorMsg).toBe('生成失败');
  });

  it('should persist to localStorage', () => {
    const shotId = 123;
    const jobId = 456;
    
    videoGenStore.startJob(shotId, jobId);
    
    // 重新加载页面（模拟）
    const stored = localStorage.getItem('video_gen_states');
    expect(stored).toBeDefined();
    
    const parsed = JSON.parse(stored!);
    expect(parsed[shotId]).toBeDefined();
    expect(parsed[shotId].active).toBe(true);
  });
});
```

- [ ] **Step 2: 运行测试**

```bash
cd frontend && npm test -- --run videoWorkbenchUtils.test.ts
```
预期：所有测试通过

- [ ] **Step 3: 提交修改**

```bash
git add frontend/src/components/videoWorkbenchUtils.test.ts
git commit -m "test: 添加videoGenStore单元测试"
```

---

### Task 5: 端到端验证

**Files:**
- Manual testing

- [ ] **Step 1: 启动开发服务器**

```bash
cd frontend && npm run dev
```

- [ ] **Step 2: 测试完整流程**

1. 打开视频工作流页面
2. 选择几个镜头
3. 点击"生成视频"按钮
4. 关闭工作台弹窗（如果打开）
5. 观察卡片区域是否显示loading状态
6. 等待生成完成，观察loading状态是否消失，视频是否正常显示

- [ ] **Step 3: 测试边界情况**

1. 测试页面刷新后loading状态是否恢复
2. 测试网络错误时的UI反馈
3. 测试部分镜头生成完成的情况

- [ ] **Step 4: 验证无回归**

运行现有测试确保没有破坏现有功能：
```bash
cd frontend && npm test
```
预期：所有现有测试通过

---

## 自检清单

1. **Spec覆盖**：检查设计文档中的每个需求是否都有对应的任务
   - ✅ 用户关闭工作台弹窗后，在卡片区域显示loading生成中状态 → Task 3
   - ✅ 状态要跟踪任务状态（pending/running/succeeded/failed） → Task 1, 2
   - ✅ 生成完成后按原流程自行渲染 → Task 2

2. **占位符扫描**：检查计划中是否有TBD、TODO等占位符
   - ✅ 无占位符，所有步骤都有具体代码

3. **类型一致性**：检查所有类型、方法签名是否一致
   - ✅ videoGenStore的API使用一致：startJob, markSucceeded, markFailed
   - ✅ 组件props类型一致

4. **完整性检查**：每个步骤都有完整的代码和验证命令
   - ✅ 每个任务都有TypeScript检查和提交步骤
   - ✅ 有端到端验证步骤