"""
作者画像引用效果对比测试

对比"引用作者画像" vs "不引用作者画像"在小说创作中的提示词差异和生成效果差异。

用法:
    cd backend
    python tests/test_author_style_effect.py            # 仅对比提示词
    python tests/test_author_style_effect.py --generate  # 同时调用 DeepSeek 生成对比
"""

import json
import os
import sys
import argparse
from dataclasses import dataclass
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


MOCK_AUTHOR_PROFILE = {
    "schema_version": 1,
    "sampled_chapters": [1, 5, 12, 20, 35],
    "style_profile": {
        "sentence": {
            "pattern": "短句为主，动作描写极简（'拔刀。挥砍。血溅。'），长句用于环境渲染",
            "avg_length": "12-15字",
            "variation": "长短交替，紧张时全短句，铺垫时加长",
        },
        "dialogue": {
            "style": "口语化，带地方色彩",
            "info_density": "每句对话都推动剧情或揭示性格",
            "action_fused": True,
        },
        "description": {
            "sensory": "视觉+听觉+触觉多感官",
            "combat_logic": "一招一式因果清晰，力度角度速度明确",
        },
        "emotion_expression": {
            "method": "行动暗示（握拳颤抖）+ 内心独白（该死！中计了！）",
            "restraint": "克制积累后爆发，收放反差",
        },
        "pov_and_narration": {
            "primary": "第三人称有限视角",
            "advanced": "章节间视角切换拼凑全景",
        },
    },
    "rhythm_profile": {
        "opening_hook": {"type": "场景悬念式", "example": "残破的祭坛上，一道血光冲天而起"},
        "chapter_end_hooks": [
            {"type": "悬念型", "description": "留下未解之谜"},
            {"type": "危机型", "description": "揭示迫在眉睫的威胁"},
        ],
        "emotion_cycle": {"pattern": "紧张→缓解→新悬念", "buildup": "隐忍积累后爆发"},
        "info_release_pattern": {"method": "迷宫式线索拼凑", "timing": "关键时刻才揭示重大设定"},
    },
    "routine_cards": [
        {
            "name": "陷阱与猎杀",
            "structure": ["敌情评估", "制定计划", "分工准备", "引君入瓮", "引爆击杀", "战后余波"],
            "emotion": "紧张→冷静→期待→悬念→高潮→意外",
        },
        {
            "name": "日常对话中的反转",
            "structure": ["日常铺垫", "埋下隐患", "危机降临", "意外反转"],
            "emotion": "平静→忧虑→紧张→意外/缓和",
        },
    ],
    "writing_guide": {
        "do": [
            "动作描写用短句制造紧张感",
            "用行动代替形容词表达情绪",
            "对话每句都要推动剧情",
            "多视角切换构建世界",
        ],
        "avoid": [
            "避免无关寒暄的废话对话",
            "避免直接用情绪形容词",
            "避免平铺直叙的信息释放",
        ],
        "prompt_notes": [
            "冲突时一律以作者画像为准",
            "句式节奏优先级高于通用写作规范",
        ],
    },
    "confidence": 0.82,
}

