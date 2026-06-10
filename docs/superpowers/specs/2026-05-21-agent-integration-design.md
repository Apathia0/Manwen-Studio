# AI 助手 Agent 集成设计文档

**日期**: 2026-05-21
**项目**: Manwen-Studio (LoreVista)
**状态**: 待审阅

---

## 1. 概述

### 1.1 目标

为 Manwen-Studio 工作台集成一个 **AI 助手 Agent**，具备以下能力：

1. **对话能力**：在右侧面板以聊天界面与用户交互
2. **阅读能力**：Agent 能读取章节全文、故事框架、角色设定等全部创作内容
3. **修改能力**：Agent 能通过工具调用修改小说的框架、正文、标题、标签、角色、大纲、分镜等所有内容类型
4. **实时反馈**：通过 SSE 流式传输，用户能看到 Agent 的推理过程、工具执行状态和最终结果

### 1.2 设计原则

- **安全性**：Agent API 密钥复用后端现有 DeepSeek 配置，不暴露到浏览器
- **一致性**：复用已有的后端 AI 服务基础设施（`AiService`、上下文构建器）
- **可扩展**：工具注册机制支持未来轻松添加新工具
- **无缝切换**：右侧面板在「漫画操作区」和「AI 助手」之间通过标签切换，对话状态保留

---

## 2. 架构概览

### 2.1 架构图

```
┌─────────────────────────────────────────────────────────┐
│  Frontend (React/TypeScript)                             │
│                                                         │
│  WorkspaceLayout                                         │
│  ┌─────────┬──────────────────┬──────────────────────┐  │
│  │Framework│  EditorPanel     │ [漫画区] [AI 助手]   │  │  ← 标签栏
│  │  Panel  │                  │                      │  │
│  │ (280px) │   (flex-1)       │  AgentPanel /        │  │
│  │         │                  │  MangaPanel          │  │
│  └─────────┴──────────────────┴──────────────────────┘  │
│                                                         │
│  AgentPanel ←→ agentChatStream() ←→ SSE ←→ Backend      │
└─────────────────────────────────────────────────────────┘
         │
         │ POST /api/stories/{story_id}/agent/chat (SSE)
         ▼
┌─────────────────────────────────────────────────────────┐
│  Backend (Python/FastAPI)                                │
│                                                         │
│  agent_router.py                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  AgentService                                    │    │
│  │  ┌──────────────┐  ┌────────────────────────┐   │    │
│  │  │  ToolRegistry  │  │  Context Assembler     │   │    │
│  │  │  ├─ get_chapter│  │  ├─ story_meta          │   │    │
│  │  │  ├─ update_... │  │  ├─ chapter_full        │   │    │
│  │  │  ├─ adjust_... │  │  ├─ framework_detail    │   │    │
│  │  │  └─ ...        │  │  └─ conversation_hist   │   │    │
│  │  └──────┬───────┘  └────────────────────────┘   │    │
│  │         │                                        │    │
│  │         ▼                                        │    │
│  │  ┌─────────────────────────────────────────┐     │    │
│  │  │  DeepSeek API (function calling)         │     │    │
│  │  └─────────────────────────────────────────┘     │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Existing API (被 Agent 工具调用)                │    │
│  │  main.py: adjustChapterContent, rewriteSelection  │    │
│  │  saveChapterContent, updateStory, framework...    │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### 2.2 核心流程

```
用户发送消息
    │
    ▼
前端 SSE 请求 → POST /api/stories/{id}/agent/chat
    │
    ▼
Backend: 构建上下文（故事元信息 + 当前章节 + 对话历史）
         + 注入工具描述（Read Tools + Write Tools 的 function calling schema）
    │
    ▼
Backend: 调用 DeepSeek API (流式 chatter 模式 + function calling)
    │
    ├─ 返回文本 token → SSE event: token
    ├─ 返回工具调用 → SSE event: tool_call
    │       │
    │       ▼
    │   Backend: 执行工具（读取/修改数据）
    │       │
    │       ▼
    │  SSE event: tool_result (成功/失败 + 摘要)
    │       │
    │       ▼
    │  结果反馈给 DeepSeek → 继续推理
    │
    └─ SSE event: done (完整回复)
```

---

## 3. 后端 Agent 服务

### 3.1 新增文件结构

```
backend/
├── routers/
│   └── agent_router.py          ← 新增：Agent SSE 端点
└── services/
    └── agent_service.py         ← 新增：Agent 核心逻辑
```

### 3.2 `agent_service.py` — ToolRegistry

```python
# backend/services/agent_service.py

from typing import Any, Callable, Awaitable
from pydantic import BaseModel

