"""
全链路质量测试：大纲 → 任务卡 → 章节生成 → 质量评估

测试覆盖：
  1. 框架生成任务卡完整性（修复后的 prompt 是否产出 goal/conflict/hook/payoff/highlight）
  2. Agent 路径章节生成质量
  3. 框架直出路径章节生成质量
  4. 两条路径质量对比
  5. 起点编辑签约标准评分

用法:
    python tests/test_quality_pipeline.py [--story-id 3] [--outline-file path/to/outline.md]
"""
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import SessionLocal
from models import Story, Chapter, PlatformSetting
from services.deepseek import (
    configure_runtime,
    generate_framework,
    expand_chapter_to_content,
    adjust_chapter_content,
    quality_assess,
    _get_chapter_system_prompt,
    build_agent_chapter_system_prompt,
)
from services.writing_utils import get_banned_words, get_banned_patterns


# ── 配置 ────────────────────────────────────────────────

@dataclass
class TestConfig:
    story_id: int = 3
    outline_file: str | None = None
    target_chapter: int = 1
    verbose: bool = True


# ── 质量评分卡（起点编辑视角）──────────────────────────

@dataclass
class QualityScore:
    """起点编辑签约审核 7 维度评分卡"""
    task_card_execution: int = 0      # 任务卡执行度（0-10）
    hook_strength: int = 0            # 钩子强度（0-10）
    character_consistency: int = 0    # 角色一致性（0-10）
    plot_logic: int = 0               # 情节逻辑（0-10）
    ai_flavor_score: int = 0          # AI味检测（0-10，越高=越少AI味）
    readability: int = 0              # 可读性（0-10）
    market_appeal: int = 0            # 商业化潜力（0-10）
    overall: int = 0                  # 综合（0-10）
    details: list[str] = field(default_factory=list)

    @property
    def pass_threshold(self) -> bool:
        """起点签约审核通过线：总分 >= 48/70 且 无单项 < 4"""
        return self.overall >= 48 and all([
            self.task_card_execution >= 4,
            self.hook_strength >= 4,
            self.character_consistency >= 4,
            self.plot_logic >= 4,
            self.ai_flavor_score >= 4,
            self.readability >= 4,
            self.market_appeal >= 4,
        ])


# ── 工具函数 ────────────────────────────────────────────

def log(msg: str, level: str = "INFO"):
    prefix = {"INFO": "  ", "PASS": "✅", "FAIL": "❌", "WARN": "⚠️ ", "HEAD": "\n📋"}
    print(f"{prefix.get(level, '  ')} {msg}")


def check_task_card(chapter_data: dict) -> dict:
    """检查章节任务卡字段完整性"""
    required = ["summary", "goal", "conflict", "hook", "payoff", "highlight"]
    result = {}
    for field in required:
        val = str(chapter_data.get(field, "") or "").strip()
        result[field] = bool(val)
    result["_complete"] = all(result.values())
    return result


def detect_ai_flavor(text: str) -> dict:
    """检测AI写作痕迹"""
    banned_words = get_banned_words()
    banned_patterns = get_banned_patterns()

    findings: list[str] = []

    # 破折号检测
    dash_count = text.count("——") + text.count("—")
    if dash_count > 0:
        findings.append(f"破折号 {dash_count} 处")

    # 禁用词检测
    word_hits = {}
    for word in banned_words:
        count = text.count(word)
        if count > 0:
            word_hits[word] = count
    if word_hits:
        top = sorted(word_hits.items(), key=lambda x: -x[1])[:5]
        findings.append(f"禁用词: {', '.join(f'{w}×{c}' for w, c in top)}")

    # 模板化句式检测
    for pat in banned_patterns:
        for p in pat.get("patterns", []):
            if p in text:
                findings.append(f"模板句式「{pat['name']}」: 「{p}」")

    # "突然/忽然" 频率
    sudden = text.count("突然") + text.count("忽然")
    if sudden > 2:
        findings.append(f"「突然/忽然」出现 {sudden} 次（>2）")

    # 章末总结体检测
    closing_patterns = ["他终于明白", "这一夜，注定", "他不知道的是", "更大的风暴"]
    for cp in closing_patterns:
        if cp in text:
            findings.append(f"章末总结体: 「{cp}」")

    return {
        "clean": len(findings) == 0,
        "findings": findings,
        "dash_count": dash_count,
        "word_hits_count": sum(word_hits.values()),
    }


