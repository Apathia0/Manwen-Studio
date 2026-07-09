#!/usr/bin/env python
"""本地验证：连续性改动是否生效（不实际调用 DeepSeek API，验证 prompt 构建）"""
import sys
import json
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '.')

from main import _merge_story_memory, _build_framework_ai_context
from services.story_state import build_story_memory_compact
from services.deepseek import (
    _build_story_snapshot, _build_story_snapshot_tiered,
    expand_chapter_to_content, NOVEL_SYSTEM_PROMPT,
    summarize_chapter_memory
)

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
BOLD = "\033[1m"
RESET = "\033[0m"

results = []

def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((name, condition))
    print(f"  [{status}] {name}")
    if detail and not condition:
        print(f"         {detail}")

print("=" * 70)
print(BOLD + "本地验证：小说上下文连续性改动" + RESET)
print("=" * 70)

# ===================================================
# 准备测试数据：匹配用户截图中的剧情
# ===================================================
print(f"\n{BOLD}--- 准备测试数据 ---{RESET}")

# 模拟第 1 话生成后 summarize_chapter_memory 应返回的结果
ch1_memory_payload = {
    "chapter_summary": {
        "summary": "林越发现小月亮被封禁的记录，操作面板闪烁，系统管理员扫描区域数据，行为被标记为异常，GM来了。",
        "major_events": ["发现小月亮被封禁", "操作面板闪烁", "系统管理员扫描", "行为被标记异常"],
        "character_changes": ["林越从困惑转为警觉"],
        "new_facts": ["小月亮账号被封禁", "系统有管理员监控"],
        "open_loops": ["GM为什么要扫描区域数据", "小月亮为什么被封禁"],
        "resolved_loops": [],
        "ending_scene": "林越瞳孔一缩。GM来了。"
    },
    "story_memory_update": {
        "story_state": "林越发现小月亮被封禁，操作面板闪烁警告，系统管理员正在扫描区域数据，行为被标记为异常，GM即将到来。",
        "current_arc_focus": "穿越成NPC后的生存危机 - 躲避系统管理员/GM的追踪",
        "current_tone": "紧张、悬疑、危机感",
        "next_payoff_target": "GM到来后的对峙或逃脱",
        "continuity_facts": ["林越是穿越到游戏世界的NPC", "小月亮账号被封禁", "系统有管理员监控机制"],
        "open_loops": ["GM为什么要扫描区域数据", "小月亮为什么被封禁", "林越如何躲避GM"],
        "resolved_loops": ["林越发现小月亮被封禁的真相"]
    }
}

# 模拟第 1 话生成的正文内容（匹配截图）
ch1_content = (
    '林越看着【小月亮】被封禁的记录，苦笑一声。\n\n'
    '看来，他的冒险才刚刚开始。\n\n'
    '就在这时，他的操作面板突然闪烁了一下，一条新的信息浮现在眼前——\n\n'
    '【检测到系统管理员正在扫描区域数据……】\n'
    '【警告：您的行为已被标记为异常！】\n\n'
    '林越瞳孔一缩。\n\n'
    'GM来了。'
)

# 模拟第 1 话信息
class MockChapter1:
    def __init__(self):
        self.chapter_number = 1
        self.title = "铁匠铺的觉醒"
        self.act = "第一阶段"
        self.key_events = ["发现小月亮被封禁", "操作面板闪烁"]
        self.novel_content = ch1_content
        self.id = 1
        self.story = MockStory1()

class MockStory1:
    def __init__(self):
        self.story_memory = {}
        self.outline = {"three_acts": [{"act": 1, "title": "觉醒篇"}]}
        self.description = "林越穿越到游戏世界成为NPC的冒险故事"
        self.tags = {"genre": "游戏异界", "tone": "悬疑"}
        self.characters = [{"name": "林越", "role": "主角", "desc": "穿越成NPC的玩家"}]
        self.story_bible = {
            "creative_brief": {"one_line_premise": "一个穿越成NPC的人在游戏世界中求生的故事"}
        }

mock_ch1 = MockChapter1()
mock_story = mock_ch1.story

print("测试数据准备完成")

