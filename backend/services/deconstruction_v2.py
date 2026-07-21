"""
oh-story 模式拆书管线 v2
参考 oh-story-claudecode story-long-analyze 方法论：

核心改进：
1. Stage 0.5: 故事框架识别（升级流/复仇线/日常单元/多线交织/蜕变成长）
2. Stage 1 停靠点：黄金三章后暂停，支持后续从 Stage 2 续跑
3. Stage 2 增强：部分失败容忍，所有章节摘要合并为一份汇总
4. Stage 3: 框架感知分块（替代固定 60 章切块）
5. Stage 3 + 4a 并行执行
6. 524/超时自动重试
"""
import asyncio
import json
import logging

from sqlalchemy.orm import Session

from database import SessionLocal
from models import DeconstructionResult, Story, Chapter
from services.errors import public_error_message
from services.deconstruction import (
    _call_deepseek_json,
    _call_deepseek_text,
    _count_words,
    _configure_deepseek_from_db,
    _get_api_key_from_db,
    _truncate_title_list,
    _truncate_json_for_context,
    _update_progress,
    STAGE2_CHAPTER_CONCURRENCY,
    should_flush_stage2_progress,
    STAGE3_CHUNK_SIZE,
)
from prompts.deconstruction import (
    STAGE_0_SUMMARY_SYSTEM, STAGE_0_SUMMARY_USER,
    STAGE_0_5_FRAMEWORK_SYSTEM, STAGE_0_5_FRAMEWORK_USER,
    STAGE_1_GOLDEN_CHAPTERS_SYSTEM, STAGE_1_GOLDEN_CHAPTERS_USER,
    STAGE_2_CHAPTER_SUMMARY_SYSTEM, STAGE_2_CHAPTER_SUMMARY_USER,
    STAGE_3_AGGREGATION_SYSTEM, STAGE_3_AGGREGATION_USER,
    STAGE_4_SETTINGS_SYSTEM, STAGE_4_SETTINGS_USER,
    STAGE_5_REPORT_SYSTEM, STAGE_5_REPORT_USER,
    STAGE_6_STYLE_SYSTEM, STAGE_6_STYLE_USER,
)

logger = logging.getLogger(__name__)

# 框架类型对应的分块建议大小
FRAMEWORK_CHUNK_SIZES = {
    "升级流": 80,
    "复仇线": 60,
    "日常单元": 40,
    "多线交织": 50,
    "蜕变成长": 60,
}


def _get_chunk_size(framework_type: str | None) -> int:
    """根据框架类型获取建议的分块大小"""
    if framework_type and framework_type in FRAMEWORK_CHUNK_SIZES:
        return FRAMEWORK_CHUNK_SIZES[framework_type]
    return STAGE3_CHUNK_SIZE


def _merge_chapter_summaries(chapter_summaries: list[dict]) -> str:
    """将章节摘要无损拼接为一份汇总文本，供 Stage 3-5 复用"""
    if not chapter_summaries:
        return ""
    parts = []
    for cs in chapter_summaries:
        if cs is None:
            continue
        cn = cs.get("chapter_number", "?")
        parts.append(f"## 第{cn}章\n{json.dumps(cs, ensure_ascii=False, indent=2)}")
    return "\n\n".join(parts)


def _build_preview_report(result: DeconstructionResult) -> str:
    """构建 Stage 1 停靠点的快速预览报告"""
    summary = result.summary or {}
    golden = result.golden_chapters or {}
    rating = golden.get("golden_three_rating", {})
    early = golden.get("early_learnable", [])

    parts = [
        f"# 快速预览：{summary.get('title', '未知')}",
        "",
        "## 基本信息",
        f"- 书名：{summary.get('title', '未知')}",
        f"- 题材：{summary.get('genre', '未知')}",
        f"- 预估总章节：{summary.get('estimated_total_chapters', '?')}",
        f"- 预估总字数：{summary.get('estimated_total_words', '?')}万",
        "",
        f"## 框架识别",
        f"- 故事框架类型：{result.framework_type or '未识别'}",
        "",
        "## 黄金三章评分",
        "",
        "| 维度 | 评分 | 说明 |",
        "|------|------|------|",
    ]

    dims = [
        ("opening_hook", "开篇钩子"),
        ("protagonist_building", "主角塑造"),
        ("pleasure_design", "爽点设计"),
        ("worldbuilding", "世界观铺设"),
        ("chapter_end_hooks", "章尾悬念"),
    ]
    for key, label in dims:
        dim = rating.get(key, {})
        score = dim.get("score", "?")
        comment = dim.get("comment", "")
        parts.append(f"| {label} | {score}/5 | {comment} |")

    if early:
        parts.append("")
        parts.append("## 可借鉴要素")
        for i, item in enumerate(early[:5], 1):
            parts.append(f"{i}. {item}")

    parts.append("")
    parts.append("## 下一步")
    parts.append("黄金三章拆解完成。可选「继续全量拆解」（Stage 2-6）或「试读前 N 章」（仅拆前 N 章，产出轻量分析报告）。")

    return "\n".join(parts)


