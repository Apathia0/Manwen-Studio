import asyncio
import json
import logging
from typing import Any, cast

from sqlalchemy.orm import Session

from database import SessionLocal
from models import DeconstructionWork, DeconstructionChapter
from prompts.deconstruction import (
    AUTHOR_ROUTINE_MERGE_SYSTEM,
    AUTHOR_ROUTINE_MERGE_USER,
    AUTHOR_STYLE_REPORT_SYSTEM,
    AUTHOR_STYLE_REPORT_USER,
    AUTHOR_STYLE_SAMPLE_SYSTEM,
    AUTHOR_STYLE_SAMPLE_USER,
)
from services.deconstruction import (
    _call_deepseek_json,
    _call_deepseek_text,
    _configure_deepseek_from_db,
    _count_words,
    _get_api_key_from_db,
    _truncate_json_for_context,
)

logger = logging.getLogger(__name__)

AUTHOR_STYLE_SAMPLE_CONCURRENCY = 4
AUTHOR_STYLE_CHAPTER_TEXT_LIMIT = 6000
ANONYMIZED_SOURCE_TITLE = "匿名样本作品"
ANONYMIZED_SOURCE_AUTHOR = "匿名作者"


def build_anonymized_author_style_profile(profile: dict[str, Any], sampled_numbers: list[int]) -> dict[str, Any]:
    for key in ("title", "author", "source_title", "source_author", "book_title", "book_author"):
        profile.pop(key, None)
    profile["sampled_chapters"] = sampled_numbers
    profile.setdefault("schema_version", 1)
    profile["source_policy"] = "anonymized"
    profile["source_label"] = "匿名样本"
    return profile


def select_author_style_samples(chapter_numbers: list[int]) -> list[int]:
    ordered = sorted(set(int(n) for n in chapter_numbers if n is not None))
    total = len(ordered)
    if total <= 12:
        return ordered

    selected: set[int] = set(ordered[:3])
    if total <= 80:
        for ratio in (0.25, 0.4, 0.55, 0.7, 0.82, 0.9):
            idx = min(total - 1, max(0, round((total - 1) * ratio)))
            selected.add(ordered[idx])
        selected.update(ordered[-5:])
    else:
        for center in (0.2, 0.4, 0.6, 0.8):
            base = round((total - 1) * center)
            selected.add(ordered[max(0, base - 1)])
            selected.add(ordered[base])
            selected.add(ordered[min(total - 1, base + 1)])
        selected.update(ordered[-2:])

    return sorted(selected)[:20]


def _update_author_style_progress(work: DeconstructionWork, db: Session, message: str) -> None:
    work.author_style_progress_markdown = (work.author_style_progress_markdown or "") + f"\n- {message}"
    db.commit()


async def run_author_style_pipeline(work_id: int, api_key: str | None, task_id: str | None = None, **kwargs: object) -> dict[str, object]:
    db = SessionLocal()
    try:
        _configure_deepseek_from_db(db)
        if not api_key:
            api_key = _get_api_key_from_db(db)

        work = db.query(DeconstructionWork).filter(DeconstructionWork.id == work_id).first()
        if not work:
            raise ValueError(f"拆书工作 {work_id} 不存在")
        chapters = db.query(DeconstructionChapter).filter(
            DeconstructionChapter.work_id == work_id,
            DeconstructionChapter.content.isnot(None),
            DeconstructionChapter.content != "",
        ).order_by(DeconstructionChapter.chapter_number).all()
        if len(chapters) < 3:
            raise ValueError(f"至少需要 3 章有内容的章节才能提取作者风格（当前 {len(chapters)} 章）")

        by_number = {ch.chapter_number: ch for ch in chapters}
        sampled_numbers = select_author_style_samples(list(by_number))
        sampled_chapters = [by_number[n] for n in sampled_numbers if n in by_number]

        work.author_style_status = "running"
        work.author_style_task_id = task_id
        work.author_style_progress_markdown = ""
        db.commit()
        _update_author_style_progress(work, db, f"已选择 {len(sampled_chapters)} 个样本章节：{sampled_numbers}")

        semaphore = asyncio.Semaphore(AUTHOR_STYLE_SAMPLE_CONCURRENCY)

        async def analyze_one(ch: DeconstructionChapter) -> dict[str, Any]:
            async with semaphore:
                text = (ch.content or "")[:AUTHOR_STYLE_CHAPTER_TEXT_LIMIT]
                return cast(dict[str, Any], await _call_deepseek_json(
                    AUTHOR_STYLE_SAMPLE_SYSTEM,
                    AUTHOR_STYLE_SAMPLE_USER.format(
                        title=ANONYMIZED_SOURCE_TITLE,
                        author=ANONYMIZED_SOURCE_AUTHOR,
                        chapter_number=ch.chapter_number,
                        chapter_title=ch.title or "",
                        word_count=ch.word_count or _count_words(ch.content),
                        chapter_text=text,
                    ),
                    api_key,
                ))

        sample_results = await asyncio.gather(*[analyze_one(ch) for ch in sampled_chapters], return_exceptions=True)
        usable_results: list[dict[str, Any]] = []
        for ch, result in zip(sampled_chapters, sample_results):
            if isinstance(result, BaseException):
                logger.warning("作者画像样本章节 %s 分析失败: %s", ch.chapter_number, result)
                _update_author_style_progress(work, db, f"第{ch.chapter_number}章样本分析失败：{result}")
                continue
            usable_results.append(result)

        if len(usable_results) < 3:
            raise ValueError("可用样本少于 3 章，无法合成作者风格画像")

        _update_author_style_progress(work, db, f"样本分析完成：成功 {len(usable_results)}/{len(sampled_chapters)} 章")
        profile = cast(dict[str, Any], await _call_deepseek_json(
            AUTHOR_ROUTINE_MERGE_SYSTEM,
            AUTHOR_ROUTINE_MERGE_USER.format(
                title=ANONYMIZED_SOURCE_TITLE,
                author=ANONYMIZED_SOURCE_AUTHOR,
                sampled_chapters=json.dumps(sampled_numbers, ensure_ascii=False),
                sample_results=_truncate_json_for_context(usable_results, 30000),
            ),
            api_key,
        ))
        profile = build_anonymized_author_style_profile(profile, sampled_numbers)

        report = await _call_deepseek_text(
            AUTHOR_STYLE_REPORT_SYSTEM,
                AUTHOR_STYLE_REPORT_USER.format(
                    title=ANONYMIZED_SOURCE_TITLE,
                    author=ANONYMIZED_SOURCE_AUTHOR,
                    profile_json=json.dumps(profile, ensure_ascii=False, indent=2),
                ),
            api_key,
        )

        work.author_style_profile = profile
        work.author_style_report_markdown = report
        work.author_style_status = "completed"
        work.decon_status = "completed"
        db.commit()
        _update_author_style_progress(work, db, "作者风格画像已生成")
        return {"status": "completed", "work_id": work.id}
    except Exception as exc:
        work = db.query(DeconstructionWork).filter(DeconstructionWork.id == work_id).first()
        if work:
            work.author_style_status = "failed"
            work.author_style_progress_markdown = (work.author_style_progress_markdown or "") + f"\n- 作者画像分析失败：{exc}"
            db.commit()
        raise
    finally:
        db.close()
