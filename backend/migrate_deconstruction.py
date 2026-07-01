"""
数据迁移脚本：将旧拆书数据迁移到独立拆书库
旧表：novel_sources + deconstruction_results + chapters(content_source='crawled')
新表：deconstruction_works + deconstruction_chapters + story_deconstruction_refs

幂等：如果 work 已存在则跳过
"""

import sys
from database import SessionLocal
from models import (
    NovelSource, DeconstructionResult, Chapter, Story,
    DeconstructionWork, DeconstructionChapter, StoryDeconstructionRef,
)

def migrate():
    db = SessionLocal()
    migrated = 0
    skipped = 0
    errors = []

    try:
        # 1. 找到所有有 NovelSource 或 DeconstructionResult 的 story
        story_ids_with_source = set(
            r[0] for r in db.query(NovelSource.story_id).distinct().all()
        )
        story_ids_with_result = set(
            r[0] for r in db.query(DeconstructionResult.story_id).distinct().all()
        )
        all_story_ids = story_ids_with_source | story_ids_with_result

        print(f"找到 {len(all_story_ids)} 个有拆书数据的作品")

        for story_id in all_story_ids:
            story = db.query(Story).filter(Story.id == story_id).first()
            if not story:
                print(f"  story_id={story_id} 不存在，跳过")
                skipped += 1
                continue

            # 检查是否已迁移
            source = db.query(NovelSource).filter(
                NovelSource.story_id == story_id,
            ).first()

            if source and source.source_book_id:
                existing = db.query(DeconstructionWork).filter(
                    DeconstructionWork.source_book_id == source.source_book_id,
                    DeconstructionWork.owner_user_id == story.owner_user_id,
                ).first()
                if existing:
                    print(f"  《{story.title}》已迁移，跳过")
                    skipped += 1
                    continue

            try:
                # 2. 创建 DeconstructionWork
                if source:
                    work = DeconstructionWork(
                        owner_user_id=story.owner_user_id or 1,
                        title=story.title,
                        author=source.author,
                        platform=source.platform,
                        source_url=source.source_url,
                        source_book_id=source.source_book_id,
                        genre=source.genre,
                        status_label=source.status,
                        crawl_status=source.crawl_status or "completed",
                        total_chapters=source.total_chapters,
                        crawled_chapters=source.crawled_chapters or 0,
                        word_count=source.word_count,
                    )
                else:
                    work = DeconstructionWork(
                        owner_user_id=story.owner_user_id or 1,
                        title=story.title,
                        platform="qidian",
                        source_url="",
                        source_book_id="",
                        crawl_status="completed",
                    )
                db.add(work)
                db.flush()

                # 3. 迁移拆书结果
                result = db.query(DeconstructionResult).filter(
                    DeconstructionResult.story_id == story_id,
                ).order_by(DeconstructionResult.created_at.desc()).first()

                if result:
                    work.decon_status = result.status
                    work.current_stage = result.current_stage
                    work.stages_completed = result.stages_completed
                    work.summary = result.summary
                    work.golden_chapters = result.golden_chapters
                    work.chapter_summaries = result.chapter_summaries
                    work.characters = result.characters
                    work.character_relations = result.character_relations
                    work.plot_lines = result.plot_lines
                    work.rhythm = result.rhythm
                    work.emotion_modules = result.emotion_modules
                    work.worldbuilding = result.worldbuilding
                    work.report_markdown = result.report_markdown
                    work.writing_style = result.writing_style
                    work.writing_techniques = result.writing_techniques
                    work.progress_markdown = result.progress_markdown
                    work.task_id = result.task_id

                # 4. 迁移爬取章节
                chapters = db.query(Chapter).filter(
                    Chapter.story_id == story_id,
                    Chapter.content_source == "crawled",
                    Chapter.novel_content.isnot(None),
                    Chapter.novel_content != "",
                ).order_by(Chapter.chapter_number).all()

                for ch in chapters:
                    dc = DeconstructionChapter(
                        work_id=work.id,
                        chapter_number=ch.chapter_number,
                        title=ch.title,
                        content=ch.novel_content,
                        word_count=ch.word_count or 0,
                    )
                    db.add(dc)

                if not chapters and source:
                    work.crawl_status = "pending"

                # 5. 创建引用关系
                ref = StoryDeconstructionRef(
                    story_id=story_id,
                    work_id=work.id,
                )
                db.add(ref)

                db.commit()
                migrated += 1
                print(f"  ✅ 《{story.title}》：{len(chapters)} 章已迁移")

            except Exception as e:
                db.rollback()
                errors.append(f"  ❌ 《{story.title}》：{e}")
                print(f"  ❌ 《{story.title}》：{e}")

    finally:
        db.close()

    print(f"\n迁移完成: {migrated} 个作品, 跳过 {skipped} 个, 错误 {len(errors)} 个")
    for err in errors:
        print(err)


if __name__ == "__main__":
    migrate()