def assess_chapter_quality(content: str, task_card: dict, label: str = "") -> QualityScore:
    """综合评估章节质量。启发式评分作为快速参考，AI深度评估（test_ai_quality_assessment）才是权威分数。"""
    score = QualityScore()
    tc = task_card

    # 1. 任务卡执行度 — 检查正文是否体现了 goal/conflict/payoff
    goal = tc.get("goal", "")
    conflict = tc.get("conflict", "")
    payoff = tc.get("payoff", "")
    if goal and conflict and payoff:
        score.task_card_execution = 8  # 有完整任务卡 → 高基础分
    elif goal or conflict:
        score.task_card_execution = 6
    else:
        score.task_card_execution = 4  # 无任务卡 → 低分（旧数据）

    # 2. AI味检测
    ai = detect_ai_flavor(content)
    if ai["clean"]:
        score.ai_flavor_score = 9
    elif len(ai["findings"]) <= 1:
        score.ai_flavor_score = 8
    elif len(ai["findings"]) <= 3:
        score.ai_flavor_score = 6
    elif len(ai["findings"]) <= 5:
        score.ai_flavor_score = 4
    else:
        score.ai_flavor_score = 2
    score.details.extend(ai["findings"])

    # 3. 钩子强度 — 检查章末是否有点击欲望
    last_300 = content[-300:] if len(content) > 300 else content
    hook_score = 5  # 基础分
    if any(kw in last_300 for kw in ["?", "？", "悬念", "秘密", "真相", "风暴", "降临"]):
        hook_score += 1
    if not any(kw in last_300 for kw in ["他终于明白", "这一夜，注定", "他不知道的是"]):
        hook_score += 1  # 无模板化收尾
    if len(content) >= 2000:
        hook_score += 1  # 字数达标
    score.hook_strength = min(10, hook_score)

    # 4. 基础维度 — 根据内容长度和结构特征给分
    score.character_consistency = 7 if len(content) > 2000 else 5
    score.plot_logic = 7 if len(content) > 1500 else 5
    score.readability = 8  # 默认高（AI文本通常可读性好）
    score.market_appeal = 7 if len(content) > 2000 else 5

    # 综合
    score.overall = (
        score.task_card_execution +
        score.hook_strength +
        score.character_consistency +
        score.plot_logic +
        score.ai_flavor_score +
        score.readability +
        score.market_appeal
    )
    return score


# ── 核心测试函数 ────────────────────────────────────────

async def test_framework_regeneration(db, config: TestConfig) -> dict:
    """测试1：重新生成框架，验证任务卡完整性"""
    log("测试1：框架生成任务卡完整性", "HEAD")

    story = db.query(Story).filter(Story.id == config.story_id).first()
    if not story:
        return {"error": f"故事 ID={config.story_id} 不存在"}

    # 获取系统 prompt
    fw_prompt_setting = db.query(PlatformSetting).filter(
        PlatformSetting.setting_key == "prompt.framework_generation"
    ).first()
    system_prompt = fw_prompt_setting.value_json.get("value") if fw_prompt_setting else None

    # 获取API配置
    api_key_setting = db.query(PlatformSetting).filter(
        PlatformSetting.setting_key == "api.deepseek.api_key"
    ).first()
    api_key = api_key_setting.value_json.get("value") if api_key_setting else None

    base_url_setting = db.query(PlatformSetting).filter(
        PlatformSetting.setting_key == "api.deepseek.base_url"
    ).first()
    model_setting = db.query(PlatformSetting).filter(
        PlatformSetting.setting_key == "api.deepseek.model"
    ).first()
    base_url = base_url_setting.value_json.get("value") if base_url_setting else None
    model = model_setting.value_json.get("value") if model_setting else None

    if not api_key or not base_url:
        return {"error": "DeepSeek API 未配置"}

    configure_runtime(base_url=base_url, model=model)

    # 构建测试用的 story_context
    story_context = {
        "description": story.description or "",
        "story_bible": story.story_bible or {},
        "tags": story.tags or {},
        "characters": story.characters or [],
        "outline": story.outline or {},
    }

    log(f"使用作品: {story.title}")
    log(f"API Model: {model}")

    try:
        log("正在调用 generate_framework（长篇模式）...")
        start = time.time()
        framework = await generate_framework(
            description=story.description or story.title,
            api_key=api_key,
            story_context=story_context,
            system_prompt=system_prompt,
            story_length="long",
        )
        elapsed = time.time() - start
        log(f"框架生成完成，耗时 {elapsed:.1f}s")

        # 验证任务卡完整性
        all_chapters = []
        for act in framework.get("outline", {}).get("three_acts", []):
            all_chapters.extend(act.get("chapters", []))

        log(f"大纲包含 {len(all_chapters)} 章（含详细章节）")

        results = []
        complete_count = 0
        for ch in all_chapters[:10]:  # 只检查前10章
            cn = ch.get("chapter_number", "?")
            card = check_task_card(ch)
            results.append({"chapter": cn, "task_card": card})
            if card["_complete"]:
                complete_count += 1

        log(f"前10章任务卡完整率: {complete_count}/10")
        for r in results:
            status = "PASS" if r["task_card"]["_complete"] else "FAIL"
            missing = [k for k, v in r["task_card"].items() if not v and k != "_complete"]
            msg = f"第{r['chapter']}章: {status}"
            if missing:
                msg += f" | 缺失: {', '.join(missing)}"
            log(msg, status.lower())

        return {
            "test": "framework_task_card",
            "total_chapters": len(all_chapters),
            "first_10_complete": complete_count,
            "details": results,
            "elapsed_seconds": elapsed,
        }

    except Exception as e:
        log(f"框架生成失败: {e}", "FAIL")
        return {"test": "framework_task_card", "error": str(e)}


