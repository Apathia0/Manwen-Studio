# 视频适配器与管理端预设 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以 `AiChannel.adapter_type` 为权威协议选择器，实现 OpenAI 官方视频适配器和现有即梦兼容／灵动中转适配器，并在管理端提供可编辑的预设填充。

**Architecture:** 新增统一视频适配器注册入口和 OpenAI 原生实现，将现有 `video_api.py` 保留为 Lingdong 中转实现。创作台和章节视频工作流只构造规范化请求，由适配器处理认证、端点、轮询、结果下载和参考图编码。

**Tech Stack:** Python 3.10+ / FastAPI / SQLAlchemy 2.0 / httpx / pytest / React 19 / TypeScript 6 / Vite 8 / Vitest

## Global Constraints

- 首批视频适配器只允许 `openai_video` 和 `lingdong_video`。
- `adapter_type` 是唯一顶层协议选择器；不得从模型名、Base URL 或 `payload_profile` 推断协议。
- `payload_profile` 只属于 `lingdong_video`；`sora_v2` 仍是旧中转 profile。
- 保留现有 `input_reference="url1|url2"` 行为。
- OpenAI 原生首批最多一张参考图；不支持 15 秒时明确拒绝，禁止静默取整。
- 保留所有既有未提交改动，不 reset、stash、clean、批量格式化或提交。
- 所有文本文件保持 UTF-8 无 BOM；所有新增代码注释使用中文。
- 禁止类型抑制、任意端点模板、JSONPath 或脚本执行。

---

### Task 1: 建立适配器常量与渠道校验

**Files:**
- Create: `backend/services/video_adapter.py`
- Modify: `backend/routers/points_ai.py`
- Test: `backend/tests/test_points_packages.py`

**Produces:**

```python
VIDEO_ADAPTER_OPENAI = "openai_video"
VIDEO_ADAPTER_LINGDONG = "lingdong_video"
SUPPORTED_VIDEO_ADAPTERS = frozenset({VIDEO_ADAPTER_OPENAI, VIDEO_ADAPTER_LINGDONG})

def normalize_video_adapter_type(
    adapter_type: str | None,
    *,
    legacy_default: bool = False,
) -> str: ...
```

- [ ] 为两个合法值、空值、`openai_compatible`、`sora_v2` 和未知值写失败测试。
- [ ] 验证新建视频渠道只能使用两个合法适配器；文本与图片渠道保持现有规则。
- [ ] 更新渠道时对最终 `modality + adapter_type` 组合做校验。
- [ ] 运行 `python -m pytest tests/test_points_packages.py -k "adapter or channel" -vv`。

### Task 2: 实现 OpenAI 原生客户端与统一调度

**Files:**
- Create: `backend/services/openai_video.py`
- Modify: `backend/services/video_adapter.py`
- Modify: `backend/services/video_api.py`
- Create: `backend/tests/test_video_adapter.py`

**Produces:**

```python
async def create_video_job(*, adapter_type: str, model: str, prompt: str,
                           aspect_ratio: str, size: str, duration_seconds: int,
                           images: list[str] | None, api_key: str | None,
                           base_url: str | None,
                           video_capabilities: dict[str, object] | None) -> dict[str, object]: ...

async def query_video_job(job_id: str, *, adapter_type: str,
                          api_key: str | None, base_url: str | None,
                          model: str | None = None) -> dict[str, object]: ...

async def materialize_video_job(*, adapter_type: str, job_id: str,
                                query_result: dict[str, object], shot_id: int,
                                api_key: str | None, base_url: str | None) -> str: ...
```

