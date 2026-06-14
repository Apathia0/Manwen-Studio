# 视频生成任务卡片级loading状态跟踪设计

## 1. 概述

### 1.1 需求背景
用户在视频工作流中点击"生成视频"后，如果关闭工作台弹窗（VideoCardWorkbench），希望在每个镜头的视频卡片区域看到一个loading状态，显示任务正在进行中，直到生成完成自动更新。

### 1.2 核心目标
1. 用户关闭工作台弹窗后，在卡片区域显示loading生成中状态
2. 状态要跟踪任务状态（pending/running/succeeded/failed）
3. 生成完成后按原流程自行渲染（自动更新UI显示视频）

### 1.3 设计原则
1. **复用现有机制**：充分利用videoGenStore和pollWorkflowUntilSettled
2. **最小改动**：在现有架构基础上扩展，不引入新的状态管理库
3. **用户体验优先**：提供清晰的视觉反馈，支持页面刷新后恢复状态

## 2. 架构设计

### 2.1 整体架构
```
用户点击"生成视频"（选择部分镜头）
  ↓
前端：1. 调用 generateChapterWorkflowVideos(workflowId, { shot_ids })
     2. 为每个选中的镜头在 videoGenStore 中创建状态（active: true, status: 'pending'）
     3. 启动轮询 pollWorkflowUntilSettled()
  ↓
后端：1. 更新 workflow_status = "generating_videos"
     2. 提交异步任务 generate_videos_for_shots()
     3. 立即返回
  ↓
前端轮询：每4秒检查 workflow_status
  ↓
后端异步：逐个镜头生成视频，更新 workflow 进度
  ↓
前端轮询检测到 workflow_status 不再是 ACTIVE_STATUSES
  ↓
前端：1. 停止轮询
     2. 为每个镜头更新 videoGenStore 状态（active: false, status: 'succeeded' 或 'failed'）
     3. 重新加载工作流详情，更新卡片显示
```

### 2.2 数据流
1. **提交阶段**：前端创建videoGenStore状态 → 调用后端API → 启动轮询
2. **执行阶段**：后端异步生成 → 前端轮询检测状态变化
3. **完成阶段**：前端更新videoGenStore状态 → 重新加载工作流详情 → UI更新

## 3. 状态管理设计

### 3.1 videoGenStore扩展现有结构
videoGenStore已支持按shotId存储状态，无需修改数据结构，只需在提交生成时调用startJob，在完成时调用markSucceeded/markFailed。

### 3.2 提交生成时的状态初始化
在`VideoStoryboardLayout.tsx`的`handleGenerateVideos`中：
```typescript
const handleGenerateVideos = useCallback(async (shotIds: number[]) => {
  setWorkflowRunning(true);
  
  // 1. 为每个选中的镜头创建初始状态
  shotIds.forEach(shotId => {
    videoGenStore.startJob(shotId, 0); // jobId暂时为0，后端返回后更新
  });
  
  // 2. 提交生成请求
  const status = await generateChapterWorkflowVideos(workflow.id, { shot_ids: shotIds });
  
  // 3. 更新每个镜头的task_id（后端返回整个任务的task_id，不是每个镜头单独的jobId）
  // videoGenStore中jobId字段可以存储整个任务的task_id，用于后续状态跟踪
  if (status.task_id) {
    shotIds.forEach(shotId => {
      videoGenStore.patch(shotId, { jobId: 0 }); // 存储task_id用于状态跟踪
    });
  }
  
  // 4. 启动轮询
  void pollWorkflowUntilSettled(workflow.id);
}, [workflow]);
```

### 3.3 轮询逻辑增强
在`pollWorkflowUntilSettled`中，当工作流完成时更新所有镜头状态：
```typescript
const pollWorkflowUntilSettled = async (workflowId: number) => {
  // ...现有轮询逻辑...
  
  if (!running) {
    // 工作流完成，更新所有镜头状态
    const detail = await getChapterVideoWorkflow(workflowId);
    detail.shots.forEach(shot => {
      if (shot.status === 'video_ready') {
        videoGenStore.markSucceeded(shot.id);
      } else if (shot.status === 'failed') {
        videoGenStore.markFailed(shot.id, '视频生成失败');
      }
    });
  }
};
```

## 4. UI显示设计