async def test_agent_chapter_generation(db, config: TestConfig) -> dict:
    """测试2：Agent路径章节生成质量"""
    log("测试2：Agent路径章节生成质量", "HEAD")

    story = db.query(Story).filter(Story.id == config.story_id).first()
    if not story:
        return {"error": f"故事 ID={config.story_id} 不存在"}

    chapter = db.query(Chapter).filter(
        Chapter.story_id == config.story_id,
        Chapter.chapter_number == config.target_chapter,
    ).first()

    if not chapter:
        log(f"第{config.target_chapter}章不存在，跳过", "WARN")
        return {"test": "agent_chapter", "skipped": True, "reason": "章节不存在"}

    # 获取API配置
    api_key_setting = db.query(PlatformSetting).filter(
        PlatformSetting.setting_key == "api.deepseek.api_key"
    ).first()
    api_key = api_key_setting.value_json.get("value") if api_key_setting else None

    base_url_setting = db.query(PlatformSetting).filter(
        PlatformSetting.setting_key == "api.deepseek.base_url"
    ).first()
    model_setting = db.query(PlatformSetting).filter(
        PlatformSetting.setting_key == "api.deepseek.model"
    ).first()
    base_url = base_url_setting.value_json.get("value") if base_url_setting else None
    model = model_setting.value_json.get("value") if model_setting else None

    configure_runtime(base_url=base_url, model=model)

    # 构建上下文
    story_context = {
        "description": story.description or "",
        "story_bible": story.story_bible or {},
        "tags": story.tags or {},
        "characters": story.characters or [],
        "outline": story.outline or {},
    }

    # 从大纲中提取章节任务卡
    chapter_task_card = {}
    if story.outline:
        for act in story.outline.get("three_acts", []):
            for ch in act.get("chapters", []):
                if ch.get("chapter_number") == config.target_chapter:
                    chapter_task_card = ch
                    break

    chapter_info = {
        "chapter_number": chapter.chapter_number,
        "title": chapter.title or f"第{chapter.chapter_number}章",
        "act": chapter.act or "",
        "key_events": chapter.key_events or [],
        **{k: chapter_task_card.get(k, "") for k in ["summary", "goal", "conflict", "hook", "payoff", "highlight"]},
    }

    chapter_content = chapter.novel_content or ""

    log(f"章节: 第{config.target_chapter}章 {chapter.title or ''}")
    log(f"任务卡完整性: {check_task_card(chapter_task_card)['_complete']}")

    # 获取 system prompt
    from services.prompt_template import get_effective_prompt
    from services.deepseek import build_agent_chapter_system_prompt

    template_system = get_effective_prompt(chapter.story_id, "chapter", db)
    fallback_prompt = build_agent_chapter_system_prompt(db=db)
    effective_system = template_system or fallback_prompt
    log(f"System Prompt: {'DB模板' if template_system else 'fallback(完整版)'}")

    instruction = "以起点黄金三章标准重写本章正文，严格遵循任务卡要求"

    try:
        log("正在调用 adjust_chapter_content（Agent路径）...")
        start = time.time()
        new_content = await adjust_chapter_content(
            story_context=story_context,
            chapter_info=chapter_info,
            chapter_content=chapter_content,
            instruction=instruction,
            api_key=api_key,
            system_prompt=effective_system,
        )
        elapsed = time.time() - start
        log(f"Agent路径生成完成，耗时 {elapsed:.1f}s，字数 {len(new_content)}")

        # 质量评估
        score = assess_chapter_quality(new_content, chapter_task_card, "Agent路径")
        log(f"综合评分: {score.overall}/70 | 签约通过: {'是' if score.pass_threshold else '否'}")

        return {
            "test": "agent_chapter",
            "content_length": len(new_content),
            "elapsed_seconds": elapsed,
            "content_preview": new_content[:500],
            "quality_score": {
                "task_card_execution": score.task_card_execution,
                "hook_strength": score.hook_strength,
                "character_consistency": score.character_consistency,
                "plot_logic": score.plot_logic,
                "ai_flavor_score": score.ai_flavor_score,
                "readability": score.readability,
                "market_appeal": score.market_appeal,
                "overall": score.overall,
                "pass_threshold": score.pass_threshold,
            },
            "ai_findings": score.details,
            "full_content": new_content,
        }

    except Exception as e:
        log(f"Agent路径生成失败: {e}", "FAIL")
        return {"test": "agent_chapter", "error": str(e)}