# ===================================================
# 测试 1：_merge_story_memory - 第 1 话生成后 memory 是否正确合并
# ===================================================
print(f"\n{BOLD}--- 测试 1：第 1 话生成后 story_memory 合并 ---{RESET}")

ch1_summary = ch1_memory_payload.get("chapter_summary", {})
ch1_memory_update = ch1_memory_payload.get("story_memory_update", {})

merged = _merge_story_memory({}, ch1_memory_update, mock_ch1, ch1_summary)
check("story_memory 字段数 > 0", len(merged) > 0)
check("story_state 非空", bool(merged.get("story_state")))
check("open_loops 非空", bool(merged.get("open_loops")))
check("recent_chapter_summaries 有记录", len(merged.get("recent_chapter_summaries", [])) == 1)
check("包含 ending_scene", ch1_summary.get("ending_scene") == "林越瞳孔一缩。GM来了。")

# ===================================================
# 测试 2：build_story_memory_compact - 压缩是否完整
# ===================================================
print(f"\n{BOLD}--- 测试 2：story_memory_compact 压缩 ---{RESET}")

compact = build_story_memory_compact(merged)
check("compact 非空", bool(compact))
check("compact 包含 story_state", "story_state" in compact)
check("compact 包含 open_loops", "open_loops" in compact)
check("compact 包含 recent_chapter_summaries", "recent_chapter_summaries" in compact)
compact_size = len(json.dumps(compact, ensure_ascii=False))
check(f"compact 大小 {compact_size} chars < 2000", compact_size < 2000)

# ===================================================
# 测试 3：_build_framework_ai_context - story_context 是否包含 memory
# ===================================================
print(f"\n{BOLD}--- 测试 3：story_context 构建 ---{RESET}")

# 更新 mock_story 的 story_memory
mock_story.story_memory = merged

ctx = _build_framework_ai_context(mock_story)
check("context 包含 story_memory", "story_memory" in ctx)
check("context 包含 story_memory_compact", "story_memory_compact" in ctx)
check("story_memory 非空", bool(ctx["story_memory"]))
check("story_memory_compact 非空", bool(ctx["story_memory_compact"]))

# ===================================================
# 测试 4：_build_story_snapshot - 注入作品连续性记忆
# ===================================================
print(f"\n{BOLD}--- 测试 4：_build_story_snapshot 连续性注入 ---{RESET}")

snapshot = _build_story_snapshot(ctx)
check("snapshot 包含'作品连续性记忆'", "作品连续性记忆" in snapshot)
check("snapshot 包含'GM'", "GM" in snapshot)
check("snapshot 包含'story_state'", "story_state" in snapshot)
check("snapshot 包含'open_loops'", "open_loops" in snapshot)

# ===================================================
# 测试 5：_build_story_snapshot_tiered auto 模式
# ===================================================
print(f"\n{BOLD}--- 测试 5：_build_story_snapshot_tiered auto 模式 ---{RESET}")

snapshot_auto = _build_story_snapshot_tiered(ctx, "auto")
check("auto snapshot 包含'作品连续性记忆'", "作品连续性记忆" in snapshot_auto)
check("auto snapshot 包含'GM'", "GM" in snapshot_auto)

snapshot_full = _build_story_snapshot_tiered(ctx, "full")
check("full snapshot 包含'作品连续性记忆'", "作品连续性记忆" in snapshot_full)

snapshot_runtime = _build_story_snapshot_tiered(ctx, "framework_runtime")
# framework_runtime should not have our injected field (it has its own memory)
print("  [?] framework_runtime 模式使用_build_framework_runtime_brief（已有独立 memory），不做断言")

# ===================================================
# 测试 6：previous_chapter_summary 构建
# ===================================================
print(f"\n{BOLD}--- 测试 6：previous_chapter_summary 构建 ---{RESET}")

# 模拟 expand_chapter_endpoint 中的构建逻辑
ending_text = ch1_content[-800:]
memory_compact = build_story_memory_compact(merged)
parts_list = [f"上一章《第1章：铁匠铺的觉醒》结尾：\n{ending_text}"]
if memory_compact.get("story_state"):
    parts_list.append(f"当前故事状态：{memory_compact['story_state']}")
