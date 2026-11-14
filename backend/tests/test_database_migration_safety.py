from sqlalchemy import create_engine, text

from database import _assert_no_duplicate_content


def test_duplicate_content_blocks_migration_without_deleting_rows():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE chapters (id INTEGER PRIMARY KEY, story_id INTEGER, chapter_number INTEGER)"))
        conn.execute(text("INSERT INTO chapters (id, story_id, chapter_number) VALUES (1, 7, 1), (2, 7, 1)"))

    try:
        _assert_no_duplicate_content(engine)
    except RuntimeError as exc:
        assert "自动迁移禁止删除用户数据" in str(exc)
    else:
        raise AssertionError("重复章节必须阻断自动迁移")

    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM chapters")).scalar() == 2
