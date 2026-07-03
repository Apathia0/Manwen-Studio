# 框架调整 Operation 化改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将小说框架调整链路从“AI 直接返回完整 framework JSON”改造成“AI 返回 operations/patches，后端确定性 apply 并校验后落库”，解决回复正确但 JSON 未正确修改的问题。

**Architecture:** 保留现有 `/framework/adjust` 与 Agent 工具入口，但把 `adjust_framework_with_chat` 改成结构化编辑规划器，只返回 `reply + operations + patches + warnings`。在 `framework_utils.py` 中新增 operation schema 校验、deterministic apply、结果一致性校验，`main.py` 与 `agent_service.py` 统一复用该执行层，前端展示真实的 `applied_operations` 与 `warnings`。

**Tech Stack:** Python, FastAPI, SQLAlchemy, DeepSeek API, React, TypeScript

---

## 文件结构与职责

- Modify: `backend/services/deepseek.py`
  - 将框架调整 prompt 从“输出完整 framework JSON”改为“输出 operations/patches/warnings”
  - 新增结构化结果解析与基础重试逻辑
- Modify: `backend/services/framework_utils.py`
  - 新增 operation schema 白名单、patch 白名单、operation apply、patch apply、consistency validate
  - 保留现有 normalize / chapter extract / merge 工具给执行层复用
- Modify: `backend/main.py`
  - `/api/stories/{story_id}/framework/adjust` 改为使用统一 apply 流程
  - 返回 `applied_operations`、`warnings`、`validation_errors`
- Modify: `backend/services/agent_service.py`
  - `adjust_framework` 工具改为复用相同 apply 流程，消除双实现分叉
- Modify: `frontend/src/api.ts`
  - 扩展 `FrameworkAdjustResponse` 类型，增加 `applied_operations`、`warnings`、`validation_errors`
- Modify: `frontend/src/components/FrameworkPanel.tsx`
  - 在 AI 回复下方展示真实已应用改动和未执行项
- Create: `backend/tests/test_framework_operation_apply.py`
  - 覆盖 operation apply / patch apply / consistency validate 的单元测试
- Create: `backend/tests/test_framework_adjust_flow.py`
  - 覆盖 `/framework/adjust` 与 `agent_service.adjust_framework` 的集成级流程测试（mock AI 返回 operations）

---

### Task 1: 定义 operation/patch 契约与失败用例

**Files:**
- Modify: `backend/services/framework_utils.py`
- Test: `backend/tests/test_framework_operation_apply.py`

- [ ] **Step 1: 写 operation schema 校验失败测试**

```python
from services.framework_utils import validate_framework_operations


def test_validate_framework_operations_rejects_unknown_op():
    errors = validate_framework_operations(
        operations=[{"op": "replace_outline", "target": {}, "changes": {}}],
        patches=[],
    )

    assert errors == ["operations[0].op 不支持: replace_outline"]


def test_validate_framework_operations_rejects_outline_root_patch():
    errors = validate_framework_operations(
        operations=[],
        patches=[{"path": "outline", "value": {"three_acts": []}}],
    )

    assert errors == ["patches[0].path 不支持: outline"]
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest backend/tests/test_framework_operation_apply.py::test_validate_framework_operations_rejects_unknown_op -v`
Expected: FAIL with `ImportError` or `cannot import name 'validate_framework_operations'`

- [ ] **Step 3: 在 `framework_utils.py` 增加 operation/patch 白名单与校验入口**

