#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
起点签约级正文质量验证脚本

验证由 expand_chapter_to_content (框架直出管道) 生成的章节正文质量。
覆盖字数铁律、场景经济性、对话铁律、章末钩子、AI写作禁令、禁用词/句式等全部维度。

用法:
  # 交互式选择故事 → 章节
  python backend/tests/test_chapter_quality.py

  # 指定故事和章节（直接生成并评测）
  python backend/tests/test_chapter_quality.py --story-id 5 --chapter 3

  # 只评测已有正文（不调用 DeepSeek API）
  python backend/tests/test_chapter_quality.py --story-id 5 --chapter 3 --review-only

  # 跳过 DeepSeek API 调用（使用模拟正文做格式验证）
  python backend/tests/test_chapter_quality.py --story-id 5 --chapter 3 --dry-run
"""

import argparse
import json
import os
import re
import sys
import traceback
from collections import Counter

# ── 项目路径 ──────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/manga_novel")

# 数据库导入在函数内按需进行（避免 --dry-run 不必要的连接）


# ── AI写作禁用词表（from banned-words.md + anti-ai-writing.md） ──
# 一级禁用词（出现即标记）
BANNED_WORDS_TIER1 = {
    # 情态类
    "仿佛", "犹如", "宛若", "如同",
    "一丝", "一抹", "些许", "几分", "隐约",
    # 动作类
    "深吸一口气", "缓缓", "不禁", "微微", "轻轻", "淡淡",
    # 表情类
    "眼中闪过", "嘴角勾起", "眉头微皱", "眉眼低垂", "瞳孔微缩",
    # 心理类
    "心中一动", "心头一震", "心下了然", "心中暗道", "心底泛起", "不由得",
    # 判断类
    "不容置疑", "不容置喙", "不易察觉", "显而易见", "毫无疑问", "不可否认",
    # 形容类
    "闪烁着光芒", "狡黠", "深邃", "凛冽", "冰冷",
    # 过渡类
    "不由自主", "情不自禁", "自然而然",
}

# 一级禁用句式（正则）
BANNED_PATTERNS_TIER1 = [
    (r"不是.+，[而]?.+是", "「不是A，而是B」否定-肯定句式"),
    (r"，带着[一这]", "「，带着XX」万能状语"),
    (r"声音不大[，却]", "「声音不大，却带着……」AI声音描写"),
    (r"仿佛[^。]*一般", "「仿佛……一般」文言腔"),
]

# 二级禁用句式
BANNED_PATTERNS_TIER2 = [
    (r"他[她]感到", "「他/她感到」告知式情绪"),
    (r"他[她]意识到", "「他/她意识到」告知式认知"),
    (r"他[她]终于明白", "「他/她终于明白」总结句式"),
    (r"他[她]这才意识到", "「他/她这才意识到」总结句式"),
    (r"此刻，", "「此刻，」升华句式"),
    (r"一切.*都", "「一切……都」总结句式"),
    (r"原来", "「原来」总结句式（语境敏感）"),
    (r"心中涌起[一那]", "「心中涌起XX」模板化心理"),
    (r"眼中闪过一丝", "「眼中闪过一丝XX」模板化"),
    (r"嘴角勾起一抹", "「嘴角勾起一抹XX」模板化"),
    (r"他不知道的是", "「他不知道的是」预告句式"),
    (r"注[定]无人", "升华式感叹"),
    (r"[就这]一[夜刻天]，", "「这一夜/这一刻/这一天」升华句式"),
]

# 破折号/省略号检测
DASH_PATTERN = re.compile(r"——|—{1,2}|\.{2,}")


# ── 质量评审函数 ──────────────────────────────────────────────

def check_word_count(text: str) -> dict:
    """字数铁律检查"""
    # 只算中文字符和标点，不计空格/换行
    clean = re.sub(r"\s+", "", text)
    chinese_chars = len([c for c in clean if "\u4e00" <= c <= "\u9fff"])
    total_chars = len(clean)
    verdict = "PASS"
    issues = []
    if total_chars > 3000:
        verdict = "FAIL"
        issues.append(f"超出字数上限 3000（实际 {total_chars}）")
    elif total_chars > 2500:
        verdict = "WARN"
        issues.append(f"超过目标范围 2000-2500（实际 {total_chars}），接近红线但仍可接受")
    elif total_chars < 1700:
        verdict = "FAIL"
        issues.append(f"低于最低字数 1700（实际 {total_chars}），信息密度不足")
    elif total_chars < 2000:
        verdict = "WARN"
        issues.append(f"低于目标下限 2000（实际 {total_chars}）")
    else:
        issues.append(f"字数在目标范围 2000-2500 内（实际 {total_chars}）")

    return {
        "维度": "字数铁律",
        "结果": verdict,
        "总字符数": total_chars,
        "中文字数": chinese_chars,
        "问题": issues,
    }


def check_chapter_hook(text: str) -> dict:
    """章末钩子检查"""
    lines = text.strip().split("\n")
    tail = ""
    # 取最后300字
    for line in reversed(lines):
        tail = line + tail
        if len(tail) >= 300:
            break

    # 检查钩子类型
    hook_found = False
    hook_type = ""
    hook_evidence = ""

    # 信息差揭示
    if re.search(r"[原来竟然居然其实]", tail):
        hook_found = True
        hook_type = "信息差揭示"

    # 冲突升级
    if re.search(r"[突然猛然忽然骤]", tail) and re.search(r"[冲杀打怒吼]", tail):
        hook_found = True
        hook_type = "冲突升级"

    # 角色面临抉择
    if re.search(r"[怎么办选抉择决定]|要么.*要么|还是", tail):
        hook_found = True
        hook_type = "角色面临抉择"

    # 意外出现
    if re.search(r"[出现来了现露]|出现|来了", tail[:100]):
        hook_found = True
        hook_type = "意外出现"

    # 禁用的结尾类型
    forbidden_endings = []
    if re.search(r"[他她]终于明白", tail):
        forbidden_endings.append("总结升华——「他终于明白」")
    if re.search(r"他不知道的是|更大的[风浪风暴]", tail):
        forbidden_endings.append("空泛预告——「他不知道的是」")
    if re.search(r"人生[就这]是|这[一就]是[人生命运]", tail):
        forbidden_endings.append("哲理收尾——「人生就是这样」")
    if re.search(r"这一[夜刻]，[注定必]", tail):
        forbidden_endings.append("升华式感叹——「这一夜，注定」")

    issues = []
    if hook_found:
        issues.append(f"✓ 章末含钩子：{hook_type}（{tail[:80]}...）")
    else:
        issues.append('⚠ 章末未检测到明确钩子，建议检查最后300字是否制造了"点击下一章"的欲望')

    if forbidden_endings:
        issues.append(f"✗ 禁用结尾类型：{'; '.join(forbidden_endings)}")

    verdict = "WARN" if not hook_found else ("FAIL" if forbidden_endings else "PASS")

    return {
        "维度": "章末钩子",
        "结果": verdict,
        "钩子类型": hook_type or "未检测到",
        "最后300字": tail[:300],
        "问题": issues,
    }


def check_banned_words(text: str) -> dict:
    """禁用词扫描"""
    violations = []
    for word in BANNED_WORDS_TIER1:
        count = text.count(word)
        if count > 0:
            # 找上下文
            for m in re.finditer(re.escape(word), text):
                start = max(0, m.start() - 20)
                end = min(len(text), m.end() + 20)
                context = text[start:end].replace("\n", " ")
                violations.append({
                    "词": word,
                    "次数": count,
                    "上下文": f"...{context}...",
                })
                break  # 一个词只记一次上下文

    issues = []
    if violations:
        for v in violations:
            issues.append(f"✗ 禁用词「{v['词']}」出现 {v['次数']} 次 → ...{v['上下文']}...")
    else:
        issues.append("✓ 未检测到一级禁用词")

    return {
        "维度": "禁用词检测",
        "结果": "FAIL" if violations else "PASS",
        "违规数": len(violations),
        "问题": issues,
    }


def check_banned_patterns(text: str) -> dict:
    """禁用句式检测"""
    violations = []
    for pattern, name in BANNED_PATTERNS_TIER1 + BANNED_PATTERNS_TIER2:
        matches = list(re.finditer(pattern, text))
        if matches:
            for m in matches[:2]:  # 最多取2处
                start = max(0, m.start() - 15)
                end = min(len(text), m.end() + 15)
                context = text[start:end].replace("\n", " ")
                violations.append({
                    "句式": name,
                    "次数": len(matches),
                    "上下文": f"...{context}...",
                })
                break

    issues = []
    if violations:
        for v in violations:
            issues.append(f"✗ {v['句式']} 出现 {v['次数']} 次 → {v['上下文']}")
    else:
        issues.append("✓ 未检测到一级/二级禁用句式")

    return {
        "维度": "禁用句式检测",
        "结果": "FAIL" if violations else "PASS",
        "违规数": len(violations),
        "问题": issues,
    }


def check_dash_ellipsis(text: str) -> dict:
    """破折号/省略号检测"""
    dashes = DASH_PATTERN.findall(text)
    count = len(dashes)
    issues = []
    if count > 0:
        issues.append(f"✗ 正文中含 {count} 处破折号或省略号（正文禁止使用）")
    else:
        issues.append("✓ 未检测到破折号或省略号")

    # 检查双连字符
    double_hyphen = text.count("--")
    if double_hyphen:
        issues.append(f"✗ 含 {double_hyphen} 处双连字符 '--'")

    return {
        "维度": "标点规范",
        "结果": "FAIL" if count > 0 or double_hyphen else "PASS",
        "违规数": count + double_hyphen,
        "问题": issues,
    }


def check_scene_economy(text: str) -> dict:
    """场景经济性检查——检测是否有超过400字无变化的段落"""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    issues = []
    long_static = 0
    for i, para in enumerate(paragraphs):
        if len(para) > 400:
            # 粗略检测：长段落中是否有"说/道/问/答/笑/怒/吼"等推进信号
            if not re.search(r"[说问道答笑怒吼站走跑看]" , para):
                long_static += 1
                preview = para[:80].replace("\n", " ")
                issues.append(f"⚠ 第{i+1}段 {len(para)}字 无剧情推进信号：{preview}...")

    if not issues:
        issues.append("✓ 段落长度和推进信号正常")

    return {
        "维度": "场景经济性",
        "结果": "FAIL" if long_static >= 3 else "WARN" if long_static > 0 else "PASS",
        "超长无推进段落": long_static,
        "问题": issues,
    }


def check_dialogue_quality(text: str) -> dict:
    """对话质量检查"""
    # 提取对话行
    dialogue_lines = re.findall(r'"[^"]*"|「[^」]*」', text)
    total_chars = len(text.replace(" ", "").replace("\n", ""))

    issues = []

    # 1. 对话比例
    dialogue_chars = sum(len(l) for l in dialogue_lines)
    dialogue_ratio = dialogue_chars / max(total_chars, 1)
    if dialogue_ratio < 0.2:
        issues.append(f"⚠ 对话占比 {dialogue_ratio:.0%}，偏低（建议 20-50%）")
    elif dialogue_ratio > 0.6:
        issues.append(f"⚠ 对话占比 {dialogue_ratio:.0%}，偏高（建议 20-50%）")

    # 2. 无信息量对话
    empty_dialogues = []
    for line in dialogue_lines:
        cleaned = line.strip('"「」').strip()
        if cleaned in ("嗯", "啊", "好的", "哦", "嗯嗯", "好吧"):
            empty_dialogues.append(cleaned)
    if empty_dialogues:
        issues.append(f"⚠ 无信息量对话出现 {len(empty_dialogues)} 次（「{', '.join(set(empty_dialogues))}」）")

    # 3. 连续纯对话检测
    pure_dialogue_streaks = 0
    current_streak = 0
    for para in text.split("\n"):
        if re.match(r'^\s*["「]', para):
            current_streak += 1
        else:
            if current_streak >= 5:
                pure_dialogue_streaks += 1
            current_streak = 0
    if pure_dialogue_streaks > 0:
        issues.append(f"⚠ 检测到 {pure_dialogue_streaks} 处连续5句以上纯对话")

    if not issues:
        issues.append("✓ 对话质量正常")

    return {
        "维度": "对话质量",
        "结果": "WARN" if issues and issues[0].startswith("⚠") else "PASS",
        "对话占比": f"{dialogue_ratio:.0%}",
        "问题": issues,
    }


def check_opening(text: str) -> dict:
    """开篇质量检查"""
    opening = text[:500]
    issues = []

    # 1. 不从天气/风景/日常开始
    weather_starters = [
        r"^[这天]" , r"^阳光", r"^窗外", r"^天空", r"^风[吹拂]",
        r"^清晨", r"^早上", r"^午后", r"^傍晚", r"^夜里",
        r"^这是一个", r"^那是",
    ]
    for pat in weather_starters:
        if re.match(pat, opening):
            issues.append(f"⚠ 开篇从天气/风景/日常时间开始")

    # 2. 前100字有事件
    first_100 = opening[:100]
    events = re.findall(r"[了。！？]", first_100)
    if len(events) < 2:
        issues.append("⚠ 前100字事件密度可能偏低（句号/感叹号少于2个）")

    # 3. 主角快速出场
    has_pronoun = re.search(r"[他她]", first_100)
    if not has_pronoun:
        issues.append("⚠ 前100字未出现角色（他/她）")

    if not issues:
        issues.append("✓ 开篇质量正常")

    return {
        "维度": "开篇质量",
        "结果": "WARN" if issues and issues[0].startswith("⚠") else "PASS",
        "前500字": opening[:200] + "..." if len(opening) > 200 else opening,
        "问题": issues,
    }


def check_sentence_variety(text: str) -> dict:
    """句式多样性检查"""
    sentences = re.split(r"[。！？\n]", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 5]

    if not sentences:
        return {"维度": "句式多样性", "结果": "SKIP", "问题": ["无足够句子分析"]}

    # 句长分布
    lengths = [len(s) for s in sentences]
    avg_len = sum(lengths) / len(lengths)
    long_sents = sum(1 for l in lengths if l > 50)
    short_sents = sum(1 for l in lengths if l < 10)

    issues = []
    if avg_len > 30:
        issues.append(f"⚠ 平均句长 {avg_len:.0f} 字（偏高，建议 15-25）")
    elif avg_len < 12:
        issues.append(f"⚠ 平均句长 {avg_len:.0f} 字（偏低，可能过于碎片化）")
    else:
        issues.append(f"✓ 平均句长 {avg_len:.0f} 字（适宜）")

    if long_sents > len(sentences) * 0.3:
        issues.append(f"⚠ 长句（>50字）占 {long_sents}/{len(sentences)}，可能阅读卡顿")
    if short_sents > len(sentences) * 0.4:
        issues.append(f"⚠ 短句（<10字）占 {short_sents}/{len(sentences)}，可能碎片化")

    # 最毒禁用句式——"不是A而是B"单独检查
    not_ab = list(re.finditer(r"不是.，[而]?.是", text))
    if not_ab:
        for m in not_ab[:2]:
            ctx = text[max(0,m.start()-10):min(len(text),m.end()+10)].replace("\n","")
            issues.append(f"✗ ★★★★★「不是A而是B」句式 → {ctx}")

    return {
        "维度": "句式多样性",
        "结果": "FAIL" if not_ab else "WARN" if avg_len > 30 or avg_len < 12 else "PASS",
        "平均句长": f"{avg_len:.1f}",
        "问题": issues,
    }


def check_adverb_density(text: str) -> dict:
    """弱化副词密度检测"""
    adverbs = {
        "微微": 0, "淡淡": 0, "缓缓": 0, "轻轻": 0,
    }
    for word in adverbs:
        adverbs[word] = text.count(word)

    total = sum(adverbs.values())
    total_chars = len(text.replace(" ", "").replace("\n", ""))
    per_1000 = total / max(total_chars, 1) * 1000

    issues = []
    if per_1000 > 3:
        details = ", ".join(f"「{w}」{c}次" for w, c in adverbs.items() if c > 0)
        issues.append(f"✗ 弱化副词密度 {per_1000:.1f}/千字（阈值 3/千字）：{details}")
    elif per_1000 > 1:
        details = ", ".join(f"「{w}」{c}次" for w, c in adverbs.items() if c > 0)
        issues.append(f"⚠ 弱化副词密度 {per_1000:.1f}/千字：{details}")
    else:
        issues.append(f"✓ 弱化副词密度 {per_1000:.1f}/千字（良好）")

    return {
        "维度": "弱化副词密度",
        "结果": "FAIL" if per_1000 > 3 else "WARN" if per_1000 > 1 else "PASS",
        "每千字": f"{per_1000:.1f}",
        "详情": adverbs,
        "问题": issues,
    }


def check_writing_quality(text: str) -> dict:
    """综合写作质量检查"""
    # 检查章节尾句是否有总结升华
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    last_3 = "\n".join(lines[-3:]) if len(lines) >= 3 else text[-300:]

    issues = []

    # 检测总结式结尾
    summary_signals = [
        (r"终于明白了", "总结式明白句"),
        (r"这就是[人生命运]", "哲理式结论"),
        (r"一切都是", "全称总结"),
        (r"从今以后", "展望式总结"),
        (r"他知道[了，这]", "他知道式总结"),
        (r"她明白[了，这]", "她明白式总结"),
    ]
    for sig_pat, sig_name in summary_signals:
        if re.search(sig_pat, last_3):
            issues.append(f"⚠ 结尾含「{sig_name}」，有总结升华风险")

    # 检测大段心理描写
    psycho_sections = re.findall(r'[^。！？\n]{100,}[。！？]', text)
    psycho_long = [s for s in psycho_sections if not re.search(r'["「]', s) and len(s) > 120]
    if psycho_long:
        issues.append(f"⚠ 检测到 {len(psycho_long)} 处过长无对话段落（>120字），可能为大段心理/描写")

    if not issues:
        issues.append("✓ 综合写作质量良好")

    return {
        "维度": "综合写作质量",
        "结果": "WARN" if issues else "PASS",
        "问题": issues,
    }


# ── 主评测函数 ──────────────────────────────────────────────

def run_quality_checks(text: str) -> dict:
    """运行全部质量检查，返回综合报告"""
    if not text or not text.strip():
        return {"综合结果": "SKIP", "错误": "正文为空，无法评测"}

    checks = [
        check_word_count(text),
        check_chapter_hook(text),
        check_banned_words(text),
        check_banned_patterns(text),
        check_dash_ellipsis(text),
        check_scene_economy(text),
        check_dialogue_quality(text),
        check_opening(text),
        check_sentence_variety(text),
        check_adverb_density(text),
        check_writing_quality(text),
    ]

    # 统计
    total = len(checks)
    passed = sum(1 for c in checks if c["结果"] == "PASS")
    warned = sum(1 for c in checks if c["结果"] == "WARN")
    failed = sum(1 for c in checks if c["结果"] == "FAIL")

    overall = "PASS"
    if failed > 0:
        overall = "FAIL"
    elif warned > len(checks) * 0.5:
        overall = "WARN"

    return {
        "综合结果": overall,
        "通过": passed,
        "警告": warned,
        "失败": failed,
        "总计": total,
        "通过率": f"{passed}/{total}",
        "逐项评测": checks,
        "原文": text,
    }


def print_report(report: dict, verbose: bool = True):
    """格式化输出评测报告"""
    print("=" * 70)
    print("             起 点 签 约 级 正 文 质 量 评 测 报 告")
    print("=" * 70)

    # 综合结果
    overall = report["综合结果"]
    if overall == "PASS":
        status_str = "✅ 通过"
    elif overall == "WARN":
        status_str = "⚠️ 警告"
    elif overall == "FAIL":
        status_str = "❌ 未通过"
    else:
        status_str = "⏭️ 跳过"

    print(f"\n综合评审结果：{status_str}")
    print(f"通过 {report['通过']}/{report['总计']} | "
          f"警告 {report['警告']} | 失败 {report['失败']}")
    print()

    # 正文统计
    text = report.get("原文", "")
    if text:
        lines = text.strip().split("\n")
        total_chars = len(text.replace(" ", "").replace("\n", ""))
        chinese_chars = len([c for c in text if "\u4e00" <= c <= "\u9fff"])
        paragraphs = [p for p in text.split("\n\n") if p.strip()]
        print(f"📊 正文统计：{total_chars} 字符 | {chinese_chars} 中文字 | "
              f"{len(lines)} 行 | {len(paragraphs)} 段")

    print()
    print("-" * 70)

    # 逐项报告
    for check in report["逐项评测"]:
        dim = check["维度"]
        result = check["结果"]
        badge = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "SKIP": "⏭️"}.get(result, "❓")
        print(f"\n{badge} {dim}：{result}")

        # 显示关键数据
        for key, val in check.items():
            if key in ("维度", "结果", "问题", "原文", "前500字", "最后300字"):
                continue
            if isinstance(val, dict):
                print(f"   {key}: {json.dumps(val, ensure_ascii=False)}")
            else:
                print(f"   {key}: {val}")

        for issue in check["问题"]:
            print(f"   {issue}")

    print()
    print("=" * 70)
    print(f"最终结论：{status_str}")
    if overall == "PASS":
        print("🎉 正文质量达到起点签约级标准")
    elif overall == "WARN":
        print("📝 正文基本合格，建议按警告项精修后发布")
    else:
        print("🔴 正文未通过起点签约级审核，请按失败项逐条修改")
    print("=" * 70)


# ── 正文生成（模拟 generate_chapter_content 流程） ──────────

async def generate_and_test_chapter(story_id: int, chapter_number: int,
                                    instruction: str = "",
                                    review_only: bool = False,
                                    dry_run: bool = False):
    """模拟 generate_chapter_content 流程生成正文并评测。"""
    print(f"\n📖 准备评测 Story ID={story_id}, Chapter={chapter_number}")

    if dry_run:
        print("   🏃 模拟模式（不连接数据库）：生成带各种违规特征的模拟正文用于格式验证\n")
        mock_text = (
            "这是一个阳光明媚的早晨，他深吸一口气，心中不由得涌起一股暖流。"
            "他缓缓地走在街上，眼中闪过一丝悲伤。仿佛整个世界都在与他作对一般。"
            "不是他不知道该怎么做，而是他根本无法选择。"
        ) * 30
        print_report(run_quality_checks(mock_text))
        return

    from database import SessionLocal
    from models import Story, Chapter

    db = SessionLocal()
    try:
        story = db.query(Story).filter(Story.id == story_id).first()
        if not story:
            print(f"❌ 故事 ID={story_id} 不存在")
            return

        print(f"   故事：{story.title} (ID={story.id}, owner={story.owner_user_id})")

        outline = story.outline if isinstance(story.outline, dict) else {}
        outline_chapters = list(outline.get("chapters", []) if isinstance(outline.get("chapters"), list) else [])
        if not outline_chapters:
            for act in outline.get("three_acts", []):
                if isinstance(act, dict):
                    outline_chapters.extend(act.get("chapters", []) if isinstance(act.get("chapters"), list) else [])

        chapter_info = next(
            (dict(ch) for ch in outline_chapters if isinstance(ch, dict) and ch.get("chapter_number") == chapter_number),
            None,
        )
        if chapter_info:
            print(f"   大纲中有第{chapter_number}章规划")
            for field in ["goal", "conflict", "hook", "payoff", "highlight"]:
                val = str(chapter_info.get(field) or "").strip()
                print(f"     {field}: {val[:80] if val else '⚠ 空'}")
        else:
            print(f"   ⚠ 大纲中无第{chapter_number}章规划，尝试直接生成")
            chapter_info = {"chapter_number": chapter_number, "title": f"第{chapter_number}章"}

        db_chapter = (
            db.query(Chapter)
            .filter(Chapter.story_id == story_id, Chapter.chapter_number == chapter_number)
            .first()
        )
        existing_content = db_chapter.novel_content if db_chapter and db_chapter.novel_content else None
        if existing_content:
            print(f"   DB 中已有正文：{len(existing_content)} 字符")

        if review_only:
            if not existing_content:
                print("   ❌ DB 中无正文，无法评测（移除 --review-only 以调用 API）")
                return
            print("   🔍 评测模式：仅评测已有正文\n")
            print_report(run_quality_checks(existing_content))
            return

        if existing_content:
            novel_content = existing_content
            print("   🔍 使用 DB 中已有正文\n")
        else:
            print("   🚀 调用框架创作管道生成正文...（约10-30秒）\n")
            from services.agent_service import _build_story_context_dict
            from services.deepseek import DEEPSEEK_API_KEY, expand_chapter_to_content
            from services.prompt_template import get_effective_prompt

            story_context = _build_story_context_dict(story, user_instruction=instruction)
            story_context["current_chapter"] = {key: value for key, value in chapter_info.items() if value not in (None, "", [], {})}
            if instruction:
                chapter_info["user_instruction"] = instruction

            previous_chapter_summary = ""
            if chapter_number > 1:
                prev_ch = (
                    db.query(Chapter)
                    .filter(
                        Chapter.story_id == story_id,
                        Chapter.chapter_number < chapter_number,
                        Chapter.novel_content.isnot(None),
                        Chapter.status.in_(["completed", "draft"]),
                    )
                    .order_by(Chapter.chapter_number.desc())
                    .first()
                )
                if prev_ch and prev_ch.novel_content:
                    ending = prev_ch.novel_content[-800:]
                    prev_title = prev_ch.title or f"第{prev_ch.chapter_number}章"
                    previous_chapter_summary = f"上一章《第{prev_ch.chapter_number}章：{prev_title}》结尾：\n{ending}"
                    print(f"   上章桥接：第{prev_ch.chapter_number}章 结尾{len(ending)}字符")

            api_key = DEEPSEEK_API_KEY or os.environ.get("DEEPSEEK_API_KEY")
            if not api_key:
                env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
                if os.path.exists(env_path):
                    with open(env_path, encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith("DEEPSEEK_API_KEY="):
                                api_key = line.split("=", 1)[1].strip().strip("\"'")
                                break
            if not api_key:
                print("⚠ 未配置 DeepSeek API Key")
                print("  请设置环境变量 DEEPSEEK_API_KEY 或修改 backend/.env")
                return

            try:
                novel_content = await expand_chapter_to_content(
                    story_context=story_context,
                    chapter_info=chapter_info,
                    api_key=api_key or None,
                    previous_chapter_summary=previous_chapter_summary,
                    system_prompt=get_effective_prompt(story_id, "chapter", db) or None,
                    db=db,
                )
            except Exception as e:
                print(f"❌ 生成失败：{e}")
                traceback.print_exc()
                return

            if not novel_content or not novel_content.strip():
                print("❌ 生成内容为空")
                return
            print(f"   ✅ 正文生成完成：{len(novel_content)} 字符\n")

        print_report(run_quality_checks(novel_content))
    finally:
        db.close()


# ── CLI 入口 ────────────────────────────────────────────────

def list_stories():
    """列出所有可用的故事"""
    from database import SessionLocal
    from models import Story, Chapter
    db = SessionLocal()
    try:
        stories = db.query(Story).order_by(Story.id).all()
        print("\n📚 可用故事列表：")
        print("-" * 60)
        for s in stories:
            outline = s.outline if isinstance(s.outline, dict) else {}
            chapters = outline.get("chapters", []) if isinstance(outline, dict) else []
            db_chapters = db.query(Chapter).filter(Chapter.story_id == s.id).count()
            print(f"  ID={s.id:3d} | {s.title[:40]:40s} | 大纲章节={len(chapters):2d} | DB章节={db_chapters:2d}")
        print("-" * 60)
        return stories
    finally:
        db.close()


def interactive_select():
    """交互式选择故事和章节"""
    stories = list_stories()
    if not stories:
        print("❌ 数据库中无故事")
        return None, None

    print()
    try:
        story_id = int(input("请选择故事 ID: ").strip())
    except (ValueError, EOFError):
        return None, None

    story = next((s for s in stories if s.id == story_id), None)
    if not story:
        print(f"❌ 故事 ID={story_id} 不存在")
        return None, None

    outline = story.outline if isinstance(story.outline, dict) else {}
    chapters = outline.get("chapters", []) if isinstance(outline, dict) else []

    print(f"\n📖 {story.title} 的大纲章节：")
    for ch in chapters[:20]:
        num = ch.get("chapter_number", "?")
        title = ch.get("title", "无标题")
        has_goal = "✓" if str(ch.get("goal") or "").strip() else "✗"
        has_conflict = "✓" if str(ch.get("conflict") or "").strip() else "✗"
        has_hook = "✓" if str(ch.get("hook") or "").strip() else "✗"
        print(f"  第{num}章 {title[:30]:30s} | goal={has_goal} conflict={has_conflict} hook={has_hook}")

    print()
    try:
        chapter_num = int(input(f"请选择章节号 (1-{len(chapters) or 10}): ").strip())
    except (ValueError, EOFError):
        return None, None

    return story_id, chapter_num


def main():
    parser = argparse.ArgumentParser(
        description="起点签约级正文质量验证脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  %(prog)s                                    # 交互式选择
  %(prog)s --story-id 5 --chapter 3           # 直接生成并评测
  %(prog)s --story-id 5 --chapter 3 --review-only  # 只评测已有正文
  %(prog)s --story-id 5 --chapter 3 --dry-run      # 模拟运行

环境变量:
  DEEPSEEK_API_KEY=sk-xxx  %(prog)s ...
        """,
    )
    parser.add_argument("--story-id", type=int, help="故事 ID")
    parser.add_argument("--chapter", type=int, help="章节号")
    parser.add_argument("--instruction", type=str, default="", help="额外写作指令")
    parser.add_argument("--review-only", action="store_true", help="仅评测已有正文，不调用 API")
    parser.add_argument("--dry-run", action="store_true", help="模拟运行（使用模拟正文）")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")

    args = parser.parse_args()

    if args.story_id and args.chapter:
        story_id = args.story_id
        chapter_num = args.chapter
    elif args.story_id or args.chapter:
        print("❌ --story-id 和 --chapter 必须同时提供")
        return
    elif args.dry_run:
        # dry-run 模式不连接数据库，使用默认值
        story_id, chapter_num = 0, 1
    else:
        # 交互模式
        result = interactive_select()
        if result[0] is None:
            return
        story_id, chapter_num = result

    import asyncio
    asyncio.run(generate_and_test_chapter(
        story_id=story_id,
        chapter_number=chapter_num,
        instruction=args.instruction,
        review_only=args.review_only,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