class ToolDef(BaseModel):
    """DeepSeek function calling 格式的工具定义"""
    name: str
    description: str
    parameters: dict  # JSON Schema

class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., Awaitable[dict]]

class ToolRegistry:
    """集中注册所有可用工具"""

    _tools: dict[str, Tool] = {}

    @classmethod
    def register(cls, name: str, description: str, parameters: dict):
        """装饰器：注册工具"""
        def decorator(handler):
            cls._tools[name] = Tool(
                name=name,
                description=description,
                parameters=parameters,
                handler=handler,
            )
            return handler
        return decorator

    @classmethod
    def get_schemas(cls) -> list[dict]:
        """返回 DeepSeek function calling 格式的 tool list"""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                }
            }
            for t in cls._tools.values()
        ]

    @classmethod
    async def execute(cls, name: str, args: dict, ctx: dict) -> dict:
        tool = cls._tools.get(name)
        if not tool:
            return {"success": False, "error": f"Unknown tool: {name}"}
        return await tool.handler(**args, ctx=ctx)
```

### 3.3 读取工具（Read Tools）

以下工具赋予 Agent 读取作品内容的能力：

#### 3.3.1 `get_chapter_full` — 读取章节全文

```python
@ToolRegistry.register(
    name="get_chapter_full",
    description="读取指定章节的完整正文、关键事件、质量评分。用于仔细阅读某章以给出修改建议或分析写作质量。",
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {
                "type": "integer",
                "description": "章节 ID"
            }
        },
        "required": ["chapter_id"]
    }
)
async def get_chapter_full(chapter_id: int, ctx: dict) -> dict:
    """从数据库读取章节全文"""
    # 从数据库获取 Chapter 记录
    # 返回: { title, content, word_count, key_events, quality_score, characters }
```

#### 3.3.2 `get_all_chapters_summary` — 阅读作品全章概览

```python
@ToolRegistry.register(
    name="get_all_chapters_summary",
    description="获取作品中所有章节的概览列表（编号、标题、字数、状态）。用于快速了解作品的整体章节结构。",
    parameters={
        "type": "object",
        "properties": {
            "story_id": {
                "type": "integer",
                "description": "故事 ID"
            }
        },
        "required": ["story_id"]
    }
)
async def get_all_chapters_summary(story_id: int, ctx: dict) -> dict:
    """返回所有章节的摘要列表"""
```

#### 3.3.3 `get_framework_detail` — 阅读故事框架

```python
@ToolRegistry.register(
    name="get_framework_detail",
    description="获取完整的故事框架信息，包括标签(tags)、角色设定(characters)、三幕式大纲(outline)。用于分析故事结构或给出框架优化建议。",
    parameters={
        "type": "object",
        "properties": {
            "story_id": {
                "type": "integer",
                "description": "故事 ID"
            }
        },
        "required": ["story_id"]
    }
)
async def get_framework_detail(story_id: int, ctx: dict) -> dict:
    """返回故事框架全量数据"""
```

#### 3.3.4 `get_story_bible` — 阅读创作圣经

```python
@ToolRegistry.register(
    name="get_story_bible",
    description="获取创作简讯(creative_brief)和写作指南(writing_guidance)。了解创作意图和风格约束。",
    parameters={
        "type": "object",
        "properties": {
            "story_id": {
                "type": "integer",
                "description": "故事 ID"
            }
        },
        "required": ["story_id"]
    }
)
async def get_story_bible(story_id: int, ctx: dict) -> dict:
    """返回 creative_brief + writing_guidance"""
```

#### 3.3.5 `get_scenes` — 阅读分镜脚本

```python
@ToolRegistry.register(
    name="get_scenes",
    description="获取指定章节的分镜脚本(scenes)列表。每个分镜包含画面描述、对白、镜头类型等。",
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {
                "type": "integer",
                "description": "章节 ID"
            }
        },
        "required": ["chapter_id"]
    }
)
async def get_scenes(chapter_id: int, ctx: dict) -> dict:
    """返回分镜列表"""
```

#### 3.3.6 `get_character_profiles` — 阅读角色外貌卡

```python
@ToolRegistry.register(
    name="get_character_profiles",
    description="获取指定章节的角色外貌描述(character_profiles)。用于确保角色外貌描述的连贯性。",
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {
                "type": "integer",
                "description": "章节 ID"
            }
        },
        "required": ["chapter_id"]
    }
)
async def get_character_profiles(chapter_id: int, ctx: dict) -> dict:
    """返回角色外貌描述"""