```python
SUPPORTED_FRAMEWORK_OPERATIONS = {
    "update_story_description",
    "update_tags",
    "add_character",
    "update_character",
    "remove_character",
    "update_act_summary",
    "add_chapter",
    "insert_chapter_after",
    "update_chapter",
    "delete_chapter",
}

SUPPORTED_FRAMEWORK_PATCH_PATHS = {
    "description",
    "tags.type",
    "tags.theme",
    "tags.style",
    "tags.audience",
    "outline.serial_strategy",
    "outline.themes",
    "outline.foreshadowing",
}


def validate_framework_operations(operations: list | None, patches: list | None) -> list[str]:
    errors: list[str] = []
    for index, item in enumerate(operations or []):
        op = str((item or {}).get("op") or "").strip()
        if op not in SUPPORTED_FRAMEWORK_OPERATIONS:
            errors.append(f"operations[{index}].op 不支持: {op or '<empty>'}")
    for index, item in enumerate(patches or []):
        path = str((item or {}).get("path") or "").strip()
        if path not in SUPPORTED_FRAMEWORK_PATCH_PATHS:
            errors.append(f"patches[{index}].path 不支持: {path or '<empty>'}")
    return errors
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `pytest backend/tests/test_framework_operation_apply.py -k validate_framework_operations -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/framework_utils.py backend/tests/test_framework_operation_apply.py
git commit -m "test: define framework operation validation contract"
```

---

### Task 2: 用 TDD 实现 operation apply 执行器

**Files:**
- Modify: `backend/services/framework_utils.py`
- Test: `backend/tests/test_framework_operation_apply.py`

- [ ] **Step 1: 写 operation apply 成功用例**

```python
from services.framework_utils import apply_framework_operations


def test_apply_framework_operations_updates_character_and_chapter():
    framework = {
        "description": "旧描述",
        "tags": {"type": "玄幻", "theme": "成长", "style": "热血", "audience": "男频"},
        "characters": [{"name": "林霁", "role": "主角", "arc": {}, "relationships": []}],
        "outline": {
            "three_acts": [
                {
                    "act": "1",
                    "title": "第一幕",
                    "summary": "起始",
                    "chapters": [
                        {"chapter_number": 1, "title": "开端", "summary": "旧概要"}
                    ],
                }
            ]
        },
    }
    result = apply_framework_operations(
        existing_framework=framework,
        operations=[
            {
                "op": "update_character",
                "target": {"name": "林霁"},
                "changes": {"role": "调查者", "motivation": "找出导师隐瞒的真相"},
            },
            {
                "op": "update_chapter",
                "target": {"chapter_number": 1},
                "changes": {"summary": "女主发现第一条异常线索"},
            },
        ],
        patches=[],
    )

    assert result["framework"]["characters"][0]["role"] == "调查者"
    assert result["framework"]["characters"][0]["motivation"] == "找出导师隐瞒的真相"
    assert result["framework"]["outline"]["three_acts"][0]["chapters"][0]["summary"] == "女主发现第一条异常线索"
    assert result["applied_operations"] == [
        "update_character:林霁",
        "update_chapter:1",
    ]
    assert result["errors"] == []
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest backend/tests/test_framework_operation_apply.py::test_apply_framework_operations_updates_character_and_chapter -v`
Expected: FAIL with `cannot import name 'apply_framework_operations'`

- [ ] **Step 3: 实现最小可用执行器**

```python
def apply_framework_operations(existing_framework: dict, operations: list | None, patches: list | None) -> dict:
    framework = {
        "description": str(existing_framework.get("description") or "").strip(),
        "tags": dict(existing_framework.get("tags") or {}),
        "characters": [dict(item) for item in (existing_framework.get("characters") or []) if isinstance(item, dict)],
        "outline": dict(existing_framework.get("outline") or {}),
    }
    applied_operations: list[str] = []
    warnings: list[str] = []
    errors = validate_framework_operations(operations, patches)
    if errors:
        return {
            "framework": framework,
            "applied_operations": applied_operations,
            "warnings": warnings,
            "errors": errors,
        }

    for item in operations or []:
        op = item.get("op")
        if op == "update_character":
            target_name = str(((item.get("target") or {}).get("name") or "")).strip()
            for character in framework["characters"]:
                if str(character.get("name") or "").strip() == target_name:
                    character.update({k: v for k, v in (item.get("changes") or {}).items() if v not in (None, "")})
                    applied_operations.append(f"update_character:{target_name}")
                    break
            else:
                warnings.append(f"未找到角色: {target_name}")
        if op == "update_chapter":
            target_number = _coerce_chapter_number((item.get("target") or {}).get("chapter_number"))
            chapters = _extract_outline_chapters(framework["outline"])
            for chapter in chapters:
                if chapter.get("chapter_number") == target_number:
                    chapter.update({k: v for k, v in (item.get("changes") or {}).items() if v not in (None, "")})
                    framework["outline"] = _normalize_framework_outline(framework["outline"], chapters)
                    applied_operations.append(f"update_chapter:{target_number}")
                    break
            else:
                warnings.append(f"未找到章节: {target_number}")

    return {
        "framework": framework,
        "applied_operations": applied_operations,
        "warnings": warnings,
        "errors": [],
    }
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `pytest backend/tests/test_framework_operation_apply.py::test_apply_framework_operations_updates_character_and_chapter -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/framework_utils.py backend/tests/test_framework_operation_apply.py
git commit -m "feat: add framework operation executor"
```