MOCK_AUTHOR_REPORT = """# 古风仙侠写作技法学习报告

## 一、文风画像

### 1. 句子结构：精准的节奏控制

*   **主体风格**：大量使用短句，尤其在动作描写和关键对话中，形成干脆利落、极具画面感的节奏。例如，"拔刀。挥砍。血溅。"这类短句能瞬间营造紧张氛围。
*   **辅助手法**：在环境渲染、心理描绘或铺垫重要信息时，会适当穿插结构较复杂的长句。长短句交替，张弛有度，避免阅读疲劳。
*   **特例**：在章节开头的致谢部分，会采用短句列表式，配合感叹号和表情符号，形成一种强烈的、社区化的互动氛围，与正文的冷峻风格形成鲜明对比。

### 2. 对话设计：信息驱动与人物塑造

*   **核心原则**：对话以"高效传递信息、推动情节发展"为首要目的。
*   **语言风格**：口语化强，常带有些许地方方言色彩，使角色更具生活气息和辨识度。对话通常极为简短，极少有无关紧要的寒暄。
*   **细节融合**：对话中嵌入了大量动作和神态描写，通过"肢体语言"辅助表达情绪和潜台词，让对话更具张力。

### 3. 描写手法：沉浸式的多感官体验

*   **环境描写**：注重细节，擅长调动读者的视觉、听觉、触觉。
*   **动作描写**：极具动态感和逻辑性。一招一式的因果关系清晰，力度、角度、速度都有所体现。
*   **人物神态**：善于捕捉极其微小的神态变化（如"眼角抽动了一下"），并将其作为揭示人物内心活动的关键线索。

## 二、节奏习惯

### 1. 开篇钩子

*   **场景悬念式**：直接呈现一个奇特、危险或无法解释的景象，立即勾起读者好奇心。
*   **危机骤降式**：故事从主角或家族遭遇突如其来的危机开始。
*   **情绪冲击式**：从角色的强烈情绪切入，迅速建立情感的代入感。

### 2. 章节结尾钩子

*   **悬念型**：留下未解之谜，迫使读者翻开下一章。
*   **危机或警示型**：揭示一个迫在眉睫的威胁或阳谋。

## 三、核心套路卡

### 套路卡 1：家族/势力发展转折

*   **意外机缘**：家族或主角获得某个意外的好处。
*   **深度思考**：决策者陷入长久的、冷静的思考，评估利弊。
*   **策略布局**：做出重大的战略调整。
*   **深藏伏笔**：暗示更深的意图，为后续发展提供空间。

### 套路卡 2：陷阱与猎杀（爽点设计）

*   **敌情评估**：发现威胁并评估能力。
*   **制定计划**：基于优势制定猎杀计划。
*   **分工准备**：团队分头行动。
*   **引君入瓮**：主角引诱敌人到陷阱区域。
*   **引爆与击杀**：陷阱触发，敌人被击败。
*   **战后余波**：清理战场，发现新线索。

## 四、复用建议

1.  **学习"短句能量"**：在描写动作、对话关键句时，刻意使用短句。
2.  **用"行动"代替"形容"**：不要直接写"他很生气"，而是写"他踢翻了凳子"。
3.  **对话作为信息泵**：删掉所有无关紧要的"废话"。
4.  **多视角构建世界**：从不同角色角度观察同一件事。

## 五、风险提醒

1.  **信息过载风险**：多视角切换过于频繁容易导致人物脸盲。
2.  **节奏失衡风险**：过度追求短句紧张感可能导致缺少呼吸感。
3.  **情感克制过度风险**：长期压抑缺少情感宣泄点可能让读者憋屈。
"""

MOCK_STYLE_SAMPLES = [
    {
        "chapter": 1,
        "snippet": "祭坛上的血光映红了半边天空。林远握紧了刀柄，指节发白。风从北方来，带着铁锈和焦糊的气味。他听见身后有脚步声，很轻，像猫踩在枯叶上。不是师父，师父走路没有声音。他猛地转身，刀出鞘——",
    },
    {
        "chapter": 5,
        "snippet": "\"有诈。\"他盯着对方的眼睛，缓缓吐出两个字。对方笑了。笑容很淡，像冬天结冰的湖面裂开一道缝。林远的手垂在身侧，指尖微微颤抖。不是害怕，是兴奋。他等这一刻，等了三年。",
    },
]

MOCK_STORY_BIBLE_WITH_REF = {
    "deconstruction_1": {"title": "匿名参考作品"},
    "creative_brief": {
        "project_positioning": "东方仙侠·成长流",
        "one_line_premise": "废柴少年偶得上古传承，在宗门阴谋中崛起",
        "core_hook": "每章结尾必有反转",
        "protagonist_core": "隐忍、果断、记仇",
        "main_conflict": "宗门内斗+外敌入侵",
        "longline_mystery": "传承的真正来历",
        "pacing_strategy": "前慢后快，三章一爽点",
    },
    "writing_guidance": {
        "opening_strategy": "危机开局",
        "chapter_density_strategy": "每章2500-3000字",
        "midgame_engine": "宗门大比+秘境探索",
        "forbidden_patterns": ["不要开局流水账", "避免大段设定解说"],
    },
    "reference_author_profile": MOCK_AUTHOR_PROFILE,
    "reference_author_report": MOCK_AUTHOR_REPORT,
    "reference_style_samples": MOCK_STYLE_SAMPLES,
}

MOCK_STORY_BIBLE_WITHOUT_REF = {
    "creative_brief": {
        "project_positioning": "东方仙侠·成长流",
        "one_line_premise": "废柴少年偶得上古传承，在宗门阴谋中崛起",
        "core_hook": "每章结尾必有反转",
        "protagonist_core": "隐忍、果断、记仇",
        "main_conflict": "宗门内斗+外敌入侵",
        "longline_mystery": "传承的真正来历",
        "pacing_strategy": "前慢后快，三章一爽点",
    },
    "writing_guidance": {
        "opening_strategy": "危机开局",
        "chapter_density_strategy": "每章2500-3000字",
        "midgame_engine": "宗门大比+秘境探索",
        "forbidden_patterns": ["不要开局流水账", "避免大段设定解说"],
    },
}