```

### 3.4 写入工具（Write Tools）

以下工具赋予 Agent 修改作品内容的能力：

#### 3.4.1 `update_chapter_content` — 直接替换章节正文

```python
@ToolRegistry.register(
    name="update_chapter_content",
    description="直接替换指定章节的完整正文(novel_content)。用于用户明确要求使用新内容覆盖旧内容时。注意：此操作会完全替换现有内容。",
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer", "description": "章节 ID"},
            "content": {"type": "string", "description": "新的章节正文内容"}
        },
        "required": ["chapter_id", "content"]
    }
)
async def update_chapter_content(chapter_id: int, content: str, ctx: dict) -> dict:
    """直接保存章节正文"""
```

#### 3.4.2 `adjust_chapter_by_instruction` — 按指令 AI 修改章节

```python
@ToolRegistry.register(
    name="adjust_chapter_by_instruction",
    description="根据用户指令 AI 调整章节内容（调长度、改风格、增删段落等）。不会完全替换，AI 会在现有内容基础上修改。",
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer", "description": "章节 ID"},
            "instruction": {"type": "string", "description": "修改指令，如"压缩到2000字""改成第一人称""增加环境描写""}
        },
        "required": ["chapter_id", "instruction"]
    }
)
async def adjust_chapter_by_instruction(chapter_id: int, instruction: str, ctx: dict) -> dict:
    """调用现有 adjustChapterContent API"""
```

#### 3.4.3 `rewrite_text_segment` — 精确替换某段文字

```python
@ToolRegistry.register(
    name="rewrite_text_segment",
    description="精确替换章节正文中的指定文本段落。用于找到并替换特定的一段内容。",
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer", "description": "章节 ID"},
            "original": {"type": "string", "description": "原文中要被替换的段落（尽量完整，确保唯一匹配）"},
            "rewritten": {"type": "string", "description": "替换后的内容"}
        },
        "required": ["chapter_id", "original", "rewritten"]
    }
)
async def rewrite_text_segment(chapter_id: int, original: str, rewritten: str, ctx: dict) -> dict:
    """精确查找替换"""
```

#### 3.4.4 `update_story_info` — 更新故事元信息

```python
@ToolRegistry.register(
    name="update_story_info",
    description="更新故事的标题、描述、标签。",
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
            "title": {"type": "string", "description": "新标题（可选）"},
            "description": {"type": "string", "description": "新描述（可选）"},
            "tags": {"type": "object", "description": "新标签对象（可选），格式: { type, theme, style, audience }"}
        },
        "required": ["story_id"]
    }
)
async def update_story_info(story_id: int, **kwargs) -> dict:
    """调用 updateStory API"""
```

#### 3.4.5 `update_characters` — 更新角色设定

```python
@ToolRegistry.register(
    name="update_characters",
    description="替换全部角色设定列表。注意：这是全量替换，需传入完整的角色数组。",
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
            "characters": {
                "type": "array",
                "description": "完整的角色设定数组",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "role": {"type": "string", "description": "主角/配角/反派"},
                        "big_five": {"type": "object"},
                        "arc": {"type": "object"},
                        "relationships": {"type": "array"}
                    }
                }
            }
        },
        "required": ["story_id", "characters"]
    }
)
async def update_characters(story_id: int, characters: list) -> dict:
    """更新角色设定"""
```

#### 3.4.6 `adjust_framework` — 对话式调整框架

```python
@ToolRegistry.register(
    name="adjust_framework",
    description="通过 AI 对话方式调整故事框架（标签/角色/大纲）。适合需要 AI 创意发挥的调整。",
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
            "instruction": {"type": "string", "description": "调整指令"}
        },
        "required": ["story_id", "instruction"]
    }
)
async def adjust_framework(story_id: int, instruction: str, ctx: dict) -> dict:
    """调用现有 adjustFramework API"""
```

#### 3.4.7 `add_chapter_plan` — 追加章节规划

```python
@ToolRegistry.register(
    name="add_chapter_plan",
    description="在故事大纲中追加一个章节规划。",
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
            "chapter": {
                "type": "object",
                "properties": {
                    "chapter_number": {"type": "integer"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "act": {"type": "integer"},
                    "key_events": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["chapter_number", "title"]
            }
        },
        "required": ["story_id", "chapter"]
    }
)
async def add_chapter_plan(story_id: int, chapter: dict) -> dict:
    """更新大纲章节列表"""
```

#### 3.4.8 `update_scenes` — 更新分镜脚本

```python
@ToolRegistry.register(
    name="update_scenes",
    description="替换指定章节的全部分镜脚本。注意：这是全量替换。",
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer"},
            "scenes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "scene_number": {"type": "integer"},
                        "description": {"type": "string"},
                        "dialogue": {"type": "string"},
                        "shot_type": {"type": "string"},
                        "character": {"type": "string"}
                    }
                }
            }
        },
        "required": ["chapter_id", "scenes"]
    }
)
async def update_scenes(chapter_id: int, scenes: list) -> dict:
    """更新分镜脚本"""