---

### Task 3: 补齐 patch apply、章节增删、结构校验

**Files:**
- Modify: `backend/services/framework_utils.py`
- Test: `backend/tests/test_framework_operation_apply.py`

- [ ] **Step 1: 写 patch 与 delete_chapter 的失败/成功测试**

```python
from services.framework_utils import apply_framework_operations


def test_apply_framework_operations_applies_supported_patch_and_delete_chapter():
    framework = {
        "description": "旧描述",
        "tags": {"type": "玄幻", "theme": "成长", "style": "热血", "audience": "男频"},
        "characters": [{"name": "林霁", "role": "主角"}],
        "outline": {
            "three_acts": [
                {
                    "act": "1",
                    "title": "第一幕",
                    "summary": "起始",
                    "chapters": [
                        {"chapter_number": 1, "title": "开端", "summary": "旧概要"},
                        {"chapter_number": 2, "title": "追踪", "summary": "旧概要2"},
                    ],
                }
            ],
            "themes": ["旧主题"],
        },
    }
    result = apply_framework_operations(
        existing_framework=framework,
        operations=[{"op": "delete_chapter", "target": {"chapter_number": 2}, "changes": {}}],
        patches=[{"path": "outline.themes", "value": ["真相", "背叛"]}],
    )

    chapters = result["framework"]["outline"]["three_acts"][0]["chapters"]
    assert [item["chapter_number"] for item in chapters] == [1]
    assert result["framework"]["outline"]["themes"] == ["真相", "背叛"]
    assert result["applied_operations"] == ["delete_chapter:2", "patch:outline.themes"]
    assert result["errors"] == []
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest backend/tests/test_framework_operation_apply.py -k "delete_chapter or outline.themes" -v`
Expected: FAIL because `delete_chapter` / patch paths not implemented

- [ ] **Step 3: 实现 patch apply、章节增删和结果一致性校验**

```python
def _apply_framework_patch(framework: dict, path: str, value):
    if path == "description":
        framework["description"] = str(value or "").strip()
        return
    if path.startswith("tags."):
        framework.setdefault("tags", {})[path.split(".", 1)[1]] = value
        return
    if path == "outline.themes":
        framework.setdefault("outline", {})["themes"] = value if isinstance(value, list) else []
        return
    if path == "outline.foreshadowing":
        framework.setdefault("outline", {})["foreshadowing"] = value if isinstance(value, list) else []
        return
    if path == "outline.serial_strategy":
        framework.setdefault("outline", {})["serial_strategy"] = value if isinstance(value, dict) else {}
        return


def validate_applied_framework_consistency(framework: dict) -> list[str]:
    errors = validate_framework_json(framework)
    chapter_numbers = [item.get("chapter_number") for item in _extract_outline_chapters(framework.get("outline"))]
    if len(chapter_numbers) != len(set(chapter_numbers)):
        errors.append("chapter_number 存在重复")
    return errors
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `pytest backend/tests/test_framework_operation_apply.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/framework_utils.py backend/tests/test_framework_operation_apply.py
git commit -m "feat: support framework patches and chapter mutations"
```

---

### Task 4: 改造 DeepSeek 返回结构化编辑计划

**Files:**
- Modify: `backend/services/deepseek.py`
- Test: `backend/tests/test_framework_adjust_flow.py`

- [ ] **Step 1: 写解析结构化返回的测试**

```python
from services.deepseek import _extract_framework_adjustment_plan