@dataclass
class MockStory:
    id: int = 1
    title: str = "测试小说"
    story_bible: dict = None
    story_memory: dict = None
    tags: list = None
    characters: list = None
    outline: dict = None

    def __post_init__(self):
        if self.story_bible is None:
            self.story_bible = {}
        if self.story_memory is None:
            self.story_memory = {}
        if self.tags is None:
            self.tags = ["仙侠", "成长", "爽文"]
        if self.characters is None:
            self.characters = [{"name": "林远", "role": "主角", "personality": "隐忍果断"}]
        if self.outline is None:
            self.outline = {"act1": "宗门危机", "act2": "秘境觉醒", "act3": "最终对决"}


@dataclass
class MockChapter:
    id: int = 1
    title: str = "第一章 血色祭坛"
    act: str = "act1"
    key_events: list = None
    goal_card: dict = None

    def __post_init__(self):
        if self.key_events is None:
            self.key_events = ["发现祭坛异变", "遭遇神秘敌人"]
        if self.goal_card is None:
            self.goal_card = {"goal": "引入主线", "conflict": "突袭", "hook": "血光", "payoff": "传承觉醒"}


def test_extract_functions():
    from services.story_state import extract_author_profile_sections, extract_report_highlights

    print("\n" + "=" * 80)
    print("【测试 1】extract_author_profile_sections — 结构化画像提取")
    print("=" * 80)

    sections = extract_author_profile_sections(MOCK_AUTHOR_PROFILE)
    for s in sections:
        print(f"\n--- {s[:60]}...")
    print(f"\n提取段落数: {len(sections)}")
    print(f"总字符数: {sum(len(s) for s in sections)}")

    print("\n" + "=" * 80)
    print("【测试 2】extract_report_highlights — 报告核心要点提取")
    print("=" * 80)

    full_report = MOCK_AUTHOR_REPORT
    highlights = extract_report_highlights(full_report)

    print(f"\n原始报告长度: {len(full_report)} 字")
    print(f"提取后长度: {len(highlights)} 字")
    print(f"压缩比: {len(highlights) / len(full_report) * 100:.1f}%")
    print("\n提取内容预览:")
    print("-" * 60)
    print(highlights[:500])
    print("..." if len(highlights) > 500 else "")


def test_prompt_diff():
    from main import _build_framework_context

    story_with_ref = MockStory(story_bible=MOCK_STORY_BIBLE_WITH_REF)
    story_without_ref = MockStory(story_bible=MOCK_STORY_BIBLE_WITHOUT_REF)
    chapter = MockChapter()

    print("\n" + "=" * 80)
    print("【测试 3】_build_framework_context — 提示词对比")
    print("=" * 80)

    prompt_with_ref = _build_framework_context(story_with_ref, chapter)
    prompt_without_ref = _build_framework_context(story_without_ref, chapter)

    print(f"\n无画像提示词长度: {len(prompt_without_ref)} 字")
    print(f"有画像提示词长度: {len(prompt_with_ref)} 字")
    print(f"差异: +{len(prompt_with_ref) - len(prompt_without_ref)} 字")

    print("\n" + "-" * 80)
    print("【无画像版本】提示词内容:")
    print("-" * 80)
    print(prompt_without_ref)

    print("\n" + "-" * 80)
    print("【有画像版本】提示词内容:")
    print("-" * 80)
    print(prompt_with_ref)

    print("\n" + "-" * 80)
    print("【差异分析】有画像版本新增的内容段落:")
    print("-" * 80)

    without_lines = set(prompt_without_ref.split('\n'))
    for line in prompt_with_ref.split('\n'):
        if line not in without_lines and line.strip():
            print(f"  + {line[:100]}")

    ref_only_keys = []
    for key in ["可复用写作套路", "作者写作指南", "参考节奏控制", "作者风格画像", "作者画像参考报告", "作者原文风格示例"]:
        if key in prompt_with_ref and key not in prompt_without_ref:
            ref_only_keys.append(key)
    print(f"\n画像专属注入段落: {ref_only_keys}")
    assert len(ref_only_keys) == 6, f"期望 6 个画像段落，实际 {len(ref_only_keys)}: {ref_only_keys}"
    print("✓ 断言通过: 6 个画像段落全部注入")