async def run_deconstruction_pipeline_v2(
    story_id: int,
    api_key: str,
    task_id: str | None = None,
    start_stage: int = 0,
    pause_after_stage1: bool = True,
    max_chapters_for_partial: int | None = None,
    partial_mode: bool = False,
    quick_report_mode: bool = False,
    **kwargs,
) -> dict:
    """运行 oh-story 模式拆书管线 Stage 0-6。

    Args:
        story_id: 故事 ID
        api_key: DeepSeek API Key
        task_id: 后台任务 ID
        start_stage: 起始阶段（续跑时使用）
        pause_after_stage1: 是否在 Stage 1 后停靠（默认 True）
        max_chapters_for_partial: 试读模式章节上限（如 100 = 仅拆前 100 章）
        partial_mode: 试读模式续跑（Stage 2'→3'→5'，不跑 Stage 4 全量聚合和 Stage 6 文风）

    Returns:
        {"status": "completed"|"paused_after_stage1"|"paused_after_partial":N, "result_id": int}
    """
    db = SessionLocal()
    try:
        _configure_deepseek_from_db(db)
        if not api_key:
            api_key = _get_api_key_from_db(db)

        story = db.query(Story).filter(Story.id == story_id).first()
        if not story:
            raise ValueError(f"故事 {story_id} 不存在")

        chapters = db.query(Chapter).filter(
            Chapter.story_id == story_id,
            Chapter.novel_content.isnot(None),
            Chapter.novel_content != "",
            Chapter.content_source.in_(["crawled", None]),
        ).order_by(Chapter.chapter_number).all()

        if len(chapters) < 3:
            raise ValueError("至少需要 3 章有内容的章节才能拆书")

        # 试读模式：仅处理前 N 章
        if max_chapters_for_partial and max_chapters_for_partial < len(chapters):
            chapters = chapters[:max_chapters_for_partial]

        # 创建或恢复 DeconstructionResult
        result = db.query(DeconstructionResult).filter(
            DeconstructionResult.story_id == story_id,
            DeconstructionResult.status.in_(["pending", "running", "paused_after_stage1"]),
        ).order_by(DeconstructionResult.created_at.desc()).first()

        if not result:
            result = DeconstructionResult(
                story_id=story_id,
                status="running",
                current_stage=start_stage,
                stages_completed=[],
                task_id=task_id,
                decon_range=max_chapters_for_partial,
            )
            db.add(result)
            db.commit()
            db.refresh(result)
        else:
            result.current_stage = start_stage
            result.status = "running"
            result.task_id = task_id
            if max_chapters_for_partial and not result.decon_range:
                result.decon_range = max_chapters_for_partial
            db.commit()

        if max_chapters_for_partial:
            _update_progress(result, db, f"试读模式：仅处理前 {len(chapters)} 章")

        try:
            # === quick_report 模式：基于黄金三章数据生成报告 ===
            if quick_report_mode and result.current_stage <= 5:
                _update_progress(result, db, "quick_report: 基于黄金三章数据生成报告...")
                summary = result.summary or {}
                decon_range = result.decon_range or len(chapters)
                response = await _call_deepseek_text(
                    STAGE_5_REPORT_SYSTEM,
                    STAGE_5_REPORT_USER.format(
                        title=summary.get("title", "未知"),
                        genre=summary.get("genre", "未知"),
                        total_chapters=decon_range,
                        total_words=summary.get("estimated_total_words", 0),
                        golden_chapters=_truncate_json_for_context(result.golden_chapters, 8000),
                        chapter_summaries=_truncate_json_for_context(None, 1000),
                        characters=_truncate_json_for_context(result.characters, 1000),
                        character_relations=_truncate_json_for_context(result.character_relations, 1000),
                        plot_lines=_truncate_json_for_context(result.plot_lines, 1000),
                        rhythm=_truncate_json_for_context(result.rhythm, 1000),
                        emotion_modules=_truncate_json_for_context(result.emotion_modules, 1000),
                        worldbuilding=_truncate_json_for_context(result.worldbuilding, 1000),
                    ),
                    api_key,
                )
                result.report_markdown = response
                result.status = "paused_after_stage1"
                db.commit()
                _update_progress(result, db, "quick_report: 报告已生成")
                return {"status": "paused_after_stage1", "result_id": result.id}

            # === Stage 0: 概要提取 ===
            if result.current_stage <= 0:
                _update_progress(result, db, "Stage 0: 概要提取中...")
                sample_text = ""
                for ch in chapters[:5]:
                    sample_text += f"\n\n## 第{ch.chapter_number}章 {ch.title or ''}\n\n{(ch.novel_content or '')[:2000]}"
                title_lines = [f"第{ch.chapter_number}章 {ch.title or ''} ({_count_words(ch.novel_content)}字)" for ch in chapters]
                all_titles = _truncate_title_list(title_lines)
                response = await _call_deepseek_json(
                    STAGE_0_SUMMARY_SYSTEM,
                    STAGE_0_SUMMARY_USER.format(chapter_text=f"章节列表：\n{all_titles}\n\n样本内容：\n{sample_text}"),
                    api_key,
                )
                result.summary = response
                result.current_stage = 0.5
                db.commit()

            # === Stage 0.5: 故事框架识别 ===
            if result.current_stage <= 0.5:
                _update_progress(result, db, "Stage 0.5: 故事框架识别中...")
                summary = result.summary or {}
                thin = summary.get("thin_summary", "")
                title_lines = [f"第{ch.chapter_number}章 {ch.title or ''}" for ch in chapters]
                titles_text = _truncate_title_list(title_lines)

                try:
                    fw_response = await _call_deepseek_json(
                        STAGE_0_5_FRAMEWORK_SYSTEM,
                        STAGE_0_5_FRAMEWORK_USER.format(thin_summary=thin, chapter_titles=titles_text),
                        api_key,
                    )
                    result.framework_type = fw_response.get("framework_type", "")
                    # 将框架信息写入进度
                    fw_info = f"Stage 0.5: 框架识别完成 - {fw_response.get('framework_type', '未知')} (置信度: {fw_response.get('confidence', '?')})"
                    _update_progress(result, db, fw_info)
                except Exception as e:
                    logger.warning(f"框架识别失败（非致命）: {e}")
                    _update_progress(result, db, f"Stage 0.5: 框架识别失败，使用默认分块策略 - {e}")

                result.current_stage = 1
                db.commit()

            # === Stage 1: 黄金三章深度拆解 ===
            if result.current_stage <= 1:
                _update_progress(result, db, "Stage 1: 黄金三章深度拆解中...")
                golden_text = ""
                for ch in chapters[:3]:
                    golden_text += f"\n\n## 第{ch.chapter_number}章 {ch.title or ''}\n\n{(ch.novel_content or '')}"
                response = await _call_deepseek_json(
                    STAGE_1_GOLDEN_CHAPTERS_SYSTEM,
                    STAGE_1_GOLDEN_CHAPTERS_USER.format(chapter_text=golden_text),
                    api_key,
                )
                result.golden_chapters = response
                result.current_stage = 2
                result.stages_completed = [0, 0.5, 1] if isinstance(result.stages_completed, list) else [0, 0.5, 1]
                db.commit()

                # === Stage 1 停靠点 ===
                if pause_after_stage1:
                    preview = _build_preview_report(result)
                    result.progress_markdown = (result.progress_markdown or "") + "\n\n" + preview
                    if max_chapters_for_partial:
                        result.status = f"paused_after_partial:{max_chapters_for_partial}"
                        result.decon_range = max_chapters_for_partial
                        db.commit()
                        return {"status": f"paused_after_partial:{max_chapters_for_partial}", "result_id": result.id, "preview": preview}
                    result.status = "paused_after_stage1"
                    db.commit()
                    return {"status": "paused_after_stage1", "result_id": result.id, "preview": preview}

            # === Stage 2: 逐章摘要（并发控制 + 部分失败容忍）===
            if result.current_stage <= 2:
                _update_progress(result, db, "Stage 2: 逐章摘要中...")
                semaphore = asyncio.Semaphore(STAGE2_CHAPTER_CONCURRENCY)
                db_lock = asyncio.Lock()
                completed = [0]
                failed = [0]
                total = len(chapters)
                fatal_error_seen = asyncio.Event()

                async def _summarize_one(ch, index: int):
                    async with semaphore:
                        if fatal_error_seen.is_set():
                            return (index, {"chapter_number": ch.chapter_number, "error": "上游服务异常，已跳过"})
                        try:
                            response = await _call_deepseek_json(
                                STAGE_2_CHAPTER_SUMMARY_SYSTEM,
                                STAGE_2_CHAPTER_SUMMARY_USER.format(
                                    chapter_number=ch.chapter_number,
                                    chapter_title=ch.title or "",
                                    word_count=_count_words(ch.novel_content),
                                    chapter_text=ch.novel_content or "",
                                ),
                                api_key,
                            )
                            async with db_lock:
                                completed[0] += 1
                                if should_flush_stage2_progress(completed[0], total):
                                    _update_progress(result, db, f"Stage 2: 逐章摘要 ({completed[0]}/{total})...")
                            return (index, response)
                        except Exception as e:
                            from services.deconstruction import FatalModelProviderError
                            if isinstance(e, FatalModelProviderError):
                                fatal_error_seen.set()
                                raise
                            logger.error(f"第{ch.chapter_number}章摘要失败: {e}")
                            async with db_lock:
                                completed[0] += 1
                                failed[0] += 1
                                if should_flush_stage2_progress(completed[0], total):
                                    _update_progress(result, db, f"Stage 2: 逐章摘要 ({completed[0]}/{total}) - 第{ch.chapter_number}章失败（已跳过）")
                            return (
                                index,
                                {
                                    "chapter_number": ch.chapter_number,
                                    "error": public_error_message(e, f"第 {ch.chapter_number} 章摘要生成失败，请稍后重试"),
                                },
                            )

                results = await asyncio.gather(
                    *[_summarize_one(ch, i) for i, ch in enumerate(chapters)]
                )
                results.sort(key=lambda x: x[0])
                result.chapter_summaries = [r[1] for r in results]

                # 合并章节摘要为一份汇总文本
                merged_text = _merge_chapter_summaries(result.chapter_summaries)
                result.progress_markdown = (result.progress_markdown or "") + "\n\n## STAGE2_MERGED\n" + merged_text[:100000]

                result.current_stage = 3
                db.commit()
                _update_progress(result, db, f"Stage 2: 逐章摘要完成 ({completed[0]}/{total})，失败 {failed[0]} 章")

            # === 试读模式：Stage 3' 轻量聚合 + Stage 5' 试读报告 ===
            if partial_mode:
                merged_text = ""
                if result.progress_markdown and "## STAGE2_MERGED" in result.progress_markdown:
                    merged_text = result.progress_markdown.split("## STAGE2_MERGED\n", 1)[1].split("\n## ")[0]
                if not merged_text:
                    merged_text = _merge_chapter_summaries(result.chapter_summaries)

                # Stage 3': 轻量聚合（单次调用，不做分块合并）
                _update_progress(result, db, "Stage 3': 轻量聚合中（试读模式）...")
                summaries_text = _truncate_json_for_context(result.chapter_summaries, 20000)
                stage3_partial = await _call_deepseek_json(
                    STAGE_3_AGGREGATION_SYSTEM,
                    STAGE_3_AGGREGATION_USER.format(all_chapter_summaries=summaries_text),
                    api_key,
                )
                result.plot_lines = stage3_partial.get("plot_lines")
                result.rhythm = stage3_partial.get("rhythm")
                result.emotion_modules = stage3_partial.get("emotion_modules")
                merged = stage3_partial.get("merged_characters", {})
                result.progress_markdown = (result.progress_markdown or "") + "\n## STAGE3_MERGED\n" + json.dumps(merged, ensure_ascii=False)

                # Stage 4a': 轻量世界观提取
                _update_progress(result, db, "Stage 4a': 世界观提取中（试读模式）...")
                try:
                    stage4a_partial = await _call_deepseek_json(
                        STAGE_4_SETTINGS_SYSTEM,
                        STAGE_4_SETTINGS_USER.format(
                            chapter_summaries=summaries_text,
                            merged_characters=json.dumps(merged, ensure_ascii=False),
                        ),
                        api_key,
                    )
                    result.worldbuilding = stage4a_partial.get("worldbuilding")
                    result.characters = stage4a_partial.get("character_profiles")
                    result.character_relations = stage4a_partial.get("character_relations")
                except Exception as e:
                    logger.warning(f"Stage 4a' 世界观提取失败（非致命）: {e}")

                # Stage 5': 试读报告
                _update_progress(result, db, "Stage 5': 试读报告生成中...")
                decon_range = result.decon_range or len(chapters)
                summary = result.summary or {}
                partial_title = f"{summary.get('title', '未知')}（前{decon_range}章）"
                response = await _call_deepseek_text(
                    STAGE_5_REPORT_SYSTEM,
                    STAGE_5_REPORT_USER.format(
                        title=partial_title,
                        genre=summary.get("genre", "未知"),
                        total_chapters=decon_range,
                        total_words=summary.get("estimated_total_words", 0),
                        golden_chapters=_truncate_json_for_context(result.golden_chapters, 8000),
                        chapter_summaries=_truncate_json_for_context(result.chapter_summaries, 15000),
                        characters=_truncate_json_for_context(result.characters, 8000),
                        character_relations=_truncate_json_for_context(result.character_relations, 5000),
                        plot_lines=_truncate_json_for_context(result.plot_lines, 5000),
                        rhythm=_truncate_json_for_context(result.rhythm, 3000),
                        emotion_modules=_truncate_json_for_context(result.emotion_modules, 3000),
                        worldbuilding=_truncate_json_for_context(result.worldbuilding, 5000),
                    ),
                    api_key,
                )
                result.report_markdown = response
                result.status = f"paused_after_partial:{decon_range}"
                result.current_stage = 5
                result.stages_completed = [0, 0.5, 1, 2, 3, 4, 5]
                db.commit()
                _update_progress(result, db, f"试读模式完成：前 {decon_range} 章分析完毕，报告见拆文报告")
                return {"status": f"paused_after_partial:{decon_range}", "result_id": result.id}

            # === Stage 3 + 4a 并行 ===
            chunk_size = _get_chunk_size(result.framework_type)

            if result.current_stage <= 3 or result.current_stage <= 4:
                _update_progress(result, db, "Stage 3+4a: 聚合分析 + 世界观提取并行执行中...")

                # 从合并的摘要文本中读取
                merged_text = ""
                if result.progress_markdown and "## STAGE2_MERGED" in result.progress_markdown:
                    merged_text = result.progress_markdown.split("## STAGE2_MERGED\n", 1)[1].split("\n## ")[0]
                if not merged_text:
                    merged_text = _merge_chapter_summaries(result.chapter_summaries)

                async def _run_stage3():
                    """Stage 3: 框架感知分块聚合"""
                    if result.current_stage > 3:
                        return None
                    _update_progress(result, db, f"Stage 3: 聚合分析中（框架: {result.framework_type or '未知'}, 分块: {chunk_size}章）...")

                    # 按章节切分，每块 chunk_size 章
                    chapter_blocks = []
                    all_summaries = result.chapter_summaries or []
                    for i in range(0, len(all_summaries), chunk_size):
                        block = all_summaries[i:i + chunk_size]
                        block_text = _merge_chapter_summaries(block)
                        chapter_blocks.append(block_text)

                    if len(chapter_blocks) <= 1:
                        # 不分块，直接聚合
                        return await _call_deepseek_json(
                            STAGE_3_AGGREGATION_SYSTEM,
                            STAGE_3_AGGREGATION_USER.format(all_chapter_summaries=merged_text[:80000]),
                            api_key,
                        )

                    # 分块聚合
                    chunk_results = []
                    for i, block_text in enumerate(chapter_blocks):
                        _update_progress(result, db, f"Stage 3: 聚合分块 {i + 1}/{len(chapter_blocks)}...")
                        chunk_result = await _call_deepseek_json(
                            STAGE_3_AGGREGATION_SYSTEM,
                            STAGE_3_AGGREGATION_USER.format(all_chapter_summaries=block_text[:80000]),
                            api_key,
                        )
                        chunk_results.append(chunk_result)

                    # 跨块合并
                    _update_progress(result, db, f"Stage 3: 跨块合并中（{len(chunk_results)} 块）...")
                    merged_chunks = json.dumps(chunk_results, ensure_ascii=False, indent=2)
                    return await _call_deepseek_json(
                        STAGE_3_AGGREGATION_SYSTEM,
                        STAGE_3_AGGREGATION_USER.format(all_chapter_summaries=merged_chunks[:80000]),
                        api_key,
                    )

                async def _run_stage4a():
                    """Stage 4a: 世界观设定（可并行，不依赖 Stage 3）"""
                    if result.current_stage > 4:
                        return None
                    _update_progress(result, db, "Stage 4a: 世界观设定提取中...")
                    summaries_text = _truncate_json_for_context(result.chapter_summaries, 15000)
                    response = await _call_deepseek_json(
                        STAGE_4_SETTINGS_SYSTEM,
                        STAGE_4_SETTINGS_USER.format(chapter_summaries=summaries_text, merged_characters="{}"),
                        api_key,
                    )
                    return response

                # 并行执行 Stage 3 和 Stage 4a
                stage3_result, stage4a_result = await asyncio.gather(
                    _run_stage3(), _run_stage4a()
                )

                if stage3_result:
                    result.plot_lines = stage3_result.get("plot_lines")
                    result.rhythm = stage3_result.get("rhythm")
                    result.emotion_modules = stage3_result.get("emotion_modules")
                    merged = stage3_result.get("merged_characters", {})
                    result.progress_markdown = (result.progress_markdown or "") + "\n## STAGE3_MERGED\n" + json.dumps(merged, ensure_ascii=False)

                if stage4a_result:
                    result.worldbuilding = stage4a_result.get("worldbuilding")
                    result.characters = stage4a_result.get("character_profiles")
                    result.character_relations = stage4a_result.get("character_relations")

                result.current_stage = 5
                db.commit()

            # === Stage 5: 汇总报告 ===
            if result.current_stage <= 5:
                _update_progress(result, db, "Stage 5: 汇总报告中...")
                summary = result.summary or {}
                response = await _call_deepseek_text(
                    STAGE_5_REPORT_SYSTEM,
                    STAGE_5_REPORT_USER.format(
                        title=summary.get("title", "未知"),
                        genre=summary.get("genre", "未知"),
                        total_chapters=summary.get("estimated_total_chapters", 0),
                        total_words=summary.get("estimated_total_words", 0),
                        golden_chapters=_truncate_json_for_context(result.golden_chapters, 8000),
                        chapter_summaries=_truncate_json_for_context(result.chapter_summaries, 15000),
                        characters=_truncate_json_for_context(result.characters, 8000),
                        character_relations=_truncate_json_for_context(result.character_relations, 5000),
                        plot_lines=_truncate_json_for_context(result.plot_lines, 5000),
                        rhythm=_truncate_json_for_context(result.rhythm, 3000),
                        emotion_modules=_truncate_json_for_context(result.emotion_modules, 3000),
                        worldbuilding=_truncate_json_for_context(result.worldbuilding, 5000),
                    ),
                    api_key,
                )
                result.report_markdown = response
                result.current_stage = 6
                db.commit()

            # === Stage 6: 文风分析 ===
            if result.current_stage <= 6:
                _update_progress(result, db, "Stage 6: 文风分析中...")
                samples = []
                for i, ch in enumerate(chapters):
                    if i < 3 or i % 10 == 0:
                        samples.append(f"## 第{ch.chapter_number}章\n\n{(ch.novel_content or '')[:3000]}")
                golden_text = json.dumps(result.golden_chapters, ensure_ascii=False, indent=2)[:5000]
                summaries_text = json.dumps(result.chapter_summaries, ensure_ascii=False, indent=2)[:5000]
                response = await _call_deepseek_json(
                    STAGE_6_STYLE_SYSTEM,
                    STAGE_6_STYLE_USER.format(
                        chapter_summaries=summaries_text,
                        golden_chapters_text=golden_text,
                        original_text_samples="\n\n".join(samples),
                    ),
                    api_key,
                )
                result.writing_style = response
                result.writing_techniques = response.get("techniques", [])
                result.current_stage = 7
                db.commit()

            result.status = "completed"
            result.stages_completed = [0, 0.5, 1, 2, 3, 4, 5, 6]
            db.commit()

            return {"status": "completed", "result_id": result.id}

        except Exception as e:
            logger.error(f"拆书管道 Stage {result.current_stage} 失败: {e}")
            result.status = "failed"
            error_message = public_error_message(e, "拆书分析失败，请稍后重试")
            result.progress_markdown = (result.progress_markdown or "") + f"\n\n## 阶段 {result.current_stage} 失败\n{error_message}"
            db.commit()
            raise

    finally:
        db.close()