def test_extract_framework_adjustment_plan_returns_operations_and_warnings():
    raw = {
        "reply": "已强化主角调查动机，并删除第 8 章。",
        "operations": [
            {"op": "update_character", "target": {"name": "林霁"}, "changes": {"motivation": "追查导师"}},
            {"op": "delete_chapter", "target": {"chapter_number": 8}, "changes": {}},
        ],
        "patches": [{"path": "outline.themes", "value": ["真相", "代价"]}],
        "warnings": ["未处理配角支线"]
    }

    result = _extract_framework_adjustment_plan(raw)

    assert result["reply"] == "已强化主角调查动机，并删除第 8 章。"
    assert len(result["operations"]) == 2
    assert result["patches"] == [{"path": "outline.themes", "value": ["真相", "代价"]}]
    assert result["warnings"] == ["未处理配角支线"]
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest backend/tests/test_framework_adjust_flow.py::test_extract_framework_adjustment_plan_returns_operations_and_warnings -v`
Expected: FAIL with `cannot import name '_extract_framework_adjustment_plan'`

- [ ] **Step 3: 实现最小解析函数并重写 prompt 目标**

```python
def _extract_framework_adjustment_plan(result: dict) -> dict:
    reply = str(result.get("reply") or "").strip() or "已根据你的建议调整框架。"
    operations = result.get("operations") if isinstance(result.get("operations"), list) else []
    patches = result.get("patches") if isinstance(result.get("patches"), list) else []
    warnings = result.get("warnings") if isinstance(result.get("warnings"), list) else []
    return {
        "reply": reply,
        "operations": operations,
        "patches": patches,
        "warnings": [str(item).strip() for item in warnings if str(item).strip()],
    }
```

```python
system_prompt = """你是故事框架编辑规划器。你的任务不是输出完整 framework JSON，而是输出结构化编辑计划。

输出 JSON 格式：
{
  "reply": "只描述实际可执行改动",
  "operations": [{"op": "update_character", "target": {"name": "林霁"}, "changes": {}}],
  "patches": [{"path": "outline.themes", "value": []}],
  "warnings": ["无法定位目标时写在这里"]
}

要求：
1. operations 优先，只有 description/tags.* / outline.serial_strategy / outline.themes / outline.foreshadowing 允许走 patches。
2. 禁止返回完整 framework。
3. 用户未要求修改的内容不要生成无关操作。
4. 找不到目标或指令有歧义时，把问题写进 warnings。"""
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `pytest backend/tests/test_framework_adjust_flow.py::test_extract_framework_adjustment_plan_returns_operations_and_warnings -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/deepseek.py backend/tests/test_framework_adjust_flow.py
git commit -m "feat: return framework adjustment plans from ai"
```

---

### Task 5: 让 `/framework/adjust` 只信任 apply 后结果

**Files:**
- Modify: `backend/main.py:6553-6641`
- Modify: `backend/services/framework_utils.py`
- Test: `backend/tests/test_framework_adjust_flow.py`

- [ ] **Step 1: 写接口流程测试，验证 reply 正确但真正落库依赖 apply 结果**