```

### 3.5 `agent_service.py` — AgentService 核心类

```python
class AgentService:
    """Agent 对话服务——协调上下文构建、LLM 调用、工具执行和 SSE 流式输出"""

    def __init__(self, db: Session, story_id: int, chapter_id: int | None = None):
        self.db = db
        self.story_id = story_id
        self.chapter_id = chapter_id
        self.story = db.query(Story).get(story_id)

    async def build_system_prompt(self) -> str:
        """构建系统提示词，包含当前作品上下文和可用工具说明"""
        context = {
            "story_meta": self._get_story_meta(),
            "framework": self._get_framework_summary(),
            "chapters_summary": self._get_chapters_summary(),
        }
        if self.chapter_id:
            context["current_chapter"] = self._get_chapter_preview()

        return f"""你是一个专业的小说创作助手，正在协助用户创作小说《{self.story.title}》。

## 当前作品信息

{json.dumps(context, ensure_ascii=False, indent=2)}

## 行为准则

1. **先读后写**：在修改任何内容前，先用读取工具阅读相关内容的当前状态
2. **精准修改**：能局部修改就不要全量替换
3. **说明理由**：每次修改后简要说明改了什么、为什么这样改
4. **尊重意图**：修改应符合作品的已有风格和设定
5. **流式思考**：边思考边展示，让用户看到你的推理过程

## 可用工具

你可以使用以下工具来读取和修改作品内容。使用工具时，系统会实时执行并返回结果。

- **读取工具**：get_chapter_full, get_all_chapters_summary, get_framework_detail, get_story_bible, get_scenes, get_character_profiles
- **写入工具**：update_chapter_content, adjust_chapter_by_instruction, rewrite_text_segment, update_story_info, update_characters, adjust_framework, add_chapter_plan, update_scenes

先思考用户需要什么，规划好工具调用顺序，然后逐步执行。"""

    async def chat_stream(
        self,
        messages: list[dict],
        on_token: Callable[[str], None],
        on_tool_call: Callable[[str, dict], None],
        on_tool_result: Callable[[str, bool, str], None],
    ):
        """处理一次完整的 Agent 对话，使用 SSE 流式输出"""
        system_prompt = await self.build_system_prompt()
        # 处理对话循环
        # ...
```

### 3.6 SSE 协议设计

#### 3.6.1 端点

```
POST /api/stories/{story_id}/agent/chat
```

**请求体**（JSON）:

```json
{
  "messages": [
    { "role": "user", "content": "第三章开头有点拖，帮我改改" },
    { "role": "assistant", "content": "好的，我来看看第三章..." }
  ],
  "chapter_id": 3
}
```

**响应**：`text/event-stream`

#### 3.6.2 事件类型

| 事件名 | 数据格式 | 说明 |
|--------|---------|------|
| `token` | `{ "type": "token", "content": "好" }` | LLM 输出的文本片段 |
| `tool_call` | `{ "type": "tool_call", "name": "get_chapter_full", "args": { "chapter_id": 3 } }` | Agent 发起了工具调用 |
| `tool_result` | `{ "type": "tool_result", "name": "get_chapter_full", "success": true, "summary": "已读取第3章，共3456字" }` | 工具执行结果 |
| `done` | `{ "type": "done", "content": "已完成修改，开头压缩到112字..." }` | 对话回复结束 |

#### 3.6.3 SSE 流示例

```
event: token
data: {"type":"token","content":"我来看看第三章的情况"}

event: token
data: {"type":"token","content":"，先读取全文分析一下。"}

event: tool_call
data: {"type":"tool_call","name":"get_chapter_full","args":{"chapter_id":3}}

event: tool_result
data: {"type":"tool_result","name":"get_chapter_full","success":true,"summary":"已读取第3章《初入宗门》，共3456字，质量评分78"}

event: token
data: {"type":"token","content":"嗯，开头确实用了300字描写环境，有点拖节奏。"}

event: token
data: {"type":"token","content":"建议压缩到100字，直接用对话切入。"}

event: tool_call
data: {"type":"tool_call","name":"adjust_chapter_by_instruction","args":{"chapter_id":3,"instruction":"压缩开头环境描写到100字，改为从对话直接切入"}}

event: tool_result
data: {"type":"tool_result","name":"adjust_chapter_by_instruction","success":true,"summary":"已调整完成，开头字数从345减到112"}

event: token
data: {"type":"token","content":"修改完成！开头现在直接从对话开始，节奏快了很多。你看看效果如何？"}

