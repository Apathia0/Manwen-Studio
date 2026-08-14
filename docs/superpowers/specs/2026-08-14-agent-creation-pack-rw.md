# Agent 助手读写章节创作包 + 正文生成以创作包为基础

- 日期：2026-08-14
- 状态：已批准，待实施
- 涉及：`backend/services/agent_service.py`、`backend/services/chapter_agents.py`、`backend/tests/test_agent_creation_pack_tools.py`（新建）

## 背景与目标

设定中心的章节创作包是正文生成的唯一事实来源。目前 Agent 助手：

1. **无法读取**创作包（`get_chapter_full` 只返回 10 个字段，不含 `creation_pack_*`），只能通过 `adjust_chapter_by_instruction` 间接消费。
2. **无法写入**创作包，用户无法通过对话让 Agent 调整创作包设定。
3. 用户指令在 `adjust_chapter_by_instruction` 中只作为外部「编辑打回意见」块（`direct_feedback`）传入写手 agent，**未注入创作包内部的 `hard_requirements` 首项**——与「创作包为基础、用户要求为增量」的目标不符。

目标：Agent 助手可读写设定中心创作包；用户要求大篇幅重写正文时，以创作包内容为基础、用户指令为增量进入写手 agent 的硬合同；用户要求精准局部修改时直接替换，不触碰创作包。

## 术语

| 术语 | 含义 |
|------|------|
| 创作包 | 章节创作包（`creation_pack_content` 文本 + `version` + `is_manual` + `source_hash`） |
| 大篇幅重写 | 用户要求调整风格、补充内容、整体重写 → `adjust_chapter_by_instruction` |
| 精准局部修改 | 用户给出明确段落要求替换 → `rewrite_text_segment` |

## 现状梳理

### 已有链路

- `adjust_chapter_by_instruction`（agent_service.py:3930）：读取 DB 持久化创作包（`_ensure_agent_chapter_creation_pack`，3425）→ 传入 `run_chapter_creation_pipeline(creation_pack=...)` → `chapter_info["user_instruction"] = instruction` → pipeline 组装 `direct_feedback = [instruction]`（chapter_agents.py:2757-2758）→ `write_chapter_from_pack(editor_feedback=direct_feedback)`（2289）。
- 创作包渲染：`_creation_pack_prompt_text(creation_pack, 14000)`（chapter_agents.py:701）——若为 `canonical_content` 结构则原样输出；否则分节渲染。
- `reusable_chapter_creation_pack(quality_score, *, expected_fingerprint, instruction)`（chapter_agents.py:126-162）：已实现「指令 → `chapter_task.user_instruction` + `hard_requirements` 首位去重」转换，但**当前无调用方**（死代码）。其输入是 `quality_score`（含 `creation_pack` + `creation_pack_fingerprint`），签名不匹配 Agent 路径（Agent 直接持有 `creation_pack` dict）。
- 凭证门：写工具必须注册进 `_STORY_KNOWLEDGE_MUTATION_TOOLS`（2100）与 `_STORY_KNOWLEDGE_CONTEXT_PROFILES`（2121），执行时过 `validate_context_receipt`（2276-2350）；写操作需 pending_changes 跟踪（`_current_pending_changes().record_chapter_field` / `update_new_value`）。
- 手动保存语义（main.py:6914-6923）：`with_for_update` 行锁 → `expected_version` 校验（不符 409）→ `is_manual=True` + `content` 原样保存 + `version+1` + `updated_at=utcnow`。
- `canonical_agent_pack(content, chapter_info)`（chapter_creation_pack.py:247）：运行时包装 `{schema_version: 2, canonical_content, chapter_task}`。
- `rewrite_text_segment`（agent_service.py:4018）：精确查找替换，独立于创作包，已注册为 chapter_writer 写工具。

### 关键约束

- **agent_service 不能 import main**（循环导入：main import agent_service）。
- 写工具凭证门：`_mutation_target_chapter_numbers`（2143）通过 `chapter_id` / `chapter_number` / `chapter` / `chapters` 参数解析目标章节号，新的写工具参数必须兼容该解析（新工具用 `chapter_id`，已支持）。
- 写工具 description 需引导：修改创作包后正文不自动同步，需用户确认后重新生成。

## 设计

### 改动 1：新增读工具 `get_chapter_creation_pack`

注册位置：agent_service.py 中 `get_all_chapters_summary` 之后（约 2677 行前）。

```python
@tool_registry.register(
    name="get_chapter_creation_pack",
    description="读取指定章节的创作包（正文生成的设定依据）。返回创作包原文、版本号、是否为手动编辑、来源哈希。",
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer", "description": "章节 ID"},
        },
        "required": ["chapter_id"],
    },
)
async def get_chapter_creation_pack(chapter_id: int) -> dict:
    """读取章节创作包。"""
```