def test_generation_comparison():
    try:
        from dotenv import load_dotenv
        load_dotenv()
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        if not api_key:
            print("\n[跳过] 未配置 DEEPSEEK_API_KEY，无法进行生成对比测试")
            return
    except Exception:
        print("\n[跳过] 环境变量加载失败")
        return

    import requests

    from main import _build_framework_context

    story_with_ref = MockStory(story_bible=MOCK_STORY_BIBLE_WITH_REF)
    story_without_ref = MockStory(story_bible=MOCK_STORY_BIBLE_WITHOUT_REF)
    chapter = MockChapter()

    framework_with = _build_framework_context(story_with_ref, chapter)
    framework_without = _build_framework_context(story_without_ref, chapter)

    system_prompt_base = "你是一位专业的网络小说写手。请根据提供的框架约束，创作一章网络小说正文。要求：字数800字左右，注意节奏感和画面感。"

    user_task = "请创作第一章的正文内容。场景：林远在祭坛旁遭遇神秘敌人，传承觉醒。"

    print("\n" + "=" * 80)
    print("【测试 4】DeepSeek 生成对比 — 同一场景，有无作者画像")
    print("=" * 80)

    def call_deepSeek(system: str, user: str) -> str:
        resp = requests.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": 2048,
                "temperature": 0.7,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    print("\n正在生成【无画像】版本...")
    content_without = call_deepSeek(
        f"{system_prompt_base}\n\n## 故事框架约束\n{framework_without}",
        user_task,
    )
    print(f"生成完成，长度: {len(content_without)} 字")

    print("\n正在生成【有画像】版本...")
    content_with = call_deepSeek(
        f"{system_prompt_base}\n\n## 故事框架约束\n{framework_with}",
        user_task,
    )
    print(f"生成完成，长度: {len(content_with)} 字")

    print("\n" + "-" * 80)
    print("【无画像版本】生成内容:")
    print("-" * 80)
    print(content_without)

    print("\n" + "-" * 80)
    print("【有画像版本】生成内容:")
    print("-" * 80)
    print(content_with)

    print("\n" + "-" * 80)
    print("【对比分析】")
    print("-" * 80)

    def count_short_sentences(text: str) -> int:
        import re
        sentences = re.split(r'[。！？]', text)
        return sum(1 for s in sentences if s.strip() and len(s.strip()) <= 10)

    def count_action_verbs(text: str) -> int:
        verbs = ["拔", "砍", "刺", "挥", "握", "踢", "抓", "推", "冲", "跳", "闪", "挡"]
        return sum(text.count(v) for v in verbs)

    short_without = count_short_sentences(content_without)
    short_with = count_short_sentences(content_with)
    action_without = count_action_verbs(content_without)
    action_with = count_action_verbs(content_with)

    print(f"\n短句数量（≤10字）:  无画像={short_without}  vs  有画像={short_with}  差异={short_with - short_without:+d}")
    print(f"动作动词数量:        无画像={action_without}  vs  有画像={action_with}  差异={action_with - action_without:+d}")
    print(f"生成字数:            无画像={len(content_without)}  vs  有画像={len(content_with)}")

    print("\n结论:")
    if short_with > short_without:
        print("  ✓ 有画像版本短句更多 — 符合画像描述的'大量使用短句'特征")
    else:
        print("  ✗ 有画像版本短句未增加 — 画像风格未生效")

    if action_with > action_without:
        print("  ✓ 有画像版本动作动词更多 — 符合画像描述的'用行动代替形容'特征")
    else:
        print("  ✗ 有画像版本动作动词未增加 — 画像风格未生效")


def main():
    parser = argparse.ArgumentParser(description="作者画像引用效果对比测试")
    parser.add_argument("--generate", action="store_true", help="调用 DeepSeek API 生成对比内容")
    args = parser.parse_args()

    print("=" * 80)
    print("作者画像引用效果对比测试")
    print("=" * 80)

    test_extract_functions()
    test_prompt_diff()

    if args.generate:
        test_generation_comparison()
    else:
        print("\n" + "=" * 80)
        print("提示：添加 --generate 参数可调用 DeepSeek API 生成实际内容对比")
        print("  python tests/test_author_style_effect.py --generate")
        print("=" * 80)

    print("\n" + "=" * 80)
    print("测试完成")
    print("=" * 80)


if __name__ == "__main__":
    main()