event: done
data: {"type":"done","content":"修改完成！开头现在直接从对话开始，节奏快了很多。你看看效果如何？"}
```

### 3.7 上下文构建复用

Agent 的上下文构建器复用现有 `main.py` 中的构建函数：

| 现有函数 | 用途 | Agent 中使用 |
|---------|------|-------------|
| `_build_framework_context(story)` | 构建框架上下文 | 注入 system prompt |
| `_build_story_memory_compact(story)` | 构建故事记忆 | 注入 system prompt |
| `_build_story_bible_compact(story)` | 构建创作圣经 | 注入 system prompt |

不需要重写这些逻辑，直接在 `AgentService.build_system_prompt()` 中调用它们。

### 3.8 `agent_router.py` — FastAPI 路由

```python
# backend/routers/agent_router.py

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/stories/{story_id}/agent")

class ChatRequest(BaseModel):
    messages: list[dict]
    chapter_id: int | None = None

@router.post("/chat")
async def agent_chat(
    story_id: int,
    req: ChatRequest,
    db: Session = Depends(get_db),
):
    """Agent 对话 SSE 端点"""

    async def event_stream():
        service = AgentService(db, story_id, req.chapter_id)

        async def on_token(content: str):
            yield f"event: token\ndata: {json.dumps({'type':'token','content':content})}\n\n"

        async def on_tool_call(name: str, args: dict):
            yield f"event: tool_call\ndata: {json.dumps({'type':'tool_call','name':name,'args':args})}\n\n"

        async def on_tool_result(name: str, success: bool, summary: str):
            yield f"event: tool_result\ndata: {json.dumps({'type':'tool_result','name':name,'success':success,'summary':summary})}\n\n"

        await service.chat_stream(
            messages=req.messages,
            on_token=on_token,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
        )

        yield f"event: done\ndata: {json.dumps({'type':'done'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
```

---

## 4. 前端组件设计

### 4.1 新增文件

```
frontend/src/components/AgentPanel/
├── AgentPanel.tsx         ← 主组件
├── AgentMessage.tsx       ← 单条消息渲染
├── AgentInput.tsx         ← 输入框
├── QuickActions.tsx       ← 快捷操作卡片
├── ToolCallStatus.tsx     ← 工具调用状态指示
├── index.ts
```

### 4.2 `AgentPanel.tsx` — 主组件

```tsx
// AgentPanel.tsx —— 右侧 AI 助手面板

import { AgentMessage } from './AgentMessage';
import { AgentInput } from './AgentInput';
import { QuickActions } from './QuickActions';
import { ToolCallStatus } from './ToolCallStatus';

interface ToolCall {
  id: string;
  name: string;
  args: Record<string, any>;
  status: 'running' | 'success' | 'error';
  summary?: string;
}

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: ToolCall[];
}

interface AgentPanelProps {
  storyId: number;
  chapterId?: number;              // 来自 EditorPanel 的当前章节
  storyTitle?: string;
  chapterTitle?: string;
}

const AgentPanel: React.FC<AgentPanelProps> = ({ storyId, chapterId, storyTitle, chapterTitle }) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const handleSend = async (content: string) => {
    const userMsg: Message = { id: uuid(), role: 'user', content };
    const assistantMsg: Message = { id: uuid(), role: 'assistant', content: '' };

    setMessages(prev => [...prev, userMsg, assistantMsg]);
    setIsStreaming(true);

    const abortController = agentChatStream(storyId, [
      ...messages.map(m => ({ role: m.role, content: m.content })),
      { role: 'user', content },
    ], chapterId, {
      onToken: (token) => {
        setMessages(prev => {
          const last = prev[prev.length - 1];
          if (last.role === 'assistant') {
            return [...prev.slice(0, -1), { ...last, content: last.content + token }];
          }
          return prev;
        });
      },
      onToolCall: (name, args) => {
        const tc: ToolCall = { id: uuid(), name, args, status: 'running' };
        setMessages(prev => {
          const last = prev[prev.length - 1];
          const toolCalls = [...(last.toolCalls || []), tc];
          return [...prev.slice(0, -1), { ...last, toolCalls }];
        });
      },
      onToolResult: (name, success, summary) => {
        setMessages(prev => {
          const last = prev[prev.length - 1];
          const toolCalls = (last.toolCalls || []).map(tc =>
            tc.name === name && tc.status === 'running'
              ? { ...tc, status: success ? 'success' as const : 'error' as const, summary }
              : tc
          );
          return [...prev.slice(0, -1), { ...last, toolCalls }];
        });
      },
      onDone: () => setIsStreaming(false),
      onError: () => setIsStreaming(false),
    });
    abortRef.current = abortController;
  };

  return (
    <div className={styles.agentPanel}>
      {/* 头部状态栏 */}
      <div className={styles.statusBar}>
        <span className={styles.statusIcon}>🤖</span>
        <span>AI 助手</span>
        {chapterTitle && (
          <span className={styles.contextTag}>当前：第{chapterId}章 · {chapterTitle}</span>
        )}
      </div>

      {/* 消息列表 */}
      <div className={styles.messageList} ref={scrollRef}>
        {messages.length === 0 && <WelcomeScreen onQuickAction={handleSend} />}
        {messages.map(msg => (
          <AgentMessage key={msg.id} message={msg} />
        ))}
      </div>

      {/* 快捷操作（仅首次时展示） */}
      {messages.length === 0 && (
        <QuickActions onSelect={handleSend} storyId={storyId} />
      )}

      {/* 底部输入 */}
      <AgentInput onSend={handleSend} disabled={isStreaming} />
    </div>
  );
};
```

### 4.3 `AgentMessage.tsx` — 消息渲染组件

```tsx
// AgentMessage.tsx