### 4.1 卡片区域loading状态
在`ChapterVideoWorkflowPanel.tsx`中，为每个镜头的视频卡片添加loading显示：
```tsx
const VideoCard = ({ shot }) => {
  const videoState = videoGenStore.get(shot.id);
  const isGenerating = videoState?.active && videoState.status === 'pending';
  
  return (
    <div className="relative">
      {shot.video_url ? (
        // 已有视频：显示视频预览
        <video src={shot.video_url} controls />
      ) : isGenerating ? (
        // 生成中：显示loading状态
        <div className="flex flex-col items-center justify-center p-4 border-2 border-dashed border-blue-200 rounded-lg bg-blue-50">
          <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
          <span className="mt-2 text-sm text-blue-600">视频生成中...</span>
          {videoState.statusMsg && (
            <span className="mt-1 text-xs text-blue-500">{videoState.statusMsg}</span>
          )}
        </div>
      ) : (
        // 无视频且未生成：显示原始状态
        <div className="text-center text-gray-400 p-4">暂无视频</div>
      )}
    </div>
  );
};
```

### 4.2 状态标签增强
在镜头状态标签中，显示更详细的状态：
```tsx
const ShotStatusLabel = ({ shot }) => {
  const videoState = videoGenStore.get(shot.id);
  
  if (videoState?.active) {
    return (
      <span className="bg-blue-100 text-blue-600">
        {videoState.statusMsg || '视频生成中'}
      </span>
    );
  }
  
  // ...现有的状态标签逻辑...
};
```

## 5. 错误处理与边界情况

### 5.1 错误处理
1. **网络错误**：轮询失败时，保持最后已知状态，不自动重试
2. **任务失败**：后端标记任务失败时，前端更新videoGenStore状态为failed
3. **页面刷新**：videoGenStore已支持localStorage持久化，刷新后恢复状态
4. **组件卸载**：使用AbortController和stopPolling()确保清理

### 5.2 边界情况
1. **重复提交**：检查videoGenStore中是否已有active状态，防止重复提交
2. **部分镜头生成**：只更新选中的镜头状态，不影响其他镜头
3. **长时间无响应**：后端有30分钟超时，前端轮询会检测到状态变化
4. **并发更新**：videoGenStore使用发布订阅模式，确保UI一致性

## 6. 测试策略

### 6.1 单元测试
1. **videoGenStore测试**：验证startJob、patch、markSucceeded、markFailed、localStorage持久化
2. **状态转换测试**：验证从pending到running到succeeded/failed的转换逻辑
3. **边界情况测试**：验证重复提交、页面刷新、组件卸载等场景

### 6.2 集成测试
1. **轮询逻辑测试**：验证pollWorkflowUntilSettled正确更新videoGenStore状态
2. **UI渲染测试**：验证loading状态正确显示，生成完成后正确切换为视频预览
3. **错误处理测试**：验证网络错误、任务失败等场景的UI反馈

### 6.3 E2E测试
1. **完整流程测试**：从提交生成到查看loading状态到生成完成的全流程
2. **关闭窗口测试**：验证关闭工作台弹窗后，卡片区域正确显示loading状态

## 7. 实现步骤

### 7.1 前端改动
1. **VideoStoryboardLayout.tsx**：在handleGenerateVideos中为每个镜头创建videoGenStore状态
2. **ChapterVideoWorkflowPanel.tsx**：在视频卡片区域订阅videoGenStore，显示loading状态
3. **状态标签组件**：增强状态标签显示，支持显示生成中状态

### 7.2 后端改动
1. **无需改动**：现有后端已支持异步任务提交和状态跟踪
2. **可选优化**：在generate_videos_for_shots中为每个镜头更新videoGenStore状态（如果需要更细粒度的进度）

### 7.3 测试改动
1. **新增单元测试**：videoGenStore的新增功能测试
2. **新增集成测试**：轮询逻辑与videoGenStore的集成测试
3. **新增E2E测试**：完整的用户流程测试

## 8. 风险评估

### 8.1 技术风险
1. **状态同步**：videoGenStore与轮询状态的同步可能存在问题
2. **性能影响**：频繁更新videoGenStore可能影响性能
3. **内存泄漏**：轮询和状态订阅需要正确清理

### 8.2 缓解措施
1. **使用现有的发布订阅模式**：videoGenStore已设计为轻量级状态管理
2. **批量更新**：在轮询完成时批量更新所有镜头状态
3. **正确的清理逻辑**：在组件卸载时停止轮询和取消订阅

## 9. 总结

本设计通过扩展现有的videoGenStore和轮询机制，为视频生成任务添加了卡片级的loading状态跟踪。设计遵循最小改动原则，复用现有架构，提供清晰的视觉反馈，支持页面刷新后恢复状态。实现复杂度适中，用户体验显著提升。