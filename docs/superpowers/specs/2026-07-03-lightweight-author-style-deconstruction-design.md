# 轻量作者风格拆书设计

## 背景

当前拆书系统以“完整拆文报告”为核心目标，管线从 Stage 0 跑到 Stage 6，其中 Stage 2 会对每一章发起一次模型调用。这个设计适合重度复盘，但不适合用户更常见的需求：快速提取某个作者的写作风格、节奏套路、爽点模板和可复用写法。

本次改造的第一阶段只新增轻量模式，不破坏现有完整拆书、试读拆解和快速报告能力。

## 目标

新增“轻量作者风格/套路提取”能力，让用户不必跑完全书逐章深拆，也能得到可用于创作参考的作者风格画像。

成功标准：

- 用户可在独立拆书库作品页启动轻量作者画像分析。
- 后端不执行全量 Stage 2 逐章摘要，只抽样约 12-20 章。
- 输出包含文风特征、节奏习惯、套路卡、证据章节和置信度。
- 结果可在前端查看，并可引用到作品创作上下文。
- 现有完整拆书流程行为不变。

## 非目标

- 不在第一阶段实现多本书跨书作者画像合并。
- 不重构完整拆书 Stage 0-6 主流程。
- 不引入向量数据库。
- 不修改现有计费套餐结构，只复用现有文本模型配额检查方式。
- 不做自动仿写，只输出可参考的结构化画像。

## 可选方案

### 方案 A：单本书抽样式作者画像 MVP（推荐）

从当前 `DeconstructionWork` 的章节中抽取黄金三章、中段、后段、结尾附近章节，调用轻量 Prompt 提取作者写法特征与套路卡。第一阶段结果直接存入 `DeconstructionWork` 新增字段，不新增独立作者画像表。

优点：改动小、上线快、成本低，直接解决“不全量拆也能提取风格套路”的痛点。

缺点：只能分析单本书，不能判断哪些特征是作者长期稳定风格。

### 方案 B：作者画像库完整版

新增 `AuthorProfile` 表，支持同一作者多本书合并分析，输出作者级画像。

优点：长期价值更高，可沉淀作者库。

缺点：需要新增作者维度页面、跨作品合并逻辑和更多测试，第一阶段风险偏高。

### 方案 C：完整拆书全面重构

同时重构 Stage 2、缓存、断点、作者画像、管线去重和前端交互。

优点：整体收益最大。

缺点：改动范围过大，容易影响现有拆书稳定性。

## 推荐方案

采用方案 A。第一阶段新增单本书轻量作者画像能力，完整拆书流程保持兼容。后续可在此基础上扩展为多本书作者画像库。

## 用户流程

在独立拆书库作品页中，用户看到三个分析入口：

- 快速作者画像：抽样分析，适合提取风格和套路。
- 试读拆解：前 N 章分析，适合判断是否值得深拆。
- 完整拆书：全书 Stage 0-6，适合系统性复盘。

第一阶段只新增“快速作者画像”。

流程：

1. 用户导入或爬取作品章节。
2. 点击“提取作者风格/套路”。
3. 后端选择样本章节。
4. 模型提取单章风格特征和套路片段。
5. 模型合并样本结果，生成作者画像。
6. 前端展示画像、套路卡和证据章节。
7. 用户可将画像引用到作品创作中。

## 抽样策略

输入为 `DeconstructionChapter` 列表，按章节数分级。

少于 12 章：使用全部章节。

12-80 章：

- 第 1-3 章。
- 中段均匀抽 4-6 章。
- 后段抽 3-5 章。
- 最后一章。

超过 80 章：

- 第 1-3 章。
- 按 20%、40%、60%、80% 位置各抽 2-3 章。
- 最后 2 章。
- 总样本控制在 16-20 章。

样本选择必须去重，并按章节号排序。

## 后端设计

### 新服务模块

新增 `backend/services/author_style.py`，负责轻量作者画像管线。

核心函数：

```python
async def run_author_style_pipeline(
    work_id: int,
    api_key: str | None,
    task_id: str | None = None,
    **kwargs,
) -> dict:
    pass
```

职责：

- 从 `DeconstructionWork` 读取章节。
- 执行抽样策略。
- 调用单章样本分析 Prompt。
- 调用合并画像 Prompt。
- 保存结果和进度。

### 新 Prompt

在 `backend/prompts/deconstruction.py` 中追加三组 Prompt：

- `AUTHOR_STYLE_SAMPLE_SYSTEM` / `AUTHOR_STYLE_SAMPLE_USER`：单章样本分析。
- `AUTHOR_ROUTINE_MERGE_SYSTEM` / `AUTHOR_ROUTINE_MERGE_USER`：合并套路卡和节奏画像。
- `AUTHOR_STYLE_REPORT_SYSTEM` / `AUTHOR_STYLE_REPORT_USER`：生成可读 Markdown 报告。

### 输出结构

结果 JSON 结构：