const AgentMessage: React.FC<{ message: Message }> = ({ message }) => {
  const isUser = message.role === 'user';

  return (
    <div className={`${styles.message} ${isUser ? styles.userMessage : styles.assistantMessage}`}>
      <div className={styles.avatar}>{isUser ? '👤' : '🤖'}</div>
      <div className={styles.bubble}>
        <div className={styles.content}>{message.content}</div>

        {/* 工具调用状态列表 */}
        {message.toolCalls?.map(tc => (
          <ToolCallStatus key={tc.id} toolCall={tc} />
        ))}
      </div>
    </div>
  );
};
```

### 4.4 `ToolCallStatus.tsx` — 工具执行状态

```tsx
// ToolCallStatus.tsx

const ToolCallStatus: React.FC<{ toolCall: ToolCall }> = ({ toolCall }) => {
  const iconMap = {
    running: '⏳',
    success: '✅',
    error: '❌',
  };

  const labelMap: Record<string, string> = {
    get_chapter_full: '正在读取章节全文…',
    get_all_chapters_summary: '正在获取章节概览…',
    get_framework_detail: '正在读取故事框架…',
    update_chapter_content: '正在保存章节内容…',
    adjust_chapter_by_instruction: '正在按指令调整章节…',
    rewrite_text_segment: '正在替换指定段落…',
    adjust_framework: '正在调整故事框架…',
  };

  return (
    <div className={`${styles.toolCall} ${styles[toolCall.status]}`}>
      <span className={styles.toolIcon}>{iconMap[toolCall.status]}</span>
      <span className={styles.toolLabel}>
        {toolCall.status === 'running'
          ? (labelMap[toolCall.name] || `正在执行 ${toolCall.name}…`)
          : (toolCall.summary || labelMap[toolCall.name] || toolCall.name)
        }
      </span>
    </div>
  );
};
```

### 4.5 `QuickActions.tsx` — 快捷操作卡片

```tsx
// QuickActions.tsx

const QUICK_ACTIONS = [
  { icon: '📖', label: '阅读当前章节', hint: '分析本章写作质量' },
  { icon: '✍️', label: '修改当前章节', hint: '按需求调整本章内容' },
  { icon: '📋', label: '优化故事框架', hint: '检查并改进故事结构' },
  { icon: '📊', label: '质量评估', hint: '对已完成的章节评分' },
  { icon: '🎨', label: '优化分镜脚本', hint: '改进本章分镜设计' },
  { icon: '👤', label: '角色设定建议', hint: '分析角色弧光' },
];

const QuickActions: React.FC<{ onSelect: (prompt: string) => void }> = ({ onSelect }) => {
  const promptMap: Record<string, string> = {
    '阅读当前章节': '请阅读本章全文，分析写作质量，给出改进建议',
    '修改当前章节': '请先阅读本章全文，然后按我的要求修改',
    '优化故事框架': '请阅读故事框架，分析结构问题并给出优化方案',
    '质量评估': '请对已完成的所有章节进行质量评估',
    '优化分镜脚本': '请阅读本章分镜并提出优化建议',
    '角色设定建议': '请阅读角色设定，分析角色弧光和发展潜力',
  };

  return (
    <div className={styles.quickActions}>
      <div className={styles.quickTitle}>快捷操作</div>
      <div className={styles.quickGrid}>
        {QUICK_ACTIONS.map(action => (
          <button
            key={action.label}
            className={styles.quickCard}
            onClick={() => onSelect(promptMap[action.label])}
          >
            <span className={styles.quickIcon}>{action.icon}</span>
            <span className={styles.quickLabel}>{action.label}</span>
            <span className={styles.quickHint}>{action.hint}</span>
          </button>
        ))}
      </div>
    </div>
  );
};
```

### 4.6 `api.ts` 追加 — SSE 流客户端

```typescript
// frontend/src/api.ts 追加