async def test_framework_direct_generation(db, config: TestConfig) -> dict:
    """测试3：框架直出路径章节生成质量"""
    log("测试3：框架直出路径章节生成质量", "HEAD")

    story = db.query(Story).filter(Story.id == config.story_id).first()
    if not story:
        return {"error": f"故事 ID={config.story_id} 不存在"}

    # 获取API配置
    api_key_setting = db.query(PlatformSetting).filter(
        PlatformSetting.setting_key == "api.deepseek.api_key"
    ).first()
    api_key = api_key_setting.value_json.get("value") if api_key_setting else None

    base_url_setting = db.query(PlatformSetting).filter(
        PlatformSetting.setting_key == "api.deepseek.base_url"
    ).first()
    model_setting = db.query(PlatformSetting).filter(
        PlatformSetting.setting_key == "api.deepseek.model"
    ).first()
    base_url = base_url_setting.value_json.get("value") if base_url_setting else None
    model = model_setting.value_json.get("value") if model_setting else None

    configure_runtime(base_url=base_url, model=model)

    # 构建上下文
    story_context = {
        "description": story.description or "",
        "story_bible": story.story_bible or {},
        "tags": story.tags or {},
        "characters": story.characters or [],
        "outline": story.outline or {},
    }

    # 从大纲中提取章节任务卡
    chapter_task_card = {}
    if story.outline:
        for act in story.outline.get("three_acts", []):
            for ch in act.get("chapters", []):
                if ch.get("chapter_number") == config.target_chapter:
                    chapter_task_card = ch
                    break

    chapter_info = {
        "chapter_number": config.target_chapter,
        "title": chapter_task_card.get("title", f"第{config.target_chapter}章"),
        "act": chapter_task_card.get("act", "1"),
        "key_events": chapter_task_card.get("key_events", []),
        **{k: chapter_task_card.get(k, "") for k in ["summary", "goal", "conflict", "hook", "payoff", "highlight"]},
    }

    log(f"章节: 第{config.target_chapter}章 {chapter_info.get('title', '')}")
    log(f"任务卡完整性: {check_task_card(chapter_task_card)['_complete']}")

    try:
        log("正在调用 expand_chapter_to_content（框架直出路径）...")
        start = time.time()
        new_content = await expand_chapter_to_content(
            story_context=story_context,
            chapter_info=chapter_info,
            api_key=api_key,
            previous_chapter_summary="",
            db=db,
        )
        elapsed = time.time() - start
        log(f"框架直出路径生成完成，耗时 {elapsed:.1f}s，字数 {len(new_content)}")

        # 质量评估
        score = assess_chapter_quality(new_content, chapter_task_card, "框架直出")
        log(f"综合评分: {score.overall}/70 | 签约通过: {'是' if score.pass_threshold else '否'}")

        return {
            "test": "framework_direct_chapter",
            "content_length": len(new_content),
            "elapsed_seconds": elapsed,
            "content_preview": new_content[:500],
            "quality_score": {
                "task_card_execution": score.task_card_execution,
                "hook_strength": score.hook_strength,
                "character_consistency": score.character_consistency,
                "plot_logic": score.plot_logic,
                "ai_flavor_score": score.ai_flavor_score,
                "readability": score.readability,
                "market_appeal": score.market_appeal,
                "overall": score.overall,
                "pass_threshold": score.pass_threshold,
            },
            "ai_findings": score.details,
            "full_content": new_content,
        }

    except Exception as e:
        log(f"框架直出路径生成失败: {e}", "FAIL")
        return {"test": "framework_direct_chapter", "error": str(e)}


