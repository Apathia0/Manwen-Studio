# Agent update_story_bible 工具补齐 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 AI Agent 助手补齐 `update_story_bible` 写入工具，使其能修改作品圣经（含世界观设定），并在 system prompt 中引导 Agent 正确使用。

**Architecture:** 在 `agent_service.py` 的 ToolRegistry 注册新写工具 `update_story_bible`，复用 `main.py:8347` PATCH 端点的 merge 逻辑（partial dict 更新）。扩展 `PendingChangesTracker` 支持 `story_bible` 类型的记录与回滚。在 Agent system prompt 的工具清单和场景对照表加入对应条目。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2.0 / DeepSeek function calling

---

## 文件结构

- Modify: `backend/services/agent_service.py` — 注册 `update_story_bible` 工具 + 扩展 PendingChangesTracker + system prompt 更新
- Test: `backend/tests/test_agent_story_bible_tool.py` — 新增测试（注意：backend/tests/ 在 .gitignore 中，测试不提交但本地验证用）

---

### Task 1: 扩展 PendingChangesTracker 支持 story_bible 类型

**Files:**
- Modify: `backend/services/agent_service.py:41` (PendingChange.type 注释)
- Modify: `backend/services/agent_service.py:83-93` (record_story_field 已有，复用)
- Modify: `backend/services/agent_service.py:124-152` (rollback 增加 story_bible 分支)
- Test: `backend/tests/test_agent_story_bible_tool.py`

- [ ] **Step 1: 写 PendingChangesTracker rollback 的 story_bible 分支测试**

```python
"""Agent update_story_bible 工具与 PendingChangesTracker story_bible 类型测试。"""

from services.agent_service import PendingChangesTracker, PendingChange


def test_rollback_story_bible_type_restores_old_value():
    tracker = PendingChangesTracker()
    change = PendingChange(
        type="story_bible",
        record_id=42,
        display_name="测试故事",
        field="story_bible",
        old_value={"creative_brief": {"project_positioning": "旧定位"}},
        new_value={"creative_brief": {"project_positioning": "新定位"}},
    )
    tracker.record(change)

    class FakeStory:
        id = 42
        story_bible = {"creative_brief": {"project_positioning": "新定位"}}

    class FakeDB:
        def get(self, cls, rid):
            if rid == 42:
                return FakeStory()
            return None

        def commit(self):
            pass

    results = tracker.rollback(FakeDB())
    assert len(results) == 1
    assert results[0]["ok"] is True
    assert results[0]["type"] == "story_bible"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_agent_story_bible_tool.py::test_rollback_story_bible_type_restores_old_value -v`
Expected: FAIL — rollback 中没有 `story_bible` 分支，`type="story_bible"` 不会被处理，results 为空

- [ ] **Step 3: 在 rollback 方法增加 story_bible 分支**

在 `agent_service.py` 的 `rollback` 方法中，`elif change.type == "scenes_file":` 之前插入：

```python
                elif change.type == "story_bible":
                    obj = db.get(Story, change.record_id)
                    if obj:
                        setattr(obj, change.field, change.old_value)
                        results.append({"ok": True, "type": "story_bible", "id": change.record_id, "field": change.field})
```

同时更新 `PendingChange` 的 type 注释（line 41）：

```python
    type: str  # "chapter" | "story" | "scenes_file" | "story_bible"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_agent_story_bible_tool.py::test_rollback_story_bible_type_restores_old_value -v`
Expected: PASS

---

### Task 2: 注册 update_story_bible 工具

**Files:**
- Modify: `backend/services/agent_service.py` (在 `update_story_info` 工具之后，约 line 816 处插入新工具)
- Test: `backend/tests/test_agent_story_bible_tool.py`

- [ ] **Step 1: 写工具注册和执行测试**

在 `backend/tests/test_agent_story_bible_tool.py` 追加：

```python
import json
from unittest.mock import patch, MagicMock
from services.agent_service import tool_registry


def test_update_story_bible_is_registered_as_write_tool():
    specs = tool_registry.get_tool_specs(mode="execute")
    names = [s["function"]["name"] for s in specs]
    assert "update_story_bible" in names, "update_story_bible 未注册"
    assert tool_registry.is_write_tool("update_story_bible"), "update_story_bible 应为写工具"


def test_update_story_bible_merges_partial_dict():
    with patch("services.agent_service.SessionLocal") as mock_session_cls:
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        class FakeStory:
            id = 1
            title = "测试故事"
            story_bible = {
                "creative_brief": {"project_positioning": "旧定位", "core_hook": "旧卖点"},
                "writing_guidance": {"opening_strategy": "旧策略"},
            }
            description = "旧描述"

        mock_db.get.return_value = FakeStory()

        import asyncio
        from services.agent_service import update_story_bible
        result = asyncio.get_event_loop().run_until_complete(
            update_story_bible(story_id=1, story_bible={
                "creative_brief": {"project_positioning": "新定位"},
            })
        )
        assert result["ok"] is True
        assert "creative_brief" in result["updated_sections"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_agent_story_bible_tool.py::test_update_story_bible_is_registered_as_write_tool tests/test_agent_story_bible_tool.py::test_update_story_bible_merges_partial_dict -v`