```python
from fastapi.testclient import TestClient


def test_adjust_framework_endpoint_applies_operations_before_persist(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        "main.adjust_framework_with_chat",
        lambda *args, **kwargs: {
            "reply": "已更新主题并删除第 2 章。",
            "operations": [{"op": "delete_chapter", "target": {"chapter_number": 2}, "changes": {}}],
            "patches": [{"path": "outline.themes", "value": ["真相"]}],
            "warnings": [],
        },
    )

    response = client.post(
        "/api/stories/1/framework/adjust",
        json={"messages": [{"role": "user", "content": "删除第2章并改主题"}]},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["reply"] == "已更新主题并删除第 2 章。"
    assert payload["applied_operations"] == ["delete_chapter:2", "patch:outline.themes"]
    assert payload["warnings"] == []
    assert payload["story"]["outline"]["themes"] == ["真相"]
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest backend/tests/test_framework_adjust_flow.py::test_adjust_framework_endpoint_applies_operations_before_persist -v`
Expected: FAIL because endpoint still expects `framework`

- [ ] **Step 3: 改造 `main.py` 调用统一 apply 流程**

```python
plan = await adjust_framework_with_chat(
    context_story,
    messages,
    api_key=deepseek_api_key,
    required_min_chapters=requested_min_chapters,
    existing_framework=existing_framework,
)
apply_result = apply_framework_operations(
    existing_framework=existing_framework,
    operations=plan.get("operations"),
    patches=plan.get("patches"),
)
framework = apply_result["framework"]
validation_errors = validate_applied_framework_consistency(framework)
if validation_errors:
    raise HTTPException(502, "；".join(validation_errors))
```

```python
return {
    "reply": plan.get("reply", ""),
    "story": {
        "description": story.description,
        "tags": story.tags,
        "characters": story.characters,
        "outline": story.outline,
    },
    "chapters": _extract_outline_chapters(story.outline),
    "applied_operations": apply_result["applied_operations"],
    "warnings": [*plan.get("warnings", []), *apply_result["warnings"]],
    "validation_errors": validation_errors,
}
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `pytest backend/tests/test_framework_adjust_flow.py::test_adjust_framework_endpoint_applies_operations_before_persist -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/services/framework_utils.py backend/tests/test_framework_adjust_flow.py
git commit -m "feat: apply framework adjustment plans in api endpoint"
```

---

### Task 6: 让 Agent 工具链复用同一执行层

**Files:**
- Modify: `backend/services/agent_service.py:761-839`
- Test: `backend/tests/test_framework_adjust_flow.py`

- [ ] **Step 1: 写 Agent 工具流程测试**

```python
import asyncio
from services.agent_service import adjust_framework


def test_agent_adjust_framework_uses_apply_result(monkeypatch):
    async def fake_adjust_framework_with_chat(**kwargs):
        return {
            "reply": "已删除第 3 章。",
            "operations": [{"op": "delete_chapter", "target": {"chapter_number": 3}, "changes": {}}],
            "patches": [],
            "warnings": [],
        }

    monkeypatch.setattr("services.agent_service.adjust_framework_with_chat", fake_adjust_framework_with_chat)

    result = asyncio.run(adjust_framework(1, "删除第3章"))

    assert result["ok"] is True
    assert result["reply"] == "已删除第 3 章。"
    assert result["applied_fields"] == ["description", "tags", "characters", "outline"]
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest backend/tests/test_framework_adjust_flow.py::test_agent_adjust_framework_uses_apply_result -v`
Expected: FAIL because tool still expects `framework`

- [ ] **Step 3: 改造 `agent_service.py` 复用 apply 流程**

```python
result = await adjust_framework_with_chat(
    story_context=story_context,
    messages=messages,
    api_key=api_key,
    existing_framework=existing_framework,
)
apply_result = apply_framework_operations(
    existing_framework=existing_framework,
    operations=result.get("operations"),
    patches=result.get("patches"),
)
framework = apply_result["framework"]
story.description = str(framework.get("description") or existing_framework["description"] or "").strip()
story.tags = framework.get("tags") if isinstance(framework.get("tags"), dict) else existing_framework["tags"]
story.characters = _normalize_characters_payload(framework.get("characters"))
story.outline = framework.get("outline") if isinstance(framework.get("outline"), dict) else existing_framework["outline"]
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `pytest backend/tests/test_framework_adjust_flow.py::test_agent_adjust_framework_uses_apply_result -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent_service.py backend/tests/test_framework_adjust_flow.py
git commit -m "feat: share framework apply flow with agent tools"
```

