# 小说创作架构读写一致性修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Agent 助手、左侧框架助手、作品圣经摘要、连续记忆与小说框架之间的读写/展示不一致，确保“系统能读写的内容”和“用户能看到、能确认、能回滚的内容”一致。

**Architecture:** 建立共享的 Story Bible/Story Memory/Framework 数据契约与工具层，后端所有入口复用同一套深合并、快照、记忆刷新与 operation apply 逻辑。前端从“固定字段摘要卡”升级为“精选摘要 + 完整回显 + 差异确认”，左侧框架助手从只会增量操作扩展为支持明确的替换/重排/删除意图，但默认仍走安全增量与快照保护。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2.0 / PostgreSQL JSON / React 19 / TypeScript / Vite / DeepSeek function calling

---

## 问题清单

1. `StoryBibleSummaryCard` 只渲染白名单字段，`raw_input`、`import_guidance`、未知扩展字段没有完整回显。
2. `WorkspaceLayout` 只有 `story.story_bible.creative_brief` 存在时才显示圣经卡，导入作品只有 `raw_input/import_guidance` 时可能完全不可见。
3. `update_story_bible` 前后端与 Agent 工具都只做一层浅合并，嵌套 `world_setting` 更新可能覆盖旧内容。
4. Agent 能读取/写入的 `story_bible`、`story_memory`、`outline` 内容，比用户 UI 能看到的更完整，形成“隐形状态”。
5. Agent 修改章节正文后不会刷新 `chapter.memory_summary` 和 `story.story_memory`，普通章节生成链路会刷新，导致入口不一致。
6. Agent 前端固定用 `execute` 模式调用，后端已有 `chat/analyze/execute`，但 UI 没有暴露只读分析模式。
7. Agent 待确认修改存放在进程内存，服务重启/多 worker/容器滚动更新后无法回滚。
8. 左侧框架助手复用 operation apply 后主要偏增量编辑；用户要求“重写/替换/重新规划整段大纲”时，容易只追加或小修，不能明确执行范围替换。
9. `/framework/generate` 保存时疑似把 `story.tags` 设回旧值，导致首次生成标签不落库。
10. 框架/圣经/记忆逻辑散落在 `main.py`、`agent_service.py`、`deepseek.py`，存在同类 compact/context 构建漂移。

---

## 文件结构与职责

- Create: `backend/services/story_state.py`
  - 集中 Story Bible 深合并、完整可视化 payload、Story Memory compact、Framework context 构建。
- Modify: `backend/main.py`
  - 复用 `story_state.py`；修复 `/story-bible` 深合并、`/framework/generate` 标签保存、章节变更后的记忆刷新一致性。
- Modify: `backend/services/agent_service.py`
  - 复用共享 Story Bible/Memory 工具；Agent 写章节后刷新记忆；增加模式与持久化待确认变更规划。
- Modify: `backend/services/framework_utils.py`
  - 扩展 operation 契约，支持范围替换/重排，同时保留安全校验和快照。
- Modify: `backend/services/deepseek.py`
  - 框架调整/续写 prompt 明确支持 `replace_*` 操作，并根据用户意图区分增量、替换、重排。
- Modify: `frontend/src/api.ts`
  - 扩展 Story Bible 类型为允许未知字段；Agent mode 类型和调用参数显式化。
- Modify: `frontend/src/components/StoryBibleSummaryCard.tsx`
  - 增加完整作品圣经递归回显；编辑保存保留未知字段；展示 raw/import/unknown sections。
- Modify: `frontend/src/components/WorkspaceLayout.tsx`
  - 只要 `story.story_bible` 非空就展示圣经卡。
- Modify: `frontend/src/components/AgentPanel/AgentPanel.tsx`
  - 增加只读/分析/执行模式切换，默认分析类快捷动作走 `analyze`。
- Modify: `frontend/src/components/FrameworkPanel.tsx`
  - 增加“增量调整 / 替换重构 / 仅分析”意图选择或自动提示；展示实际应用范围。
- Create: `backend/tests/test_story_state_contract.py`
  - 覆盖深合并、完整回显 payload、memory compact 一致性。
- Create: `backend/tests/test_agent_memory_refresh.py`
  - 覆盖 Agent 写章节后刷新记忆。