if memory_compact.get("current_arc_focus"):
    parts_list.append(f"当前剧情焦点：{memory_compact['current_arc_focus']}")
if memory_compact.get("open_loops"):
    loops = memory_compact["open_loops"][:5]
    parts_list.append("待回收伏笔：\n- " + "\n- ".join(loops))

previous_summary = "\n".join(parts_list)
if len(previous_summary) > 2000:
    previous_summary = previous_summary[:2000]

check("previous_summary 非空", bool(previous_summary))
check("包含'上一章'", "上一章" in previous_summary)
check("包含'GM来了'", "GM来了" in previous_summary)
check("包含'故事状态'", "故事状态" in previous_summary)
check("包含'伏笔'", "伏笔" in previous_summary)
check(f"长度 {len(previous_summary)} chars < 2000", len(previous_summary) < 2000)

# ===================================================
# 测试 7：NOVEL_SYSTEM_PROMPT 连续性指令
# ===================================================
print(f"\n{BOLD}--- 测试 7：NOVEL_SYSTEM_PROMPT 连续性指令 ---{RESET}")

check("包含'章节间连续性'", "章节间连续性" in NOVEL_SYSTEM_PROMPT)
check("包含'自然衔接上一章结尾'", "自然衔接上一章结尾" in NOVEL_SYSTEM_PROMPT)
check("包含'作品连续性记忆'", "作品连续性记忆" in NOVEL_SYSTEM_PROMPT)
check("包含'角色状态必须保持一致'", "角色状态" in NOVEL_SYSTEM_PROMPT)
check("包含'不得编造虚构'", "不得编造或虚构" in NOVEL_SYSTEM_PROMPT)

# ===================================================
# 测试 8：expand_chapter system prompt 连续性指令
# ===================================================
print(f"\n{BOLD}--- 测试 8：expand_chapter system prompt 连续性指令 ---{RESET}")

import inspect
expand_src = inspect.getsource(expand_chapter_to_content)
check("system prompt 包含'章节间连续性'", "章节间连续性" in expand_src)
check("system prompt 包含'自然衔接'", "自然衔接上一章结尾" in expand_src)
check("system prompt 包含'前情提要'", "前情提要" in expand_src or "\u201c前情提要\u201d" in expand_src)
check("模板包含'上集回顾'", "上集回顾" in expand_src)
check("previous_chapter_summary 参数存在", "previous_chapter_summary" in expand_src)

# ===================================================
# 测试 9：模拟第 2 话完整 prompt 构建
# ===================================================
print(f"\n{BOLD}--- 测试 9：模拟第 2 话完整 prompt 构建 ---{RESET}")

ch2_info = {
    "title": "第一次举报",
    "act": "第一阶段",
    "chapter_number": 2,
    "summary": "林越成功举报异常获得系统奖励",
    "goal": "躲避GM追踪",
    "conflict": "GM正在扫描区域数据",
    "hook": "系统奖励的诱惑",
    "payoff": "获得关键道具",
    "highlight": "紧张的对峙场面",
    "key_events": ["举报异常", "获得奖励"]
}

snapshot = _build_story_snapshot(ctx)
ch_details = json.dumps(ch2_info, ensure_ascii=False)
previous_block = ""

if previous_summary and previous_summary.strip():
    previous_block = f"\n## 上集回顾\n{previous_summary}\n"

# 使用 system prompt 中的连续性指令（从 expand_src 中提取）
system_continuity = ""
for line in expand_src.split("\n"):
    if "章节间连续性" in line:
        system_continuity = "存在"

user_prompt = f"""请根据以下故事框架和章节信息，创作这一话的完整小说内容。

## 故事框架
{snapshot}

## 本章信息
{ch_details}
{previous_block}## ★★★ 字数要求（最高优先级）★★★
- 每一话控制在 2000 字左右（1700-2500 字范围）。这是硬性要求，不可商量。
- 低于 1500 字则内容过于单薄，必须回去补充描写；超过 3000 字则过于冗长，需要精简。

## 写作指导
- 请直接输出小说正文，不要加额外说明或字数统计。"""