- [ ] 先写 OpenAI 提交、查询、结构化错误和内容下载的失败测试。
- [ ] 断言 OpenAI 提交只包含 `model`、`prompt`、字符串 `seconds`、像素 `size` 和可选单图 `input_reference.image_url`。
- [ ] 断言多参考图在发 HTTP 请求前失败。
- [ ] 断言 Lingdong 仍使用现有查询路径和管道符 `input_reference`。
- [ ] 实现 OpenAI `/v1/videos`、`/v1/videos/{id}`、`/v1/videos/{id}/content`。
- [ ] 将现有 `video_api.py` 明确限制为 Lingdong 分支，不把 `sora_v2` 改成 OpenAI 原生。
- [ ] 运行 `python -m pytest tests/test_video_adapter.py -vv`。

### Task 3: 按适配器验证模型能力

**Files:**
- Modify: `backend/routers/points_ai.py`
- Test: `backend/tests/test_points_packages.py`
- Test: `backend/tests/test_video_adapter.py`

- [ ] 将 `_validate_model_capabilities` 增加 `adapter_type` 参数，并从模型所属渠道获取。
- [ ] Lingdong 继续允许 `legacy_lingdong`、`seedance_fast`、`sora_v2` 和现有受控 wire 字段。
- [ ] OpenAI 拒绝 `payload_profile`、中转 `reference_field` 和任意字段名。
- [ ] OpenAI 校验时长集合、最多一张参考图和受控 `size_by_resolution_aspect`。
- [ ] 覆盖有效配置、非法 size、多图、旧 `sora_v2` 保留和手动能力子集测试。

### Task 4: 创作台按渠道适配器执行

**Files:**
- Modify: `backend/services/creation_studio.py`
- Modify: `backend/services/video_generation.py`
- Test: `backend/tests/test_creation_studio.py`
- Test: `backend/tests/test_video_generation_stability.py`

- [ ] 写测试断言 `AIExecutionContext.adapter_type` 传入创建、查询和结果物化。
- [ ] 将创作台的直接 `video_api` 调用替换为统一适配器入口。
- [ ] 原生 OpenAI 完成任务时直接下载 content，不再要求结果 URL。
- [ ] 给共享 submit/query/fetch 接口增加 `adapter_type`，旧调用默认 `lingdong_video`。
- [ ] 保持取消、计费、失败释放和 Lingdong 行为不变。
- [ ] 运行 `python -m pytest tests/test_creation_studio.py tests/test_video_generation_stability.py -vv`。

### Task 5: 修复并统一章节视频工作流契约

**Files:**
- Modify: `backend/schemas.py`
- Modify: `backend/routers/video.py`
- Modify: `backend/services/video_chapter_pipeline.py`
- Test: `backend/tests/test_video_chapter_stage_api.py`
- Test: `backend/tests/test_video_chapter_workflow_api.py`
- Test: `backend/tests/test_video_chapter_pipeline.py`
- Test: `backend/tests/test_user_upstream_override.py`

- [ ] 给 `RegenerateShotRequest` 增加 `duration_seconds: int | None`，并将列表默认值改为 `default_factory`。
- [ ] 写测试证明章节批量生成向 `regenerate_shot_video` 传 `video_api_key`，而非 `image_api_key`。
- [ ] 给批量和单镜头路径透传 `adapter_type` 与实际 `duration_seconds`。
- [ ] 移除最终提交点硬编码的 15 秒，使用镜头值或 15 秒领域默认值。
- [ ] 确保计费与上游提交使用同一时长。
- [ ] OpenAI 对不支持的 15 秒和多参考图在预扣／提交前明确拒绝。
- [ ] 保持 Lingdong 的 storyboard、character、scene、prop、style 参考图顺序测试通过。
- [ ] 运行四个章节视频相关测试文件。

### Task 6: 增加管理端预设下拉并保留手动覆盖

**Files:**
- Create: `frontend/src/lib/videoAdapterPresets.ts`
- Create: `frontend/src/lib/videoAdapterPresets.test.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/admin/PointsAiAdminPage.tsx`
- Test: `frontend/src/api.test.ts`

**Produces:**