Expected: FAIL — `update_story_bible` 工具未注册

- [ ] **Step 3: 注册 update_story_bible 工具**

在 `agent_service.py` 的 `update_story_info` 函数结束后（`update_characters` 工具注册之前，约 line 816），插入：

```python
@tool_registry.register(
    name="update_story_bible",
    description="更新作品圣经（Story Bible），包含世界观设定、创意简报、写作指导。支持部分更新——只更新提供的字段，未提供的字段保留原值。用户要求调整世界观、修改核心设定、改创意简报时用此工具。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
            "story_bible": {
                "type": "object",
                "description": "要更新的作品圣经字段（partial merge）。顶层 key 可包括 creative_brief、writing_guidance、import_guidance。只需提供要修改的部分，未提供的会保留原值。",
                "additionalProperties": True,
            },
        },
        "required": ["story_id", "story_bible"],
    },
)
async def update_story_bible(story_id: int, story_bible: dict) -> dict:
    """部分更新作品圣经，merge 到现有 story_bible 上。"""
    db = SessionLocal()
    try:
        story = _validate_story_ownership(db, story_id, _current_story_id())
        if not story:
            return {"error": "故事不存在或无权访问"}
        if not isinstance(story_bible, dict) or not story_bible:
            return {"error": "story_bible 必须是非空对象"}

        if _current_pending_changes():
            _current_pending_changes().record(PendingChange(
                type="story_bible",
                record_id=story.id,
                display_name=story.title,
                field="story_bible",
                old_value=dict(story.story_bible) if isinstance(story.story_bible, dict) else {},
                new_value=None,
            ))

        current = dict(story.story_bible) if isinstance(story.story_bible, dict) else {}
        for top_key, top_value in story_bible.items():
            if isinstance(top_value, dict) and isinstance(current.get(top_key), dict):
                merged_section = dict(current[top_key])
                merged_section.update(top_value)
                current[top_key] = merged_section
            else:
                current[top_key] = top_value
        story.story_bible = current

        creative_brief = current.get("creative_brief") if isinstance(current.get("creative_brief"), dict) else {}
        next_description = str(creative_brief.get("one_line_premise") or "").strip()
        if not next_description:
            next_description = str(creative_brief.get("project_positioning") or "").strip()
        if next_description:
            story.description = next_description

        if _current_pending_changes():
            _current_pending_changes().update_new_value("story_bible", story.id, "story_bible", dict(story.story_bible))

        db.commit()
        updated_sections = list(story_bible.keys())
        return {"ok": True, "updated_sections": updated_sections}
    finally:
        db.close()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_agent_story_bible_tool.py -v`
Expected: 3 passed

---

### Task 3: 更新 Agent system prompt 引导

**Files:**
- Modify: `backend/services/agent_service.py:1531-1541` (写入工具清单)
- Modify: `backend/services/agent_service.py:1547-1559` (场景对照表)

- [ ] **Step 1: 在写入工具清单加入 update_story_bible**

在 system prompt 的 `### 写入工具（用于执行修改）` 部分（约 line 1531），`update_story_info` 行之后加入：

```
- `update_story_bible` — 更新作品圣经（世界观设定/创意简报/写作指导），支持部分更新。用户要求调整世界观、修改核心设定时用此工具
```

- [ ] **Step 2: 在场景对照表加入世界观调整条目**

在 `## 📋 第三步：场景 → 行动对照表`（约 line 1547），在"帮我修改角色设定"行之后加入：

```
| "帮我调整世界观/修改核心设定/改作品圣经" | 调 `get_story_bible` 查看当前圣经 → 给出调整方案 → 待确认后调 `update_story_bible` |
```

- [ ] **Step 3: 验证模块导入正常**

Run: `cd backend && python -c "import services.agent_service; print('ok')"`
Expected: 输出 `ok`

- [ ] **Step 4: 运行全部测试确认无回归**

Run: `cd backend && python -m pytest tests/test_agent_story_bible_tool.py tests/test_alipay_f2f.py -v`
Expected: 全部 PASS

---

### Task 4: 提交并打 tag

- [ ] **Step 1: 提交**

```bash
git add backend/services/agent_service.py
git commit -m "feat(agent): 补齐 update_story_bible 工具支持世界观设定调整" -m "Agent 原只有 get_story_bible 只读工具，无法修改作品圣经（世界观/创意简报/写作指导）。新增 update_story_bible 写工具（partial merge），PendingChangesTracker 增加 story_bible 回滚类型，system prompt 工具清单和场景对照表加入对应引导。"
```

- [ ] **Step 2: rebase + push + tag**

```bash
git pull --rebase origin pro
git push origin pro
git tag -a v3.0.34 -m "v3.0.34 - Agent 补齐 story_bible 写入工具"
git push origin v3.0.34
```