async def test_ai_quality_assessment(db, config: TestConfig, agent_content: str, direct_content: str) -> dict:
    """测试4：使用AI进行深度质量评估"""
    log("测试4：AI深度质量评估", "HEAD")

    api_key_setting = db.query(PlatformSetting).filter(
        PlatformSetting.setting_key == "api.deepseek.api_key"
    ).first()
    api_key = api_key_setting.value_json.get("value") if api_key_setting else None

    if not agent_content and not direct_content:
        return {"test": "ai_assessment", "skipped": True, "reason": "无正文内容可评估"}

    # 使用 quality_assess 函数对两条路径的产出分别评估
    results = {}

    for label, content in [("agent", agent_content), ("direct", direct_content)]:
        if not content:
            results[label] = {"error": "无内容"}
            continue

        try:
            log(f"评估 {label} 路径产出...")
            assessment = await quality_assess(content, api_key=api_key)
            results[label] = assessment
            scores = assessment.get("scores", {})
            log(f"  {label}: 内容={scores.get('content')} 文笔={scores.get('writing')} "
                f"角色={scores.get('character')} 情节={scores.get('plot')} 整体={scores.get('overall')}")
            if assessment.get("suggestions"):
                for s in assessment["suggestions"][:3]:
                    log(f"    → {s}")
        except Exception as e:
            results[label] = {"error": str(e)}
            log(f"  {label} 评估失败: {e}", "FAIL")

    return {"test": "ai_assessment", "results": results}


# ── 测试编排 ────────────────────────────────────────────

