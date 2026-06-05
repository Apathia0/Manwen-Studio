"""验证：Agent 架构重构 — 阶段一 & 二变更。"""

import ast
import sys

sys.path.insert(0, ".")

# ─── 1. 死代码确认删除 ──────────────────────────────────
def test_dead_code_removed():
    """_apply_framework_operations 函数已删除"""
    code = open("services/agent_service.py", encoding="utf-8").read()
    assert "_apply_framework_operations" not in code, (
        "死代码 _apply_framework_operations 未删除！"
    )


# ─── 2. max_tokens 配置 ─────────────────────────────────
def test_max_tokens_32768():
    """max_tokens 从 16384 提升到 32768"""
    code = open("services/agent_service.py", encoding="utf-8").read()
    assert '"max_tokens": 32768' in code, "max_tokens 未更新到 32768"


# ─── 3. 工具注册 ────────────────────────────────────────
def test_tools_registered():
    """新工具已注册到 tool_registry"""
    from services.agent_service import tool_registry

    specs = tool_registry.get_tool_specs()
    names = [s["function"]["name"] for s in specs]

    assert "apply_framework_ops" in names, "apply_framework_ops 未注册"
    assert "adjust_framework" in names, "adjust_framework 未注册（不该被删除）"
    assert "bulk_add_chapter_plans" in names, "bulk_add_chapter_plans 未注册"


# ─── 4. apply_framework_ops 参数结构 ────────────────────
def test_apply_framework_ops_params():
    """apply_framework_ops 工具参数包含 dry_run"""
    from services.agent_service import tool_registry

    specs = tool_registry.get_tool_specs()
    names = [s["function"]["name"] for s in specs]
    idx = names.index("apply_framework_ops")
    props = specs[idx]["function"]["parameters"]["properties"]

    assert "story_id" in props
    assert "operations" in props
    assert "patches" in props
    assert "dry_run" in props, "dry_run 参数缺失"
    assert props["dry_run"]["type"] == "boolean", "dry_run 应为 boolean 类型"
    assert props["dry_run"].get("description", ""), "dry_run 应有描述"


# ─── 5. apply_framework_ops 定义包含 dry_run 参数 ────────
def test_apply_framework_ops_dry_run_implementation():
    """apply_framework_ops 函数签名含 dry_run，且有 dry_run 分支"""
    code = open("services/agent_service.py", encoding="utf-8").read()
    assert "dry_run: bool = False" in code, "函数签名缺少 dry_run 参数"
    assert "if dry_run:" in code, "缺少 dry_run 条件分支"
    assert '"dry_run": True' in code, "dry_run 分支缺少 dry_run=True 标记"
    assert '"preview_framework"' in code, "dry_run 分支缺少 preview_framework 字段"


# ─── 6. adjust_framework 返回 _generated_operations ─────
def test_adjust_framework_returns_generated_operations():
    """adjust_framework 返回值包含 _generated_operations"""
    code = open("services/agent_service.py", encoding="utf-8").read()
    assert '"_generated_operations"' in code, "返回缺失 _generated_operations"
    # 确认它在 adjust_framework 的 return dict 里，而非其他地方
    # 找到 return 块中紧挨着 warnings 的地方
    idx = code.index('"warnings": warnings,')
    snippet = code[idx : idx + 80]
    assert '"_generated_operations"' in snippet, (
        "_generated_operations 不在 adjust_framework 的 return 块中"
    )


# ─── 7. System Prompt — 决策树 ──────────────────────────
def test_system_prompt_decision_tree():
    """System prompt 包含工具选择决策树"""
    code = open("services/agent_service.py", encoding="utf-8").read()
    assert "工具选择决策树" in code or "框架修改工具选择决策树" in code, "缺少决策树"
    assert "apply_framework_ops" in code.split("决策树")[1][:300], (
        "决策树中未提及 apply_framework_ops"
    )


# ─── 8. System Prompt — operation schema 参考 ───────────
def test_system_prompt_operation_schema():
    """System prompt 包含 operation schema 参考表"""
    code = open("services/agent_service.py", encoding="utf-8").read()
    assert "apply_framework_ops 操作格式" in code, "缺少 operation schema 标题"
    assert "update_story_description" in code, "缺少 update_story_description"
    assert "add_character" in code
    assert "update_character" in code
    assert "delete_chapter" in code
    assert "dry_run" in code.split("delete_chapter")[1][:500], (
        "schema 中未提及 dry_run"
    )


# ─── 9. System Prompt — 工具列表包含新工具 ──────────────
def test_system_prompt_tool_list():
    """写入工具列表包含 apply_framework_ops"""
    code = open("services/agent_service.py", encoding="utf-8").read()
    assert "- `apply_framework_ops`" in code, "工具列表缺少 apply_framework_ops"
    assert "- `bulk_add_chapter_plans`" in code, "工具列表缺少 bulk_add_chapter_plans"


# ─── 10. framework_utils 核心函数未被改动 ───────────────
def test_framework_utils_unchanged():
    """apply_framework_operations 核心函数签名未变"""
    from services.framework_utils import apply_framework_operations
    import inspect

    sig = inspect.signature(apply_framework_operations)
    params = list(sig.parameters.keys())
    assert "existing_framework" in params
    assert "operations" in params
    assert "patches" in params