- Create: `backend/tests/test_framework_replace_operations.py`
  - 覆盖替换型 framework operations。
- Create: `frontend/src/components/__tests__/StoryBibleSummaryCard.test.tsx`
  - 覆盖完整回显和未知字段保留。

---

### Task 1: 建立 Story Bible 深合并与完整回显契约

**Files:**
- Create: `backend/services/story_state.py`
- Modify: `backend/main.py:8364-8388`
- Modify: `backend/services/agent_service.py:849-893`
- Test: `backend/tests/test_story_state_contract.py`

- [ ] **Step 1: 写深合并失败测试**

```python
from services.story_state import deep_merge_story_bible


def test_deep_merge_story_bible_preserves_nested_world_setting():
    existing = {
        "creative_brief": {
            "one_line_premise": "旧梗概",
            "world_setting": {
                "power_system": {"levels": ["凡人", "修士"]},
                "society_structure": "宗门与王朝并存",
            },
        },
        "import_guidance": {"must_keep": "保留原主线"},
    }
    update = {
        "creative_brief": {
            "world_setting": {
                "power_system": {"source": "星辉"},
            }
        }
    }

    merged = deep_merge_story_bible(existing, update)

    assert merged["creative_brief"]["one_line_premise"] == "旧梗概"
    assert merged["creative_brief"]["world_setting"]["society_structure"] == "宗门与王朝并存"
    assert merged["creative_brief"]["world_setting"]["power_system"]["levels"] == ["凡人", "修士"]
    assert merged["creative_brief"]["world_setting"]["power_system"]["source"] == "星辉"
    assert merged["import_guidance"]["must_keep"] == "保留原主线"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_story_state_contract.py::test_deep_merge_story_bible_preserves_nested_world_setting -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'services.story_state'`

- [ ] **Step 3: 创建共享深合并工具**

在 `backend/services/story_state.py` 写入：

```python
from __future__ import annotations

from copy import deepcopy
from typing import Any


def _is_plain_dict(value: Any) -> bool:
    return isinstance(value, dict)


def deep_merge_dict(existing: dict | None, update: dict | None) -> dict:
    base = deepcopy(existing) if isinstance(existing, dict) else {}
    incoming = update if isinstance(update, dict) else {}
    for key, value in incoming.items():
        if _is_plain_dict(value) and _is_plain_dict(base.get(key)):
            base[key] = deep_merge_dict(base[key], value)
        else:
            base[key] = deepcopy(value)
    return base


def deep_merge_story_bible(existing: dict | None, update: dict | None) -> dict:
    return deep_merge_dict(existing, update)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_story_state_contract.py::test_deep_merge_story_bible_preserves_nested_world_setting -v`

Expected: PASS

- [ ] **Step 5: 替换后端 PATCH 与 Agent 工具的浅合并**

在 `backend/main.py` 的 `update_story_bible` 中把 line `8371-8379` 的手写合并替换为：

```python
    from services.story_state import deep_merge_story_bible

    current = deep_merge_story_bible(story.story_bible, bible_update)
    story.story_bible = current
```

在 `backend/services/agent_service.py` 的 `update_story_bible` 中把 line `868-876` 的手写合并替换为：

```python
        from services.story_state import deep_merge_story_bible

        current = deep_merge_story_bible(story.story_bible, story_bible)
        story.story_bible = current
```

- [ ] **Step 6: 运行后端相关测试**

Run: `cd backend && python -m pytest tests/test_story_state_contract.py -v`

Expected: PASS

---

### Task 2: 前端作品圣经摘要完整回显与未知字段保留

**Files:**
- Modify: `frontend/src/api.ts:388-432`
- Modify: `frontend/src/components/StoryBibleSummaryCard.tsx`
- Modify: `frontend/src/components/WorkspaceLayout.tsx:54-62`
- Test: `frontend/src/components/__tests__/StoryBibleSummaryCard.test.tsx`

- [ ] **Step 1: 放宽 Story Bible 类型，允许未知字段**

在 `frontend/src/api.ts` 更新类型：