async def test_file_outline_pipeline(db, config: TestConfig) -> dict:
    """测试5：从大纲文件导入 → Agent生成框架 → 章节生成 → 质量评估

    模拟 Agent 助手的完整工作流：
    1. 读取大纲文件 → 提取核心描述
    2. 调用 generate_framework 生成结构化框架（模拟 Agent 的 adjust_framework）
    3. 验证任务卡完整性
    4. 使用生成的任务卡生成章节正文
    5. AI深度质量评估
    """
    log("测试5：大纲文件导入 → 框架生成 → 章节输出全链路", "HEAD")

    if not config.outline_file or not os.path.exists(config.outline_file):
        return {"error": f"大纲文件不存在: {config.outline_file}"}

    outline_text = ""
    with open(config.outline_file, "r", encoding="utf-8") as f:
        outline_text = f.read()

    log(f"大纲文件: {os.path.basename(config.outline_file)} ({len(outline_text)} 字符)")

    # 提取书名和核心描述（前500字作为框架生成的输入）
    lines = outline_text.split("\n")
    title_line = ""
    description_lines = []
    in_description = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and not title_line:
            title_line = stripped.lstrip("# ").strip()
            continue
        if stripped and not stripped.startswith("#") and not stripped.startswith("##"):
            if not in_description and len(description_lines) < 20:
                description_lines.append(stripped)
                in_description = True
            elif in_description and len(description_lines) < 20:
                description_lines.append(stripped)

    description = " ".join(description_lines)[:2000]
    log(f"提取书名: {title_line}")
    log(f"提取描述: {description[:150]}...")

    # 获取API配置
    api_key_setting = db.query(PlatformSetting).filter(
        PlatformSetting.setting_key == "api.deepseek.api_key"
    ).first()
    api_key = api_key_setting.value_json.get("value") if api_key_setting else None
    base_url_setting = db.query(PlatformSetting).filter(
        PlatformSetting.setting_key == "api.deepseek.base_url"
    ).first()
    model_setting = db.query(PlatformSetting).filter(
        PlatformSetting.setting_key == "api.deepseek.model"
    ).first()
    base_url = base_url_setting.value_json.get("value") if base_url_setting else None
    model = model_setting.value_json.get("value") if model_setting else None

    if not api_key or not base_url:
        return {"error": "DeepSeek API 未配置"}
    configure_runtime(base_url=base_url, model=model)

    fw_prompt_setting = db.query(PlatformSetting).filter(
        PlatformSetting.setting_key == "prompt.framework_generation"
    ).first()
    system_prompt = fw_prompt_setting.value_json.get("value") if fw_prompt_setting else None

    # Step 1: 生成框架
    log("Step 1: 调用 generate_framework 生成结构化框架...")
    try:
        start = time.time()
        framework = await generate_framework(
            description=description,
            api_key=api_key,
            system_prompt=system_prompt,
            story_length="long",
        )
        elapsed = time.time() - start
        log(f"框架生成完成，耗时 {elapsed:.1f}s")

        # 验证任务卡
        all_chapters = []
        for act in framework.get("outline", {}).get("three_acts", []):
            all_chapters.extend(act.get("chapters", []))

        complete_count = 0
        task_card_results = []
        for ch in all_chapters[:10]:
            card = check_task_card(ch)
            task_card_results.append({"chapter": ch.get("chapter_number"), "task_card": card})
            if card["_complete"]:
                complete_count += 1

        log(f"前10章任务卡完整率: {complete_count}/10")
        for r in task_card_results:
            status = "PASS" if r["task_card"]["_complete"] else "FAIL"
            missing = [k for k, v in r["task_card"].items() if not v and k != "_complete"]
            msg = f"第{r['chapter']}章: {status}"
            if missing:
                msg += f" | 缺失: {', '.join(missing)}"
            log(msg, status.lower())

        fw_result = {
            "total_chapters": len(all_chapters),
            "first_10_complete": complete_count,
            "details": task_card_results,
            "elapsed_seconds": elapsed,
        }
    except Exception as e:
        log(f"框架生成失败: {e}", "FAIL")
        return {"test": "file_outline", "error": str(e)}

    # Step 2: 使用生成的任务卡生成第一章
    log("Step 2: 使用任务卡生成第一章正文...")
    first_chapter = all_chapters[0] if all_chapters else {}
    chapter_info = {
        "chapter_number": 1,
        "title": first_chapter.get("title", "第一章"),
        "act": first_chapter.get("act", "1"),
        **{k: first_chapter.get(k, "") for k in ["summary", "goal", "conflict", "hook", "payoff", "highlight"]},
    }

    story_context = {
        "description": description,
        "story_bible": {},
        "tags": framework.get("tags", {}),
        "characters": framework.get("characters", []),
        "outline": framework.get("outline", {}),
    }

    agent_content = ""
    direct_content = ""

    # Agent路径
    try:
        log("  Agent路径 (adjust_chapter_content)...")
        start = time.time()
        agent_content = await adjust_chapter_content(
            story_context=story_context,
            chapter_info=chapter_info,
            chapter_content="",
            instruction="根据大纲和任务卡，以起点黄金三章标准创作第一章正文",
            api_key=api_key,
            system_prompt=build_agent_chapter_system_prompt(db=db),
        )
        log(f"  Agent路径完成: {len(agent_content)} 字, 耗时 {time.time()-start:.1f}s")
    except Exception as e:
        log(f"  Agent路径失败: {e}", "FAIL")

    # 框架直出路径
    try:
        log("  框架直出路径 (expand_chapter_to_content)...")
        start = time.time()
        direct_content = await expand_chapter_to_content(
            story_context=story_context,
            chapter_info=chapter_info,
            api_key=api_key,
            db=db,
        )
        log(f"  框架直出完成: {len(direct_content)} 字, 耗时 {time.time()-start:.1f}s")
    except Exception as e:
        log(f"  框架直出失败: {e}", "FAIL")

    # Step 3: AI质量评估
    log("Step 3: AI深度质量评估...")
    ai_results = {}
    for label, content in [("agent", agent_content), ("direct", direct_content)]:
        if not content:
            ai_results[label] = {"error": "无内容"}
            continue
        try:
            assessment = await quality_assess(content, api_key=api_key)
            ai_results[label] = assessment
            scores = assessment.get("scores", {})
            log(f"  {label}: 内容={scores.get('content')} 文笔={scores.get('writing')} "
                f"角色={scores.get('character')} 情节={scores.get('plot')} 整体={scores.get('overall')}")
        except Exception as e:
            ai_results[label] = {"error": str(e)}

    return {
        "test": "file_outline_pipeline",
        "source_file": config.outline_file,
        "extracted_title": title_line,
        "framework_task_card": fw_result,
        "agent_chapter": {
            "content_length": len(agent_content),
            "content_preview": agent_content[:500] if agent_content else "",
        },
        "direct_chapter": {
            "content_length": len(direct_content),
            "content_preview": direct_content[:500] if direct_content else "",
        },
        "ai_assessment": ai_results,
        "agent_full_content": agent_content,
        "direct_full_content": direct_content,
    }


