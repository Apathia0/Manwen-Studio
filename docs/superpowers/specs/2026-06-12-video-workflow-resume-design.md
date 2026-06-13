# 视频工作流无硬超时与状态恢复设计

## 背景

当前章节视频工作流通过 `TaskManager.submit_task()` 在后台运行，但任务被统一包裹在 `asyncio.wait_for(..., timeout=timeout)` 中。

对于 chapter video workflow，当前调用方在 `backend/services/video_chapter_pipeline.py` 中传入的是：

- `timeout=1800.0`（30 分钟）

这导致问题：

1. 视频任务本身运行时间过长时，会被统一任务级超时直接中断。
2. 前端页面关闭后，虽然浏览器本地轮询停止，但后端任务寿命仍被同一 timeout 规则约束。
3. 用户重新打开页面时，只能依赖已有 workflow 状态恢复；如果后台任务已因 timeout 被杀掉，恢复就没有意义。

用户要求：

- 视频任务不再因统一任务超时被强制失败
- 用户关闭窗口后后台继续执行
- 用户重新打开页面时自动恢复状态与轮询

## 目标

将“后台执行寿命”和“前端页面监听寿命”彻底解耦，使章节视频工作流具备以下行为：

1. 页面关闭不会取消后台任务
2. 后台任务没有统一任务级硬超时
3. 用户重新打开页面后自动恢复 workflow 状态与轮询
4. 任务只会因为成功、业务失败或用户主动取消而结束

## 核心原则

### 1. 页面关闭 ≠ 任务取消

前端页面关闭仅表示：

- 停止浏览器本地轮询器

不表示：

- 取消后台任务
- 将工作流标记失败
- 停止 provider 轮询

### 2. 任务级超时与 provider 级超时分离

本次需要明确区分两类超时：

- **任务级超时**：整个章节视频工作流必须在 N 秒内结束
  - 本次移除

- **provider 级超时**：某一次外部轮询或请求最多等待多长时间
  - 可以继续存在，并单独配置

也就是说，本次设计只取消“整个后台任务的硬寿命限制”，不等于移除所有外部调用保护。

## 设计方案

### 1. 章节视频工作流取消任务级硬超时

在 `TaskManager.submit_task()` 中，当前统一使用：

```python
asyncio.wait_for(coro_func(...), timeout=timeout)
```

本次要求：

- 章节视频工作流不再传任务级硬超时
- `TaskManager` 必须支持“无超时任务”
- 当 timeout 为 `None` 时，直接执行协程，不包裹 `wait_for`

这样后台任务可以持续运行到自然完成，而不会因为统一超时被中断。

### 2. 后台状态继续以持久化记录为真源

当前已有两类状态真源：

- `BackgroundTask`
- `ChapterVideoWorkflow`

本次不新增新的任务中心，只继续依赖这两层持久化状态：

- 后台任务运行态
- workflow 阶段态
- 已完成镜头数
- 失败镜头数
- 错误信息

前端恢复逻辑统一信任这些持久化状态，而不依赖浏览器本地内存。

### 3. 前端页面重开后自动恢复轮询

`VideoStoryboardLayout` 当前已经有：

- `loadLatestWorkflow()`
- `getChapterVideoWorkflowStatus()`
- `pollWorkflowUntilSettled()`

本次设计要求将其明确固化为恢复模型：

1. 页面进入时加载最新 workflow
2. 若 workflow 状态属于运行中阶段：
   - `parsing_shots`
   - `generating_storyboards`
   - `generating_videos`
3. 自动恢复轮询
4. 恢复 loading / running UI 状态

页面关闭时：

- 仅停止本地 `setTimeout` / polling timer
- 不发取消请求

### 4. 任务结束条件收敛

章节视频工作流任务结束只保留以下三类：

1. **成功完成**
2. **业务失败**（provider 返回失败、生成异常、依赖缺失等）
3. **用户主动取消**

本次移除“因为统一任务超时而失败”这一条。

### 5. stale task 清理策略保持独立

当前 `TaskManager.cleanup_stale_tasks()` 会清理创建太久仍处于运行状态的任务。

本次设计不移除 stale 清理机制，但要明确：

- 它是“僵尸任务兜底清理”
- 不是“正常长任务的标准结束方式”

也就是说，长视频任务应该优先通过自然完成 / 用户取消结束，而不是依赖 cleanup。

## 范围

### 包含

- `TaskManager` 的 timeout 行为调整
- chapter video workflow 后台提交逻辑调整
- `VideoStoryboardLayout` 的状态恢复轮询逻辑固化
- workflow 运行中状态恢复体验

### 不包含

- WebSocket / SSE 主动推送
- 浏览器系统通知
- 邮件 / 站内信 / 企业微信通知
- 全局任务中心重构
- 新增复杂任务订阅机制

## 风险

### 风险 1：任务无限运行

取消任务级硬超时后，如果 provider 一直不返回成功/失败，任务理论上可能长时间停留在运行中。

应对方式：

- 保留 provider 级轮询超时或错误判定
- 保留 stale cleanup 作为兜底

### 风险 2：前端恢复时状态不一致

若前端重新进入页面时：

- workflow 状态更新了
- 但 chapter assets / detail / status 未一起刷新

可能出现 UI 与实际后台状态不同步。

应对方式：

- 页面恢复时统一刷新 workflow detail 与 chapter assets
- polling 中每轮都以服务端状态为准

### 风险 3：取消语义混乱

如果未来有人误以为“关闭页面 = 取消任务”，会再次引入耦合。

应对方式：

- 在实现中明确分离 `stopPolling()` 和取消 API
- 保留独立的主动取消入口

## 测试策略

### 后端测试

至少覆盖：

1. chapter video workflow 提交时允许无 timeout
2. `TaskManager.submit_task()` 在 timeout 为 `None` 时不包裹 `wait_for`
3. chapter workflow 任务不会因统一 timeout 被标记 failed

### 前端测试

至少覆盖：

1. 页面重新进入时，如果 workflow 状态为运行中，会自动恢复 polling
2. 页面卸载只停止本地轮询，不发取消请求

### 手动验证

至少验证：

1. 启动长视频任务
2. 关闭页面
3. 等待任务继续运行一段时间
4. 重新打开页面
5. 自动恢复状态与轮询
6. 最终看到完成或失败结果

## 验收标准

满足以下条件即视为完成：

1. 章节视频工作流不再因为统一任务级 timeout 被强制失败
2. 页面关闭不影响后台任务继续运行
3. 页面重新打开后自动恢复 workflow 状态与轮询
4. 任务结束只由成功、业务失败或用户主动取消驱动
5. 前端恢复后的状态展示与后台真实状态一致

## Implementation Notes

- `TaskManager.submit_task()` 已在 `backend/services/task_manager.py` 中支持 `timeout=None`，当 timeout 为 None 时不包裹 `asyncio.wait_for`。
- `start_workflow_background()` 已改为 `timeout=None`，不再传 1800 秒硬超时。
- 前端 `VideoStoryboardLayout` 页面进入时若 workflow 处于运行态，会自动恢复 `pollWorkflowUntilSettled()`。
- 页面卸载时仅停止本地轮询器，不发送任何取消请求。