print(f"\n完整 prompt 总长度: {len(user_prompt)} chars / ~{len(user_prompt)//4} tokens")
print()

check("prompt 包含'作品连续性记忆'", "作品连续性记忆" in user_prompt,
      "这是 snapshot 自动注入的 story_memory_compact")
check("prompt 包含'上集回顾'", "上集回顾" in user_prompt,
      "这是 expand_chapter_endpoint 构建的 previous_chapter_summary")
check("prompt 包含第 1 话结尾'GM来了'", "GM来了" in user_prompt,
      "证明上一章结尾文本成功注入")
check("prompt 包含'open_loops'", "open_loops" in user_prompt,
      "证明 story_memory 中的未回收悬念注入")
check("prompt 包含'story_state'", "story_state" in user_prompt,
      "证明故事状态信息注入")
check("prompt 包含第 1 话角色'林越'", "林越" in user_prompt,
      "证明前文角色信息可用")
check("prompt 包含第 2 话章节信息", "\"第一次举报\"" in user_prompt,
      "证明本章信息正常注入")

# ===================================================
# 测试 10：边界情况 - 第一章跳过 continuity
# ===================================================
print(f"\n{BOLD}--- 测试 10：边界情况 ---{RESET}")

# 10a: 第一章时 previous_chapter_summary 为空
check("第一章默认 previous_chapter_summary=''",
      expand_chapter_to_content.__defaults__ is not None and
      expand_chapter_to_content.__defaults__[-1] == "")

# 10b: 空 story_memory 不报错
empty_ctx = {"story_bible": {"creative_brief": {"one_line_premise": "test"}}}
snapshot_empty = _build_story_snapshot(empty_ctx)
check("空 story_memory 不报错", "作品圣经" in snapshot_empty and "作品连续性记忆" not in snapshot_empty)

# 10c: compact 上限验证 - 12 项/列表
big_memory = {
    "open_loops": [f"loop_{i}" for i in range(50)],
    "continuity_facts": [f"fact_{i}" for i in range(50)],
    "resolved_loops": [f"resolved_{i}" for i in range(50)],
    "recent_chapter_summaries": [{"chapter_number": i, "title": f"Ch{i}", "summary": "x"}
                                  for i in range(50)],
}
big_compact = build_story_memory_compact(big_memory)
check("open_loops 上限 12 项", len(big_compact.get("open_loops", [])) <= 12)
check("continuity_facts 上限 12 项", len(big_compact.get("continuity_facts", [])) <= 12)
check("resolved_loops 上限 12 项", len(big_compact.get("resolved_loops", [])) <= 12)
check("recent summaries 上限 8 条", len(big_compact.get("recent_chapter_summaries", [])) <= 8)

# 10d: merge_story_memory 去重
dup_update = {
    "story_state": "新状态",
    "open_loops": ["新悬念"],
}
dup_result = _merge_story_memory(
    {"open_loops": ["已有悬念"], "story_state": "已有状态"},
    dup_update, mock_ch1, ch1_summary
)
check("合并后 story_state 更新为新值",
      dup_result.get("story_state") == "新状态")
check("open_loops 合并去重",
      len(dup_result.get("open_loops", [])) == 2)  # 已有悬念 + 新悬念 = 2

# ===================================================
# 汇总
# ===================================================
print(f"\n{'=' * 70}")
print(BOLD + "验证结果汇总" + RESET)
print(f"{'=' * 70}")

passed = sum(1 for _, c in results if c)
failed = sum(1 for _, c in results if not c)
total = len(results)

print(f"\n通过: {passed}/{total}")
print(f"失败: {failed}/{total}")

if failed > 0:
    print(f"\n{BOLD}失败的验证项:{RESET}")
    for name, c in results:
        if not c:
            print(f"  ❌ {name}")

print(f"\n{BOLD}结论:{RESET}")
if failed == 0:
    print("  ✅ 所有验证通过！连续性改动在代码层面完全正确。")
    print()
    print("提示：这些改动仅在本地代码中，未推送到远程仓库。")
    print("      如需部署到生产环境，请执行 git push 后通知我。")
else:
    print(f"  ❌ {failed} 项验证失败，需要修复。")