```ts
export interface CreativeBrief extends Record<string, any> {
  project_positioning: string;
  genre: string;
  audience: string;
  tone: string;
  core_hook: string;
  one_line_premise: string;
  protagonist_core: string;
  main_conflict: string;
  longline_mystery: string;
  serial_length_target: string;
  must_keep_rules: string[];
  reveal_strategy: string;
  pacing_strategy: string;
  world_setting?: any;
  open_story_notes?: string;
}

export interface StoryBible extends Record<string, any> {
  raw_input?: Record<string, any>;
  creative_brief?: CreativeBrief;
  writing_guidance?: Record<string, any>;
  import_guidance?: Record<string, any>;
}
```

- [ ] **Step 2: 修改显示条件为 story_bible 非空**

在 `frontend/src/components/WorkspaceLayout.tsx` 把：

```tsx
{story.story_bible?.creative_brief && (
```

替换为：

```tsx
{story.story_bible && Object.keys(story.story_bible).length > 0 && (
```

- [ ] **Step 3: 添加通用递归回显组件**

在 `StoryBibleSummaryCard.tsx` 的 `WorldSettingNode` 后新增：

```tsx
const STORY_BIBLE_SECTION_LABELS: Record<string, string> = {
  raw_input: '原始输入',
  creative_brief: '创意摘要',
  writing_guidance: '写作指导',
  import_guidance: '导入指导',
};

function StoryBibleFullView({ storyBible }: { storyBible: StoryBible }) {
  const entries = Object.entries(storyBible).filter(([, value]) => hasRenderableValue(value));
  if (!entries.length) return null;
  return (
    <div className="mt-3 rounded-xl border border-[#d7e3f4] bg-white/80 p-3 sm:col-span-2 lg:col-span-3">
      <div className="mb-2 text-[11px] font-medium text-[#2563eb]">完整作品圣经</div>
      <div className="space-y-2">
        {entries.map(([key, value]) => (
          <GenericJsonNode key={key} label={STORY_BIBLE_SECTION_LABELS[key] ?? key} value={value} />
        ))}
      </div>
    </div>
  );
}

function GenericJsonNode({ label, value, depth = 0 }: { label: string; value: unknown; depth?: number }) {
  if (!hasRenderableValue(value)) return null;
  if (Array.isArray(value)) {
    return (
      <div className={`rounded-lg border border-[#e5edf8] bg-[#fafdff] p-2 ${depth > 0 ? 'ml-2' : ''}`}>
        <div className="text-[10px] font-medium text-slate-500">{label}</div>
        <div className="mt-1 space-y-1">
          {value.map((item, index) => (
            <GenericJsonNode key={index} label={`#${index + 1}`} value={item} depth={depth + 1} />
          ))}
        </div>
      </div>
    );
  }
  if (typeof value === 'object' && value !== null) {
    return (
      <div className={`rounded-lg border border-[#e5edf8] bg-[#fafdff] p-2 ${depth > 0 ? 'ml-2' : ''}`}>
        <div className="text-[10px] font-medium text-slate-500">{label}</div>
        <div className="mt-1 space-y-1">
          {Object.entries(value as Record<string, unknown>).map(([key, child]) => (
            <GenericJsonNode key={key} label={translateLabel(key)} value={child} depth={depth + 1} />
          ))}
        </div>
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-[#e5edf8] bg-[#fafdff] p-2">
      <div className="text-[10px] font-medium text-slate-500">{label}</div>
      <div className="mt-0.5 whitespace-pre-wrap text-xs leading-5 text-slate-600">{String(value)}</div>
    </div>
  );
}

function hasRenderableValue(value: unknown): boolean {
  if (value == null) return false;
  if (typeof value === 'string') return value.trim().length > 0;
  if (Array.isArray(value)) return value.some(hasRenderableValue);
  if (typeof value === 'object') return Object.values(value as Record<string, unknown>).some(hasRenderableValue);
  return true;
}
```

- [ ] **Step 4: 在展开区渲染完整作品圣经**

在 `StoryBibleSummaryCard.tsx` 的精选字段 grid 末尾、`</div>` 前加入：

```tsx
<StoryBibleFullView storyBible={storyBible} />
```

- [ ] **Step 5: 让没有 creative_brief 的 story_bible 也能显示**

把 `if (!brief) return null;` 替换为：

```tsx
if (!storyBible || Object.keys(storyBible).length === 0) return null;
```

并把所有 `brief.xxx` 直读改为可选链，例如：

```tsx
{brief?.one_line_premise ? (
```

- [ ] **Step 6: 保存 payload 保留未知字段**

确认 `buildStoryBiblePayload` 保留 `...storyBible`。若 `creative_brief` 和 `writing_guidance` 重建会丢同 section 未知字段，则改成：

```ts
creative_brief: {
  ...(storyBible.creative_brief ?? {}),
  project_positioning: form.project_positioning.trim(),
  genre: form.genre.trim(),
  audience: form.audience.trim(),
  tone: form.tone.trim(),
  core_hook: form.core_hook.trim(),
  one_line_premise: form.one_line_premise.trim(),
  protagonist_core: form.protagonist_core.trim(),
  main_conflict: form.main_conflict.trim(),
  longline_mystery: form.longline_mystery.trim(),
  serial_length_target: form.serial_length_target.trim(),
  must_keep_rules: toLineList(form.must_keep_rules),
  reveal_strategy: form.reveal_strategy.trim(),
  pacing_strategy: form.pacing_strategy.trim(),
  world_setting: parseWorldSetting(form.world_setting),
  open_story_notes: form.open_story_notes.trim(),
},
writing_guidance: {
  ...(storyBible.writing_guidance ?? {}),
  opening_strategy: form.opening_strategy.trim(),
  chapter_density_strategy: form.chapter_density_strategy.trim(),
  midgame_engine: form.midgame_engine.trim(),
  late_game_direction: form.late_game_direction.trim(),
  forbidden_patterns: toLineList(form.forbidden_patterns),
  preferred_plot_patterns: toLineList(form.preferred_plot_patterns),
},
```

- [ ] **Step 7: 运行前端验证**

Run: `cd frontend && npm run build`

Expected: PASS

---

### Task 3: Agent 写章节后同步连续记忆

**Files:**
- Modify: `backend/services/story_state.py`
- Modify: `backend/services/agent_service.py:592-1212`
- Modify: `backend/main.py:3459-3497`
- Test: `backend/tests/test_agent_memory_refresh.py`

- [ ] **Step 1: 抽出记忆刷新服务函数**

在 `backend/services/story_state.py` 增加：

```python
async def refresh_chapter_memory_for_content(
    *,
    chapter,
    api_key: str | None,
    story_context: dict,
    summarize_chapter_memory,
    merge_story_memory,
) -> bool:
    content = str(getattr(chapter, "novel_content", "") or "").strip()
    if not content:
        return False
    payload = await summarize_chapter_memory(
        story_context,
        {
            "chapter_number": chapter.chapter_number,
            "title": chapter.title or f"第{chapter.chapter_number}话",
            "act": chapter.act or "",
            "key_events": chapter.key_events or [],
        },
        content,
        api_key=api_key,
    )
    chapter_summary = payload.get("chapter_summary") if isinstance(payload.get("chapter_summary"), dict) else {}
    chapter_handoff = payload.get("chapter_handoff") if isinstance(payload.get("chapter_handoff"), dict) else {}
    story_memory_update = payload.get("story_memory_update") if isinstance(payload.get("story_memory_update"), dict) else {}
    chapter.memory_summary = {
        "chapter_summary": chapter_summary,
        "chapter_handoff": chapter_handoff,
        "summary": chapter_summary.get("summary"),
        "ending_scene": chapter_summary.get("ending_scene"),
    } if (chapter_summary or chapter_handoff) else None
    chapter.story.story_memory = merge_story_memory(chapter.story.story_memory, story_memory_update, chapter, chapter_summary)
    return True
```

- [ ] **Step 2: 在 Agent 单章写入后刷新记忆**

在 `update_chapter_content`、`adjust_chapter_by_instruction`、`batch_adjust_chapters` 的成功写入分支中，在 `db.commit()` 前加入共享刷新调用。示例：

```python
        from services.story_state import refresh_chapter_memory_for_content
        from services.deepseek import summarize_chapter_memory
        from main import _merge_story_memory

        await refresh_chapter_memory_for_content(
            chapter=chapter,
            api_key=_current_api_key(),
            story_context=_build_story_context_dict(chapter.story),
            summarize_chapter_memory=summarize_chapter_memory,
            merge_story_memory=_merge_story_memory,
        )
```

如果没有 API Key，则跳过刷新并在返回结果增加 `memory_refreshed: False`。

- [ ] **Step 3: 避免循环导入**

如果从 `agent_service.py` 直接 import `main._merge_story_memory` 引起循环导入，将 `_merge_story_memory` 一并迁移到 `story_state.py`，并让 `main.py` 从 `story_state.py` import。

- [ ] **Step 4: 写测试覆盖 Agent 写入刷新**

```python
import pytest

from services.story_state import refresh_chapter_memory_for_content


class FakeStory:
    story_memory = {"continuity_facts": ["旧事实"]}


class FakeChapter:
    id = 1
    chapter_number = 3
    title = "雨夜重逢"
    act = "2"
    key_events = ["主角发现旧信"]
    novel_content = "主角在雨夜发现旧信，并决定追查当年的真相。"
    memory_summary = None
    story = FakeStory()


def merge_story_memory(existing, update, chapter, chapter_summary):
    memory = dict(existing or {})
    memory.update(update or {})
    memory["recent_chapter_summaries"] = [{
        "chapter_number": chapter.chapter_number,
        "summary": chapter_summary.get("summary"),
    }]
    return memory


@pytest.mark.asyncio
async def test_refresh_chapter_memory_for_content_updates_chapter_and_story_memory():
    async def fake_summarize(story_context, chapter_info, novel_content, api_key=None):
        assert chapter_info["chapter_number"] == 3
        assert "旧信" in novel_content
        return {
            "chapter_summary": {"summary": "主角发现旧信", "ending_scene": "雨夜街口"},
            "chapter_handoff": {"ending_location": "街口", "active_characters": ["主角"]},
            "story_memory_update": {"story_state": "真相线开启"},
        }

    chapter = FakeChapter()
    refreshed = await refresh_chapter_memory_for_content(
        chapter=chapter,
        api_key="test-key",
        story_context={"description": "测试故事"},
        summarize_chapter_memory=fake_summarize,
        merge_story_memory=merge_story_memory,
    )

    assert refreshed is True
    assert chapter.memory_summary["summary"] == "主角发现旧信"
    assert chapter.memory_summary["chapter_handoff"]["ending_location"] == "街口"
    assert chapter.story.story_memory["story_state"] == "真相线开启"
    assert chapter.story.story_memory["recent_chapter_summaries"][0]["chapter_number"] == 3
```

- [ ] **Step 5: 运行后端验证**

Run: `cd backend && python -m pytest tests/test_agent_memory_refresh.py -v`

Expected: PASS

---

### Task 4: Agent 模式与前端只读/执行一致

**Files:**
- Modify: `frontend/src/api.ts:2582-2603`
- Modify: `frontend/src/components/AgentPanel/AgentPanel.tsx`
- Modify: `frontend/src/components/AgentPanel/QuickActions.tsx`
- Test: `frontend` build

- [ ] **Step 1: 保留 `AgentMode` 类型并显式传参**

确认 `api.ts` 存在：

```ts
export type AgentMode = 'chat' | 'analyze' | 'execute';
```

如果不存在则新增到 Agent API 类型区域。

- [ ] **Step 2: 在 AgentPanel 增加模式 state**

```tsx
const [agentMode, setAgentMode] = useState<'chat' | 'analyze' | 'execute'>('analyze');
```

把 `agentChatStream(..., 'execute', ...)` 改为：

```tsx
abortRef.current = agentChatStream(storyId, conversationId, content, chapterId, agentMode, {
```

- [ ] **Step 3: 增加模式切换 UI**

在 Agent 标题栏加入三个按钮：

```tsx
{(['chat', 'analyze', 'execute'] as const).map((mode) => (
  <button
    key={mode}
    onClick={() => setAgentMode(mode)}
    className={`rounded-lg px-2 py-1 text-[11px] ${agentMode === mode ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-500'}`}
  >
    {mode === 'chat' ? '聊天' : mode === 'analyze' ? '分析' : '执行'}
  </button>
))}
```

- [ ] **Step 4: 快捷分析动作默认 analyze**

让 `QuickActions` 支持返回 `{ prompt, mode }` 或在 `AgentPanel` 中按 prompt 关键词选择模式。最小改动：QuickActions 仍只传 prompt，AgentPanel 发送前如果 prompt 包含“分析/检查/建议/评估”，临时使用 `analyze`。

- [ ] **Step 5: 运行前端验证**

Run: `cd frontend && npm run build`

Expected: PASS

---

### Task 5: 左侧框架助手支持替换型改动，而不是只能增量

**Files:**
- Modify: `backend/services/framework_utils.py`
- Modify: `backend/services/deepseek.py`
- Modify: `backend/main.py:9094-9190`
- Modify: `backend/services/agent_service.py:932-1033`
- Modify: `frontend/src/components/FrameworkPanel.tsx`
- Test: `backend/tests/test_framework_replace_operations.py`

- [ ] **Step 1: 定义替换型 operations**

在 `framework_utils.py` 的 operation 白名单加入：

```python
"replace_tags",
"replace_characters",
"replace_outline",
"replace_act_chapters",
"reorder_chapters",
```

- [ ] **Step 2: 写替换大纲测试**

```python
from services.framework_utils import apply_framework_operations, _extract_outline_chapters


def test_replace_outline_replaces_chapters_instead_of_appending():
    existing = {
        "description": "旧故事",
        "tags": {},
        "characters": [],
        "outline": {
            "three_acts": [
                {"act": "1", "title": "旧第一幕", "chapters": [{"chapter_number": 1, "title": "旧章"}]}
            ]
        },
    }
    result = apply_framework_operations(
        existing,
        operations=[{
            "op": "replace_outline",
            "changes": {
                "outline": {
                    "three_acts": [
                        {"act": "1", "title": "新第一幕", "chapters": [{"chapter_number": 1, "title": "新章"}]}
                    ]
                }
            },
        }],
        patches=[],
    )
    chapters = _extract_outline_chapters(result["framework"]["outline"])
    assert chapters == [{"chapter_number": 1, "title": "新章", "act": "1"}]
    assert result["applied_operations"] == ["replace_outline"]
```

- [ ] **Step 3: 实现替换 operation**

在 `apply_framework_operations` 中 add_chapter 分支之前加入：

```python
        if op == "replace_outline":
            next_outline = changes.get("outline") if isinstance(changes, dict) else None
            if isinstance(next_outline, dict):
                framework["outline"] = _normalize_framework_outline(next_outline, _extract_outline_chapters(next_outline))
                applied_operations.append("replace_outline")
            else:
                warnings.append("replace_outline 缺少 changes.outline")
            continue
```

按同样模式实现 `replace_tags`、`replace_characters`、`replace_act_chapters`。`replace_act_chapters` 必须只替换指定 act 的 `chapters`，保留其他 acts。

- [ ] **Step 4: 更新 DeepSeek 框架调整 prompt**

在 `adjust_framework_with_chat` 使用的 system prompt 中明确：

```text
当用户说“重写大纲 / 重新规划 / 替换第 N 幕 / 不要追加而是改成”时，必须使用 replace_outline 或 replace_act_chapters。
当用户说“增加 / 补充 / 续写 / 添加”时，才使用 add_chapter / insert_chapter_after。
返回 reply 时必须说明本次是增量修改还是替换修改。
```

- [ ] **Step 5: 前端 FrameworkPanel 暴露意图选项**

在 `FrameworkPanel.tsx` 增加 state：

```tsx
const [frameworkEditMode, setFrameworkEditMode] = useState<'incremental' | 'replace' | 'analyze'>('incremental');
```

发送给后端前在用户指令前加系统化前缀：

```tsx
const modePrefix = frameworkEditMode === 'replace'
  ? '【替换重构模式：允许替换相关范围，不要只追加】'
  : frameworkEditMode === 'analyze'
    ? '【仅分析模式：只提出建议，不要修改】'
    : '【增量调整模式：优先保留现有内容，只做必要增量修改】';
const nextMessages: FrameworkChatMessage[] = [...chatMessages, { role: 'user', content: `${modePrefix}\n${instruction}` }];
```

- [ ] **Step 6: 后端拒绝仅分析模式落库**

在 `/framework/adjust` 中，如果最后一条消息包含 `【仅分析模式`，调用 AI 生成建议但不 apply；返回 `warnings=["仅分析模式未写入数据库"]`，`applied_operations=[]`。

- [ ] **Step 7: 运行测试**

Run: `cd backend && python -m pytest tests/test_framework_replace_operations.py -v`

Expected: PASS

---

### Task 6: 修复首次框架生成 tags 不落库

**Files:**
- Modify: `backend/main.py:8617-8628`
- Test: `backend/tests/test_framework_generate_persistence.py`

- [ ] **Step 1: 写持久化测试**

```python
def test_apply_generated_framework_to_story_persists_generated_tags():
    from main import _apply_generated_framework_to_story

    class FakeStory:
        description = "旧描述"
        tags = {"type": "旧题材"}
        characters = []
        outline = {}

    story = FakeStory()
    framework = {
        "tags": {"type": "玄幻", "theme": "成长", "style": "热血", "audience": "男频"},
        "characters": [{"name": "林霁", "role": "主角"}],
        "outline": {
            "three_acts": [
                {"act": "1", "title": "觉醒篇", "chapters": [{"chapter_number": 1, "title": "旧城雨夜"}]}
            ]
        },
        "chapters": [{"chapter_number": 1, "title": "旧城雨夜", "act": "1"}],
    }

    _apply_generated_framework_to_story(
        story=story,
        framework=framework,
        raw_description="新描述",
        resolved_description="新描述",
    )

    assert story.description == "新描述"
    assert story.tags == framework["tags"]
    assert story.characters == [{"name": "林霁", "role": "主角"}]
    assert story.outline["three_acts"][0]["chapters"][0]["title"] == "旧城雨夜"
```

为让该测试可执行，需要先从 `generate_framework_endpoint` 抽出纯函数 `_apply_generated_framework_to_story(story, framework, raw_description, resolved_description)`，避免直接跑 HTTP 与真实 AI。

- [ ] **Step 2: 修复保存逻辑**

把 `backend/main.py:8622-8627` 改为：

```python
    story.tags = _merge_tags(story.tags, framework.get("tags"))
    story.characters = _normalize_characters_payload(framework.get("characters"))
    story.outline = _merge_framework_outline(story.outline, framework.get("outline"), framework.get("chapters"))
```

- [ ] **Step 3: 运行测试**

Run: `cd backend && python -m pytest tests/test_framework_generate_persistence.py -v`

Expected: PASS

---

### Task 7: 持久化 Agent 待确认修改，消除重启后不可见/不可回滚

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/database.py`
- Modify: `backend/services/agent_service.py`
- Modify: `backend/routers/agent_router.py`
- Test: `backend/tests/test_agent_pending_changes_persistence.py`

- [ ] **Step 1: 新增模型**

在 `backend/models.py` 增加：

```python
class AgentPendingChange(Base):
    __tablename__ = "agent_pending_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    story_id: Mapped[int] = mapped_column(Integer, ForeignKey("stories.id"), nullable=False, index=True)
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey("agent_conversations.id"), nullable=False, index=True)
    change_type: Mapped[str] = mapped_column(String(40), nullable=False)
    record_id: Mapped[int] = mapped_column(Integer, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    field: Mapped[str] = mapped_column(String(120), nullable=False)
    old_value: Mapped[dict[str, Any] | list[Any] | str | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict[str, Any] | list[Any] | str | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
```

- [ ] **Step 2: 增量迁移**

在 `backend/database.py` 的 `_migrate()` 中增加 `CREATE TABLE IF NOT EXISTS agent_pending_changes (...)`，字段与模型一致，确保幂等。

- [ ] **Step 3: Agent 写入完成时持久化 pending changes**

在 `AgentPendingChangeStore.set()` 保留内存逻辑，同时新增 DB 写入函数 `persist_pending_changes(key, tracker)`；写入前删除同 user/story/conversation 的旧记录。

- [ ] **Step 4: confirm/rollback/pending-changes 读取 DB 优先**

在 `backend/routers/agent_router.py`：

```python
@router.get("/pending-changes")
def get_pending_changes(...):
    # 先查 agent_pending_changes 表；没有再查内存 store
```

`confirm` 删除 DB 记录；`rollback` 从 DB 恢复旧值并删除记录。

- [ ] **Step 5: 运行测试**

Run: `cd backend && python -m pytest tests/test_agent_pending_changes_persistence.py -v`

Expected: PASS

---

### Task 8: 收敛 context/compact 构建，避免三处漂移

**Files:**
- Modify: `backend/services/story_state.py`
- Modify: `backend/main.py`
- Modify: `backend/services/agent_service.py`
- Modify: `backend/services/deepseek.py`
- Test: `backend/tests/test_story_state_contract.py`

- [ ] **Step 1: 把 `_build_story_memory_compact` 迁移到 `story_state.py`**

函数行为必须保留 `recent_chapter_summaries`：

```python
def build_story_memory_compact(story_memory: dict | None) -> dict[str, Any]:
    if not isinstance(story_memory, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in ("story_state", "current_arc_focus", "current_tone", "next_payoff_target"):
        value = str(story_memory.get(key) or "").strip()
        if value:
            compact[key] = value
    for key in ("continuity_facts", "open_loops", "resolved_loops"):
        raw = story_memory.get(key)
        if isinstance(raw, list):
            cleaned = [str(item).strip() for item in raw if str(item).strip()]
            if cleaned:
                compact[key] = cleaned[:12]
    recent = story_memory.get("recent_chapter_summaries")
    if isinstance(recent, list):
        compact["recent_chapter_summaries"] = [item for item in recent[-8:] if isinstance(item, dict)]
    return compact
```

- [ ] **Step 2: Agent 版 compact 复用共享函数**

删除或废弃 `agent_service.py:_build_memory_compact` 的独立实现，改为 import `build_story_memory_compact`。

- [ ] **Step 3: 写一致性测试**

```python
from services.story_state import build_story_memory_compact


def test_memory_compact_includes_recent_chapter_summaries():
    compact = build_story_memory_compact({
        "story_state": "主角进入第二幕",
        "recent_chapter_summaries": [{"chapter_number": 1, "summary": "开端"}],
    })
    assert compact["story_state"] == "主角进入第二幕"
    assert compact["recent_chapter_summaries"] == [{"chapter_number": 1, "summary": "开端"}]
```

- [ ] **Step 4: 运行测试**

Run: `cd backend && python -m pytest tests/test_story_state_contract.py -v`

Expected: PASS

---

## 验收标准

- [ ] 作品圣经卡在只有 `raw_input/import_guidance` 时也显示。
- [ ] 展开作品圣经后，所有顶层 section、嵌套对象、未知字段都能看到。
- [ ] 编辑作品圣经保存后，不会丢失同 section 未知字段，不会覆盖 `world_setting` 未修改子树。
- [ ] Agent `analyze` 模式不会暴露写工具；`execute` 模式的写入会出现在用户可见 pending changes 中。
- [ ] Agent 修改章节正文后，连续记忆卡能反映最新章节摘要和承接信息。
- [ ] 左侧框架助手能区分“增量添加”和“替换重构”，替换模式不会变成只追加。
- [ ] 初始框架生成后 tags、characters、outline 都真实落库且前端可见。
- [ ] 服务重启后，未确认 Agent 修改仍可查看、确认或回滚。

---

## 推荐验证命令

```bash
cd backend
python -m pytest tests/test_story_state_contract.py -v
python -m pytest tests/test_framework_replace_operations.py -v
python -m pytest tests/test_agent_memory_refresh.py -v
python -m pytest tests/test_agent_pending_changes_persistence.py -v
```

```bash
cd frontend
npm run build
```

---

## 执行顺序建议

1. 先做 Task 1 + Task 2：解决“存了但看不到/保存会覆盖”的核心体验问题。
2. 再做 Task 6：修复首次框架生成 tags 不落库，避免新作品继续产生脏状态。
3. 再做 Task 4 + Task 5：统一助手意图模式和框架替换能力。
4. 再做 Task 3 + Task 8：修复连续记忆同步与上下文构建漂移。
5. 最后做 Task 7：持久化待确认变更，增强生产稳定性。

---

## 风险与注意事项

- `backend/tests/` 可能被 `.gitignore` 忽略；本地测试仍要写，提交前按仓库策略决定是否纳入版本控制。
- 不要为了修复展示问题删除或重命名已有 JSON 字段；必须兼容旧数据。
- 不要把 `story_bible`、`story_memory` 的未知字段丢弃；AI 生成和导入链路可能依赖这些扩展字段。
- 替换型 framework operation 必须有快照；任何 destructive operation 都要能从历史版本恢复。
- Agent 写章节后刷新记忆会额外消耗文本调用，必须在返回结果或日志里标记 `memory_refreshed`，避免隐藏成本。