```typescript
export type VideoAdapterType = 'openai_video' | 'lingdong_video';

export interface VideoAdapterPreset {
  id: VideoAdapterType;
  label: string;
  adapterType: VideoAdapterType;
  baseUrl: string;
  modelKey: string;
  capabilities: Record<string, unknown>;
}
```

- [ ] 用纯函数测试 OpenAI 和 Lingdong 预设填充。
- [ ] 测试 Lingdong 空 Base URL 不覆盖已有手动地址。
- [ ] 测试选择预设不自动保存，预设后手动修改保持不变。
- [ ] 渠道表单新增并保存 `adapter_type`，编辑时加载现有值。
- [ ] 视频渠道显示两个预设，列表显示适配器类型。
- [ ] 模型预设填充 `model_key` 和 capabilities 草稿，但不锁定字段。
- [ ] 运行 `npm run test -- src/lib/videoAdapterPresets.test.ts src/api.test.ts`、`npm run build`、`npm run lint`。

### Task 7: 幂等迁移历史视频渠道

**Files:**
- Modify: `backend/database.py`
- Modify: `backend/services/ai/bootstrap.py`
- Test: `backend/tests/test_points_packages.py`

- [ ] 写迁移测试：视频渠道 `openai_compatible`、空值迁移为 `lingdong_video`。
- [ ] 证明现有 `lingdong_video`、`openai_video` 保持不变。
- [ ] 证明文本／图片渠道不变，未知非空值不静默重写。
- [ ] 证明 `sora_v2` 配置仍属于 Lingdong。
- [ ] 在现有 `_migrate()` 体系中加入幂等更新，不引入 Alembic。
- [ ] 连续执行迁移两次并断言结果一致。

### Task 8: 验证与审查

- [ ] 对所有改动 Python／TypeScript 文件运行 LSP diagnostics，要求零新增错误。
- [ ] 运行聚焦后端测试：

```powershell
python -m pytest tests/test_video_adapter.py tests/test_creation_studio.py tests/test_video_generation_stability.py tests/test_video_chapter_stage_api.py tests/test_video_chapter_workflow_api.py tests/test_video_chapter_pipeline.py tests/test_user_upstream_override.py tests/test_points_packages.py -vv
```

- [ ] 运行后端完整测试 `python -m pytest -q`。
- [ ] 运行 `python -m py_compile` 检查所有改动 Python 文件。
- [ ] 运行前端 `npm run test`、`npm run build`、`npm run lint`。
- [ ] 搜索确认没有 `api_key=image_api_key`、章节 5／10 秒 fallback、类型抑制或错误的 OpenAI profile 推断。
- [ ] 运行 `git diff --check` 并逐文件审查最终 diff，区分本功能改动与既有脏工作区改动。
- [ ] 再次检查全部新改文本文件前 3 字节，确认无 `EF BB BF`。
- [ ] 并行委派 reviewer 与 tester；收集并处理所有与本功能有关的问题。

## 测试矩阵

| 维度 | OpenAI 官方 | 即梦兼容／Lingdong |
|---|---|---|
| 文生视频 | `/videos` 原生 payload | 现有 legacy/profile payload |
| 图生视频 | 单图 `input_reference.image_url` | 多图管道符 `input_reference` |
| 多参考图 | 明确拒绝 | 保持原顺序与上限 |
| 轮询 | `/videos/{id}` | `/video/generations/{task_id}` |
| 下载 | `/videos/{id}/content` | 结果 URL／现有下载逻辑 |
| 时长 | 能力集合内显式值 | 4–15 或 profile 限制 |
| 错误 | 结构化 OpenAI error | 现有中转错误归一化 |
| 管理预设 | 自动填官方默认值，可编辑 | 填模型与能力，保留手动 URL |
| 兼容迁移 | 仅显式新建／保留 | 历史视频渠道默认归入此适配器 |

## 执行顺序

`Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7 → Task 8`。后端共享文件必须单写者修改；管理端视觉工作交给 `visual-engineering`；最终 reviewer 与 tester 可并行只读审查。