export function agentChatStream(
  storyId: number,
  messages: { role: string; content: string }[],
  chapterId?: number,
  callbacks: {
    onToken: (token: string) => void;
    onToolCall: (name: string, args: any) => void;
    onToolResult: (name: string, success: boolean, summary: string) => void;
    onDone: () => void;
    onError: (err: string) => void;
  },
): AbortController {
  const controller = new AbortController();

  fetch(`/api/stories/${storyId}/agent/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, chapter_id: chapterId }),
    signal: controller.signal,
  }).then(async response => {
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      let eventType = '';
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          const data = JSON.parse(line.slice(6));
          handleEvent(eventType, data, callbacks);
        }
      }
    }
  }).catch(err => {
    if (err.name !== 'AbortError') {
      callbacks.onError(err.message);
    }
  });

  return controller;
}

function handleEvent(
  eventType: string,
  data: any,
  callbacks: { onToken: Function; onToolCall: Function; onToolResult: Function; onDone: Function; onError: Function },
) {
  switch (eventType) {
    case 'token':
      callbacks.onToken(data.content);
      break;
    case 'tool_call':
      callbacks.onToolCall(data.name, data.args);
      break;
    case 'tool_result':
      callbacks.onToolResult(data.name, data.success, data.summary);
      break;
    case 'done':
      callbacks.onDone();
      break;
  }
}
```

---

## 5. WorkspaceLayout 改造

### 5.1 改造目标

将右侧固定 `MangaPanel` 改为标签切换面板：

```
改造前：
┌──────────┬──────────────────────┬────────────┐
│          │                      │            │
│ Framework │                      │   Manga    │
│  Panel   │     EditorPanel      │   Panel    │
│  (280px) │      (flex-1)        │  (400px)   │
│          │                      │            │
└──────────┴──────────────────────┴────────────┘

改造后：
┌──────────┬──────────────────────┬──────────────────┐
│          │                      │ [漫画操作区] [🤖 AI助手]│
│ Framework │                      │                  │
│  Panel   │     EditorPanel      │  MangaPanel /    │
│  (280px) │      (flex-1)        │  AgentPanel      │
│          │                      │  (400px)         │
└──────────┴──────────────────────┴──────────────────┘
```

### 5.2 WorkspaceLayout.tsx 改动

```tsx
// WorkspaceLayout.tsx 关键改动

// 状态定义
const [rightPanelTab, setRightPanelTab] = useState<'manga' | 'agent'>(
  // 优先使用上次选中的标签（localStorage），默认 AI 助手
  () => (localStorage.getItem('rightPanelTab') as 'manga' | 'agent') || 'agent'
);

// 标签栏
const renderRightPanelTabs = () => (
  <div className={styles.rightPanelHeader}>
    <button
      className={`${styles.tab} ${rightPanelTab === 'manga' ? styles.activeTab : ''}`}
      onClick={() => { setRightPanelTab('manga'); localStorage.setItem('rightPanelTab', 'manga'); }}
    >
      <span>🖼️</span> 漫画操作区
    </button>
    <button
      className={`${styles.tab} ${rightPanelTab === 'agent' ? styles.activeTab : ''}`}
      onClick={() => { setRightPanelTab('agent'); localStorage.setItem('rightPanelTab', 'agent'); }}
    >
      <span>🤖</span> AI 助手
    </button>
  </div>
);

// 右侧面板内容
const renderRightPanel = () => {
  if (rightPanelTab === 'manga') {
    return <MangaPanel chapterId={editorChapterId} />;
  }
  return (
    <AgentPanel
      storyId={storyId}
      chapterId={editorChapterId}
      storyTitle={story?.title}
      chapterTitle={currentChapter?.title}
    />
  );
};
```

### 5.3 与 EditorPanel 的联动

AgentPanel 通过 `chapterId` prop 与 EditorPanel 保持同步：

```
EditorPanel（用户正在编辑第3章）
    │ setEditorChapterId(3)
    ▼
WorkspaceLayout 将 editorChapterId 传递给 AgentPanel
    │
    ▼
AgentPanel 在状态栏显示 "当前：第3章 · 初入宗门"
    │
用户提问 → 自动携带 chapter_id=3 发送给后端 Agent
后端在 system prompt 中包含第3章全文
```

### 5.4 标签切换状态保留（方案 B：状态提升）

```tsx
// WorkspaceLayout.tsx

// 状态提升到 WorkspaceLayout 层级
const [agentMessages, setAgentMessages] = useState<Message[]>([]);
const [agentStreaming, setAgentStreaming] = useState(false);

// AgentPanel 变为纯受控组件
<AgentPanel
  messages={agentMessages}
  setMessages={setAgentMessages}
  streaming={agentStreaming}
  setStreaming={setAgentStreaming}
  storyId={storyId}
  chapterId={editorChapterId}
  storyTitle={story?.title}
  chapterTitle={currentChapter?.title}
/>
```

---

## 6. 完整性对话示例

以下是一个完整对话流程，展示 Agent 如何实现「阅读 → 分析 → 修改」的闭环：

```
✨ 用户：
"第二章的节奏太慢了，帮我优化一下，压缩到2000字以内"

🤖 Agent（流式输出）：
"好的，我先看看第二章目前的状态。"

  ┌─ 🔍 get_chapter_full(chapter_id=2)  ──────────────────┐
  │  "已读取第2章，共3654字，描述性段落占比约60%"         │
  └───────────────────────────────────────────────────────┘

"第二章共3654字，其中环境描写和内心独白占了主要篇幅。
我建议：
1. 压缩环境描写，从500字减到150字
2. 将大段的内心独白改为对话形式
3. 加快情节推进速度"

  ┌─ ✍️ adjust_chapter_by_instruction(chapter_id=2,       ─┐
  │      instruction="压缩到2000字以内，减少环境描写，     │
  │      将内心独白改为对话形式，加快情节节奏")            │
  │  "已按指令调整完成，共1956字，压缩率46%"               │
  └───────────────────────────────────────────────────────┘

"修改完成！从3654字压缩到1956字，删减了环境描写，把主角
的内心独白改为与配角的对话，节奏快了很多。你看看吧？👀"
```

---

## 7. 文件改动清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `backend/services/agent_service.py` | **新建** | ToolRegistry + AgentService 核心逻辑 |
| `backend/routers/agent_router.py` | **新建** | SSE 端点 `POST /api/stories/{id}/agent/chat` |
| `backend/main.py` | 修改 | 注册 `agent_router` |
| `frontend/src/api.ts` | 追加 | `agentChatStream()` SSE 客户端函数 |
| `frontend/src/components/AgentPanel/` | **新建目录** | AgentPanel 组件族 |
| `frontend/src/components/AgentPanel/AgentPanel.tsx` | **新建** | 主组件 |
| `frontend/src/components/AgentPanel/AgentMessage.tsx` | **新建** | 消息渲染 |
| `frontend/src/components/AgentPanel/AgentInput.tsx` | **新建** | 输入框 |
| `frontend/src/components/AgentPanel/QuickActions.tsx` | **新建** | 快捷操作卡片 |
| `frontend/src/components/AgentPanel/ToolCallStatus.tsx` | **新建** | 工具状态指示 |
| `frontend/src/components/AgentPanel/index.ts` | **新建** | 导出 |
| `frontend/src/components/WorkspaceLayout.tsx` | 修改 | 右侧面板改为标签切换，状态提升 |
| `frontend/src/components/WorkspaceLayout.css` | 修改 | 标签栏样式 |

---

## 8. 约束与限制

- **工具调用超时**：单次工具调用上限 30 秒，超时标记为 error
- **对话上下文长度**：保留最近 20 条消息，超出时自动截断最早的用户/助手对
- **章节正文长度**：超过 8000 字的章节，system prompt 中只包含前 2000 字预览，Agent 需通过 `get_chapter_full` 读取全文
- **并发**：同一故事同一时间只允许一个 Agent 对话进行中（避免数据竞争）
- **API 密钥**：复用后端 `settings.DEEPSEEK_API_KEY`，前端不接触

---

## 9. 后续迭代（本次范围外）

- 记忆持久化：Agent 能记住跨对话的连续性信息（已修复的问题、用户的风格偏好）
- 多轮工具链：支持 Agent 并行调用多个工具
- 撤销操作：用户能回退 Agent 的修改
- 对比模式：修改前后内容对比显示
- 批量操作：对多章同时执行相同操作
- Agent 自定义：用户可自定义 system prompt 或添加私有知识

---

## 10. 风险与注意事项

- **SSE 连接中断**：前端需实现重连机制，工具执行可能产生脏数据
- **工具调用时序**：DeepSeek function calling 可能一次返回多个工具调用，后端需顺序执行
- **大章节性能**：读取 10000 字+章节全文时，工具返回数据量较大，注意 SSE 分片
- **对话长度膨胀**：长时间使用后，messages 列表增长，需实施合理的截断策略
- **现有 API 适配**：部分现有 API（如 `adjustChapterContent`）返回格式需要标准化包装，确保 Agent 工具 handler 能正确解析
