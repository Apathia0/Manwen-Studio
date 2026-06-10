# 章节视频分阶段工作流设计

**目标**：将当前“章节正文 → 拆镜 → 故事版 → 视频 → 拼接”的一键全自动流程，改造成**默认分阶段手动控制**，同时保留一键生成作为辅助模式；并修复故事版图片阶段错误使用 DeepSeek key 调 Image2 导致的 401 问题。

## 1. 现状问题

### 1.1 当前流程过度自动化

当前后端主链路在 [backend/services/video_chapter_pipeline.py](file:///C:/Users/Administrator/Desktop/Desktop/Manwen-Studio/backend/services/video_chapter_pipeline.py) 的 `run_chapter_video_workflow()` 中被硬编码为顺序串联：

1. 正文拆镜
2. 自动生成全部故事版图片
3. 自动生成全部视频
4. 前端仅轮询状态并展示结果

这导致用户无法：

- 先审核拆镜结果再继续
- 只选择部分镜头生成故事版
- 编辑故事版提示词后再生成图片
- 只选择部分故事版成功镜头进入视频阶段
- 在某一阶段失败后停住并手动处理

### 1.2 故事版图片鉴权错误

当前章节工作流创建入口在 [backend/routers/video.py](file:///C:/Users/Administrator/Desktop/Desktop/Manwen-Studio/backend/routers/video.py) 中使用的是 `_user_deepseek_api_key()`，并把这个 key 传入后台工作流，再继续传给 `image_service.generate_manga_image()`。

这意味着：

- DeepSeek key 被当成 Image2 key 使用
- `https://newapi.aifusion6.cn/v1/images/generations` 收到错误 token
- 故事版图片阶段批量 401，日志显示 `Invalid token`

### 1.3 手动入口缺失

当前 [frontend/src/components/ChapterVideoWorkflowPanel.tsx](file:///C:/Users/Administrator/Desktop/Desktop/Manwen-Studio/frontend/src/components/ChapterVideoWorkflowPanel.tsx) 只有：

- 一键生成整章视频
- 重生故事版
- 重生视频
- 拼接成片

缺少：

- 重新分析故事版提示词
- 编辑故事版提示词
- 勾选镜头后批量生成故事版
- 勾选镜头后批量生成视频
- 按阶段推进的用户确认断点

## 2. 用户确认的设计原则

### 2.1 主模式

- **默认主模式：分阶段手动控制**
- **辅助模式：一键全自动保留**

### 2.2 阶段推进原则

主路径应改为：

1. 仅拆镜
2. 用户审核镜头
3. 勾选镜头并编辑故事版提示词
4. 批量/逐镜生成故事版
5. 用户再次勾选镜头进入视频阶段
6. 批量/逐镜生成视频
7. 拼接成片

### 2.3 失败处理原则

- **故事版阶段失败即停在当前阶段**
- 不自动继续到视频阶段
- 用户自行决定：
  - 重新分析 prompt
  - 重新生成故事版
  - 跳过个别镜头
  - 或确认继续下一阶段

### 2.4 镜头级控制粒度

拆镜完成后，默认允许：

- 勾选镜头
- 编辑故事版提示词
- 重新分析故事版提示词
- 生成故事版

不默认开放过重的结构编辑（如直接改动作/运镜/情绪字段），避免工作台变成复杂剪辑台。

### 2.5 视频阶段控制

- 故事版成功后，**用户再次手动勾选**要进入视频阶段的镜头
- 不自动全量推进到视频

## 3. 推荐方案

### 3.1 方案选择

采用：

- **架构上：阶段式状态机**
- **实现上：尽量复用现有 workflow / shot 模型与现有 UI 骨架**

即：

- 不推翻 `ChapterVideoWorkflow` / `ChapterVideoShot`
- 不引入 `ScriptScene / VideoShot` 旧链路
- 不重做新页面
- 只把现有章节工作流从“自动串行脚本”改造成“可分阶段调用的工作流”

### 3.2 为什么不用“前端假分阶段”

如果只在前端加按钮，而后端仍保持 `run_chapter_video_workflow()` 一次跑到底：

- 用户无法真正停在 `shots_ready`
- 失败后只能救火，不能阻止继续推进
- 批量选镜头也只是 UI 假象

所以必须在后端把阶段拆出来。

## 4. 新的后端工作流结构

### 4.1 保留数据模型

继续使用：

- [ChapterVideoWorkflow](file:///C:/Users/Administrator/Desktop/Desktop/Manwen-Studio/backend/models.py#L353-L385)
- [ChapterVideoShot](file:///C:/Users/Administrator/Desktop/Desktop/Manwen-Studio/backend/models.py#L387-L433)

不切回旧的 `ScriptScene / VideoShot` 体系。

### 4.2 工作流阶段拆分

将当前 `run_chapter_video_workflow()` 拆为四类可独立调用的阶段函数：

1. `parse_chapter_shots(workflow_id, ...)`
   - 正文 → 10s 镜头
   - 保存 shot 数据
   - 停在 `shots_ready`

2. `generate_storyboards_for_shots(workflow_id, shot_ids, ...)`
   - 对指定镜头生成故事版图片
   - 支持批量和逐镜
   - 失败即留在故事版阶段，不自动继续

3. `generate_videos_for_shots(workflow_id, shot_ids, ...)`
   - 对指定镜头生成视频
   - 仅允许对 `storyboard_ready` 的镜头调用

4. `concat_workflow_videos(workflow_id)`
   - 保持现有拼接能力

### 4.3 一键模式实现方式

一键模式不再依赖单个“大协程硬串联到底”，而是：

- 顺序调用上述 4 个阶段函数
- 在内部自动选择所有 eligible 镜头
- 但仍复用与手动模式相同的阶段 API

这样一键与手动共享同一套核心逻辑。

### 4.4 工作流状态建议

建议 workflow 主状态至少支持：

- `pending`
- `parsing_shots`
- `shots_ready`
- `generating_storyboards`
- `storyboards_ready`
- `generating_videos`
- `videos_ready`
- `completed`
- `failed`

shot 状态继续使用并细化：

- `pending`
- `storyboard_generating`
- `storyboard_ready`
- `video_generating`
- `video_ready`
- `failed`

## 5. 鉴权修复方案

### 5.1 必须分离两类 API key

后端工作流入参不应再使用一个泛化的 `api_key` 同时处理 DeepSeek 与 Image2。

应拆为：

- `deepseek_api_key`
- `image_api_key`

### 5.2 具体链路

在章节工作流创建与故事版重生成入口中：

- DeepSeek 相关逻辑使用 `_user_deepseek_api_key(...)`
- Image2 相关逻辑使用 `_user_image_api_key(...)`

并将二者分别传入：

- 拆镜 / prompt 分析 → `deepseek_api_key`
- 故事版图片生成 → `image_api_key`

### 5.3 兼容平台设置

视频 router 中的 `_user_image_api_key` 行为应与主业务侧保持一致：

- 读取 `PlatformSetting` 中 `api.image.api_key`
- 同步 `IMAGE_API_BASE_URL`
- 同步 `IMAGE_MODEL`

否则工作流拿到的图片配置与旧系统行为不一致。

## 6. 前端改造方案

### 6.1 保留现有页面骨架

继续使用：

- [VideoStoryboardLayout](file:///C:/Users/Administrator/Desktop/Desktop/Manwen-Studio/frontend/src/components/VideoStoryboardLayout.tsx)
- [ChapterVideoWorkflowPanel](file:///C:/Users/Administrator/Desktop/Desktop/Manwen-Studio/frontend/src/components/ChapterVideoWorkflowPanel.tsx)
- [ChapterListPanel](file:///C:/Users/Administrator/Desktop/Desktop/Manwen-Studio/frontend/src/components/ChapterListPanel.tsx)

### 6.2 顶部工具条改造

将现有主按钮重构为：

- 生成镜头
- 批量生成故事版
- 批量生成视频
- 拼接成片
- 一键全自动（辅助按钮）

其中：

- “生成镜头”是主入口
- “一键全自动”从主按钮降级为辅助功能

### 6.3 镜头卡片改造

每个镜头卡片新增：

- 勾选框
- 故事版提示词文本区
- 重新分析提示词按钮
- 生成故事版按钮
- 生成视频按钮
- 只看失败镜头时的错误信息

### 6.4 镜头筛选

建议增加筛选视图：

- 全部镜头
- 待生成故事版
- 故事版失败
- 可生成视频
- 视频失败

### 6.5 批量操作规则

批量生成故事版：

- 仅对勾选镜头执行
- 允许逐镜使用用户已编辑的 prompt

批量生成视频：

- 仅对勾选且 `storyboard_ready` 的镜头执行
- 不自动默认全选

## 7. 失败恢复与用户操作路径

### 7.1 故事版阶段失败

当任意镜头故事版失败时：

- workflow 不自动进入视频阶段
- 失败镜头停留在 `failed`
- 成功镜头保留在 `storyboard_ready`

用户可执行：

- 重新分析 prompt
- 修改 prompt
- 重试生成故事版
- 跳过个别镜头后继续视频阶段

### 7.2 视频阶段失败

视频阶段失败同理：

- 不影响已成功镜头
- 失败镜头可单独重试
- 用户决定是否只拼接成功片段

## 8. 测试与验证要求

### 8.1 后端测试

至少需要覆盖：

- 阶段状态流转正确
- 手动模式不会自动跨阶段推进
- 一键模式能顺序调用所有阶段
- Image2 与 DeepSeek key 分离传递
- 故事版失败时 workflow 停在当前阶段

### 8.2 前端验证

至少需要验证：

- 默认主按钮变为阶段性入口
- 可勾选镜头后批量生成故事版
- 可编辑故事版 prompt
- 故事版失败后不会自动进入视频阶段
- 一键模式仍可完整跑通

## 9. 范围边界

本次设计**不包含**：

- 重回 `ScriptScene / VideoShot` 旧体系
- 开放用户直接编辑运镜/动作/情绪结构字段
- 重做一个全新视频页面
- 引入更复杂的审批流或多人协作流

本次设计**必须包含**：

- 默认改为手动分阶段流程
- 保留一键模式
- 故事版失败即停下
- 修复 Image2 401 鉴权错误
- 增加重新分析提示词与镜头级手动入口
