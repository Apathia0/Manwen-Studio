"""
拆书服务：编排长篇拆文 Stage 0-6 管道。
参考 oh-story-claudecode story-long-analyze 方法论。
"""

import json
import logging

import httpx
from sqlalchemy.orm import Session

from database import SessionLocal
from models import DeconstructionResult, Story, Chapter
from services.deepseek import DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, _deepseek_auth_headers, _loads_json_lenient
from prompts.deconstruction import (
    STAGE_0_SUMMARY_SYSTEM, STAGE_0_SUMMARY_USER,
    STAGE_1_GOLDEN_CHAPTERS_SYSTEM, STAGE_1_GOLDEN_CHAPTERS_USER,
    STAGE_2_CHAPTER_SUMMARY_SYSTEM, STAGE_2_CHAPTER_SUMMARY_USER,
    STAGE_3_AGGREGATION_SYSTEM, STAGE_3_AGGREGATION_USER,
    STAGE_4_SETTINGS_SYSTEM, STAGE_4_SETTINGS_USER,
    STAGE_5_REPORT_SYSTEM, STAGE_5_REPORT_USER,
    STAGE_6_STYLE_SYSTEM, STAGE_6_STYLE_USER,
)

logger = logging.getLogger(__name__)


async def _call_deepseek_json(system: str, user: str, api_key: str | None = None) -> dict:
    """调用 DeepSeek，返回 JSON 解析结果。"""
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return _loads_json_lenient(content)


async def _call_deepseek_text(system: str, user: str, api_key: str | None = None) -> str:
    """调用 DeepSeek，返回纯文本。"""
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers=_deepseek_auth_headers(api_key),
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _count_words(text: str | None) -> int:
    """统计中文字数"""
    if not text:
        return 0
    return len(text.replace("\n", "").replace(" ", ""))


def _update_progress(result: DeconstructionResult, db: Session, message: str):
    """更新进度信息到数据库"""
    result.progress_markdown = (result.progress_markdown or "") + f"\n- {message}"
    db.commit()