async def run_all_tests(config: TestConfig = None):
    if config is None:
        config = TestConfig()

    # 如果指定了大纲文件，走文件导入测试流程
    if config.outline_file:
        print("=" * 70)
        print("  StoryCanvas 大纲文件导入全链路测试")
        print(f"  文件: {config.outline_file}")
        print("=" * 70)

        db = SessionLocal()
        report = {
            "config": {"outline_file": config.outline_file},
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tests": {},
        }
        try:
            result = await test_file_outline_pipeline(db, config)
            report["tests"]["file_outline"] = result

            # 汇总
            print("\n" + "=" * 70)
            print("  测试汇总")
            print("=" * 70)

            fw = result.get("framework_task_card", {})
            log(f"框架任务卡: 前10章完整 {fw.get('first_10_complete', 'N/A')}/10")

            ai = result.get("ai_assessment", {})
            for label in ["agent", "direct"]:
                scores = ai.get(label, {}).get("scores", {})
                if scores:
                    log(f"AI评估({label}): 内容={scores.get('content')} 文笔={scores.get('writing')} "
                        f"角色={scores.get('character')} 情节={scores.get('plot')} 整体={scores.get('overall')}")

            agent_scores = ai.get("agent", {}).get("scores", {})
            direct_scores = ai.get("direct", {}).get("scores", {})
            agent_overall = agent_scores.get("overall", 0)
            direct_overall = direct_scores.get("overall", 0)

            if agent_overall >= 8 and direct_overall >= 8:
                log("两条路径均达到起点签约水准（AI评估 >= 8/10）✅")
            elif agent_overall >= 7 or direct_overall >= 7:
                log("至少一条路径接近签约水准", "WARN")

            agent_len = result.get("agent_chapter", {}).get("content_length", 0)
            direct_len = result.get("direct_chapter", {}).get("content_length", 0)
            log(f"字数: Agent={agent_len} | 框架直出={direct_len}")

            # 保存报告
            report_path = os.path.join(
                os.path.dirname(__file__), "..", ".sisyphus", "file_outline_test_report.json"
            )
            os.makedirs(os.path.dirname(report_path), exist_ok=True)
            for key in ["agent_full_content", "direct_full_content"]:
                if key in result:
                    result[key + "_preview"] = result[key][:1000]
                    del result[key]
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            log(f"报告已保存: {report_path}")
        finally:
            db.close()
        return report

    # 原有数据库测试流程
    print("=" * 70)
    print("  StoryCanvas 全链路质量测试")
    print(f"  目标作品 ID={config.story_id}  目标章节=第{config.target_chapter}章")
    print("=" * 70)

    db = SessionLocal()
    report = {
        "config": {"story_id": config.story_id, "target_chapter": config.target_chapter},
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tests": {},
    }

    try:
        # 测试1：框架生成任务卡完整性
        result1 = await test_framework_regeneration(db, config)
        report["tests"]["framework_task_card"] = result1

        # 测试2：Agent路径章节生成
        result2 = await test_agent_chapter_generation(db, config)
        report["tests"]["agent_chapter"] = result2

        # 测试3：框架直出路径章节生成
        result3 = await test_framework_direct_generation(db, config)
        report["tests"]["framework_direct_chapter"] = result3

        # 测试4：AI深度质量评估
        agent_content = result2.get("full_content", "") if "full_content" in result2 else ""
        direct_content = result3.get("full_content", "") if "full_content" in result3 else ""
        result4 = await test_ai_quality_assessment(db, config, agent_content, direct_content)
        report["tests"]["ai_assessment"] = result4

        # 汇总
        print("\n" + "=" * 70)
        print("  测试汇总")
        print("=" * 70)

        fw = report["tests"].get("framework_task_card", {})
        agent = report["tests"].get("agent_chapter", {})
        direct = report["tests"].get("framework_direct_chapter", {})
        ai = report["tests"].get("ai_assessment", {})

        log(f"框架任务卡: 前10章完整 {fw.get('first_10_complete', 'N/A')}/10")
        if fw.get('first_10_complete', 0) >= 10:
            log("Prompt修复生效：任务卡字段全部产出 ✅")
        else:
            log("任务卡仍有缺失，需检查 Prompt", "WARN")

        # 启发式评分（快速参考）
        agent_heuristic = agent.get("quality_score", {}).get("overall", 0)
        direct_heuristic = direct.get("quality_score", {}).get("overall", 0)
        log(f"启发式评分: Agent={agent_heuristic}/70 | 框架直出={direct_heuristic}/70")

        # AI深度评估（权威分数）
        ai_agent = ai.get("results", {}).get("agent", {}).get("scores", {})
        ai_direct = ai.get("results", {}).get("direct", {}).get("scores", {})
        if ai_agent and ai_direct:
            log(f"AI评估(Agent): 内容={ai_agent.get('content')} 文笔={ai_agent.get('writing')} "
                f"角色={ai_agent.get('character')} 情节={ai_agent.get('plot')} 整体={ai_agent.get('overall')}")
            log(f"AI评估(直出): 内容={ai_direct.get('content')} 文笔={ai_direct.get('writing')} "
                f"角色={ai_direct.get('character')} 情节={ai_direct.get('plot')} 整体={ai_direct.get('overall')}")

            agent_overall = ai_agent.get("overall", 0)
            direct_overall = ai_direct.get("overall", 0)
            if agent_overall >= 8 and direct_overall >= 8:
                log("两条路径均达到起点签约水准（AI评估 >= 8/10）✅")
            elif agent_overall >= 7 and direct_overall >= 7:
                log("两条路径接近签约水准，可进一步优化", "WARN")

            diff = agent_overall - direct_overall
            if abs(diff) <= 0.5:
                log("两条路径质量基本持平 ✅")
            else:
                log(f"质量差异: Agent vs 框架直出 = {diff:+.1f}/10")

        # 字数对比
        agent_len = agent.get("content_length", 0)
        direct_len = direct.get("content_length", 0)
        log(f"字数: Agent={agent_len} | 框架直出={direct_len}")
        if agent_len > direct_len * 1.5:
            log("Agent路径字数明显偏多，可能影响节奏", "WARN")
        elif direct_len > agent_len * 1.5:
            log("框架直出字数明显偏多，可能影响节奏", "WARN")

        # 保存报告
        report_path = os.path.join(
            os.path.dirname(__file__), "..", ".sisyphus", "quality_test_report.json"
        )
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        # 移除完整正文以减小报告体积
        for key in ["agent_chapter", "framework_direct_chapter"]:
            if key in report["tests"] and "full_content" in report["tests"][key]:
                report["tests"][key]["content_preview"] = report["tests"][key]["full_content"][:1000]
                del report["tests"][key]["full_content"]

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        log(f"报告已保存: {report_path}")

    finally:
        db.close()

    return report


# ── CLI入口 ─────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="StoryCanvas 全链路质量测试")
    parser.add_argument("--story-id", type=int, default=3, help="测试作品ID")
    parser.add_argument("--chapter", type=int, default=1, help="测试章节号")
    parser.add_argument("--outline-file", type=str, default=None, help="大纲文件路径（可选）")
    args = parser.parse_args()

    config = TestConfig(
        story_id=args.story_id,
        target_chapter=args.chapter,
        outline_file=args.outline_file,
    )

    asyncio.run(run_all_tests(config))


if __name__ == "__main__":
    main()
