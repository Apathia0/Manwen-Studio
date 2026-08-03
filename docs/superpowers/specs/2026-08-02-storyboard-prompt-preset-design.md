# 漫画分镜脚本提示词模板管理设计

## 目标与范围

在漫画工作台中提供作品级的分镜脚本提示词模板管理入口。用户可以查看系统模板，复制系统模板为当前作品的自定义模板，新增、编辑、删除自定义模板，并将任一模板绑定到当前作品。分镜生成和选中文字生成分镜时使用当前绑定的模板。

本次仅修改前端：`frontend/src/api.ts`、新增 `frontend/src/components/StoryboardPresetModal.tsx`、以及 `frontend/src/components/MangaPanel.tsx`。不引入依赖，不改动后端和既有按钮结构。

## API 适配

`api.ts` 新增 `StoryboardPromptPreset`，并按现有 `fetch`、`apiHeaders(true)` 和 `readErrorMessage` 约定封装模板 CRUD、复制和作品绑定接口。

`generateScenes(chapterId, signal?, presetId?)` 只有在 `presetId` 为有效数字时设置 `Content-Type: application/json` 并发送 `{ "preset_id": presetId }`；未绑定模板时维持旧请求的无 body 行为。`scenesFromSelection` 的参数类型增加可选 `preset_id`，由调用方决定是否发送。

## 弹窗与状态

`StoryboardPresetModal` 采用 `StyleSelectorModal` 一致的 fixed 遮罩、白色居中卡片、Portal 挂载和蓝色主操作样式。打开时并行读取当前作品可见模板和作品绑定；内部维护列表、当前绑定、待应用模板、当前页签、表单与加载状态。

系统模板在“系统模板”页签展示，只能复制为当前作品自定义模板。自定义模板在“我的模板”页签展示，支持选择、编辑、删除。删除通过全局 `confirm` 确认，所有失败使用全局 `toast.error`，成功使用 `toast.success`。系统模板不能进入编辑和删除路径。

表单在同一弹窗内切换，不额外嵌套弹窗。字段包括名称、描述、正文模板和可选系统提示词；正文模板区使用等宽小字号并占据主要垂直空间。表单明确展示 `{page_count}` 占位符说明。

点击“应用模板”时，弹窗写入作品绑定接口，再调用 `onPresetApplied(presetId, presetName)` 让父组件同步显示状态。允许选择“默认分镜模板”以解绑，回调名称为“默认分镜模板”。

## MangaPanel 集成

`MangaPanel` 以 `chapter.story_id` 为作品级键。章节变更时读取 `getStoryStoryboardPreset`，将 `preset_id` 和预设名称写入本地 state，并用请求序号避免过期异步结果覆盖新章节状态。

在既有“生成配置”区域插入一个分镜模板按钮，显示当前绑定名称或“默认分镜模板”，点击打开新弹窗。弹窗回调只更新本地 state，因为作品绑定已经由弹窗成功写入。

普通分镜生成向 `generateScenes` 传入当前预设 ID；选中文字生成分镜在 payload 中添加同一 ID。未绑定时传 `undefined`，从而保持旧后端兼容性。

## 验证

API 测试覆盖 `generateScenes` 的绑定与未绑定请求体行为。修改的 TypeScript 文件需通过语言服务诊断，随后运行 `npm run test`、`npm run build` 和 `npm run lint`。所有新增文本文件及改动文件须确认 UTF-8 无 BOM。
