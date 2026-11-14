"""知识版本推进事件（knowledge_revision）与作品删除的兼容性回归测试。

覆盖：删除作品时不应抛 StaleKnowledgeContextError；普通上下文写入仍应推进版本。
"""

from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import Base
from models import Chapter, Story, User


def _make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed_story(db):
    user = User(email="tester@example.com", password_hash="x")
    db.add(user)
    db.commit()
    story = Story(owner_user_id=user.id, title="测试故事")
    db.add(story)
    db.commit()
    return story


def test_delete_story_does_not_raise_stale_knowledge_error():
    """删除含章节的作品时，提交不应抛 StaleKnowledgeContextError。"""
    Session = _make_session()
    db = Session()
    try:
        story = _seed_story(db)
        db.add(Chapter(story_id=story.id, chapter_number=1, title="第一章"))
        db.commit()
        # 触发与 delete_story 相同的路径：ORM 级联删除章节 + 删除作品本身
        db.delete(story)
        db.commit()
        assert db.query(Story).filter_by(id=story.id).first() is None
        assert db.query(Chapter).count() == 0
    finally:
        db.close()


def test_story_context_write_still_advances_revision():
    """普通上下文写入（改标题）仍应推进 knowledge_revision。"""
    Session = _make_session()
    db = Session()
    try:
        story = _seed_story(db)
        before = story.knowledge_revision
        story.title = "改名后的故事"
        db.commit()
        db.refresh(story)
        assert story.knowledge_revision == before + 1
    finally:
        db.close()


def test_chapter_context_write_still_advances_revision():
    """章节上下文写入（改正文）仍应推进 knowledge_revision。"""
    Session = _make_session()
    db = Session()
    try:
        story = _seed_story(db)
        chapter = Chapter(story_id=story.id, chapter_number=1, title="第一章")
        db.add(chapter)
        db.commit()
        before = story.knowledge_revision
        chapter.novel_content = "修改后的正文"
        db.commit()
        db.refresh(story)
        assert story.knowledge_revision == before + 1
    finally:
        db.close()