- 校验：`_validate_chapter_ownership(db, chapter_id, _current_story_id())`。
- 返回：
  ```python
  {
      "ok": True,
      "chapter_id": ...,
      "chapter_number": ...,
      "title": ...,
      "creation_pack_content": chapter.creation_pack_content or "",
      "creation_pack_version": int(chapter.creation_pack_version or 1),
      "is_manual": bool(chapter.creation_pack_is_manual),
      "source_hash": chapter.creation_pack_source_hash or "",
      "updated_at": ...,
  }
  ```
- 无创作包时 `creation_pack_content` 返回空字符串 + `"has_creation_pack": False`，便于 Agent 判断是否需要先提取。
- 读工具：不进 `_STORY_KNOWLEDGE_MUTATION_TOOLS` / `_STORY_KNOWLEDGE_CONTEXT_PROFILES`（不触发凭证门），但需注册进 chapter_writer skill 的 `tool_names`（1222-1228）。
- 归属：`_STORY_KNOWLEDGE_CONTEXT_PROFILES` 不加入；若希望读工具也要求上下文凭证，需额外处理——**本设计不要求**（与 `get_chapter_full` 一致，读工具无凭证门）。

### 改动 2：新增写工具 `update_chapter_creation_pack`

注册位置：agent_service.py 中 `update_chapter_content`（3459）之后。

```python
@tool_registry.register(
    name="update_chapter_creation_pack",
    description="保存/更新章节创作包（正文生成的设定依据）。适用于用户要求调整创作包设定。注意：修改创作包后正文不会自动同步，用户需确认后通过「重新生成正文」使改动生效。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer", "description": "章节 ID"},
            "content": {"type": "string", "description": "新的创作包全文"},
            "expected_version": {"type": "integer", "description": "期望的当前版本号（可选）。不传则强制保存；传了且不匹配时返回版本冲突错误。"},
        },
        "required": ["chapter_id", "content"],
    },
)
async def update_chapter_creation_pack(chapter_id: int, content: str, expected_version: int | None = None) -> dict:
    """保存章节创作包（is_manual=True）。"""
```

- 语义与 main.py:6914-6923 一致：`with_for_update` 行锁 → `expected_version` 可选校验 → `is_manual=True` + `content` 原样保存（不 sanitize）+ `version+1` + `updated_at=utcnow`。
- 凭证门：加入 `_STORY_KNOWLEDGE_MUTATION_TOOLS`（"update_chapter_creation_pack"）与 `_STORY_KNOWLEDGE_CONTEXT_PROFILES`（映射 `("chapter_writer",)`）→ 自动获得 `validate_context_receipt` + pending_changes 跟踪（`record_chapter_field(chapter, "creation_pack_content")` + `update_new_value`）。
- `_mutation_target_chapter_numbers` 无需改动（`chapter_id` 参数已支持）。
- 冲突返回：`{"error": "创作包已在其他位置更新，请重新读取后再保存", "version_conflict": True, "current_version": ...}`。
- 成功返回：`{"ok": True, "chapter_id", "creation_pack_version": 新版本, "is_manual": True, "note": "创作包已更新，正文不会自动同步..."}`。
- **不 import main**：实现为独立函数，逻辑约 20 行，直接写 `Chapter` ORM。

### 改动 3：用户指令注入创作包 `hard_requirements` 首项

在 `adjust_chapter_by_instruction`（3930）中，`_ensure_agent_chapter_creation_pack` 返回 `reusable_creation_pack`（`canonical_agent_pack` 结构：`{schema_version, canonical_content, chapter_task}`）后，若 `instruction` 非空，将指令注入创作包：

- 若 `canonical_pack_content(creation_pack)` 非空（有持久化创作包原文），则在**渲染文本层**注入：在 `canonical_content` 的末尾追加一个「## 用户要求」小节，把用户指令写入；同时更新 `chapter_task["user_instruction"]`。
- 若创作包为空（无持久化包），保持现状（指令走 `direct_feedback` + `chapter_info["user_instruction"]`，由 `build_chapter_creation_pack` 内部规则 #17 处理）。

实现方式：新增辅助函数 `_inject_user_instruction_into_pack(creation_pack, instruction) -> dict`（agent_service.py，紧邻 `adjust_chapter_by_instruction`）：