async def run_deconstruction_pipeline(
    story_id: int,
    api_key: str,
    task_id: str | None = None,
    start_stage: int = 0,
) -> dict:
    """运行完整拆书管道 Stage 0-6。

    Args:
        story_id: 故事 ID
        api_key: DeepSeek API Key
        task_id: 后台任务 ID（用于进度更新和取消检测）
        start_stage: 起始阶段（续跑时使用）

    Returns:
        {"status": "completed", "result_id": int}
    """
    db = next(SessionLocal())
    try:
        story = db.query(Story).filter(Story.id == story_id).first()
        if not story:
            raise ValueError(f"故事 {story_id} 不存在")

        chapters = db.query(Chapter).filter(
            Chapter.story_id == story_id,
            Chapter.novel_content.isnot(None),
            Chapter.novel_content != "",
        ).order_by(Chapter.chapter_number).all()

        if len(chapters) < 3:
            raise ValueError("至少需要 3 章有内容的章节才能拆书")

        # 创建或恢复 DeconstructionResult
        result = db.query(DeconstructionResult).filter(
            DeconstructionResult.story_id == story_id,
            DeconstructionResult.status.in_(["pending", "running"]),
        ).order_by(DeconstructionResult.created_at.desc()).first()

        if not result:
            result = DeconstructionResult(
                story_id=story_id,
                status="running",
                current_stage=start_stage,
                stages_completed=[],
                task_id=task_id,
            )
            db.add(result)
            db.commit()
            db.refresh(result)
        else:
            result.current_stage = start_stage
            result.status = "running"
            db.commit()

        try:
            # Stage 0: 概要提取
            if result.current_stage <= 0:
                _update_progress(result, db, "Stage 0: 概要提取中...")
                sample_text = ""
                for ch in chapters[:5]:
                    sample_text += f"\n\n## 第{ch.chapter_number}章 {ch.title or ''}\n\n{(ch.novel_content or '')[:2000]}"
                all_titles = "\n".join(
                    [f"第{ch.chapter_number}章 {ch.title or ''} ({_count_words(ch.novel_content)}字)" for ch in chapters]
                )
                response = await _call_deepseek_json(
                    STAGE_0_SUMMARY_SYSTEM,
                    STAGE_0_SUMMARY_USER.format(chapter_text=f"章节列表：\n{all_titles}\n\n样本内容：\n{sample_text}"),
                    api_key,
                )
                result.summary = response
                result.current_stage = 1
                db.commit()

            # Stage 1: 黄金三章深度拆解
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
                db.commit()

            # Stage 2: 逐章摘要
            if result.current_stage <= 2:
                summaries = []
                for i, ch in enumerate(chapters):
                    _update_progress(result, db, f"Stage 2: 逐章摘要 ({i+1}/{len(chapters)})...")
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
                        summaries.append(response)
                    except Exception as e:
                        logger.error(f"第{ch.chapter_number}章摘要失败: {e}")
                        summaries.append({"chapter_number": ch.chapter_number, "error": str(e)})
                result.chapter_summaries = summaries
                result.current_stage = 3
                db.commit()

            # Stage 3: 聚合分析
            if result.current_stage <= 3:
                _update_progress(result, db, "Stage 3: 聚合分析中...")
                summaries_text = json.dumps(result.chapter_summaries, ensure_ascii=False, indent=2)
                response = await _call_deepseek_json(
                    STAGE_3_AGGREGATION_SYSTEM,
                    STAGE_3_AGGREGATION_USER.format(all_chapter_summaries=summaries_text),
                    api_key,
                )
                result.plot_lines = response.get("plot_lines")
                result.rhythm = response.get("rhythm")
                result.emotion_modules = response.get("emotion_modules")
                # 暂存合并角色数据
                merged = response.get("merged_characters", {})
                result.progress_markdown = (result.progress_markdown or "") + "\n## STAGE3_MERGED\n" + json.dumps(merged, ensure_ascii=False)
                result.current_stage = 4
                db.commit()

            # Stage 4: 设定+关系
            if result.current_stage <= 4:
                _update_progress(result, db, "Stage 4: 设定+关系提取中...")
                summaries_text = json.dumps(result.chapter_summaries, ensure_ascii=False, indent=2)
                merged = "{}"
                if result.progress_markdown and "## STAGE3_MERGED" in result.progress_markdown:
                    merged = result.progress_markdown.split("## STAGE3_MERGED\n", 1)[1].split("\n## ")[0]
                response = await _call_deepseek_json(
                    STAGE_4_SETTINGS_SYSTEM,
                    STAGE_4_SETTINGS_USER.format(chapter_summaries=summaries_text, merged_characters=merged),
                    api_key,
                )
                result.worldbuilding = response.get("worldbuilding")
                result.characters = response.get("character_profiles")
                result.character_relations = response.get("character_relations")
                result.current_stage = 5
                db.commit()

            # Stage 5: 汇总报告
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
                        golden_chapters=json.dumps(result.golden_chapters, ensure_ascii=False, indent=2),
                        chapter_summaries=json.dumps(result.chapter_summaries, ensure_ascii=False, indent=2),
                        characters=json.dumps(result.characters, ensure_ascii=False, indent=2),
                        character_relations=json.dumps(result.character_relations, ensure_ascii=False, indent=2),
                        plot_lines=json.dumps(result.plot_lines, ensure_ascii=False, indent=2),
                        rhythm=json.dumps(result.rhythm, ensure_ascii=False, indent=2),
                        emotion_modules=json.dumps(result.emotion_modules, ensure_ascii=False, indent=2),
                        worldbuilding=json.dumps(result.worldbuilding, ensure_ascii=False, indent=2),
                    ),
                    api_key,
                )
                result.report_markdown = response
                result.current_stage = 6
                db.commit()

            # Stage 6: 文风分析
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
                result.current_stage = 7
                db.commit()

            result.status = "completed"
            result.stages_completed = [0, 1, 2, 3, 4, 5, 6]
            db.commit()

            return {"status": "completed", "result_id": result.id}

        except Exception as e:
            logger.error(f"拆书管道 Stage {result.current_stage} 失败: {e}")
            result.status = "failed"
            result.progress_markdown = (result.progress_markdown or "") + f"\n\n## Stage {result.current_stage} 失败\n{str(e)}"
            db.commit()
            raise

    finally:
        db.close()