```json
{
  "schema_version": 1,
  "sampled_chapters": [1, 2, 3, 24, 25, 49, 50, 76, 77, 99, 100],
  "style_profile": {
    "sentence": {},
    "dialogue": {},
    "description": {},
    "emotion_expression": {},
    "pov_and_narration": {}
  },
  "rhythm_profile": {
    "opening_hook": {},
    "chapter_end_hooks": [],
    "emotion_cycle": {},
    "info_release_pattern": {}
  },
  "routine_cards": [
    {
      "name": "套路名称",
      "category": "开篇钩子/爽点设计/反转/关系拉扯/升级推进/章节结尾/信息控制",
      "structure": ["步骤1", "步骤2"],
      "emotion_curve": "情绪曲线",
      "best_position": "适用位置",
      "reuse_condition": "复用条件",
      "reuse_risk": "复用风险",
      "evidence": [
        {"chapter": 1, "summary": "证据说明"}
      ],
      "confidence": 0.8
    }
  ],
  "writing_guide": {
    "do": [],
    "avoid": [],
    "prompt_notes": []
  },
  "confidence": 0.0
}
```

### 数据存储

第一阶段优先使用 `DeconstructionWork` 新增字段，避免新增作者实体带来的范围扩大。

新增字段：

- `author_style_status: String(30)`，默认 `not_started`。
- `author_style_task_id: String(80)`。
- `author_style_profile: JSON`。
- `author_style_report_markdown: Text`。
- `author_style_progress_markdown: Text`。

迁移在 `database.py` 中保持幂等：检查列存在后再 `ALTER TABLE`。

### API 设计

新增端点挂在独立拆书库路由中：

- `POST /api/deconstruct/works/{work_id}/author-style/start`
- `GET /api/deconstruct/works/{work_id}/author-style/status`
- `GET /api/deconstruct/works/{work_id}/author-style/result`

第一阶段复用现有 `POST /api/stories/{story_id}/deconstruct/refs` 引用关系。作品引用拆书工作后，创作上下文读取该 `DeconstructionWork` 时同时可读取 `author_style_profile`。单独的作者画像引用表留到后续多本书作者库阶段。

### 配额与任务

复用现有 `task_manager.submit_task`。

配额第一阶段复用 `deconstruction.run.monthly_limit`，但进度文案要明确“作者画像分析”。后续可拆成独立配额项。

任务超时建议 1800 秒。相比完整拆书 7200 秒更短。

## 前端设计

### API 类型

在 `frontend/src/api.ts` 增加：

- `AuthorStyleStatus`
- `AuthorStyleResult`
- `startAuthorStyleAnalysis(workId)`
- `getAuthorStyleStatus(workId)`
- `getAuthorStyleResult(workId)`

### 页面入口

在 `DeconstructionWorkPage.tsx` 的未拆书或已爬取/已导入状态中增加按钮：

- 主按钮：`提取作者风格/套路`
- 辅助说明：`抽样分析，成本低于完整拆书`

### 结果展示

增加 `authorStyle` tab 或在现有 `style` tab 中区分：

- 作者画像概览。
- 文风特征。
- 节奏画像。
- 套路卡列表。
- 证据章节。
- 可用于写作的提示词备注。

## 错误处理

- 少于 3 章：拒绝启动，提示至少需要 3 章。
- 模型配置缺失：复用现有 DeepSeek 配置错误提示。
- 单章样本失败：记录失败样本，继续处理其他样本。
- 合并画像失败：任务失败，保留样本分析进度。
- 用户取消：调用 `task_manager.request_cancellation`，状态置为 `failed` 并写入进度。

## 测试策略

后端测试：

- 抽样策略去重、排序、数量上限。
- 少章节时使用全部章节。
- API 权限校验。
- 启动任务时写入 `author_style_status=running`。
- 成功后保存 `author_style_profile` 和 `author_style_report_markdown`。

前端验证：

- 按钮显示条件正确。
- 状态轮询能从 running 进入 completed。
- 结果 tab 能展示套路卡和报告。

手动验证：

- 上传一本文本章节。
- 启动作者画像。
- 确认不进入完整 Stage 2 逐章摘要。
- 确认输出包含 sampled_chapters、routine_cards、writing_guide。

## 风险与缓解

- 抽样不代表全书：结果中必须显示样本章节和置信度。
- AI 输出 JSON 不稳定：复用 `_loads_json_lenient` 与截断修复逻辑。
- 与完整拆书结果混淆：前端文案明确区分“作者画像”和“完整拆书”。
- 数据字段增加过多：第一阶段只加在 `DeconstructionWork`，不新增复杂作者库。

## 后续扩展

- 新增 `AuthorProfile` 表，支持多本书合并。
- 增加章节 hash 缓存，避免同一章节重复分析。
- 将作者画像映射到 `PromptTemplate.chapter_params.custom_style_notes`。
- 在 Agent 工具中新增读取作者画像的能力。