```python
def _inject_user_instruction_into_pack(creation_pack: dict[str, Any], instruction: str) -> dict[str, Any]:
    """把用户指令注入创作包文本，使「创作包为基础、用户要求为增量」进入写手 agent 硬合同。"""
    instruction = str(instruction or "").strip()
    if not instruction:
        return creation_pack
    pack = copy.deepcopy(creation_pack)
    canonical = str(pack.get("canonical_content") or "").strip()
    if canonical:
        if "## 用户要求" in canonical:
            # 替换旧用户要求小节，保留其余创作包内容
            parts = canonical.split("## 用户要求")[0].rstrip()
            canonical = parts
        pack["canonical_content"] = f"{canonical}\n\n## 用户要求\n{instruction}".strip()
    chapter_task = pack.get("chapter_task")
    if not isinstance(chapter_task, dict):
        chapter_task = {}
        pack["chapter_task"] = chapter_task
    chapter_task["user_instruction"] = instruction
    return pack
```

- 调用点：`adjust_chapter_by_instruction` 中 `reusable_creation_pack = _ensure_agent_chapter_creation_pack(...)` 之后：
  ```python
  reusable_creation_pack = _inject_user_instruction_into_pack(reusable_creation_pack, instruction)
  ```
- `direct_feedback` 链路保留（pipeline 内 2757-2758 仍会把 `user_instruction` 组装为编辑打回意见块），双通道传达。
- `reusable_chapter_creation_pack`（chapter_agents.py:126）保持不动：其签名面向 `quality_score`，Agent 路径通过上述辅助函数实现同等语义，避免改动框架路径。
- 注意：注入发生在内存中的 `creation_pack` dict，**不落库**，不改变 `creation_pack_version` / `source_hash`；保存后校验（3996-3997）仍以持久化版本为准，逻辑不变。

### 改动 4：工具选择引导更新

- `_build_writing_quality_section`（6260-6271）补充：
  - 大篇幅重写（调整风格/补充内容/整体重写）→ `adjust_chapter_by_instruction`（自动以创作包为基础）。
  - 精准局部修改（用户给出明确段落）→ `rewrite_text_segment`（直接替换，不涉及创作包）。
  - 调整创作包设定 → 先 `get_chapter_creation_pack` 读取，再 `update_chapter_creation_pack` 保存，最后提示用户重新生成正文。
- 工具指南区域（6447 / 6468 附近）同步补充对应条目。

## 测试计划（TDD，红→绿）

新建 `backend/tests/test_agent_creation_pack_tools.py`：

1. **get 读工具**：
   - `test_get_chapter_creation_pack_returns_content_version_and_manual_flag`：预置带创作包的章节，调用函数断言返回 content / version / is_manual / source_hash。
   - `test_get_chapter_creation_pack_empty_when_no_pack`：无创作包返回 `has_creation_pack=False` + 空 content。
   - `test_get_chapter_creation_pack_denies_foreign_chapter`：无权访问返回 error。
2. **update 写工具**：
   - `test_update_chapter_creation_pack_sets_manual_and_increments_version`：保存后 `is_manual=True`、version+1、content 原样保存。
   - `test_update_chapter_creation_pack_expected_version_mismatch`：expected_version 不匹配返回 `version_conflict=True`，内容不变。
   - `test_update_chapter_creation_pack_optional_expected_version`：不传 expected_version 强制保存。
   - 凭证门/注册断言：`"update_chapter_creation_pack" in _STORY_KNOWLEDGE_MUTATION_TOOLS`、`_STORY_KNOWLEDGE_CONTEXT_PROFILES[name] == ("chapter_writer",)`、chapter_writer skill tool_names 含两个新工具。
3. **指令注入**：
   - `test_adjust_chapter_by_instruction_injects_instruction_into_canonical_pack`：构造含 canonical_content 的创作包 + instruction，调用 `_inject_user_instruction_into_pack`，断言 `## 用户要求` 小节存在且 `chapter_task.user_instruction == instruction`。
   - `test_inject_pack_keeps_existing_content`：注入不破坏原有创作包正文。
   - `test_inject_empty_instruction_returns_unchanged`：空指令原样返回。
   - `test_adjust_chapter_by_instruction_end_to_end`（集成）：monkeypatch pipeline 捕获传入的 `creation_pack`，断言包含「## 用户要求」。

回归：`test_story_knowledge.py`、`test_chapter_generation_length_policy.py`、`test_agent_policy_boundaries.py` 全量通过；`python -m py_compile` 全部后端文件；`npx tsc -b` 前端零错误。

## 不做的事

- 不改 `run_chapter_creation_pipeline` / `write_chapter_from_pack` 内部（创作包渲染逻辑已完整）。
- 不改 `reusable_chapter_creation_pack`（chapter_agents.py:126）——保持框架路径不动，Agent 路径用 `_inject_user_instruction_into_pack`。
- 不改前端设定中心（请求 2 已完成）。
- 不落库注入后的创作包（仅内存，避免污染 `source_hash` / `version`）。
- 不把 `update_chapter_creation_pack` 暴露为可自动提取创作包的工具——用户明确是「修改读写」，AI 提取链路保持现状（设定中心手动按钮 + Agent 改大纲源头）。
