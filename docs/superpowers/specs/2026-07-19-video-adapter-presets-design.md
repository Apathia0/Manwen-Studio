# 视频供应商适配器与配置预设设计

> 状态：已确认  
> 日期：2026-07-19  
> 首批范围：OpenAI 官方 Videos API、现有即梦兼容／灵动中转协议

## 1. 目标

管理后台为视频渠道提供协议预设下拉。管理员选择预设后，系统自动填充适配器、Base URL、示例模型和模型能力；填充后的 Base URL、模型标识与能力参数仍可手动修改。

预设不能只停留在前端。后端必须根据 `AiChannel.adapter_type` 选择提交、轮询和下载实现，避免出现“配置保存成功，但运行时仍按旧 `/v1/videos` 中转协议调用”的假支持。

## 2. 首批范围

### 2.1 OpenAI 官方视频协议

- `adapter_type`: `openai_video`
- 默认 Base URL：`https://api.openai.com/v1`
- 创建任务：`POST /v1/videos`
- 查询任务：`GET /v1/videos/{id}`
- 下载结果：`GET /v1/videos/{id}/content`
- 时长字段：字符串 `seconds`
- 尺寸字段：像素尺寸 `size`
- 首批图生视频只支持一张 `input_reference.image_url`
- 不读取 `payload_profile`，也不接受中转商的 `duration`、`orientation`、`ratio`、`resolution` 或管道符参考图格式

### 2.2 现有即梦兼容／灵动中转协议

- `adapter_type`: `lingdong_video`
- 继续使用现有 `backend/services/video_api.py`
- 保留 `legacy_lingdong`、`seedance_fast`、`sora_v2` 三种中转 payload profile
- 多参考图继续编码为 `input_reference="url1|url2"`
- 保留管理员手动填写中转 Base URL 和 `sd-2-vip-*`、`seedance*` 等模型标识的能力
- `sora_v2` 只表示旧中转 payload 变体，不得触发 OpenAI 官方适配器

### 2.3 明确不在首批范围

- 火山方舟 Ark 官方协议
- 火山即梦 Visual 官方产品协议
- Google Gemini API、Vertex AI、xAI Grok
- OpenAI webhook、视频编辑、remix、extension、characters 等扩展 API
- OpenAI 多参考图合成
- 管理员自定义认证头、端点模板、JSONPath 或脚本解析器

## 3. 权威配置模型

`adapter_type` 是唯一顶层协议选择器：

```text
AiChannel.adapter_type
        ↓
video adapter registry
        ↓
submit → poll → materialize
```

`AiModel.capabilities_json.video` 只表达模型能力：

- 支持文生视频还是图生视频
- 默认时长、比例和分辨率
- 可用时长、比例和分辨率
- 最大参考图数量
- 受控的尺寸映射
- `lingdong_video` 内部的兼容 payload profile

它不能定义认证方式、端点、任务 ID 字段、状态字段、结果解析路径或任意可执行表达式。

## 4. 后端结构

新增统一适配器入口 `backend/services/video_adapter.py`：

```python
async def create_video_job(..., adapter_type: str) -> dict[str, object]: ...
async def query_video_job(..., adapter_type: str) -> dict[str, object]: ...
async def materialize_video_job(..., adapter_type: str) -> str: ...
```

新增 `backend/services/openai_video.py`，只负责 OpenAI 官方协议。现有 `video_api.py` 收敛为 `lingdong_video` 的实现，保留其 OSS 上传、管道符参考图和旧任务解析行为。

创建与查询结果在适配层归一化为内部任务状态：`queued`、`in_progress`、`completed`、`failed`。业务层不再解析供应商特有的 `id`、`task_id`、`request_id` 或结果嵌套结构。

## 5. 调用链迁移

### 5.1 创作台

`begin_ai_call()` 已返回 `AIExecutionContext.adapter_type`。创作台必须将它传入统一视频适配器，不再直接调用固定协议的 `video_api.create_video_job()`。

### 5.2 视频分镜与章节工作流

按以下顺序渐进迁移：

1. 单镜头重新生成；
2. 章节批量生成；
3. 传统 shot render；
4. 旧 `PlatformSetting api.video.*` 保留只读回退，待所有入口验证后再移除。

本批同步修复：

- 章节批量视频生成必须传 `video_api_key`，不能错传 `image_api_key`；
- `RegenerateShotRequest` 声明 `duration_seconds`；
- 章节工作流生成时长默认值统一为 15 秒；
- 计费时长必须与实际上游提交时长一致。

OpenAI 官方模型若不支持 15 秒，系统必须在预扣和提交前明确拒绝，不能静默改成 12 秒。OpenAI 原生首批如果收到多张参考图，也必须明确拒绝，不能丢弃多余图片。

## 6. 管理端交互

渠道表单在能力类型为“视频”时显示“视频协议预设”：

- OpenAI 官方 Videos API
- 即梦兼容／灵动中转

选择预设只更新当前草稿，不自动保存。管理员之后可继续修改：

- 渠道名称
- Base URL
- API Key
- 模型标识
- 默认时长、比例和分辨率
- 能力限制与高级 JSON

编辑已有渠道时不自动重套预设，避免覆盖生产配置。即梦兼容预设没有权威公共 Base URL，因此其空默认值不能清除管理员已经填写的地址。

## 7. 兼容迁移

不新增数据库列，复用现有 `AiChannel.adapter_type` 和 `AiModel.capabilities_json`。

历史视频渠道按确定性规则迁移：

| 原值 | 目标值 |
|---|---|
| `lingdong_video` | 保持不变 |
| `openai_video` | 保持不变 |
| `openai_compatible`、空值 | `lingdong_video` |
| 未知非空值 | 不静默修改，报告为无效配置 |

迁移只处理 `modality='video'`，必须幂等，不能根据 Base URL、模型名或 `sora_v2` 推断为 OpenAI 官方协议。

## 8. 安全与运维

- API Key 继续加密存储，响应和日志不输出明文。
- 手填 Base URL 继续执行现有 URL 安全校验；必须防止 loopback、link-local、metadata 和私网 SSRF。
- 异步任务应保存适配器类型及必要的非秘密运行时快照，防止管理员改渠道后旧任务使用新协议轮询。
- OpenAI 内容下载和中转结果均落入 StoryCanvas 受控存储，不能长期依赖临时结果 URL。

## 9. 验收标准

1. 新视频渠道只能明确选择 `openai_video` 或 `lingdong_video`。
2. OpenAI 官方调用使用 `/videos`、`/videos/{id}`、`/videos/{id}/content` 三段协议。
3. OpenAI 官方不读取 `payload_profile`，最多接收一张参考图。
4. 即梦兼容链路继续使用管道符 `input_reference`，现有 profile 零回归。
5. 创作台、单镜头和章节批量生成均按渠道 `adapter_type` 调度。
6. 章节批量生成使用视频 Key，默认时长为 15 秒，计费与提交时长一致。
7. 管理员应用预设后仍能手动覆盖 Base URL、模型和能力参数。
8. 历史视频渠道迁移幂等，不误判 `sora_v2`。
9. 后端相关 pytest、前端测试、TypeScript 构建、ESLint、BOM 与 diff 检查全部通过。