---

### Task 7: 前端展示真实已应用改动与未执行项

**Files:**
- Modify: `frontend/src/api.ts:245-257`
- Modify: `frontend/src/components/FrameworkPanel.tsx:81-145`

- [ ] **Step 1: 先扩展响应类型**

```ts
export interface FrameworkAdjustResponse {
  reply: string;
  story: Story;
  chapters?: FrameworkChapterPlan[];
  applied_fields?: string[];
  applied_operations?: string[];
  warnings?: string[];
  validation_errors?: string[];
}
```

- [ ] **Step 2: 在面板中追加真实执行结果展示**

```tsx
const operationHint = result.applied_operations?.length
  ? `\n\n实际已应用改动：\n- ${result.applied_operations.join('\n- ')}`
  : '';
const warningHint = result.warnings?.length
  ? `\n\n未执行或需注意：\n- ${result.warnings.join('\n- ')}`
  : '';
const validationHint = result.validation_errors?.length
  ? `\n\n校验提示：\n- ${result.validation_errors.join('\n- ')}`
  : '';
setChatMessages((prev) => [
  ...prev,
  { role: 'assistant', content: `${result.reply}${operationHint}${warningHint}${validationHint}` },
]);
```

- [ ] **Step 3: 运行前端类型检查**

Run: `npm --prefix frontend run build`
Expected: PASS with no TypeScript error related to `FrameworkAdjustResponse`

- [ ] **Step 4: 手动验证交互文案**

Run: `npm --prefix frontend run dev`
Expected: 在框架 中发送“删除第2章并改主题”后，回复中能看到“实际已应用改动”列表，而不是只显示 AI 口头说明

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.ts frontend/src/components/FrameworkPanel.tsx
git commit -m "feat: show applied framework operations in ui"
```

---

### Task 8: 回归验证与交付检查

**Files:**
- Modify: `backend/tests/test_framework_operation_apply.py`
- Modify: `backend/tests/test_framework_adjust_flow.py`

- [ ] **Step 1: 运行后端目标测试集**

Run: `pytest backend/tests/test_framework_operation_apply.py backend/tests/test_framework_adjust_flow.py -v`
Expected: PASS

- [ ] **Step 2: 运行已有框架相关脚本验证未破坏基础能力**

Run: `python backend/scripts/verify_transaction_safety.py`
Expected: 输出总结 JSON，`framework_generate` 与相关流程无新增失败

- [ ] **Step 3: 运行前端构建**

Run: `npm --prefix frontend run build`
Expected: PASS

- [ ] **Step 4: 记录人工验收场景**

```text
场景 1："删除第 8 章，并把主题改成真相与背叛"
预期：第 8 章从 outline.three_acts 中消失；outline.themes 更新；回复包含 delete_chapter:8 与 patch:outline.themes。

场景 2："把林霁改成调查者型主角，并加强她与导师的冲突"
预期：characters 中林霁字段被更新；若导师角色不存在，warnings 提示未找到目标。

场景 3："把第二幕压缩到 6 章"
预期：若第一期未实现 rebalance_act，则 reply 保守，warnings 明确说明当前未支持自动重排整幕。
```

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_framework_operation_apply.py backend/tests/test_framework_adjust_flow.py
git commit -m "test: verify framework operation adjustment flow"
```

---

## 自检结果

- **Spec coverage:** 已覆盖 operation schema、AI 输出结构、统一 apply 流程、API/Agent 共用执行层、前端真实执行反馈、测试与回归验证。
- **Placeholder scan:** 已移除 TBD/TODO/“自行处理”等占位描述，每个任务均包含明确文件、代码片段、命令与预期结果。
- **Type consistency:** 统一使用 `operations`、`patches`、`warnings`、`applied_operations`、`validation_errors` 命名；执行入口统一为 `apply_framework_operations` 与 `validate_applied_framework_consistency`。
